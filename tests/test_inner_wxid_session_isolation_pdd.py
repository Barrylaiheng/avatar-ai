# -*- coding: utf-8 -*-
"""
P3-2 · wxid 会话隔离修复 — pytest 测试用例

Bug #11: AppEngine.process_message 硬编码 wxid="ui_user"，所有微信用户
         共用同一会话上下文 → 隐私泄露 P0

修复：process_message / process_message_stream 新增 wxid 参数（默认 "ui_user"），
      _handle_wechat_message 传入 wxid=msg.sender_id

6 Grill 覆盖：
  G1. process_message 签名含 wxid 参数，默认值="ui_user"
  G2. 不同 wxid → 不同 session
  G3. _handle_wechat_message 调用时传 wxid=msg.sender_id
  G4. process_message_stream 签名含 wxid 参数
  G5. UI 路径（不传 wxid）仍使用默认 "ui_user"（向后兼容）
  G6. 两个不同 wxid 用户上下文隔离
"""
import os
import sys
import shutil
import json
import inspect
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

TMP = str(ROOT / "tests" / "data" / "tmp_p32_pytest")
TMP = TMP.replace("\\", "/")
if Path(TMP).exists():
    shutil.rmtree(TMP, ignore_errors=True)
Path(TMP).mkdir(parents=True, exist_ok=True)
os.environ["SCAI_DATA_DIR"] = TMP
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_OFFLINE"] = "1"

cfg_path = Path(TMP) / "config.json"
with open(cfg_path, "w", encoding="utf-8") as f:
    json.dump({
        "llm_api_key": "test-key", "llm_provider": "kimi", "llm_model": "auto",
        "llm_base_url": "https://test.mock/v1",
        "kb_wiki_root": f"{TMP}/wiki", "oa_cloud_base_url": "",
    }, f, ensure_ascii=False, indent=2)


@pytest.fixture(scope="module")
def engine():
    from aibridge.app_engine import AppEngine
    eng = AppEngine()
    eng.initialize()
    # Mock LLM 生成器避免真实 API 调用
    mock_llm = MagicMock()
    mock_llm.generate.return_value = {
        "content": "测试回复", "model": "mock", "tokens_in": 10, "tokens_out": 5,
    }
    eng._llm_generator = mock_llm
    return eng


# ============================================================
# G1. process_message 签名含 wxid 参数，默认值="ui_user"
# ============================================================

def test_g1_process_message_has_wxid_param(engine):
    """G1-1: process_message 签名包含 wxid 参数"""
    sig = inspect.signature(engine.process_message)
    params = list(sig.parameters.keys())
    assert "wxid" in params, f"process_message 应含 wxid 参数，实际 params={params}"


def test_g1_wxid_default_is_ui_user(engine):
    """G1-2: wxid 参数默认值为 'ui_user'"""
    sig = inspect.signature(engine.process_message)
    assert "wxid" in sig.parameters
    assert sig.parameters["wxid"].default == "ui_user", (
        f"wxid 默认值应为 'ui_user'，实际={sig.parameters['wxid'].default!r}"
    )


def test_g1_wxid_after_session_id(engine):
    """G1-3: wxid 参数位于 session_id 之后"""
    sig = inspect.signature(engine.process_message)
    params = list(sig.parameters.keys())
    assert params.index("wxid") > params.index("session_id"), (
        f"wxid 应在 session_id 之后，实际顺序={params}"
    )


# ============================================================
# G2. 不同 wxid → 不同 session
# ============================================================

def test_g2_different_wxid_different_session(engine):
    """G2: 不同 wxid 创建不同 session"""
    ca = engine._context_assembler
    session_a = ca.get_or_create_session(wxid="wxid_test_A", session_type="chat")
    session_b = ca.get_or_create_session(wxid="wxid_test_B", session_type="chat")

    assert session_a.wxid == "wxid_test_A"
    assert session_b.wxid == "wxid_test_B"
    assert session_a.session_id != session_b.session_id, (
        f"不同 wxid 的 session_id 应不同：a={session_a.session_id}, b={session_b.session_id}"
    )


def test_g2_same_wxid_reuses_session(engine):
    """G2-5: 同一 wxid 复用 active session"""
    ca = engine._context_assembler
    session_1 = ca.get_or_create_session(wxid="wxid_reuse_test", session_type="chat")
    session_2 = ca.get_or_create_session(wxid="wxid_reuse_test", session_type="chat")
    assert session_1.session_id == session_2.session_id, (
        f"同 wxid 应复用 session：1={session_1.session_id}, 2={session_2.session_id}"
    )


# ============================================================
# G3. _handle_wechat_message 调用时传 wxid=msg.sender_id
# ============================================================

def test_g3_handle_wechat_passes_wxid(engine):
    """G3: _handle_wechat_message 调用时传 wxid=msg.sender_id
    P3-3 后流程默认走 15 步流水线 process_v2 → process_v2 的 sender_wxid 必须为 msg.sender_id。
    当强制 _message_processor=None 走 fallback 简化路径时，process_message 的 wxid 也必须为 msg.sender_id。
    两路径双验证，确保 P3-2 的 wxid 会话隔离在 P3-3 新架构下仍有效。
    """
    from aibridge.bridges.internal_message import InternalMessage

    msg = InternalMessage(
        msg_id="msg_g3_001", channel="wechat", sender_id="wxid_g3_customer",
        sender_name="G3客户", receiver_id="bot_wxid", content="你好",
        msg_type="text", group_id="", group_name="", is_at_me=False,
        is_private=True, timestamp=1234567890,
    )

    # --------- 路径A：P3-3 新默认 process_v2 ----------
    if engine._message_processor is not None:
        from aibridge.bridges.utils import map_internal_to_processor
        expect_kwargs = map_internal_to_processor(msg, master_wxid_set=engine._master_wxid_set)
        with patch.object(engine._message_processor,
                          'process_v2', wraps=engine._message_processor.process_v2) as mock_v2:
            engine._handle_wechat_message(msg)
            assert mock_v2.called, "process_v2 应被调用（新默认路径）"
            actual_kw = mock_v2.call_args.kwargs
            assert actual_kw.get("sender_wxid") == "wxid_g3_customer", (
                f"process_v2 的 sender_wxid 应=msg.sender_id='wxid_g3_customer'，"
                f"实际={actual_kw.get('sender_wxid')}"
            )

    # --------- 路径B：P3-3 fallback 简化路径 ----------
    mp_backup = engine._message_processor
    engine._message_processor = None  # 强制走简化路径
    try:
        with patch.object(engine, 'process_message', wraps=engine.process_message) as mock_pm:
            engine._handle_wechat_message(msg)
            assert mock_pm.called, "简化路径下 process_message 应被调用"
            kw = mock_pm.call_args
            assert kw.kwargs.get("wxid") == "wxid_g3_customer", (
                f"简化路径 wxid 应=msg.sender_id='wxid_g3_customer'，"
                f"实际={kw.kwargs.get('wxid')}"
            )
    finally:
        engine._message_processor = mp_backup


# ============================================================
# G4. process_message_stream 签名含 wxid 参数
# ============================================================

def test_g4_stream_has_wxid_param(engine):
    """G4-1: process_message_stream 签名含 wxid 参数"""
    sig = inspect.signature(engine.process_message_stream)
    params = list(sig.parameters.keys())
    assert "wxid" in params, f"process_message_stream 应含 wxid 参数，实际 params={params}"


def test_g4_stream_wxid_default(engine):
    """G4-2: process_message_stream wxid 默认值为 'ui_user'"""
    sig = inspect.signature(engine.process_message_stream)
    assert sig.parameters["wxid"].default == "ui_user"


# ============================================================
# G5. UI 路径（不传 wxid）仍使用默认 'ui_user'（向后兼容）
# ============================================================

def test_g5_ui_path_uses_default_wxid(engine):
    """G5: UI 路径不传 wxid 时使用默认 'ui_user'"""
    result = engine.process_message("你好", session_id="ui_session_g5")
    assert "content" in result, f"UI 调用应返回 content，实际 keys={list(result.keys())}"

    db = engine._db
    db.execute("SELECT wxid FROM sessions WHERE wxid='ui_user' AND status='active' LIMIT 1")
    row = db.fetchone()
    assert row is not None, "UI 路径应在 sessions 表中有 wxid='ui_user' 的记录"


# ============================================================
# G6. 两个不同 wxid 用户上下文隔离
# ============================================================

def test_g6_session_isolation_in_db(engine):
    """G6: 两个不同 wxid 用户的 session 在 DB 中隔离"""
    ca = engine._context_assembler
    db = engine._db

    session_a = ca.get_or_create_session(wxid="wxid_iso_A", session_type="chat")
    session_b = ca.get_or_create_session(wxid="wxid_iso_B", session_type="chat")

    db.execute(
        "SELECT session_id, wxid FROM sessions WHERE wxid IN (?, ?) AND status='active'",
        ("wxid_iso_A", "wxid_iso_B")
    )
    rows = db.fetchall()
    assert len(rows) == 2, f"sessions 表应有 2 条记录，实际 {len(rows)}"

    wxids = [r[1] for r in rows]
    assert "wxid_iso_A" in wxids, f"wxid_iso_A 应在 DB 中，实际 {wxids}"
    assert "wxid_iso_B" in wxids, f"wxid_iso_B 应在 DB 中，实际 {wxids}"

    session_ids = [r[0] for r in rows]
    assert len(set(session_ids)) == 2, f"两个 session_id 应不同，实际 {session_ids}"
