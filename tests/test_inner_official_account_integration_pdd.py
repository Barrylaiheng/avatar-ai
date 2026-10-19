# -*- coding: utf-8 -*-
"""
P3-5 · 公众号渠道集成修复 pytest 测试用例
覆盖 G1~G6：
  G1: OfficialAccountAdapter.health_check() 结构合法不误导
  G2: get_channel_messages wechat_mp / mp 双别名支持
  G3: get_workspace_stats 双别名 + channel 回显
  G4: AppEngine 注册 wechat_mp handler + route 正常
  G5: CHANNEL_NAME 与 CHANNEL_TO_SESSION_TYPE 对齐
  G6: get_channel_health 聚合 OACloudClient 云端健康状态

运行:
  $env:TRANSFORMERS_OFFLINE="1"; $env:HF_HUB_OFFLINE="1"
  python -m pytest tests/test_inner_official_account_integration_pdd.py -v
"""
from __future__ import annotations
import os, sys, shutil, json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


@pytest.fixture
def tmp_scai_data_dir(tmp_path):
    d = tmp_path / "tmp_p35_pytest"
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
            "llm_api_key": "MOCK_P35", "llm_provider": "mock", "llm_model": "auto",
            "llm_base_url": "https://test.mock/v1",
            "kb_wiki_root": str(d / "wiki").replace("\\", "/"),
            "oa_cloud_base_url": "", "master_wxid": "wxid_master_p35",
        }, f, ensure_ascii=False, indent=2)
    yield str(d).replace("\\", "/")
    if old:
        os.environ["SCAI_DATA_DIR"] = old
    else:
        os.environ.pop("SCAI_DATA_DIR", None)


@pytest.fixture
def engine(tmp_scai_data_dir):
    from aibridge.app_engine import AppEngine
    e = AppEngine()
    assert e.initialize(), "AppEngine.initialize() 必须成功"
    yield e


# --------- T1 · G5 CHANNEL_NAME 与 CHANNEL_TO_SESSION_TYPE 键名对齐 ---------
def test_t1_g5_channel_name_alignment():
    """G5: OfficialAccountAdapter.CHANNEL_NAME 与 CHANNEL_TO_SESSION_TYPE 键名对齐"""
    from aibridge.bridges.official_account_adapter import OfficialAccountAdapter
    from aibridge.bridges.utils import CHANNEL_TO_SESSION_TYPE

    adapter_name = OfficialAccountAdapter.CHANNEL_NAME
    assert adapter_name in CHANNEL_TO_SESSION_TYPE, (
        f"OfficialAccountAdapter.CHANNEL_NAME={adapter_name} "
        f"不在 CHANNEL_TO_SESSION_TYPE 键中: {list(CHANNEL_TO_SESSION_TYPE.keys())}"
    )
    assert CHANNEL_TO_SESSION_TYPE[adapter_name] == "mp", (
        f"公众号渠道 session_type 应为 'mp'，实际={CHANNEL_TO_SESSION_TYPE[adapter_name]}"
    )


# --------- T2 · G1 OfficialAccountAdapter.health_check() 结构合法 ---------
def test_t2_g1_oa_health_check_struct():
    """G1: OfficialAccountAdapter.health_check() 返回合法结构（channel/connected 必需）"""
    from aibridge.bridges.official_account_adapter import OfficialAccountAdapter

    oa = OfficialAccountAdapter(app_id="wx_test", token="test_token")
    result = oa.health_check()
    assert isinstance(result, dict), "health_check() 必须返回 dict"
    assert "channel" in result, "必须包含 channel 字段"
    assert "connected" in result, "必须包含 connected 字段"
    assert result["channel"] == OfficialAccountAdapter.CHANNEL_NAME
    assert result["connected"] == oa.is_connected()


# --------- T3 · G4 wechat_mp handler 已注册 ---------
def test_t3_g4_mp_handler_registered(engine):
    """G4-a: AppEngine.initialize() 后 wechat_mp 渠道 handler 列表非空"""
    handlers = engine._message_router.get_registered_handlers("wechat_mp")
    assert len(handlers) >= 1, (
        f"wechat_mp 渠道 handler 未注册！已注册: "
        f"{list(engine._message_router._handlers.keys())}"
    )


def test_t4_g4_mp_handler_routable(engine):
    """G4-b: route wechat_mp 渠道消息时 handler 被调用（不 warning 不崩溃）"""
    from aibridge.bridges.internal_message import InternalMessage

    handlers = engine._message_router.get_registered_handlers("wechat_mp")
    assert len(handlers) >= 1

    msg = InternalMessage(
        msg_id="msg_p35_t4_001", channel="wechat_mp",
        sender_id="openid_t4_user", sender_name="T4公众号用户",
        receiver_id="wx_mp_appid", content="测试公众号路由",
        msg_type="text", group_id="", group_name="", is_at_me=False,
        is_private=True, timestamp=1234567890,
    )

    mock_handler = MagicMock()
    original_handlers = list(handlers)
    try:
        engine._message_router._handlers["wechat_mp"] = [mock_handler]
        engine.route_message(msg)
        assert mock_handler.called, "route wechat_mp 消息后 handler 应被调用"
    finally:
        engine._message_router._handlers["wechat_mp"] = original_handlers


# --------- T5 · G2 get_channel_messages 双别名 ---------
def test_t5_g2_get_channel_messages_dual_alias(engine):
    """G2: get_channel_messages('wechat_mp') / get_channel_messages('mp') 都返回 list 不崩溃"""
    r1 = engine.get_channel_messages("wechat_mp", limit=5)
    assert isinstance(r1, list), f"'wechat_mp' 别名必须返回 list，实际={type(r1)}"

    r2 = engine.get_channel_messages("mp", limit=5)
    assert isinstance(r2, list), f"'mp' 别名必须返回 list，实际={type(r2)}"


# --------- T6 · G3 get_workspace_stats 双别名 + channel 回显 ---------
def test_t6_g3_get_workspace_stats_wechat_mp(engine):
    """G3-a: get_workspace_stats('wechat_mp') channel 回显 = 'wechat_mp'"""
    s = engine.get_workspace_stats("wechat_mp")
    assert isinstance(s, dict)
    assert s["channel"] == "wechat_mp", (
        f"channel 回显应与入参一致 'wechat_mp'，实际={s['channel']}"
    )
    for key in ("total_messages", "avg_response_time", "satisfaction"):
        assert key in s, f"缺少必需字段 {key}: {s}"


def test_t7_g3_get_workspace_stats_mp(engine):
    """G3-b: get_workspace_stats('mp') channel 回显 = 'mp'"""
    s = engine.get_workspace_stats("mp")
    assert isinstance(s, dict)
    assert s["channel"] == "mp", (
        f"channel 回显应与入参一致 'mp'，实际={s['channel']}"
    )


# --------- T8 · G6 get_channel_health 聚合云端健康状态 ---------
def test_t8_g6_channel_health_no_client(engine):
    """G6-a: 无 OACloudClient 时沿用适配器自身状态，channel 回显正确"""
    from aibridge.bridges.official_account_adapter import OfficialAccountAdapter
    oa_adapter = OfficialAccountAdapter(app_id="wx_test", token="test_token")
    oa_adapter._connected = False
    engine._message_router.register_adapter(oa_adapter)

    h = engine.get_channel_health("wechat_mp")
    assert h["channel"] == "wechat_mp", f"channel 回显错误: {h}"


def test_t9_g6_channel_health_cloud_online(engine):
    """G6-b: 云端在线时，即使本地适配器未连接，connected=True"""
    from aibridge.bridges.official_account_adapter import OfficialAccountAdapter
    oa_adapter = OfficialAccountAdapter(app_id="wx_test", token="test_token")
    oa_adapter._connected = False
    engine._message_router.register_adapter(oa_adapter)

    mock_client = MagicMock()
    mock_client.is_configured = True
    mock_client.health_check.return_value = True
    mock_client.get_stats.return_value = {
        "is_configured": True, "base_url": "https://oa.test.com",
        "last_pull_count": 3, "last_error": "", "is_online": True,
    }
    engine._oa_cloud_client = mock_client

    h = engine.get_channel_health("wechat_mp")
    assert h["connected"] is True, (
        f"云端在线时 connected 应为 True，实际={h.get('connected')}"
    )
    assert h.get("oa_cloud_online") is True


def test_t10_g6_channel_health_cloud_offline(engine):
    """G6-c: 云端离线时，connected=False + 明细字段保留"""
    from aibridge.bridges.official_account_adapter import OfficialAccountAdapter
    oa_adapter = OfficialAccountAdapter(app_id="wx_test", token="test_token")
    oa_adapter._connected = False
    engine._message_router.register_adapter(oa_adapter)

    mock_client = MagicMock()
    mock_client.is_configured = True
    mock_client.health_check.return_value = False
    mock_client.get_stats.return_value = {
        "is_configured": True, "base_url": "https://oa.test.com",
        "last_pull_count": 0, "last_error": "连接超时", "is_online": False,
    }
    engine._oa_cloud_client = mock_client

    h = engine.get_channel_health("wechat_mp")
    assert h.get("connected") is False, (
        f"云端离线时 connected 应为 False，实际={h.get('connected')}"
    )
