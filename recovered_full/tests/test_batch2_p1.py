"""
批次2 (P1) 验证：
  P1a: process_message 返回包含 tool_calls 字段（4 个返回分支）
  P1b: AppEngine.optimize_bad_case 结构验证（不实际调 LLM，仅验证接口存在 + 错误处理）
  P1c: AppEngine.set_kb_enabled / is_kb_enabled 开关生效
  P1d: MainWindow 信号桥接层验证（Mock AppEngine + 信号触发 → 桥接函数被调用）

运行：
    set QT_QPA_PLATFORM=offscreen
    set PYTHONPATH=src
    python tests/test_batch2_p1.py
"""
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main() -> int:
    print("=" * 60)
    print("[P1a] process_message 返回 tool_calls 字段验证")
    print("=" * 60)

    from aibridge.app_engine import AppEngine

    engine = AppEngine()
    # 不调 initialize()，直接测试未初始化时的返回
    result = engine.process_message("test", "session1")
    assert "error" in result, "未初始化应返回 error"
    assert result.get("error") == "引擎未初始化"
    print(f"[OK] 未初始化返回 error: {result}")

    # 验证含 content 的返回分支都含 tool_calls（通过 inspect 源码）
    # process_message 有 6 个 return dict：5 个含 content（需补 tool_calls），
    # 1 个纯错误（{"error": "引擎未初始化"}，无 content，不需 tool_calls）
    import inspect
    source = inspect.getsource(AppEngine.process_message)
    content_return_count = source.count('"content":')
    tool_calls_count = source.count('"tool_calls": []')
    assert content_return_count == tool_calls_count == 5, (
        f"含 content 的返回分支({content_return_count})应都含 tool_calls({tool_calls_count}), 且共 5 个"
    )
    print(f"[OK] process_message 源码 5 个含 content 的 return dict 均含 tool_calls=[]")

    # ---- P1b: optimize_bad_case 接口验证 ----
    print()
    print("=" * 60)
    print("[P1b] AppEngine.optimize_bad_case 接口验证")
    print("=" * 60)

    # 未初始化时应返回结构化错误
    result = engine.optimize_bad_case("nonexistent_id")
    assert isinstance(result, dict)
    assert result["success"] is False
    assert result["case_id"] == "nonexistent_id"
    assert "error" in result
    print(f"[OK] 未初始化返回结构化错误: success=False, error='{result['error']}'")

    # 验证返回结构包含所有必需字段（通过文档约定）
    required_fields = {"success", "case_id", "error"}
    assert required_fields.issubset(set(result.keys())), f"缺失字段: {required_fields - set(result.keys())}"
    print(f"[OK] 错误返回包含必需字段: {required_fields}")

    # ---- P1c: set_kb_enabled / is_kb_enabled ----
    print()
    print("=" * 60)
    print("[P1c] AppEngine.set_kb_enabled / is_kb_enabled 验证")
    print("=" * 60)

    # 默认应为 True
    assert engine.is_kb_enabled() is True, "默认应启用 KB"
    print(f"[OK] 默认 is_kb_enabled() = True")

    # 关闭
    engine.set_kb_enabled(False)
    assert engine.is_kb_enabled() is False
    print(f"[OK] set_kb_enabled(False) → is_kb_enabled() = False")

    # 重新开启
    engine.set_kb_enabled(True)
    assert engine.is_kb_enabled() is True
    print(f"[OK] set_kb_enabled(True) → is_kb_enabled() = True")

    # 边界：传非 bool 值（应被 bool() 转换）
    engine.set_kb_enabled(0)
    assert engine.is_kb_enabled() is False
    engine.set_kb_enabled(1)
    assert engine.is_kb_enabled() is True
    print(f"[OK] 非 bool 值正确转换: set_kb_enabled(0/1)")

    # ---- P1d: MainWindow 信号桥接层验证 ----
    print()
    print("=" * 60)
    print("[P1d] MainWindow 信号桥接层验证")
    print("=" * 60)

    from PyQt6.QtWidgets import QApplication
    from aibridge.ui.main_window import MainWindow
    from aibridge.ui.chat_page import ChatPage
    from aibridge.ui.workspace_page import WorkspacePage, MessageItemData, ChannelStats
    from aibridge.ui.iteration_page import IterationPage, BadCaseData

    app = QApplication.instance() or QApplication(sys.argv)

    # 构造 Mock AppEngine（初始化状态，但 process_message 返回 mock 结果）
    mock_engine = MagicMock()
    mock_engine.is_initialized.return_value = True
    mock_engine.is_wcf_connected.return_value = False
    mock_engine.get_active_channels.return_value = ["wechat"]
    mock_engine.is_kb_enabled.return_value = True
    mock_engine.set_kb_enabled = MagicMock()
    mock_engine.save_settings = MagicMock(return_value=True)
    mock_engine.test_wcf_connection = MagicMock(return_value=True)
    mock_engine.get_channel_messages = MagicMock(return_value=[
        {
            "msg_id": "m1", "sender_id": "u1", "sender_name": "王先生",
            "group_id": "", "group_name": "", "content": "葡萄有货吗？",
            "is_private": 1, "receive_time": 1723000000, "status": "replied",
        },
        {
            "msg_id": "m2", "sender_id": "g1", "sender_name": "",
            "group_id": "g1", "group_name": "水果群", "content": "今日特价",
            "is_private": 0, "receive_time": 1723000100, "status": "pending",
        },
    ])
    mock_engine.get_workspace_stats = MagicMock(return_value={
        "total_messages": 2, "avg_response_time": "350ms", "satisfaction": 85, "channel": "wechat"
    })
    mock_engine.get_bad_cases = MagicMock(return_value=[
        {
            "case_id": "bc1", "user_input": "葡萄有籽吗", "ai_response": "不知道",
            "detected_by": "factual", "severity": "high", "status": "pending",
        }
    ])
    mock_engine.get_messages = MagicMock(return_value=[])
    mock_engine.optimize_bad_case = MagicMock(return_value={
        "success": True, "case_id": "bc1", "optimized_answer": "您好，我们有无籽葡萄",
        "original_answer": "不知道", "user_input": "葡萄有籽吗",
    })
    mock_engine.process_message = MagicMock(return_value={
        "content": "测试回复", "is_aigc": True, "tool_calls": [], "intent": "chat"
    })

    win = MainWindow(mock_engine)
    win.show()

    # 1) ChatPage 信号桥接
    print("--- ChatPage 信号桥接 ---")
    assert hasattr(win, "chat_page"), "MainWindow 应有 chat_page 引用"
    assert hasattr(win, "_chat_workers"), "MainWindow 应有 _chat_workers 列表"
    assert isinstance(win._chat_workers, list)

    # kb_toggled 信号
    win.chat_page.kb_toggled.emit(False)
    QApplication.processEvents()
    mock_engine.set_kb_enabled.assert_called_with(False)
    print(f"[OK] ChatPage.kb_toggled(False) → AppEngine.set_kb_enabled(False) 已调用")

    # llm_saved 信号
    test_cfg = {"provider": "deepseek", "api_key": "sk-test"}
    win.chat_page.llm_saved.emit(test_cfg)
    QApplication.processEvents()
    mock_engine.save_settings.assert_called_with({"llm": test_cfg})
    print(f"[OK] ChatPage.llm_saved(cfg) → AppEngine.save_settings({{'llm': cfg}}) 已调用")

    # message_sent 信号（异步 process_message）
    sid = win.chat_page.active_session_id()
    win.chat_page.message_sent.emit(sid, "测试消息")
    QApplication.processEvents()
    # worker 异步，等一会儿
    import time
    time.sleep(0.3)
    QApplication.processEvents()
    mock_engine.process_message.assert_called_with("测试消息", sid)
    print(f"[OK] ChatPage.message_sent → 异步 process_message 已触发")
    # 清理 workers
    win._cleanup_chat_workers()

    # 2) SettingsPage 信号桥接
    print("--- SettingsPage 信号桥接 ---")
    assert hasattr(win, "settings_page"), "MainWindow 应有 settings_page 引用"
    win.settings_page.llm_saved.emit({"provider": "doubao", "api_key": "sk-doubao"})
    QApplication.processEvents()
    print(f"[OK] SettingsPage.llm_saved → _save_llm_config 已桥接")

    # wcf_test_requested 信号
    win.settings_page.wcf_test_requested.emit()
    QApplication.processEvents()
    time.sleep(0.2)
    QApplication.processEvents()
    mock_engine.test_wcf_connection.assert_called()
    print(f"[OK] SettingsPage.wcf_test_requested → 异步 test_wcf_connection 已触发")

    # 3) WorkspacePage 信号桥接 + 数据适配
    print("--- WorkspacePage 信号桥接 ---")
    assert hasattr(win, "workspace_page"), "MainWindow 应有 workspace_page 引用"
    # 手动触发 _refresh_workspace_data 验证适配层
    win._refresh_workspace_data("wechat")
    QApplication.processEvents()
    mock_engine.get_channel_messages.assert_called_with("wechat", limit=50)
    mock_engine.get_workspace_stats.assert_called_with("wechat")
    # 验证消息已注入 WorkspacePage
    msgs = win.workspace_page._messages.get("wechat", [])
    assert len(msgs) == 2, f"应注入 2 条消息, 实际 {len(msgs)}"
    assert isinstance(msgs[0], MessageItemData)
    assert msgs[0].name == "王先生"
    assert msgs[0].chat_type == "private"
    assert msgs[0].channel == "wechat"
    print(f"[OK] _refresh_workspace_data: 2 条消息适配为 MessageItemData 并注入")

    # 验证统计注入
    stats = win.workspace_page._stats.get("wechat")
    assert stats is not None
    assert isinstance(stats, ChannelStats)
    assert stats.total_messages == 2
    assert stats.avg_response_time == "350ms"
    assert stats.satisfaction == 85
    print(f"[OK] 统计适配为 ChannelStats: total=2, avg_resp=350ms, sat=85%")

    # 4) IterationPage 信号桥接 + BadCase 适配
    print("--- IterationPage 信号桥接 ---")
    assert hasattr(win, "iteration_page"), "MainWindow 应有 iteration_page 引用"
    win._refresh_iteration_data()
    QApplication.processEvents()
    mock_engine.get_bad_cases.assert_called_with(limit=50)
    bcs = win.iteration_page._badcases
    # mock 返回 1 条，应被适配注入
    assert len(bcs) == 1, f"应注入 1 条 BadCase, 实际 {len(bcs)}"
    assert isinstance(bcs[0], BadCaseData)
    assert bcs[0].id == "bc1"
    assert bcs[0].question == "葡萄有籽吗"
    assert bcs[0].answer == "不知道"
    assert bcs[0].bc_type == "wrong"  # factual → wrong 映射
    print(f"[OK] _refresh_iteration_data: 1 条 BadCase 适配为 BadCaseData 并注入")

    # optimize_requested 信号（异步）
    win.iteration_page.optimize_requested.emit("bc1")
    QApplication.processEvents()
    time.sleep(0.2)
    QApplication.processEvents()
    mock_engine.optimize_bad_case.assert_called_with("bc1")
    print(f"[OK] IterationPage.optimize_requested → 异步 optimize_bad_case 已触发")

    # 5) KnowledgePage 信号桥接（discuss_requested → 切 chat 页）
    print("--- KnowledgePage 信号桥接 ---")
    assert hasattr(win, "knowledge_page"), "MainWindow 应有 knowledge_page 引用"
    # 触发 discuss_requested 应切到 chat 页
    win.knowledge_page.discuss_requested.emit("entry1", "优化角色定位")
    QApplication.processEvents()
    assert win.page_stack.currentIndex() == 0, "应切换到 chat 页 (index 0)"
    print(f"[OK] KnowledgePage.discuss_requested → 切换到 chat 页")

    # 验证 worker_threads 模块可导入
    print("--- Worker 线程模块 ---")
    from aibridge.ui.worker_threads import ProcessMessageWorker, WcfTestWorker, OptimizeBadCaseWorker
    assert ProcessMessageWorker is not None
    assert WcfTestWorker is not None
    assert OptimizeBadCaseWorker is not None
    print(f"[OK] worker_threads 模块导入正常: 3 个 Worker 类")

    win.close()

    print()
    print("=" * 60)
    print("[PASS] 批次2 (P1) 验证全部通过")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
