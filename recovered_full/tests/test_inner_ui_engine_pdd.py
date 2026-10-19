# -*- coding: utf-8 -*-
"""
SCAI · 里层 PDD · 模块 7 · Phase 5 TDD
模块：INNER-UI07 · UI ↔ Engine 数据流打通
Seams: 15
规范：docs/PDD_INNER_ui_engine_flow.md
原型：_prototypes/ui_engine_flow_prototype.py（15/15 全绿）

运行：
    pytest tests/test_inner_ui_engine_pdd.py -v
    # 预期：15 passed
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


# ---------------------------------------------------------------------------
# MockAppEngine：同 _prototypes/ui_engine_flow_prototype.py 中的实现
# 因为正式 AppEngine 尚未完全对接，此阶段以 Mock 为准（Phase 5 TDD 后可替换）
# ---------------------------------------------------------------------------

sys.path.insert(0, str(PROJECT_ROOT / "_prototypes"))
from ui_engine_flow_prototype import MockAppEngine  # noqa: E402


@pytest.fixture
def engine():
    return MockAppEngine()


@pytest.fixture
def engine_with_key(engine):
    engine.save_settings({"provider": "deepseek", "api_key": "sk-test"})
    return engine


@pytest.fixture
def engine_with_kb(engine_with_key):
    engine_with_key.initialize(kb_root="/mock/kb")
    return engine_with_key


# ============================================================
# UI-01: PersonaEditor 保存 → engine.persona 更新
# ============================================================
def test_ui01_persona_save_and_read(engine):
    persona = {
        "identity": "你是 Barry，AI 数字分身实战导师。",
        "tone": "专业、有温度、偶尔幽默。",
        "knowledge_boundary": "只讲自己跑通过的案例，不编造。",
        "reply_rules": "回复不超过 250 字，一次一个步骤。",
        "safety_bottomline": "不讨论政治色情暴力。",
        "examples": "用户：怎么做数字分身？\nBarry：第一步先整理你的知识库。",
        "language_style": "用「我们」不用「您」，可以加 emoji。",
    }
    ok = engine.save_persona(persona)
    assert ok, "save_persona 返回 False"
    saved = engine.get_persona()
    for k, v in persona.items():
        assert saved[k] == v, f"Persona 字段 {k} 不匹配"


# ============================================================
# UI-02: RAG Reader 注入
# ============================================================
def test_ui02_rag_injection_on_initialize(engine_with_key):
    e = engine_with_key
    # 未 init：rag_count=0
    r = e.process_message("什么是 PDD？")
    assert r["rag_count"] == 0
    # init
    e.initialize(kb_root="/mock/kb")
    r2 = e.process_message("什么是 PDD？")
    assert r2["rag_count"] >= 1
    assert r2["system_has_knowledge"] is True


# ============================================================
# UI-03: ChatPage → process_message → 标准 8 字段
# ============================================================
def test_ui03_process_message_returns_std_fields(engine_with_key):
    r = engine_with_key.process_message("你好")
    # 8 个核心字段
    for k in ["content", "is_aigc", "tool_calls", "rag_count",
              "model", "tokens_in", "tokens_out", "safety_check"]:
        assert k in r, f"返回结构缺失字段 {k}"
    assert isinstance(r["content"], str) and r["content"], "content 非空字符串"
    assert r["is_aigc"] is True
    # 其他调试字段
    for k in ["intent", "fallback", "bad_case_written"]:
        assert k in r, f"返回结构缺失调试字段 {k}"


# ============================================================
# UI-04: KB 开关切换
# ============================================================
def test_ui04_kb_toggle_affects_rag_count(engine_with_kb):
    e = engine_with_kb
    # on
    r_on = e.process_message("PDD 是什么？")
    assert r_on["rag_count"] >= 1, f"KB 开时 rag_count>=1, got {r_on['rag_count']}"
    # off
    e.set_kb_enabled(False)
    r_off = e.process_message("PDD 是什么？")
    assert r_off["rag_count"] == 0
    assert e.is_kb_enabled() is False
    # on 再开
    e.set_kb_enabled(True)
    r_on2 = e.process_message("PDD 是什么？")
    assert r_on2["rag_count"] >= 1


# ============================================================
# UI-05: tool_calls 字段稳定（接口契约）
# ============================================================
def test_ui05_tool_calls_field_stable_even_when_empty(engine_with_key):
    r = engine_with_key.process_message("随便说点啥")
    assert "tool_calls" in r
    assert isinstance(r["tool_calls"], list)
    # 空消息也应有 tool_calls 字段
    r2 = engine_with_key.process_message("")
    assert "tool_calls" in r2


# ============================================================
# UI-06: Workbench 消息列表
# ============================================================
def test_ui06_workbench_wechat_channel_messages(engine_with_key):
    e = engine_with_key
    e.connect_wcf()
    e._on_wcf_message({"msg_id": "m1", "content": "你好", "sender_wxid": "wxid_a"})
    e._on_wcf_message({"msg_id": "m2", "content": "CPS 怎么搞？", "sender_wxid": "wxid_b"})
    msgs = e.get_channel_messages("wechat", limit=10)
    assert len(msgs) >= 2
    mp_msgs = e.get_channel_messages("mp", limit=10)
    assert mp_msgs == [], "mp 渠道 MVP 阶段返回空"


# ============================================================
# UI-07: Workbench 手动发消息
# ============================================================
def test_ui07_workbench_send_channel_message(engine):
    engine.connect_wcf()
    # WCF 已连接
    ok1 = engine.send_channel_message("wechat", "wxid_c", "你好呀")
    assert ok1
    assert engine._wcf and len(engine._wcf._sent) >= 1
    # WCF 断开
    engine.disconnect_wcf()
    ok2 = engine.send_channel_message("wechat", "wxid_c", "再发一条")
    assert ok2 is False
    # 错渠道
    ok3 = engine.send_channel_message("mp", "gh_x", "test")
    assert ok3 is False


# ============================================================
# UI-08: WCF 连接状态切换
# ============================================================
def test_ui08_wcf_connect_disconnect_state(engine):
    assert engine.is_wcf_connected() is False, "初始状态应为未连接"
    ok = engine.connect_wcf()
    assert ok
    assert engine.is_wcf_connected() is True
    engine.disconnect_wcf()
    assert engine.is_wcf_connected() is False


# ============================================================
# UI-09: WCF 收消息 → process → Store → 回发
# ============================================================
def test_ui09_wcf_incoming_full_flow(engine_with_key):
    e = engine_with_key
    e.connect_wcf()
    store_before = len(e._store._records)
    sent_before = len(e._wcf._sent) if e._wcf else 0
    e._on_wcf_message({
        "msg_id": "ui09_1", "content": "你好", "sender_wxid": "wxid_test1",
    })
    store_after = len(e._store._records)
    sent_after = len(e._wcf._sent) if e._wcf else 0
    assert store_after > store_before, f"写入 Store: {store_before} -> {store_after}"
    assert sent_after > sent_before, f"WCF 回发: {sent_before} -> {sent_after}"
    last_sent = e._wcf._sent[-1] if e._wcf else None
    assert last_sent and last_sent[1], "回发内容不应为空"


# ============================================================
# UI-10: 主人消息 → 同步历史 direction=out，不回复
# ============================================================
def test_ui10_master_message_sync_only(engine):
    engine.connect_wcf()
    engine.set_master_wxid("wxid_barry")
    sent_before = len(engine._wcf._sent) if engine._wcf else 0
    store_before = len(engine._store._records)
    engine._on_wcf_message({
        "msg_id": "u10_master",
        "content": "今天天气不错",
        "sender_wxid": "wxid_barry",
    })
    sent_after = len(engine._wcf._sent) if engine._wcf else 0
    store_after = len(engine._store._records)
    assert sent_after == sent_before, f"主人消息不应 WCF 回发，sent_before={sent_before} after={sent_after}"
    assert store_after > store_before, "主人消息应写入历史"
    last_rec = engine._store._records[-1]
    assert last_rec.get("direction") == "out", f"主人消息 direction 应为 'out', got {last_rec.get('direction')}"


# ============================================================
# UI-11: AIGC 显式标识开关
# ============================================================
def test_ui11_aigc_explicit_toggle(engine_with_key):
    e = engine_with_key
    # 关
    e.save_settings({"aigc_explicit": False})
    r_off = e.process_message("你好")
    assert not r_off["content"].endswith("[AI]"), "AIGC 关时回复不应有 [AI] 尾巴"
    # 开
    e.save_settings({"aigc_explicit": True})
    r_on = e.process_message("你好")
    assert r_on["content"].endswith("[AI]"), f"AIGC 开时回复应以 [AI] 结尾, got: ...{r_on['content'][-20:]}"
    # aigc_metadata 字段
    assert r_off["aigc_metadata"]["explicit"] is False
    assert r_on["aigc_metadata"]["explicit"] is True


# ============================================================
# UI-12: LLM Key 保存 + test_llm_connection
# ============================================================
def test_ui12_llm_save_and_test_connection(engine):
    # 未配置
    t1 = engine.test_llm_connection()
    assert t1["success"] is False
    assert t1["provider"] == "deepseek"
    # 配置有效 Key
    engine.save_settings({"provider": "deepseek", "api_key": "sk-valid-key"})
    t2 = engine.test_llm_connection()
    assert t2["success"] is True, f"test_llm_connection 应成功: {t2}"
    assert t2.get("model"), "成功时应返回 model"


# ============================================================
# UI-13: 七段式 Persona → persona_segments
# ============================================================
def test_ui13_persona_segments_count(engine_with_key):
    e = engine_with_key
    r_full = e.process_message("测试")
    assert r_full.get("persona_segments") == 7, f"完整人设 persona_segments 应=7, got {r_full.get('persona_segments')}"
    # 缺 1 段
    partial = {
        "identity": "身份", "tone": "语气",
        "reply_rules": "规则", "safety_bottomline": "底线",
        "examples": "示例", "language_style": "风格",
    }
    e.save_persona(partial)
    r_partial = e.process_message("测试")
    assert r_partial.get("persona_segments") == 6, f"缺 knowledge_boundary 段后应为 6, got {r_partial.get('persona_segments')}"


# ============================================================
# UI-14: RAG rag_count 正确性
# ============================================================
def test_ui14_rag_count_hit_vs_miss(engine_with_kb):
    e = engine_with_kb
    r_hit = e.process_message("请讲一下 PDD 方法论")
    assert r_hit["rag_count"] >= 1, f"命中查询 rag_count>=1, got {r_hit['rag_count']}"
    r_miss = e.process_message("今天吃什么？今晚去哪里玩？")
    assert r_miss["rag_count"] == 0, f"无关查询 rag_count 应=0, got {r_miss['rag_count']}"


# ============================================================
# UI-15: BadCase 写入并可查
# ============================================================
def test_ui15_bad_case_written_queryable(engine):
    before = len(engine.get_bad_cases())
    # 不配 Key → fallback
    engine.process_message("你好呀")
    after = len(engine.get_bad_cases())
    assert after > before, f"fallback 时应写 BadCase: before={before} after={after}"
    case = engine.get_bad_cases()[-1]
    reasons_text = " ".join(case.get("reasons", []))
    assert "API Key 未配置" in reasons_text, f"BadCase reasons 应含 API Key 信息: {case.get('reasons')}"
