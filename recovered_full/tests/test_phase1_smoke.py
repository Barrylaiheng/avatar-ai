"""
阶段1冒烟测试：验证 MainWindow + Sidebar 骨架
- 5个导航页切换
- 主题切换信号可驱动
- StatusBar 状态文字更新
- 无崩溃退出

运行方式（推荐 offscreen 平台）：
    set QT_QPA_PLATFORM=offscreen
    python tests/test_phase1_smoke.py
"""
import os
import sys
from pathlib import Path

# 确保 src 在路径
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class MockAppEngine:
    """AppEngine 的最小 mock，满足 MainWindow 的接口查询需求"""

    def __init__(self, initialized=True, channels=None, wcf_connected=False):
        self._initialized = initialized
        self._channels = channels or []
        self._wcf_connected = wcf_connected

    def is_initialized(self):
        return self._initialized

    def is_wcf_connected(self):
        return self._wcf_connected

    def get_active_channels(self):
        return list(self._channels)


def main() -> int:
    # PyQt6 offscreen 平台，无需显示环境
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QTimer

    from aibridge.ui.theme import get_current_theme, set_current_theme
    from aibridge.ui.main_window import MainWindow, PAGE_ORDER

    app = QApplication.instance() or QApplication(sys.argv)
    # 初始化主题，避免 QSS 构建失败
    from aibridge.ui.theme import apply_theme
    apply_theme(None, "light")

    engine = MockAppEngine(initialized=True, channels=["wcf"], wcf_connected=True)
    win = MainWindow(engine)
    win.show()

    # ---- 检查：默认激活页是 chat（索引 0）
    assert win.page_stack.currentIndex() == 0, (
        f"默认页非 chat: index={win.page_stack.currentIndex()}"
    )
    assert win.sidebar.current_page() == "chat"
    print("[OK] 默认激活页 = chat (index 0)")

    # ---- 触发 5 个导航页切换信号，验证索引
    errors = []
    for idx, page_id in enumerate(PAGE_ORDER):
        win._switch_page(page_id, show_status=False)
        QApplication.processEvents()
        if win.page_stack.currentIndex() != idx:
            errors.append(
                f"切到 {page_id} 后 index={win.page_stack.currentIndex()}, 期望 {idx}"
            )
        if win.sidebar.current_page() != page_id:
            errors.append(
                f"切到 {page_id} 后 sidebar.current_page={win.sidebar.current_page()}, 期望 {page_id}"
            )
    if not errors:
        print("[OK] 5个导航页切换（sidebar 当前页 / stack 索引）均对齐")
    else:
        for e in errors:
            print(f"[FAIL] {e}", file=sys.stderr)
        return 1

    # ---- 触发主题切换按钮（通过点击 signal），验证 current_theme == "dark"
    assert get_current_theme() == "light"
    # 直接调用 _toggle_theme（避免需要模拟点击）
    win.sidebar._toggle_theme()
    QApplication.processEvents()
    if get_current_theme() != "dark":
        print(f"[FAIL] 主题切换后 theme={get_current_theme()}, 期望 dark", file=sys.stderr)
        return 1
    print("[OK] 主题切换 light -> dark 成功")
    # 再切回 light
    win.sidebar._toggle_theme()
    QApplication.processEvents()
    if get_current_theme() != "light":
        print(f"[FAIL] 主题切换后 theme={get_current_theme()}, 期望 light", file=sys.stderr)
        return 1
    print("[OK] 主题切换 dark -> light 成功")

    # ---- StatusBar 引擎/渠道状态检查（mock 里 channels 有 wcf + initialized）
    assert "就绪" in win.engine_status.text() or "引擎: 就绪" == win.engine_status.text(), (
        f"引擎状态未就绪: {win.engine_status.text()}"
    )
    assert "微信" in win.channel_status.text() or "wcf" in win.channel_status.text(), (
        f"渠道状态文字异常: {win.channel_status.text()}"
    )
    print(f"[OK] StatusBar: 引擎='{win.engine_status.text()}' 渠道='{win.channel_status.text()}'")

    # ---- 未初始化引擎的 StatusBar 颜色验证（重建一个窗口）
    win2 = MainWindow(MockAppEngine(initialized=False, channels=[], wcf_connected=False))
    win2._refresh_status_bar()
    QApplication.processEvents()
    assert "未初始化" in win2.engine_status.text(), (
        f"未初始化引擎状态: {win2.engine_status.text()}"
    )
    print(f"[OK] 未初始化引擎状态='{win2.engine_status.text()}'")
    win2.close()

    # ---- 最后，窗口关闭无崩溃
    win.close()

    # 定时退出 QApplication 事件循环（保障在有显示环境下也自动退出）
    QTimer.singleShot(50, app.quit)
    app.exec()

    print("\n[PASS] 阶段1冒烟测试全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
