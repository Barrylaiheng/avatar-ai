"""
阶段2.5 冒烟测试：SettingsPage (v2.0)
- 6 个分组卡片渲染
- 主题卡片点击切换 light/dark
- 版本切换（微信版/公众号版）→ WCF/OA section 可见性
- LLM API Key 显示/隐藏
- LLM 保存按钮 → settingsSaved + llm_saved 信号
- ToggleSwitch 状态切换
- 与 MainWindow 集成

运行：
    set QT_QPA_PLATFORM=offscreen
    python tests/test_phase2_5_settingspage.py
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

    from PyQt6.QtWidgets import QApplication, QWidget, QLineEdit
    from PyQt6.QtCore import QTimer

    from aibridge.ui.theme import apply_theme, get_current_theme
    from aibridge.ui.settings_page_v2 import SettingsPage, _SettingsSection, _ThemeCard, _SafetyCell
    from aibridge.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    apply_theme(None, "light")

    # ---- 1) 构造 + 6 个分组 ----
    sp = SettingsPage(app_engine=MockAppEngine())
    sp.show()
    # 统计 _SettingsSection 数量
    sections = [sp._body_layout.itemAt(i).widget() for i in range(sp._body_layout.count())]
    sections = [s for s in sections if isinstance(s, _SettingsSection)]
    assert len(sections) == 6, f"分组数: {len(sections)}"
    print(f"[OK] 6 个分组卡片渲染: 主题/LLM/WCF/OA/系统/合规")

    # ---- 2) 主题卡片点击 → theme_changed 信号 ----
    assert sp._tc_light._selected is True
    assert sp._tc_dark._selected is False
    theme_signals = []
    sp.theme_changed.connect(lambda t: theme_signals.append(t))
    sp._on_theme_card_click("dark")
    QApplication.processEvents()
    assert sp._tc_light._selected is False
    assert sp._tc_dark._selected is True
    assert theme_signals == ["dark"]
    assert get_current_theme() == "dark"
    print(f"[OK] 主题切换: light → dark, theme_changed 信号触发")
    # 切回 light
    sp._on_theme_card_click("light")
    QApplication.processEvents()
    assert get_current_theme() == "light"
    print(f"[OK] 主题切换: dark → light")

    # ---- 3) 版本切换 → WCF/OA 可见性 ----
    assert sp._version == "wechat"
    assert sp._wcf_section.isVisible() is True
    assert sp._oa_section.isVisible() is False
    ver_signals = []
    sp.version_changed.connect(lambda v: ver_signals.append(v))
    sp._switch_version("oa")
    QApplication.processEvents()
    assert sp._version == "oa"
    assert sp._wcf_section.isVisible() is False
    assert sp._oa_section.isVisible() is True
    assert ver_signals == ["oa"]
    print(f"[OK] 版本切换: wechat → oa, WCF隐藏/OA显示, version_changed 信号触发")
    # 切回
    sp._switch_version("wechat")
    QApplication.processEvents()
    assert sp._wcf_section.isVisible() is True
    assert sp._oa_section.isVisible() is False
    print(f"[OK] 版本切换: oa → wechat, WCF显示/OA隐藏")

    # ---- 4) API Key 显示/隐藏 ----
    assert sp._apikey_edit.echoMode() == QLineEdit.EchoMode.Password
    sp._toggle_apikey_visibility()
    assert sp._apikey_edit.echoMode() == QLineEdit.EchoMode.Normal
    sp._toggle_apikey_visibility()
    assert sp._apikey_edit.echoMode() == QLineEdit.EchoMode.Password
    print(f"[OK] API Key 显示/隐藏切换正常")

    # ---- 5) LLM 保存 → settingsSaved + llm_saved ----
    saved_signals = []
    llm_signals = []
    sp.settingsSaved.connect(lambda: saved_signals.append(True))
    sp.llm_saved.connect(lambda cfg: llm_signals.append(cfg))
    sp._apikey_edit.setText("sk-test123")
    sp._on_save_llm()
    QApplication.processEvents()
    assert len(saved_signals) == 1
    assert len(llm_signals) == 1
    assert llm_signals[0]["api_key"] == "sk-test123"
    print(f"[OK] LLM 保存: settingsSaved + llm_saved(api_key='sk-test123')")

    # ---- 6) 合规与安全 2×2 网格 ----
    safety_section = sections[5]  # 最后一个 section
    # 找到 _SafetyCell
    from PyQt6.QtWidgets import QGridLayout
    safety_cells = []
    for i in range(safety_section._layout.count()):
        w = safety_section._layout.itemAt(i).widget()
        if w and isinstance(w, QWidget):
            # 递归找 _SafetyCell
            for child in w.findChildren(_SafetyCell):
                safety_cells.append(child)
    assert len(safety_cells) == 4, f"安全壳 cell 数: {len(safety_cells)}"
    print(f"[OK] 合规与安全 2×2 网格: 4 个 _SafetyCell")

    # ---- 7) MainWindow 集成 ----
    win = MainWindow(MockAppEngine())
    win.show()
    win._switch_page("settings", show_status=False)
    QApplication.processEvents()
    assert win.page_stack.currentIndex() == 4  # settings = PAGE_ORDER[4]
    from aibridge.ui.settings_page_v2 import SettingsPage as SP2
    assert isinstance(win._pages.get("settings"), SP2)
    print(f"[OK] MainWindow settings 路由 → SettingsPage v2 (index 4)")

    sp.close()
    win.close()
    QTimer.singleShot(50, app.quit)
    app.exec()

    print("\n[PASS] 阶段2.5 SettingsPage 冒烟测试全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
