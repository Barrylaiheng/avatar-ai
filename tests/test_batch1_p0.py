"""
批次1 (P0) 最小闭环验证：
  P0a: AppEngine.initialize() 后 _message_store 已初始化 + get_channel_messages("wechat") 不再返回空
  P0b: AppEngine.get_workspace_stats("wechat") 返回结构正确
  P0c: ChatPage.append_reply() 注入回复成功 + typing/processing 复位

运行：
    set QT_QPA_PLATFORM=offscreen
    set PYTHONPATH=src
    python tests/test_batch1_p0.py
"""
import os
import sys
import tempfile
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main() -> int:
    # ---- P0a: AppEngine 懒初始化 Bug 修复 ----
    print("=" * 60)
    print("[P0a] AppEngine 消息存储懒初始化验证")
    print("=" * 60)

    # 注意：不调用完整 initialize()，因为它会触发 RAGEngine 下载 HuggingFace
    # embedding 模型，测试环境网络不通会卡死。改为直接验证 _init_message_store
    # 逻辑 + 模拟 initialize() 中调用 _init_message_store 的行为。
    from aibridge.app_engine import AppEngine

    engine = AppEngine()

    # 模拟 initialize() 修复后的行为：手动标记 _initialized=True 并调用 _init_message_store
    # （真实 initialize() 中 _init_message_store 在 _initialized=True 之前调用，这里复刻该顺序）
    engine._init_message_store()
    engine._initialized = True

    assert engine._message_store is not None, "_init_message_store 后 _message_store 应已初始化"
    assert engine.is_initialized() is True
    print("[OK] _init_message_store() 调用后 _message_store 已初始化（复刻 initialize() 修复后顺序）")

    # get_channel_messages("wechat") 不应报错（即使空表也返回 []，不是 None）
    # 这一行之前因 _message_store 为 None 直接返回 []，且若 _message_store 非None 会因
    # channel=channel 参数报 TypeError —— 现在两者都已修复
    msgs = engine.get_channel_messages("wechat", limit=10)
    assert isinstance(msgs, list), f"get_channel_messages 应返回 list, 实际: {type(msgs)}"
    print(f"[OK] get_channel_messages('wechat') 返回 list, 长度={len(msgs)}（隐藏 channel 参数 TypeError 已修复）")

    # 验证防御式懒初始化：临时置空 _message_store，再调 get_channel_messages 应自动重建
    engine._message_store = None
    msgs2 = engine.get_channel_messages("wechat", limit=5)
    assert isinstance(msgs2, list), "防御式懒初始化后应正常返回 list"
    assert engine._message_store is not None, "防御式懒初始化应重建 _message_store"
    print(f"[OK] 防御式懒初始化: _message_store 置空后自动重建")

    # ---- P0b: get_workspace_stats 结构验证 ----
    print()
    print("=" * 60)
    print("[P0b] AppEngine.get_workspace_stats(channel) 验证")
    print("=" * 60)

    stats_wechat = engine.get_workspace_stats("wechat")
    required_keys = {"total_messages", "avg_response_time", "satisfaction", "channel"}
    assert set(stats_wechat.keys()) >= required_keys, f"缺失字段: {required_keys - set(stats_wechat.keys())}"
    assert isinstance(stats_wechat["total_messages"], int)
    assert isinstance(stats_wechat["avg_response_time"], str)
    assert isinstance(stats_wechat["satisfaction"], int)
    assert 0 <= stats_wechat["satisfaction"] <= 100
    assert stats_wechat["channel"] == "wechat"
    print(f"[OK] wechat stats: total={stats_wechat['total_messages']}, "
          f"avg_resp={stats_wechat['avg_response_time']}, sat={stats_wechat['satisfaction']}%")

    stats_mp = engine.get_workspace_stats("mp")
    assert stats_mp["channel"] == "mp"
    assert stats_mp["total_messages"] == 0, "mp 渠道阶段4未实现，应为 0"
    print(f"[OK] mp stats: 零值返回（阶段4待实现）")

    stats_unknown = engine.get_workspace_stats("unknown_channel")
    assert stats_unknown["total_messages"] == 0
    print(f"[OK] 未知渠道: 返回零值不崩")

    # ---- P0c: ChatPage.append_reply 验证 ----
    print()
    print("=" * 60)
    print("[P0c] ChatPage.append_reply() 注入接口验证")
    print("=" * 60)

    from PyQt6.QtWidgets import QApplication
    from aibridge.ui.chat_page import ChatPage

    app = QApplication.instance() or QApplication(sys.argv)
    page = ChatPage()
    page.show()

    # 获取默认会话
    sessions = page.sessions()
    assert len(sessions) >= 1, "ChatPage 应有默认会话"
    sid = next(iter(sessions))
    print(f"[OK] ChatPage 默认会话: {sid}, 消息数={len(sessions[sid].messages)}")

    # 注入回复
    ok = page.append_reply(
        session_id=sid,
        content="测试注入回复",
        tool_calls=[{"tool": "test_tool", "result": {"success": True}}],
    )
    assert ok is True, "append_reply 应返回 True"
    assert sessions[sid].messages[-1].content == "测试注入回复"
    assert sessions[sid].messages[-1].role == "assistant"
    assert len(sessions[sid].messages[-1].tool_calls) == 1
    print(f"[OK] append_reply 注入成功: content='测试注入回复', tool_calls=1")

    # 注入到不存在的 session
    ok = page.append_reply(session_id="nonexistent", content="应该失败")
    assert ok is False, "不存在的 session_id 应返回 False"
    print(f"[OK] 不存在的 session_id 返回 False")

    # 验证 typing/processing 复位（模拟 processing 状态后注入）
    page._set_processing(True)
    page._typing.start()
    page._typing.show()
    assert page._processing is True
    assert page._typing.is_running() is True
    print(f"[OK] 模拟 processing=True, typing=running")

    page.append_reply(sid, "触发复位")
    assert page._processing is False, "append_reply 后 processing 应复位"
    assert page._typing.is_running() is False, "append_reply 后 typing 应停止"
    print(f"[OK] append_reply 后 processing/typing 自动复位")

    # 验证注入到非激活会话（仅更新数据不切换）
    other_sid = page.create_new_session("另一个会话", activate=True)
    page._select_session(sid)  # 切回原会话
    active_before = page.active_session_id()
    page.append_reply(other_sid, "注入到非激活会话")
    assert page.active_session_id() == active_before, "注入非激活会话不应切换激活态"
    # 重新获取 sessions 快照（create_new_session 后旧快照不含新会话）
    latest_sessions = page.sessions()
    assert latest_sessions[other_sid].messages[-1].content == "注入到非激活会话", "数据应已更新"
    print(f"[OK] 注入到非激活会话: 数据更新但不切换激活态")

    page.close()
    # 不调用 engine.shutdown()，避免触发未初始化模块的清理逻辑（本测试只验证 P0 改动点）

    print()
    print("=" * 60)
    print("[PASS] 批次1 (P0) 最小闭环验证全部通过")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
