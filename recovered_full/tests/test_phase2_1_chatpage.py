"""
阶段2.1 冒烟测试：ChatPage
- 会话创建/切换、消息发送、mock 回复、TypingIndicator 显示
- LLM Dialog 构造不崩溃
- 与 MainWindow 集成（chat 路由激活）

运行：
    set QT_QPA_PLATFORM=offscreen
    python tests/test_phase2_1_chatpage.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class MockAppEngine:
    def is_initialized(self):
        return True

    def is_wcf_connected(self):
        return False

    def get_active_channels(self):
        return []


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QTimer, Qt
    from PyQt6.QtTest import QTest

    from aibridge.ui.theme import apply_theme
    from aibridge.ui.chat_page import ChatPage, _ChatMessage
    from aibridge.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    apply_theme(None, "light")

    # ---- 1) 裸 ChatPage 构造 + 会话 ----
    cp = ChatPage()
    cp.show()
    # 默认创建1个会话
    assert len(cp.sessions()) == 1, f"默认会话数: {len(cp.sessions())}"
    first_id = cp.active_session_id()
    assert first_id is not None
    print("[OK] ChatPage 默认创建1个会话")

    # ---- 2) 新建会话，激活态切换 ----
    s2 = cp.create_new_session("测试会话2", activate=True)
    assert len(cp.sessions()) == 2
    assert cp.active_session_id() == s2
    # 再切回 first
    cp._select_session(first_id)
    assert cp.active_session_id() == first_id
    print("[OK] 新建/切换会话正常")

    # ---- 3) 发送消息：直接调用 send click 流程 ----
    # 先模拟 setPlainText -> send
    cp._input_edit.setPlainText("当前状态怎么样")
    cp._on_send_click()
    # user 消息已入列表
    msgs0 = cp.sessions()[first_id].messages
    assert len(msgs0) == 1 and msgs0[0].role == "user", f"msgs0: {[(m.role, m.content) for m in msgs0]}"
    assert cp._typing.isVisible()
    assert cp._processing is True
    print("[OK] 发送消息后：用户消息入库、TypingIndicator 显示、processing=True")

    # 等待 mock reply timer (1.2s)
    finished = {"ok": False}

    def _after_reply():
        msgs = cp.sessions()[first_id].messages
        try:
            assert len(msgs) == 2, f"reply未生成: {len(msgs)}"
            assert msgs[1].role == "assistant"
            assert cp._typing.isVisible() is False
            assert cp._processing is False
            finished["ok"] = True
        except AssertionError as e:
            print(f"[FAIL] reply 断言失败: {e}", file=sys.stderr)
        finally:
            app.quit()

    QTimer.singleShot(1400, _after_reply)
    app.exec()
    assert finished["ok"], "reply 未完成或断言失败"
    print("[OK] 1.4s 后 mock 回复入库、TypingIndicator 隐藏、处理中状态清除")

    # ---- 4) 工具调用气泡显示（模拟配置 LLM）----
    cp._input_edit.setPlainText("帮我配置 DeepSeek API")
    cp._on_send_click()
    done2 = {"ok": False}

    def _after_reply2():
        try:
            msgs = cp.sessions()[first_id].messages
            assert len(msgs) == 4, f"预期4条(2之前+2本轮): {len(msgs)}"
            last = msgs[-1]
            assert last.role == "assistant"
            assert any(tc.get("tool") for tc in last.tool_calls), f"缺少 tool_calls: {last.tool_calls}"
            done2["ok"] = True
        except AssertionError as e:
            print(f"[FAIL] tool_calls 断言失败: {e}", file=sys.stderr)
        finally:
            app.quit()

    QTimer.singleShot(1400, _after_reply2)
    app.exec()
    assert done2["ok"]
    print("[OK] 配置 LLM 场景生成带 tool_calls 的 Assistant 气泡")

    # ---- 5) LLMSelector Dialog 构造不崩溃 ----
    from aibridge.ui.chat_page import _LLMConfigDialog
    dlg = _LLMConfigDialog(cp)
    cfg = dlg.current_config()
    assert "provider" in cfg and "api_key" in cfg
    dlg.close()
    print("[OK] LLM 配置 Dialog 构造 & current_config 正常")

    # ---- 6) 与 MainWindow 集成：MainWindow 的 chat 页面是 ChatPage ----
    win = MainWindow(MockAppEngine())
    win.show()
    assert hasattr(win, "chat_page") and isinstance(win.chat_page, ChatPage)
    win._switch_page("chat", show_status=False)
    QApplication.processEvents()
    assert win.page_stack.currentIndex() == 0  # chat = 0 (PAGE_ORDER 第一个)
    print("[OK] MainWindow 路由 chat → 对应 ChatPage 实例（index 0）")

    # 关闭
    cp.close()
    win.close()
    QTimer.singleShot(50, app.quit)
    app.exec()

    print("\n[PASS] 阶段2.1 ChatPage 冒烟测试全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
