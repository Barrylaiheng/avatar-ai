"""
S4 UI 集成验证测试

测试场景：
1. 主窗口创建
2. 聊天面板消息交互
3. 页面切换
4. 设置保存
5. UI ↔ 后端绑定测试
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

app = QApplication.instance() or QApplication(sys.argv)

from aibridge.ui.chat_panel import ChatPanel, MessageBubble
from aibridge.ui.main_window import MainWindow
from aibridge.app_engine import AppEngine


def _get_engine():
    """获取已初始化的 AppEngine 实例"""
    engine = AppEngine()
    engine.initialize()
    return engine


def test_message_bubble():
    """测试消息气泡"""
    bubble = MessageBubble("用户", "你好", is_user=True)
    assert bubble.sender == "用户"
    assert bubble.content == "你好"
    assert bubble.is_user is True
    print("✓ 测试 1 通过：消息气泡组件")


def test_chat_panel():
    """测试聊天面板"""
    panel = ChatPanel()

    panel.add_user_message("测试消息")
    assert len(panel.messages) == 1
    assert panel.messages[0]["sender"] == "我"

    panel.add_ai_message("回复内容", "AI")
    assert len(panel.messages) == 2
    assert panel.messages[1]["sender"] == "AI"

    panel.add_system_message("系统提示")

    panel.clear_messages()
    assert len(panel.messages) == 0

    panel.input_edit.setText("hello")
    assert panel.get_input_text() == "hello"
    panel.clear_input()
    assert panel.get_input_text() == ""

    panel.set_input_enabled(False)
    assert not panel.input_edit.isEnabled()
    panel.set_input_enabled(True)
    assert panel.input_edit.isEnabled()

    print("✓ 测试 2 通过：聊天面板")


def test_main_window():
    """测试主窗口"""
    engine = _get_engine()
    window = MainWindow(engine)

    assert window.windowTitle() == "AI Bridge - 智能客服代理系统"

    assert window.stack.count() == 5

    assert len(window.nav_buttons) == 5

    assert window.status_bar is not None

    window.set_online_status(True)
    assert "在线" in window.status_indicator.text()
    window.set_online_status(False)
    assert "离线" in window.status_indicator.text()

    engine.shutdown()
    print("✓ 测试 3 通过：主窗口")


def test_page_switching():
    """测试页面切换"""
    engine = _get_engine()
    window = MainWindow(engine)

    page_map = {
        "chat": 0,
        "role": 1,
        "kb": 2,
        "iteration": 3,
        "settings": 4,
    }

    for key, index in page_map.items():
        window._switch_page(key)
        assert window.stack.currentIndex() == index

        for btn, k in window.nav_buttons:
            if k == key:
                assert btn.isChecked() is True
            else:
                assert btn.isChecked() is False

    engine.shutdown()
    print("✓ 测试 4 通过：页面切换")


def test_new_chat():
    """测试新建对话"""
    engine = _get_engine()
    window = MainWindow(engine)

    window.chat_panel.add_user_message("旧消息")
    assert len(window.chat_panel.messages) == 1

    window._new_chat()
    assert len(window.chat_panel.messages) == 0
    assert window.stack.currentIndex() == 0

    engine.shutdown()
    print("✓ 测试 5 通过：新建对话")


def test_ui_engine_binding():
    """测试 UI ↔ 后端绑定"""
    engine = _get_engine()
    window = MainWindow(engine)

    assert window._app_engine is not None
    assert window._app_engine.is_initialized() is True

    settings = window._app_engine.get_settings()
    assert isinstance(settings, dict)
    assert "api_key" in settings

    kb_id = window._app_engine.create_knowledge_base("测试KB", "测试描述")
    assert kb_id is not None

    kbs = window._app_engine.get_knowledge_bases()
    assert len(kbs) >= 1

    if kb_id:
        window._app_engine.delete_knowledge_base(kb_id)

    result = window._app_engine.process_message("测试消息")
    assert isinstance(result, dict)

    engine.shutdown()
    print("✓ 测试 6 通过：UI ↔ 后端绑定")


if __name__ == "__main__":
    print("=== S4 UI 集成验证测试 ===")

    try:
        test_message_bubble()
        test_chat_panel()
        test_main_window()
        test_page_switching()
        test_new_chat()
        test_ui_engine_binding()

        print("\n=== 所有测试通过 ===")
    except Exception as e:
        print(f"\n✗ 测试失败：{e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)