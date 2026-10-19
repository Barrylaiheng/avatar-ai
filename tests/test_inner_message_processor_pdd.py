# -*- coding: utf-8 -*-
"""
里层 PDD · Phase 5 TDD · 测试骨架（15 步流水线 · 22 Seams）
模块：src/aibridge/engine/message_processor.py（PDD_INNER_message_processor.md §3）

Seams 列表：
  SE-01~SE-04: 基础（私聊文字/语音/群聊@/触发词）
  SE-05~SE-12: 边界短路（群闲聊无触发/图片/空消息/去重滑窗/10s去重/管理群命令/管理群非命令/主人同步）
  SE-13~SE-17: 安全（砍价/广告/三击拉黑/黑期拦截/关键词库完整覆盖）
  SE-18~SE-22: 兜底+迭代（无API Key/超时/其他错/用户说不对/正常不写bad_case）

执行: pytest tests/test_inner_message_processor_pdd.py -v
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


# ---------------- 常量（对齐 prototype + 规格文档） ----------------

MSG_TEXT = "text"
MSG_VOICE = "voice"
MSG_IMAGE = "image"
MSG_VIDEO = "video"
MSG_FILE = "file"
MSG_SYSTEM = "system"
MSG_RECALL = "recall"

ADMIN_GROUP_IDS = {"admin-group-master"}
AI_TRIGGER_WORDS = {"@AI", "@搭搭", "@分身", "AI 在吗", "搭搭"}

# 24 + 11
ADVERTISING_KW = [
    "加我", "加微信", "加V", "薇信", "微我", "V我", "私聊", "私信我", "私信",
    "加好友", "加群", "拉群", "入群", "拉我", "佳薇", "伽薇", "vx", "VX",
    "v信", "V信", "二维码", "扫码",
]
KANJIA_KW = [
    "砍一刀", "帮砍", "砍价", "助力", "投票", "拉票", "点一下",
    "帮忙点", "帮我砍", "砍一个", "砍完",
]

WARN_KANJIA = "⚠️ 检测到疑似砍价/助力链接，这类链接本群不允许发哦～请遵守群规，以免被移出群聊 🙏"
WARN_AD = "⚠️ 检测到疑似引流内容，本群禁止发广告哦～有问题直接在群里说，搭搭帮你找优惠 😊"

FALLBACK_NO_APIKEY = "AI 配置未完成，请在设置页填写 API Key"
FALLBACK_TIMEOUT = "搭搭正在思考，请稍等..."
FALLBACK_OTHER = "抱歉，我暂时无法回答，请稍后再试"
AIGC_TAIL_DEFAULT = "\n\n— 本内容由 AI 生成，仅代表主人的 AI 分身观点，非真人意见。"


# ---------------- 辅助函数：把 result 统一成 Result 视图（兼容新旧接口） ----------------

def inspect_result(result: Any) -> Dict[str, Any]:
    """
    返回：{
      "reply": str,              # 最终要发的内容
      "action": str,             # reply / silent_drop / block
      "write_chat_history": bool,
      "write_audit_log": bool,
      "write_bad_case": bool,
      "bad_case_reasons": List[str],
      "traces": List[Dict],      # 每一步的 details
    }
    """
    # 先按规格文档里 ProcessingResult 扩展字段试读
    reply = ""
    action = "silent_drop"
    write_chat = False
    write_audit = False
    write_bad = False
    bad_reasons: List[str] = []
    traces: List[Dict] = []

    if hasattr(result, "to_dict"):
        d = result.to_dict()
    else:
        d = result

    # 新接口的 content 即 reply
    reply = (d.get("content") or "").strip()
    action = d.get("action", "silent_drop") if reply else "silent_drop"
    # 新字段（我们在 T6 会加进来，Red 阶段不存在，先靠 d.get 兜底）
    write_chat = bool(d.get("write_chat_history", False))
    write_audit = bool(d.get("write_audit_log", False))
    write_bad = bool(d.get("write_bad_case", False))
    r = d.get("bad_case_reasons")
    if isinstance(r, list):
        bad_reasons = list(r)
    elif isinstance(r, str) and r:
        bad_reasons = [r]

    layer_traces = d.get("layer_traces") or []
    for lt in layer_traces:
        traces.append({
            "step_name": lt.get("layer", ""),
            "details": lt.get("details") or {},
            "stopped": (not lt.get("success", True)) or bool((lt.get("details") or {}).get("stopped_here"))
        })

    return {
        "reply": reply,
        "action": action,
        "write_chat_history": write_chat,
        "write_audit_log": write_audit,
        "write_bad_case": write_bad,
        "bad_case_reasons": bad_reasons,
        "traces": traces,
    }


# ---------------- T1 Fixtures ----------------

@pytest.fixture
def tmp_db(tmp_path):
    """T1：临时 DB，避免污染真实库"""
    p = tmp_path / "pdd_test.db"
    from aibridge.database.database_manager import DatabaseManager
    db = DatabaseManager(str(p))
    db.connect()
    try:
        from aibridge.database.database_migrator import DatabaseMigrator
        DatabaseMigrator(db).migrate()
    except Exception:
        pass
    yield db
    db.disconnect()


@pytest.fixture
def config(tmp_path):
    """T1：临时 ConfigManager（正常回复走 mock reply，不烧 token；dm-05 盖章默认开）"""
    from aibridge.config.config_manager import ConfigManager
    cfg = ConfigManager()
    cfg.set("security.safety_shell_enabled", False)   # PDD 用内部 S07 关键词实现，不走 v1.6 合规规则
    cfg.set("ui.aigc_stamp_enabled", True)            # dm-05 盖章默认开
    cfg.set("llm.provider", "mock")
    # 给一个看起来有效的假 Key，让 S11 判定 "有 Key" → 走 mock 分支（S11 内部会再检查 llm_client 可用性，
    # 未配置则 fallback，但 S11 mock 分支优先用伪回复）
    cfg.set("llm.api_key", "MOCK_VALID_SEAM_22")
    return cfg


@pytest.fixture
def processor(config, tmp_db):
    """T1：MessageProcessor 实例（状态清理在每次 teardown 时重建）"""
    from aibridge.engine.message_processor import MessageProcessor
    return MessageProcessor(config, tmp_db)


# ---------------- 通用调用帮助：把 Msg 转成旧 process() 参数格式 ----------------

def make_msg(
    *,
    msg_id: str,
    content: str = "",
    msg_type: str = MSG_TEXT,
    group_name: str = "",
    group_wxid: str = "",
    sender_wxid: str = "u-user",
    is_at_me: bool = False,
    sender_is_master: bool = False,
    session_type: str = "chat",
) -> Dict[str, Any]:
    """T2 之前先用临时 dict 传参数；T2 正式会加 process_message(Msg) 接口"""
    return {
        "msg_id": msg_id,
        "msg_type": msg_type,
        "group_name": group_name,
        "group_wxid": group_wxid,
        "sender_wxid": sender_wxid,
        "is_at_me": is_at_me,
        "sender_is_master": sender_is_master,
        "content": content,
        "session_type": session_type,
    }


def call(processor, m: Dict[str, Any]) -> Dict[str, Any]:
    """
    T2 之前统一走这里：先尝试新的 15 步接口 process_v2()；没有就 fallback 旧 process() 然后返回 empty dict。
    Red 阶段应该全部 FAILED — 这是 TDD 的正确姿势。
    """
    if hasattr(processor, "process_v2"):
        raw = processor.process_v2(**m)
        return inspect_result(raw)
    # Fallback：旧 process()，返回结构里不含 PDD 新增字段 — 所有断言会红
    raw = processor.process(
        wxid=m["sender_wxid"],
        content=m.get("content", ""),
        session_type=m.get("session_type", "chat"),
    )
    out = inspect_result(raw)
    # 关键：T2 之前新接口还没写，所有 write_* 都显式为 False，action=reply 如果有内容
    return out


# ======================================================================
# SE-01 ~ SE-04：基础 4 条
# ======================================================================

def test_se01_private_text_ok(processor):
    """SE-01：私聊文本 → 正常回复 + 写 chat_history + 盖章"""
    m = make_msg(msg_id="se01-1", content="最近有什么奶茶优惠")
    out = call(processor, m)
    assert out["action"] == "reply", f"action 应=reply，实={out['action']}"
    assert len(out["reply"]) > 0, "reply 不应为空"
    assert AIGC_TAIL_DEFAULT.strip() in out["reply"], "应加 AIGC 盖章"
    assert out["write_chat_history"] is True, "正常回复应写 chat_history"
    assert out["write_audit_log"] is False
    assert out["write_bad_case"] is False


def test_se02_private_voice_ocr(processor):
    """SE-02：私聊语音(OCR) → 正常回复，S01 details.type_final=ocr_text"""
    m = make_msg(msg_id="se02-1", msg_type=MSG_VOICE, content="（OCR文本）最近有什么奶茶优惠")
    out = call(processor, m)
    assert out["action"] == "reply"
    assert len(out["reply"]) > 0
    # 查 trace
    s01 = next((t for t in out["traces"] if "S01" in t["step_name"] or "消息类型" in t["step_name"]), None)
    assert s01 is not None, "应存在 S01 类型检查 trace"
    assert s01["details"].get("type_final") == "ocr_text"


def test_se03_group_at_me(processor):
    """SE-03：群聊@我 → 触发 AI；S02 has_trigger 不应当 stopped"""
    m = make_msg(
        msg_id="se03-1",
        content="@AI 电影票最近有啥活动",
        group_name="测试群1",
        group_wxid="g-test-1",
        is_at_me=True,
    )
    out = call(processor, m)
    assert out["action"] == "reply"
    s02 = next((t for t in out["traces"] if "S02" in t["step_name"] or "群/私" in t["step_name"]), None)
    assert s02 is not None
    assert s02["stopped"] is False, "群聊@我 不应被 S02 截断"


def test_se04_group_trigger_word(processor):
    """SE-04：群聊触发词「搭搭」→ 触发，S02.details.has_trigger_word=True"""
    m = make_msg(
        msg_id="se04-1",
        content="搭搭，帮我找个外卖券",
        group_name="测试群1",
        group_wxid="g-test-1",
    )
    out = call(processor, m)
    assert out["action"] == "reply"
    s02 = next((t for t in out["traces"] if "S02" in t["step_name"] or "群/私" in t["step_name"]), None)
    assert s02 is not None
    assert s02["details"].get("has_trigger_word") is True


# ======================================================================
# SE-05 ~ SE-12：边界短路 8 条
# ======================================================================

def test_se05_group_no_trigger_silent_drop(processor):
    """SE-05：群闲聊无触发 → silent_drop，不写任何库"""
    m = make_msg(
        msg_id="se05-1",
        content="今天天气好吗",
        group_name="测试群1",
        group_wxid="g-test-1",
    )
    out = call(processor, m)
    assert out["action"] == "silent_drop"
    assert out["reply"] == ""
    assert out["write_chat_history"] is False
    assert out["write_audit_log"] is False
    assert out["write_bad_case"] is False


def test_se06_image_silent_drop(processor):
    """SE-06：图片 → silent_drop"""
    m = make_msg(msg_id="se06-1", msg_type=MSG_IMAGE, content="")
    out = call(processor, m)
    assert out["action"] == "silent_drop"
    assert out["reply"] == ""


def test_se07_empty_silent_drop(processor):
    """SE-07：空消息/纯空格 → silent_drop"""
    m = make_msg(msg_id="se07-1", content="   \n  \t  ")
    out = call(processor, m)
    assert out["action"] == "silent_drop"


def test_se08_msgid_sliding_window(processor):
    """SE-08：同 msg_id 两条 → 第二条 silent_drop"""
    shared_id = "se08-shared"
    m1 = make_msg(msg_id=shared_id, content="这是去重占位")
    out1 = call(processor, m1)
    assert out1["action"] == "reply"   # 第一条正常
    m2 = make_msg(msg_id=shared_id, content="这是去重占位")
    out2 = call(processor, m2)
    assert out2["action"] == "silent_drop", "第二条同 msg_id 应被滑窗去重"


def test_se09_10s_same_user_same_content(processor):
    """SE-09：10s 内同用户同内容 → 第二条丢"""
    u = "u-se09"
    c = "重复123"
    m1 = make_msg(msg_id="se09-a1", sender_wxid=u, content=c)
    out1 = call(processor, m1)
    assert out1["action"] == "reply"
    m2 = make_msg(msg_id="se09-a2", sender_wxid=u, content=c)
    out2 = call(processor, m2)
    assert out2["action"] == "silent_drop", "10s 内同用户同内容 应被去重"


def test_se10_admin_group_command(processor):
    """SE-10：管理群命令「查看兜底规则」→ 不进安全/不进大模型 → 命令返回结果"""
    m = make_msg(
        msg_id="se10-1",
        content="查看兜底规则",
        group_name="管理群",
        group_wxid=ADMIN_GROUP_IDS.__iter__().__next__(),
    )
    out = call(processor, m)
    assert out["action"] == "reply", f"管理群命令应 reply，实={out['action']}"
    assert "查看兜底规则" in out["reply"] or "管理命令" in out["reply"], \
        f"命令执行结果应包含命令名，实={out['reply'][:80]}"
    s06 = next((t for t in out["traces"] if "S06" in t["step_name"] or "管理群" in t["step_name"]), None)
    assert s06 is not None, "应有 S06 管理群 trace"


def test_se11_admin_group_non_command_ignore(processor):
    """SE-11：管理群非命令 → silent_drop，不写任何库"""
    m = make_msg(
        msg_id="se11-1",
        content="你好",
        group_name="管理群",
        group_wxid=next(iter(ADMIN_GROUP_IDS)),
    )
    out = call(processor, m)
    assert out["action"] == "silent_drop"
    assert out["write_chat_history"] is False


def test_se12_master_manual_sync_history(processor):
    """SE-12：主人手动发消息 → 不回、只写 chat_history；不调 LLM"""
    m = make_msg(
        msg_id="se12-1",
        sender_is_master=True,
        content="我自己说：这个 CPS 项目的佣金比例是 20%",
    )
    out = call(processor, m)
    assert out["action"] == "silent_drop", f"主人手动消息不应回复，实={out['action']}"
    assert out["reply"] == ""
    assert out["write_chat_history"] is True, "主人手动消息必须同步 chat_history（防风格漂移）"
    # 确保 S11 没进：没有 llm trace 或 trace 明确 skipped
    llm_trace = next((t for t in out["traces"] if "LLM" in t["step_name"] or "S11" in t["step_name"]), None)
    if llm_trace is not None:
        assert llm_trace["details"].get("skipped") is True, "主人手动消息不应调 LLM"


# ======================================================================
# SE-13 ~ SE-17：安全 5 条
# ======================================================================

def test_se13_kanjia_block(processor):
    """SE-13：砍价拦截 → 发 WARN_KANJIA；不写 chat；写 audit+bad_case(待审阅)"""
    m = make_msg(msg_id="se13-1", content="帮我砍一刀，谢谢")
    out = call(processor, m)
    assert out["action"] == "reply"
    # 不逐字比较前缀，但核心要一致（含"砍价/助力"+"不允许发"）
    assert "砍价" in out["reply"] and "不允许发" in out["reply"], f"砍价话术不对：{out['reply']}"
    assert out["write_chat_history"] is False, "安全拦截不写正常历史"
    assert out["write_audit_log"] is True, "安全拦截应写 audit_log"
    assert out["write_bad_case"] is True, "第 1 击应写 bad_case(待审阅)"
    assert any("安全命中待审阅" in r for r in out["bad_case_reasons"])


def test_se14_ad_block(processor):
    """SE-14：广告拦截 → 发 WARN_AD；不写 chat；写 audit+bad_case(待审阅)"""
    m = make_msg(msg_id="se14-1", content="加我，我有内部券")
    out = call(processor, m)
    assert out["action"] == "reply"
    assert "引流" in out["reply"] and "禁止发广告" in out["reply"]
    assert out["write_chat_history"] is False
    assert out["write_audit_log"] is True
    assert out["write_bad_case"] is True


def test_se15_safety_3rd_hit_blacklist_7d(processor):
    """SE-15：三击（连续广告）→ 第 3 次 silent_drop；升级信息写在 S07 trace"""
    u = "u-se15"
    ids = ["se15-h1", "se15-h2", "se15-h3"]
    contents = ["加我领券", "加V拿内部价", "扫码进福利群"]
    last_out = None
    for mid, c in zip(ids, contents):
        m = make_msg(msg_id=mid, sender_wxid=u, content=c)
        last_out = call(processor, m)
    # 第 3 击
    assert last_out is not None
    assert last_out["action"] == "silent_drop", f"第 3 击应静默丢，实={last_out['action']}"
    s07 = next((t for t in last_out["traces"] if "S07" in t["step_name"] or "安全壳" in t["step_name"]), None)
    assert s07 is not None, "应有 S07 安全壳 trace"
    details_str = str(s07["details"])
    assert "拉黑 7 天" in details_str or "7 天" in details_str, \
        f"S07 trace 应出现 7 天拉黑，实={details_str[:200]}"


def test_se16_blacklist_period_still_blocked(processor):
    """SE-16：第 4 条（在 7 天黑期里，哪怕非广告）→ 黑名单前置 S05 拦截"""
    u = "u-se16"
    # 先三连击拉黑
    for i, c in enumerate(["加我", "加V", "扫码"]):
        call(processor, make_msg(msg_id=f"se16-h{i+1}", sender_wxid=u, content=c))
    # 第 4 条普通消息
    m4 = make_msg(msg_id="se16-4", sender_wxid=u, content="你好")
    out = call(processor, m4)
    assert out["action"] == "silent_drop", f"黑期内第 4 条应被 S05 前置拦截，实={out['action']}"
    s05 = next((t for t in out["traces"] if "S05" in t["step_name"] or "黑名单" in t["step_name"]), None)
    s07 = next((t for t in out["traces"] if "S07" in t["step_name"] or "安全壳" in t["step_name"]), None)
    details_str = str((s05 or {}).get("details", "")) + str((s07 or {}).get("details", ""))
    assert "黑名" in details_str or "168h" in details_str or "黑名单" in details_str, \
        f"S05/S07 应出现 黑名单 描述，实={details_str[:200]}"


def test_se17_keyword_lib_full_coverage(processor):
    """SE-17：24 + 11 关键词库逐条测试，不交叉错分"""
    errors = []
    for i, kw in enumerate(ADVERTISING_KW):
        m = make_msg(msg_id=f"se17-ad-{i}", content=f"欢迎咨询，{kw}了解更多", sender_wxid=f"use17ad-{i}")
        out = call(processor, m)
        if "引流" not in out["reply"] and "禁止发广告" not in out["reply"]:
            errors.append(f"广告KW未命中广告分类: kw={kw!r} reply={out['reply'][:60]!r}")
    for i, kw in enumerate(KANJIA_KW):
        m = make_msg(msg_id=f"se17-kj-{i}", content=f"帮我一下，{kw}谢谢", sender_wxid=f"use17kj-{i}")
        out = call(processor, m)
        if "砍价" not in out["reply"] and "助力" not in out["reply"]:
            errors.append(f"砍价KW未命中砍价分类: kw={kw!r} reply={out['reply'][:60]!r}")
    assert not errors, "\n".join(errors)


# ======================================================================
# SE-18 ~ SE-22：兜底 + 迭代 5 条
# ======================================================================

def test_se18_fallback_no_apikey(processor, config):
    """SE-18：无 API Key → 兜底文案 + bad_case(LLM兜底=no_api_key) + 盖章"""
    # 确保：provider=deepseek + api_key=空（非 mock 模式下必触发 no_api_key）
    config.set("llm.provider", "deepseek")
    config.set("llm.api_key", "")
    m = make_msg(msg_id="se18-1", content="你好")
    out = call(processor, m)
    assert out["action"] == "reply"
    assert FALLBACK_NO_APIKEY in out["reply"], f"无 Key 兜底文案不对：{out['reply'][:80]}"
    assert AIGC_TAIL_DEFAULT.strip() in out["reply"], "兜底回复也要盖章"
    assert out["write_bad_case"] is True
    assert any("LLM兜底" in r or "no_api_key" in r for r in out["bad_case_reasons"]), \
        f"bad_case_reasons 应包含 LLM兜底=no_api_key，实={out['bad_case_reasons']}"


def test_se19_fallback_timeout(processor, config, monkeypatch):
    """SE-19：LLM 超时 → 超时兜底 + bad_case(LLM兜底=timeout)"""
    # T5 里真正实现会有 LLMGenerator mock 超时；这里 Red 阶段先依赖接口字段
    m = make_msg(msg_id="se19-1", content="你好 __fallback_timeout__")
    out = call(processor, m)
    assert out["action"] == "reply"
    assert FALLBACK_TIMEOUT in out["reply"]
    assert out["write_bad_case"] is True
    assert any("timeout" in r.lower() or "超时" in r for r in out["bad_case_reasons"])


def test_se20_fallback_other_error(processor):
    """SE-20：其他错误 → 通用兜底 + bad_case(LLM兜底=other_error)"""
    m = make_msg(msg_id="se20-1", content="你好 __fallback_other__")
    out = call(processor, m)
    assert out["action"] == "reply"
    assert FALLBACK_OTHER in out["reply"]
    assert out["write_bad_case"] is True
    assert any("other" in r.lower() or "LLM兜底" in r for r in out["bad_case_reasons"])


def test_se21_user_says_wrong(processor):
    """SE-21：用户显式说「你刚才说的不对」→ bad_case(用户反馈：刚才说的不对)"""
    m = make_msg(msg_id="se21-1", content="__你刚才说的不对__ 我问的是CPS不是CPC")
    out = call(processor, m)
    assert out["action"] == "reply"   # 哪怕用户说不对，也正常回复 + 记 bad_case
    assert out["write_bad_case"] is True, "用户说不对应写 bad_case"
    assert any("用户反馈" in r or "说的不对" in r or "刚才说的不对" in r
               for r in out["bad_case_reasons"]), \
        f"bad_case_reasons 应包含用户反馈：刚才说的不对，实={out['bad_case_reasons']}"


def test_se22_normal_flow_no_bad_case(processor):
    """SE-22：正常私聊文本 → 不写 bad_case"""
    m = make_msg(msg_id="se22-1", content="你好，今天有什么推荐吗")
    out = call(processor, m)
    assert out["action"] == "reply"
    assert out["write_bad_case"] is False, f"正常流程不应写 bad_case，实 write_bad_case={out['write_bad_case']}; reasons={out['bad_case_reasons']}"
    assert len(out["bad_case_reasons"]) == 0
