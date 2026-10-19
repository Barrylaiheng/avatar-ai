# -*- coding: utf-8 -*-
"""
P3-3 · 15 步流水线集成 pytest 测试用例
覆盖 Grill G1~G6：AppEngine._message_processor 实例化、master_wxid_set、
              群聊静默/私聊回复/安全拦截/主人同步/回退路径/UI 兼容

运行:
  $env:TRANSFORMERS_OFFLINE="1"; $env:HF_HUB_OFFLINE="1"
  $env:SCAI_DATA_DIR=".../tmp_p33_pytest"
  python -m pytest tests/test_inner_pipeline_integration_pdd.py -v
"""
from __future__ import annotations
import os
import sys
import shutil
import json
from pathlib import Path
from typing import Dict, Any
from unittest.mock import patch, MagicMock, call

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


@pytest.fixture
def tmp_scai_data_dir(tmp_path):
    d = tmp_path / "tmp_p33_pytest"
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)
    old = os.environ.get("SCAI_DATA_DIR")
    os.environ["SCAI_DATA_DIR"] = str(d).replace("\\", "/")
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_OFFLINE"] = "1"

    cfg_path = d / "config.json"
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump({
            "llm_api_key": "MOCK_P33", "llm_provider": "mock", "llm_model": "auto",
            "llm_base_url": "https://test.mock/v1",
            "kb_wiki_root": str(d / "wiki").replace("\\", "/"),
            "oa_cloud_base_url": "",
            "master_wxid": "wxid_master_p33",
            "master_wxid_list": ["wxid_master_second"],
        }, f, ensure_ascii=False, indent=2)
    yield str(d).replace("\\", "/")
    if old:
        os.environ["SCAI_DATA_DIR"] = old
    else:
        os.environ.pop("SCAI_DATA_DIR", None)


@pytest.fixture
def engine(tmp_scai_data_dir):
    from aibridge.app_engine import AppEngine
    engine = AppEngine()
    ok = engine.initialize()
    assert ok, "AppEngine.initialize() 必须成功"
    # mock LLM generator 避免真实请求
    mock_llm = MagicMock()
    mock_llm.generate.return_value = {"content": "Mock LLM 回复", "model": "mock",
                                       "tokens_in": 10, "tokens_out": 5}
    engine._llm_generator = mock_llm
    # 如果有 process_v2 内部的 llm generator，也替换
    if engine._message_processor is not None:
        engine._message_processor._llm_generator = mock_llm
    yield engine


def make_im(msg_id, sender_id, content, *,
            group_id="", group_name="", is_at_me=False, is_private=None):
    from aibridge.bridges.internal_message import InternalMessage
    if is_private is None:
        is_private = not bool(group_id)
    return InternalMessage(
        msg_id=msg_id, channel="wechat", sender_id=sender_id,
        sender_name=f"n_{sender_id}", receiver_id="self_bot_wxid",
        content=content, msg_type="text",
        group_id=group_id, group_name=group_name,
        is_at_me=is_at_me, is_private=is_private,
        timestamp=1000000000 + int(msg_id[-3:]) if msg_id[-3:].isdigit() else 1000000001,
    )


# --------- T1 · _message_processor 实例化 ---------
def test_t1_message_processor_instantiated(engine):
    from aibridge.engine.message_processor import MessageProcessor
    mp = getattr(engine, "_message_processor", None)
    assert mp is not None, "AppEngine.initialize() 后 _message_processor 不能为 None"
    assert isinstance(mp, MessageProcessor), (
        f"_message_processor 类型错误：{type(mp).__name__}"
    )


# --------- T2 · master_wxid_set 正确性 ---------
def test_t2_master_wxid_set(engine):
    mset = getattr(engine, "_master_wxid_set", None)
    assert mset is not None, "_master_wxid_set 属性必须存在"
    assert isinstance(mset, set), f"_master_wxid_set 应为 set，实际 {type(mset).__name__}"
    assert "wxid_master_p33" in mset, f"master_wxid 应在集合中：{mset}"
    assert "wxid_master_second" in mset, f"master_wxid_list 应在集合中：{mset}"


# --------- T3 · 群聊无@机器人 → 不 send_response ---------
def test_t3_group_no_at_silent_drop(engine):
    msg = make_im("t3_001", "wxid_g_user", "今天天气不错",
                  group_id="g_wxid_fruit", group_name="水果交流群",
                  is_at_me=False)
    with patch.object(engine, "send_response", wraps=engine.send_response) as mock_sr:
        engine._handle_wechat_message(msg)
        assert not mock_sr.called, (
            f"群聊无@机器人不应 send_response，实际被调用 {mock_sr.call_count} 次"
        )


# --------- T4 · 群聊@机器人 → send_response 被调用 ---------
def test_t4_group_at_me_reply(engine):
    msg = make_im("t4_001", "wxid_g_user", "@我 有苹果吗",
                  group_id="g_wxid_fruit", group_name="水果交流群",
                  is_at_me=True)
    with patch.object(engine, "send_response", wraps=engine.send_response) as mock_sr:
        engine._handle_wechat_message(msg)
        assert mock_sr.called, "群聊@机器人应 send_response"


# --------- T5 · 私聊文本 → send_response 参数正确 ---------
def test_t5_private_reply_sent(engine):
    msg = make_im("t5_001", "wxid_pvt_user", "有阿克苏苹果吗？")
    with patch.object(engine, "send_response", wraps=engine.send_response) as mock_sr:
        engine._handle_wechat_message(msg)
        assert mock_sr.called, "私聊应 send_response"
        args = mock_sr.call_args
        # send_response(msg, reply_content)
        first_arg = args[0][0] if args[0] else None
        second_arg = args[0][1] if len(args[0]) > 1 else args.kwargs.get("reply_content", "")
        assert first_arg is msg, f"send_response 第一参数应为 msg 对象，实际 {type(first_arg)}"
        assert isinstance(second_arg, str) and len(second_arg) > 0, (
            f"回复内容应为非空字符串，实际 '{second_arg}'"
        )


# --------- T6 · 砍价消息 → 回复含警告关键词 ---------
def test_t6_safety_kanjia_hit(engine):
    from aibridge.bridges.utils import map_internal_to_processor
    msg = make_im("t6_001", "wxid_kanjia", "帮我拼多多砍价助力一下！")
    kwargs = map_internal_to_processor(msg, master_wxid_set=engine._master_wxid_set)
    result = engine._message_processor.process_v2(**kwargs)
    content = getattr(result, "content", "") or ""
    warning_words = ["砍价", "砍价", "⚠", "警告", "禁止", "不允许", "群规"]
    assert any(w in content for w in warning_words), (
        f"砍价消息应被拦截（含警告关键词），实际 content={content[:100]}"
    )


# --------- T7 · 安全命中 → write_audit_log=True ---------
def test_t7_safety_writes_audit(engine):
    from aibridge.bridges.utils import map_internal_to_processor
    msg = make_im("t7_001", "wxid_audit", "扫码免费送手机！帮我砍价！")
    kwargs = map_internal_to_processor(msg, master_wxid_set=engine._master_wxid_set)
    result = engine._message_processor.process_v2(**kwargs)
    write_audit = getattr(result, "write_audit_log", False)
    assert write_audit is True, (
        f"安全命中应 write_audit_log=True，实际 write_audit_log={write_audit}"
    )


# --------- T8 · 主人消息 → send_response 不被调用（仅同步历史） ---------
def test_t8_master_message_only_sync(engine):
    # 使用 master_wxid 集合中的 wxid 作为 sender
    master_wxid = "wxid_master_p33"
    msg = make_im("t8_001", master_wxid, "机器人上线了吗？")
    with patch.object(engine, "send_response", wraps=engine.send_response) as mock_sr:
        engine._handle_wechat_message(msg)
        assert not mock_sr.called, (
            f"主人消息不应被 AI 回复（仅同步历史），实际被调用 {mock_sr.call_count} 次"
        )


# --------- T9 · process_message (UI 路径) 向后兼容 ---------
def test_t9_ui_process_message_works(engine):
    result = engine.process_message("你好，介绍一下产品", session_id="ui_sess_p33")
    assert isinstance(result, dict), f"process_message 应返回 dict，实际 {type(result).__name__}"
    assert "content" in result, f"返回应含 content 键，实际 keys={list(result.keys())}"
    assert isinstance(result["content"], str), (
        f"content 应为字符串，实际 {type(result['content']).__name__}"
    )


# --------- T10 · process_v2 异常 → 回退路径仍回复 ---------
def test_t10_process_v2_exception_fallback(engine):
    mp = engine._message_processor
    assert mp is not None, "测试前提：_message_processor 必须已实例化"

    def raise_panic(**_k):
        raise RuntimeError("mock process_v2 故障")

    msg = make_im("t10_001", "wxid_fb_user", "测试回退路径")
    with patch.object(mp, "process_v2", side_effect=raise_panic):
        with patch.object(engine, "send_response", wraps=engine.send_response) as mock_sr:
            engine._handle_wechat_message(msg)
            assert mock_sr.called, (
                "process_v2 异常时，回退路径仍应 send_response（消息不丢失）"
            )
