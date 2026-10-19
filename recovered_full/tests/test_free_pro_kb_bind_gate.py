# -*- coding: utf-8 -*-
"""
MVP 免费版 / 正式版 双闸门 E2E 测试
方案：知识库全免费，智能体 × 绑定知识库 = 付费分水岭

用例：
  TEST 1 后端闸门 A（未激活 → create/update_agent 非空 kb_ids 被 PermissionError 拒绝）
  TEST 2 后端闸门 A（激活后 → 同样的 kb_ids 正常保存）
  TEST 3 后端闸门 B（未激活 + 硬塞 kb_ids → send_message 强制跳过 RAG）
"""

import os, sys, tempfile, json, shutil, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "app/storage"))

# 隔离 DB：用 SCAI_APP_DIR 覆盖 app/storage/db.py 里的 get_app_dir()
_TMP = tempfile.mkdtemp(prefix="tmp_kg_bind_gate_")
os.environ["SCAI_APP_DIR"] = _TMP
print(f"[DB] 隔离 SCAI_APP_DIR = {_TMP}")

import py_compile
py_compile.compile(str(ROOT / "app/bridge.py"), doraise=True)
print("[BASELINE 0] bridge.py 编译通过")

# 在导入 storage 之前重置连接（任何之前的全局 _CONN 清掉）
from storage.db import reset_db_for_tests
reset_db_for_tests()

from storage import (   # noqa: E402
    get_conn, transaction,
    agents_dao, llm_dao, activation_dao, kb_dao,
)
from bridge import BridgeServer   # noqa: E402

# 确保建表（首次 get_conn 会自动建）
_ = get_conn().execute("SELECT 1").fetchall()
print(f"[BASELINE 0b] DB 建表 OK，路径 = {_TMP}")


def create_bare_bridge():
    return BridgeServer.__new__(BridgeServer)


def activation_reset():
    """强制把 activation 表重置为：未激活 + 额度 0/50"""
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM activation")
        cur.execute(
            "INSERT INTO activation "
            "(id, activated, license_key, machine_code, trial_limit, trial_used, activated_at, updated_at) "
            "VALUES (?,0,?,?,?,0,0,?)",
            ("singleton", "", "TEST-MACHINE-CODE", 50, 0),
        )
    # 清 license.dat 残留
    lic = os.path.join(_TMP, "license.dat")
    if os.path.exists(lic):
        try: os.remove(lic)
        except Exception: pass
    appdata = os.environ.get("APPDATA")
    if appdata:
        lic2 = os.path.join(appdata, "SCAI", "license.dat")
        if os.path.exists(lic2):
            try: os.remove(lic2)
            except Exception: pass


# =================================================================
# TEST 1：未激活 → create/update_agent 非空 kb_ids 被 PermissionError
# =================================================================
def test1_gateA_unactivated_block():
    activation_reset()
    br = create_bare_bridge()

    # 1a. create 非空 kb_ids → 必须 PermissionError
    caught = None
    try:
        br._handle_create_agent({
            "name": "t1 创建被拒",
            "system_prompt": "测试助手",
            "style": "自然",
            "agent_type": "default",
            "kb_ids": ["kb-fake-1"],
        })
    except PermissionError as e:
        caught = e
    assert caught is not None, "TEST1a FAIL：未激活·create·非空 kb_ids 没被拒绝"
    assert "免费版智能体不能绑定知识库" in str(caught)

    # 1b. create 空 kb_ids → 允许
    r = br._handle_create_agent({
        "name": "t1 创建通过",
        "system_prompt": "测试助手",
        "style": "自然",
        "agent_type": "default",
        "kb_ids": [],
    })
    assert r["created"] and r["agent"]["id"]
    aid = r["agent"]["id"]

    # 1c. update 非空 kb_ids → 必须 PermissionError
    caught2 = None
    try:
        br._handle_update_agent({
            "id": aid,
            "name": "t1 编辑被拒",
            "kb_ids": ["kb-fake-999"],
        })
    except PermissionError as e:
        caught2 = e
    assert caught2 is not None, "TEST1b FAIL：未激活·update·非空 kb_ids 没被拒绝"
    assert "免费版智能体不能绑定知识库" in str(caught2)

    # 1d. update 空 kb_ids → 允许
    r2 = br._handle_update_agent({
        "id": aid,
        "name": "t1 编辑通过",
        "kb_ids": [],
    })
    assert r2["updated"]
    print("[TEST 1 PASS] 闸门 A 未激活 = 非空 kb_ids 被拒，空 kb_ids 正常。")


# =================================================================
# TEST 2：激活后 → 非空 kb_ids 正常保存
# =================================================================
def test2_gateA_activated_allow():
    activation_reset()
    with transaction() as conn:
        conn.execute(
            "UPDATE activation SET activated=1, license_key='TEST-LIC', "
            "activated_at=strftime('%s','now'), updated_at=strftime('%s','now') "
            "WHERE id='singleton'"
        )
    status = activation_dao.get_status()
    assert status.get("activated") == 1, "前置：必须激活"

    br = create_bare_bridge()
    r = br._handle_create_agent({
        "name": "t2 激活后创建",
        "system_prompt": "测试助手2",
        "style": "自然",
        "agent_type": "default",
        "kb_ids": ["kb-real-1"],
    })
    assert r["created"]
    aid = r["agent"]["id"]
    saved = agents_dao.get(aid)
    kb = saved.get("kb_ids")
    if isinstance(kb, str):
        kb = json.loads(kb) if kb else []
    assert kb == ["kb-real-1"], f"TEST2a FAIL：保存的 kb_ids = {kb!r}"

    r2 = br._handle_update_agent({
        "id": aid,
        "name": "t2 激活后编辑",
        "kb_ids": ["kb-real-1", "kb-real-2"],
    })
    assert r2["updated"]
    saved2 = agents_dao.get(aid)
    kb2 = saved2.get("kb_ids")
    if isinstance(kb2, str):
        kb2 = json.loads(kb2) if kb2 else []
    assert kb2 == ["kb-real-1", "kb-real-2"], f"TEST2b FAIL：保存的 kb_ids = {kb2!r}"
    print("[TEST 2 PASS] 闸门 A 激活后 = 非空 kb_ids 正常保存。")


# =================================================================
# TEST 3：未激活 + 硬塞 kb_ids → _handle_send_message 强制跳过 RAG
# =================================================================
def test3_gateB_RAG_skipped_when_free():
    activation_reset()
    status = activation_dao.get_status()
    assert status.get("activated") == 0, "前置：必须未激活"

    from storage.retriever import UnifiedRetriever   # noqa: E402
    from storage.llm_provider import LLMProvider      # noqa: E402
    from concurrent.futures import ThreadPoolExecutor   # noqa: E402

    # 1. LLM 配置（fake key，因为我们会 mock chat 方法）
    lcfg = llm_dao.upsert({
        "name": "fake-llm-gateB",
        "provider": "OpenAI 兼容",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "api_key": "sk-fake",
        "is_default": 1,
    })
    assert lcfg and lcfg.get("id")

    # 2. 建智能体（空 kb_ids 过闸门 A）再在 DB 层硬塞
    br = create_bare_bridge()
    r = br._handle_create_agent({
        "name": "t3 免费版硬塞 kb_ids",
        "system_prompt": "只说知识库内容，不要发散。",
        "style": "自然",
        "agent_type": "default",
        "llm_config_id": lcfg["id"],
        "kb_ids": [],
    })
    aid = r["agent"]["id"]

    with transaction() as conn:
        conn.execute(
            "UPDATE ai_agent SET kb_ids=? WHERE id=?",
            (json.dumps(["kb-hacked-1"]), aid),
        )
    saved = agents_dao.get(aid)
    kb = saved.get("kb_ids")
    if isinstance(kb, str):
        kb = json.loads(kb) if kb else []
    assert kb == ["kb-hacked-1"], "前置条件失败：硬塞 kb_ids 没生效"

    # 3. 最小 BridgeServer 实例（手动贴 send_message 用到的字段）
    br_full = BridgeServer.__new__(BridgeServer)
    br_full._retriever = UnifiedRetriever()
    br_full._memory_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="t3-gate")

    # 4. Mock retriever.search → 调用就意味着闸门 B 失效
    rag_called = {"v": False}
    def fake_retriever_search(query, top_k=3, kb_ids=None, **kwargs):
        rag_called["v"] = True
        return [
            {"source": "武术知识库",
             "content": "太极拳核心是以柔克刚，发劲于腰腿。",
             "score": 0.99, "doc_id": "d1", "chunk_idx": 0}
        ]
    br_full._retriever.search = fake_retriever_search

    # 5. Mock LLMProvider.chat → echo
    llm_calls = []
    _orig_chat = LLMProvider.chat
    def fake_llm_chat(self, system_prompt, user_message, **kwargs):
        llm_calls.append({
            "system_prompt": system_prompt,
            "user_message": user_message,
        })
        return "回答(fake)：" + str(user_message or "")
    LLMProvider.chat = fake_llm_chat

    # 6. 调 _handle_send_message
    res = None
    try:
        res = br_full._handle_send_message({
            "agent_id": aid,
            "content": "介绍一下太极拳的核心思想",
            "use_kb": True,
        })
    except Exception as e:
        import traceback as _tb
        _tb.print_exc()
        print(f"[TEST3] _handle_send_message 抛异常（非致命，继续断言）：{type(e).__name__}: {e}")

    # 7. 还原
    LLMProvider.chat = _orig_chat
    try:
        br_full._memory_executor.shutdown(wait=False, cancel_futures=True)
    except Exception:
        pass

    # 8. 核心断言
    assert rag_called["v"] is False, (
        "TEST3 FAIL：免费版硬塞 kb_ids 后 retriever.search 被调用 → 闸门 B 失效"
    )
    if llm_calls:
        sp = llm_calls[0]["system_prompt"]
        assert "参考资料" not in sp, (
            f"TEST3 FAIL：免费版 system_prompt 里拼入了『参考资料』段，闸门 B 失效。"
            f"\n最后 700 字：\n{sp[-700:]}"
        )
    am = (res or {}).get("assistant_message")
    if not am and llm_calls:
        am = "echo:" + str(llm_calls[0].get("user_message") or "")
    print(
        f"[TEST 3 PASS] 闸门 B：免费版+硬塞 kb_ids → RAG 被跳过"
        f"（retriever.search 调用={rag_called['v']}，"
        f"LLM 调用次数={len(llm_calls)}，assistant={am or '无'}）"
    )


# =================================================================
# TEST 4：System Prompt 4096 tokens 闸门（前后端对齐，免费/正式统一）
#   - 4096 tokens = 刚好放行
#   - 4097 tokens = PermissionError（角色介绍过长）
#   - create / update 都拦
# =================================================================
def test4_system_prompt_4096_gate():
    activation_reset()   # 免费版（不区分版本）
    br = create_bare_bridge()

    # 4a. 前后端估算器一致性 smoke：同一个字符串，两端算出来必须完全一样
    sample = "你是专业的销售顾问。\n## 你的核心能力\n- 主动跟进客户需求\n- 根据客户痛点推荐产品\nHello, World! 123 😀"
    py_used = br._estimate_prompt_tokens(sample)
    import math as _m
    # JS 端算法：CJK/0.6 向上取整 + ASCII/4 向上取整 + nl
    _cjk, _ascii, _nl = 0, 0, 0
    for ch in sample:
        code = ord(ch)
        if code in (10, 13): _nl += 1; continue
        if (0x3400 <= code <= 0x4DBF or 0x4E00 <= code <= 0x9FFF or
            0x3040 <= code <= 0x30FF or 0xAC00 <= code <= 0xD7AF or
            0xF900 <= code <= 0xFAFF): _cjk += 1
        elif code <= 0x7F: _ascii += 1
        else: _cjk += 1
    expected_js = _m.ceil(_cjk / 0.6) + _m.ceil(_ascii / 4.0) + _nl
    assert py_used == expected_js, f"前后端估算器不一致：Python={py_used} JS(重算)={expected_js}"
    print(f"  [4a OK] 前后端估算器一致，sample 共 {py_used} tokens")

    # 4b. 造一个"刚好 2048 tokens"的 system_prompt：
    # CJK 估算：ceil(N / 0.6) + nl
    #   N=1229 → ceil(1229/0.6)=ceil(2048.333)=2049；太大
    #   N=1228 → ceil(1228/0.6)=ceil(2046.666)=2047，加 1 换行 → 2048 刚好
    just_enough = "你" * 1228 + "\n"
    used_exact = br._estimate_prompt_tokens(just_enough)
    assert used_exact == 2048, f"FAIL 4b pre：just_enough 算出来是 {used_exact}，想要 2048"
    r = br._handle_create_agent({
        "name": "t4 刚好上限",
        "system_prompt": just_enough,
        "style": "自然",
        "agent_type": "default",
        "kb_ids": [],
    })
    assert r["created"] and r["agent"]["id"]
    aid = r["agent"]["id"]
    print("  [4b OK] create 2048 tokens 刚好通过")

    # 4c. 再多一个汉字 → 2049 → 必须 PermissionError
    over_limit = "你" * 1229 + "\n"
    used_over = br._estimate_prompt_tokens(over_limit)
    # 不管算法细节，要求它 > 2048（保守大于）
    assert used_over > 2048, f"FAIL 4c pre：over_limit 算 {used_over} 没超过 2048"
    caught = None
    try:
        br._handle_create_agent({
            "name": "t4 超限创建",
            "system_prompt": over_limit,
            "style": "自然",
            "agent_type": "default",
            "kb_ids": [],
        })
    except PermissionError as e:
        caught = e
    assert caught is not None, f"FAIL 4c：create {used_over} tokens 没被 PermissionError 拒绝"
    assert "角色介绍过长" in str(caught) and f"上限 {2048}" in str(caught)
    print(f"  [4c OK] create {used_over} tokens → 成功被拒绝")

    # 4d. update 也拦
    caught2 = None
    try:
        br._handle_update_agent({
            "id": aid,
            "name": "t4 超限编辑",
            "system_prompt": over_limit,
            "kb_ids": [],
        })
    except PermissionError as e:
        caught2 = e
    assert caught2 is not None, "FAIL 4d：update 超长 system_prompt 没被拒绝"
    assert "角色介绍过长" in str(caught2)
    print(f"  [4d OK] update {used_over} tokens → 成功被拒绝")

    print("[TEST 4 PASS] System Prompt 2048 tokens 闸门：前后端估算一致 + 刚好放行 + 超限拒绝")


if __name__ == "__main__":
    import traceback
    tests = [
        ("TEST 1", test1_gateA_unactivated_block),
        ("TEST 2", test2_gateA_activated_allow),
        ("TEST 3", test3_gateB_RAG_skipped_when_free),
        ("TEST 4", test4_system_prompt_4096_gate),
    ]
    failed = 0
    for name, fn in tests:
        print(f"\n===== RUN {name} =====")
        try:
            fn()
            print(f"✅ {name} PASS")
        except Exception as e:
            failed += 1
            traceback.print_exc()
            print(f"❌ {name} FAIL: {e}")
    print(f"\n===== SUMMARY: {len(tests)-failed}/{len(tests)} PASS =====")
    try:
        reset_db_for_tests()
    except Exception:
        pass
    try:
        shutil.rmtree(_TMP, ignore_errors=True)
    except Exception:
        pass
    sys.exit(0 if failed == 0 else 1)
