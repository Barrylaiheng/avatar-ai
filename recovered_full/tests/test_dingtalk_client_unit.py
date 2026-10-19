# -*- coding: utf-8 -*-
"""dingtalk_client 连接层单元测试（纯函数，不依赖网络与真实 dws CLI）。

覆盖连接层的四个关键不变量：
- self-filter：本端（AI / dws CLI）回声必须被识别，真人消息不得被误杀
- 连接判定：未绑定 → False；鉴权有效 → True；CLI 探测不出结论 → 回退为已绑定即连接
- 去重集合：加载/保存上限一致，且运行期会滑窗裁剪
- 轮询游标：仅当本轮全部 peer 拉取成功才推进，失败时保留游标以防静默丢消息

运行:
  python -m pytest tests/test_dingtalk_client_unit.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parent.parent / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from channel import dingtalk_client as dc  # noqa: E402
from channel.dingtalk_client import DingtalkClient  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    """隔离到临时目录，绝不触碰真实的 ~/.dws 与 ~/.config/dingtalk。"""
    monkeypatch.setattr(dc, "_IDENTITY_FILE", tmp_path / "identity.json")
    monkeypatch.setattr(dc, "_STATE_FILE", tmp_path / ".last_processed")
    monkeypatch.setattr(dc, "_SEEN_FILE", tmp_path / ".seen_msgs")
    c = DingtalkClient()
    # 默认视为「本账号 open id 已解析但为空」，避免 _is_self_message 兜底去调真实 CLI
    c._self_open_id = ""
    c._self_open_id_resolved = True
    return c


def _bind(client):
    """模拟「已绑定」：identity.json 存在。"""
    dc._IDENTITY_FILE.write_text("{}", encoding="utf-8")


# ---------- self-filter ----------

def test_ai_flag_marks_self(client):
    """dws CLI 发送的消息带 messageAiSendFlag，必须被判为本端。"""
    assert client._is_self_message(
        {"messageAiSendFlag": "DWS", "senderId": "DSother"}
    ) is True


def test_human_message_is_not_self(client):
    """普通真人消息不得被误杀。"""
    assert client._is_self_message({"senderId": "DSother"}) is False


def test_self_echo_without_flag_detected(client):
    """兜底：无 AI 标记但 senderId 等于本账号 open id，也应判为本端。"""
    client._self_open_id = "DSself"
    assert client._is_self_message({"senderId": "DSself"}) is True


def test_empty_message_is_not_self(client):
    assert client._is_self_message({}) is False


def test_text_marker_alone_does_not_mark_self(client):
    """回归：历史版本用文本标记做 self-filter，会误吞含该文本的真人消息。"""
    assert client._is_self_message(
        {"senderId": "DSother", "text": "（AI 生成内容）"}
    ) is False


# ---------- 连接判定 ----------

def test_connected_false_when_unbound(client):
    assert client.connected is False


def test_connected_true_when_authenticated(client, monkeypatch):
    _bind(client)
    monkeypatch.setattr(client, "_cli_run", lambda *a, **k: (True, {"authenticated": True}, ""))
    assert client.connected is True


def test_connected_false_when_auth_invalid(client, monkeypatch):
    _bind(client)
    monkeypatch.setattr(client, "_cli_run", lambda *a, **k: (True, {"authenticated": False}, ""))
    assert client.connected is False


def test_connected_falls_back_true_when_auth_inconclusive(client, monkeypatch):
    """CLI 探测不出结论（超时/网络）时，回退为「已绑定即连接」，避免误判离线。"""
    _bind(client)
    monkeypatch.setattr(client, "_cli_run", lambda *a, **k: (False, None, "timeout"))
    assert client.connected is True


# ---------- health_check ----------

def test_health_check_unbound(client):
    h = client.health_check()
    assert h["channel"] == "dingtalk"
    assert h["ok"] is False


def test_health_check_authenticated(client, monkeypatch):
    _bind(client)
    monkeypatch.setattr(
        client, "_cli_run",
        lambda *a, **k: (True, {"authenticated": True, "user_name": "张三", "corp_name": "某公司"}, ""),
    )
    h = client.health_check()
    assert h == {
        "channel": "dingtalk",
        "ok": True,
        "corp_name": "某公司",
        "user_name": "张三",
        "error": "",
    }


# ---------- self open id 解析 ----------

def test_resolve_self_open_id_matches_by_user_id(client, monkeypatch):
    """多结果时按 userId 精确匹配，避免重名错认。"""
    monkeypatch.setattr(
        client, "_cli_run",
        lambda *a, **k: (True, {"data": {"users": [
            {"userId": "U2", "openDingTalkId": "DS2"},
            {"userId": "U1", "openDingTalkId": "DS1"},
        ]}}, ""),
    )
    monkeypatch.setattr(client, "auth_status", lambda refresh=False: {"user_name": "张三", "user_id": "U1"})
    assert client._resolve_self_open_id() == "DS1"


def test_resolve_self_open_id_single_result_fallback(client, monkeypatch):
    """无 userId 可匹配但结果唯一时，退取该结果。"""
    monkeypatch.setattr(
        client, "_cli_run",
        lambda *a, **k: (True, {"users": [{"userId": "U9", "openDingTalkId": "DS9"}]}, ""),
    )
    monkeypatch.setattr(client, "auth_status", lambda refresh=False: {"user_name": "张三", "user_id": "U1"})
    assert client._resolve_self_open_id() == "DS9"


def test_resolve_self_open_id_ambiguous_returns_empty(client, monkeypatch):
    """多结果且无 userId 匹配时返回空，宁可不用兜底也不误判。"""
    monkeypatch.setattr(
        client, "_cli_run",
        lambda *a, **k: (True, {"users": [
            {"userId": "U8", "openDingTalkId": "DS8"},
            {"userId": "U9", "openDingTalkId": "DS9"},
        ]}, ""),
    )
    monkeypatch.setattr(client, "auth_status", lambda refresh=False: {"user_name": "张三", "user_id": "U1"})
    assert client._resolve_self_open_id() == ""


# ---------- 去重集合 ----------

def test_seen_msgs_roundtrip_caps_at_seen_max(client):
    """保存与加载的上限必须一致（回归：曾出现 5000/2500 不对称）。"""
    assert client._load_seen_msgs() == set()
    client._seen_msgs = {str(i) for i in range(dc._SEEN_MAX + 500)}
    client._save_seen_msgs()
    assert len(client._load_seen_msgs()) == dc._SEEN_MAX


def test_trim_seen_msgs_slides_window(client):
    """超上限时滑窗裁剪，避免长时间运行内存无界增长。"""
    client._seen_msgs = {str(i) for i in range(dc._SEEN_MAX * 2 + 10)}
    client._trim_seen_msgs()
    assert len(client._seen_msgs) == dc._SEEN_MAX


# ---------- 轮询游标（防静默丢消息） ----------

def test_poll_once_advances_cursor_on_success(client, monkeypatch):
    """全部 peer 拉取成功时，游标推进到当前时间。"""
    client._bound_peers = [{"peer_id": "P1", "peer_type": "friend", "peer_name": "张三"}]
    client._last_processed_ts = 1000.0
    monkeypatch.setattr(client, "_pull_messages", lambda pid, st: [])
    client._poll_once()
    assert client._last_processed_ts > 1000.0


def test_poll_once_keeps_cursor_when_pull_fails(client, monkeypatch):
    """回归：拉取失败时不得推进游标，否则失败窗口内的消息会被静默跳过。"""
    client._bound_peers = [{"peer_id": "P1", "peer_type": "friend", "peer_name": "张三"}]
    client._last_processed_ts = 1000.0
    monkeypatch.setattr(client, "_pull_messages", lambda pid, st: None)
    client._poll_once()
    assert client._last_processed_ts == 1000.0


def test_poll_once_keeps_cursor_when_any_peer_fails(client, monkeypatch):
    """只要有一个 peer 失败就整体不推进，保证其窗口下一轮仍被覆盖。"""
    client._bound_peers = [
        {"peer_id": "P1", "peer_type": "friend", "peer_name": "甲"},
        {"peer_id": "P2", "peer_type": "friend", "peer_name": "乙"},
    ]
    client._last_processed_ts = 1000.0
    monkeypatch.setattr(
        client, "_pull_messages",
        lambda pid, st: [] if pid == "P1" else None,
    )
    client._poll_once()
    assert client._last_processed_ts == 1000.0


def test_poll_once_dispatches_only_human_new_messages(client, monkeypatch):
    """正常路径：真人消息分发一次；本端回声与重复消息都不重复分发。"""
    client._bound_peers = [{"peer_id": "P1", "peer_type": "friend", "peer_name": "张三"}]
    client._last_processed_ts = 1000.0
    got: list = []
    client._on_message = got.append
    msgs = [
        {"messageId": "M1", "senderId": "DSother", "sender": "张三",
         "text": "你好", "createTime": "2026-09-15 10:00:00"},
        {"messageId": "M2", "messageAiSendFlag": "DWS", "senderId": "DSself",
         "text": "AI 回复", "createTime": "2026-09-15 10:00:01"},
        {"messageId": "M1", "senderId": "DSother", "sender": "张三",
         "text": "你好", "createTime": "2026-09-15 10:00:00"},
    ]
    monkeypatch.setattr(client, "_pull_messages", lambda pid, st: msgs)
    n = client._poll_once()
    assert n == 1
    assert [m.content for m in got] == ["你好"]


def test_pull_messages_none_on_cli_error(client, monkeypatch):
    """_pull_messages 必须在 CLI 报错时返回 None，而不是空列表（否则无法区分失败）。"""
    monkeypatch.setattr(client, "_cli_run", lambda *a, **k: (False, None, "boom"))
    assert client._pull_messages("P1", "2026-09-15 10:00:00") is None
