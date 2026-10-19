"""端到端自测：智能记忆「每 10 条消息 → LLM 自动提炼 → 写回 DB → 可注入」全链路。

完全模拟真实用户行为，不依赖 GUI，不手动点任何按钮：
  Baseline 检查：已配置 LLM + API 能 ping 通（确保 LLM 调用不会失败）
  1) agents_dao.create 临时测试智能体（记忆开关 enabled=true）
  2) conv_dao.create 临时测试会话
  3) msg_dao.create 连续写 10 条消息（5 轮 user/assistant 交替对话，含 13 个关键词）
     写完第 10 条时 conv.message_count=10，达到触发阈值
  4) bridge._maybe_trigger_memory_refine() → 拿到 Future → fut.result(timeout=120) 同步等完成
  5) 断言 ① user_profile + episodic 条目总数 ≥ 3
        ② 13 个关键词命中率 ≥ 50%（7 个以上，给 LLM 容错）
        ③ _format_memory_for_prompt 注入文本必须出现「长期画像 / 近期重点」和至少 2 个关键词
  6) cleanup：删会话 + 删智能体（放到所有断言之后，避免提前删导致后台读不到）

输出：PASS / FAIL + 写入的 memories 原文供肉眼审计。
"""
from __future__ import annotations
import json
import sys
import time
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "app/storage"))

import py_compile  # noqa: E402
py_compile.compile(str(ROOT / "app/bridge.py"), doraise=True)
print("[BASELINE 1/3] bridge.py 编译通过")

from storage import (  # noqa: E402
    agents_dao, conv_dao, msg_dao, llm_dao,
)
from storage.llm_provider import LLMProvider  # noqa: E402
from bridge import BridgeServer, MEMORY_REFINE_THRESHOLD  # noqa: E402

assert MEMORY_REFINE_THRESHOLD == 10, f"阈值被改了？期望 10 实际 {MEMORY_REFINE_THRESHOLD}"
print(f"[BASELINE 2/3] 阈值确认 = {MEMORY_REFINE_THRESHOLD}")

# ---------- 基线 3：默认 LLM 可用 ----------
llm_cfg = llm_dao.get_default()
if not llm_cfg:
    sys.stderr.write(
        "\n[BASELINE 3/3 失败] 还没有配置默认 LLM。请先到「设置 → LLM 管理」"
        "添加 1 个可用的配置并设为默认，然后再运行本脚本。\n"
    )
    sys.exit(2)
ping = LLMProvider.from_config(llm_cfg).test_connection()
if not ping.get("connected"):
    sys.stderr.write(
        "\n[BASELINE 3/3 失败] 已找到默认 LLM，但 ping 不通："
        f"模型={ping.get('model')} 原因={ping.get('reason')}。"
        "请先在「设置 → LLM 管理 → 测试连接」连通后再跑本脚本。\n"
    )
    sys.exit(3)
print(
    f"[BASELINE 3/3] 默认 LLM 连通：模型={ping.get('model')} "
    f"延迟={ping.get('latency_ms')}ms"
)

# ---------- 5 轮对话（10 条消息），13 个待提炼关键词 ----------
DIALOGUE_TURNS: list[tuple[str, str]] = [
    (
        "你好，我叫 Barry，是做产品经理的，现在在深圳工作。",
        "你好 Barry！深圳做产品经理很辛苦吧？最近项目忙吗？",
    ),
    (
        "还可以，不过我下周要考英语六级，最近每天都在背单词，压力有点大。",
        "加油呀！六级准备得怎么样了？有不会的题可以问我。",
    ),
    (
        "对了说一下我的饮食习惯，我不吃香菜，而且比较喜欢吃辣，火锅必须牛油锅底。",
        "记下来了，下次如果聊到吃饭的话题我会注意不给你推荐带香菜的菜～",
    ),
    (
        "我最近在学太极拳，每周三晚上去上课，感觉挺有意思的，身体也比之前好一点了。",
        "太极拳很养生啊！坚持下去一定有效果，记得每周三别迟到。",
    ),
    (
        "对了我有个长期目标，就是明年想自己做一个独立产品，现在在写 PRD。",
        "哇太酷了！等你产品上线了一定要告诉我，我第一个来体验～",
    ),
]
EXPECTED_KEYWORDS = [
    # user_profile（长期稳定特征，6 个）
    "Barry", "产品经理", "深圳",
    "不吃香菜", "辣", "牛油锅底",
    # episodic（近期事件/目标，7 个）
    "英语六级", "背单词", "压力",
    "太极拳", "每周三", "长期目标", "PRD",
    # 额外同义兜底
    "独立产品", "下周",
]
EXPECTED_KEYWORDS_LOWER = [k.lower() for k in EXPECTED_KEYWORDS]

TEST_TAG = f"__auto_memory_test_{int(time.time())}"
test_agent_id = None
test_conv_id = None
bridge = BridgeServer()

def cleanup():
    try:
        if test_conv_id:
            conv_dao.delete(test_conv_id)
            print(f"[CLEANUP] 会话 {test_conv_id} 已删除", flush=True)
    except Exception as e:
        print(f"[CLEANUP] 会话删除异常: {e}", flush=True)
    try:
        if test_agent_id:
            agents_dao.delete(test_agent_id)
            print(f"[CLEANUP] 智能体 {test_agent_id} 已删除", flush=True)
    except Exception as e:
        print(f"[CLEANUP] 智能体删除异常: {e}", flush=True)
    try:
        bridge._memory_executor.shutdown(wait=False, cancel_futures=True)
    except Exception:
        try:
            bridge._memory_executor.shutdown(wait=False)
        except Exception:
            pass

# ---------- 主体（失败时通过 raise/fail 退出，但先走到 finally 做 cleanup 或在断言后手动清理）
# 注意：清理必须放在 "断言读完 DB 之后"，不能在后台任务跑完之前。
try:
    # 1. 建测试智能体
    agent = agents_dao.create({
        "name": TEST_TAG,
        "description": "请不要删除，E2E 测试用智能体。",
        "system_prompt": "你是 Barry 的数字分身测试用智能体。",
        "style": "简洁友好",
        "memories": json.dumps({
            "enabled": True, "user_profile": [], "episodic": [],
        }, ensure_ascii=False),
        "aigc_enabled": False,
        "emoji_enabled": False,
        "llm_config_id": llm_cfg.get("id"),
        "kb_ids": [],
    })
    test_agent_id = agent["id"]
    print(f"[SETUP] 创建测试智能体: id={test_agent_id[:10]}…")

    # 2. 建测试会话
    conv = conv_dao.create(
        agent_id=test_agent_id,
        title="自动提炼记忆 E2E 测试",
        channel="mvp_test",
        peer_id="barry_e2e_test",
        peer_name="Barry 测试账号",
        peer_type="friend",
    )
    test_conv_id = conv["id"]
    print(f"[SETUP] 创建测试会话: id={test_conv_id[:10]}…")

    # 3. 写 9 条消息（前 4 轮 + 最后一轮 user）
    channel = "mvp_test"
    model_name = llm_cfg.get("model", "")
    for i, (user_text, ai_text) in enumerate(DIALOGUE_TURNS):
        msg_dao.create(test_conv_id, "user", user_text, channel=channel)
        if i < len(DIALOGUE_TURNS) - 1:
            msg_dao.create(
                test_conv_id, "assistant", ai_text,
                channel=channel, model=model_name,
            )

    # 4. 写最后一条 assistant → message_count 达到 10
    msg_dao.create(
        test_conv_id, "assistant", DIALOGUE_TURNS[-1][1],
        channel=channel, model=model_name,
    )
    conv_now = conv_dao.get(test_conv_id)
    cnt_now = int(conv_now.get("message_count") or 0)
    print(f"[SETUP] 10 条消息写入完毕，conversation.message_count = {cnt_now}")
    assert cnt_now == 10, f"message_count 不为 10，实得 {cnt_now}。触发条件不满足，终止测试。"

    # 5. 触发提炼并同步等待（最稳定的方式：Future.result(timeout=...)）
    t0 = time.time()
    fut = bridge._maybe_trigger_memory_refine(test_agent_id, test_conv_id, llm_cfg)
    if fut is None:
        raise RuntimeError("调用 _maybe_trigger_memory_refine 返回 None，未触发提炼。")

    print("[RUN] 提炼任务已提交，同步等待完成（最长 120s）…")
    try:
        fut.result(timeout=120)
    except FutureTimeout:
        raise RuntimeError("等待记忆提炼超时（>120s），LLM 可能卡住了。")

    elapsed = round(time.time() - t0, 1)
    print(f"[RUN] 记忆提炼任务完成，耗时 {elapsed}s")

    # 6. 读最新 agent.memories（必须在 cleanup 之前读！）
    agent_new = agents_dao.get(test_agent_id) or {}
    memories_raw = agent_new.get("memories") or ""
    memories = bridge._parse_memory_json_safe(memories_raw)
    print("\n==================== 写入的 memories 原文 ====================")
    print(json.dumps(memories, ensure_ascii=False, indent=2))
    print("==============================================================\n")

    # ---------- 3 条断言 ----------
    fails: list[str] = []

    profile_cnt = len(memories.get("user_profile") or [])
    episodic_cnt = len(memories.get("episodic") or [])
    total = profile_cnt + episodic_cnt
    if total < 3:
        fails.append(
            f"❌ 提炼后条目数 = {total}（user_profile={profile_cnt}, episodic={episodic_cnt}），"
            "目标 ≥ 3。"
        )
    else:
        print(f"[ASSERT 1/3] ✅ 条目总数 = {total}（≥3）")

    hit_keywords: list[str] = []
    haystacks: list[str] = []
    for entry in (memories.get("user_profile") or []) + (memories.get("episodic") or []):
        t = (entry.get("title") or "").lower()
        c = (entry.get("content") or "").lower()
        haystacks.append(t)
        haystacks.append(c)
    haystack_all = "\n".join(haystacks)
    for kw_orig, kw_low in zip(EXPECTED_KEYWORDS, EXPECTED_KEYWORDS_LOWER):
        if kw_low in haystack_all:
            hit_keywords.append(kw_orig)
    hit_rate = len(hit_keywords) / max(1, len(EXPECTED_KEYWORDS))
    if len(hit_keywords) < 7:
        fails.append(
            f"❌ {len(EXPECTED_KEYWORDS)} 个关键词仅命中 {len(hit_keywords)} 个 "
            f"（{hit_rate:.0%}）：{hit_keywords}，目标 ≥ 7 个（50%）。"
        )
    else:
        print(
            f"[ASSERT 2/3] ✅ 关键词命中 = {len(hit_keywords)}/{len(EXPECTED_KEYWORDS)} "
            f"（{hit_rate:.0%}），命中词 = {hit_keywords}"
        )

    inject_txt = bridge._format_memory_for_prompt(memories_raw)
    if not inject_txt:
        fails.append("❌ _format_memory_for_prompt 返回空字符串，下轮对话无法注入记忆。")
    else:
        inject_lower = inject_txt.lower()
        inject_hits = [k for k in EXPECTED_KEYWORDS if k.lower() in inject_lower]
        have_section_tags = ("长期画像" in inject_txt) and ("近期重点" in inject_txt)
        if not have_section_tags:
            fails.append(
                f"❌ 注入文本缺分区标题「长期画像/近期重点」。"
                f"注入文本前 300 字：{inject_txt[:300]!r}"
            )
        elif len(inject_hits) < 2:
            fails.append(
                f"❌ 注入文本关键词命中仅 {inject_hits}，目标 ≥ 2 个。注入内容：\n{inject_txt}"
            )
        else:
            print(
                f"[ASSERT 3/3] ✅ 注入文本结构完整，含 {len(inject_hits)} 个关键词：{inject_hits}"
            )

    # cleanup 在 finally 里做（此时 DB 已经读完，清理不会影响断言）
    if fails:
        sys.stderr.write("\n===== E2E 测试 FAIL =====\n")
        for f in fails:
            sys.stderr.write(f"  {f}\n")
        sys.stderr.write("===== 写入的 memories 原文（供肉眼审计）=====\n")
        sys.stderr.write(json.dumps(memories, ensure_ascii=False, indent=2) + "\n")
        sys.exit(1)

    print("\n🎉 全部 3 条断言通过：智能记忆自动提炼 E2E PASS")
    sys.exit(0)

finally:
    cleanup()
