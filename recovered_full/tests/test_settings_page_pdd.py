"""
SettingsPage PDD 验证测试（Phase 5 /tdd）

原型契约 (ui_mockup.html L2384-2570):
  ┌─ Header ──────────────────────────────────────────────────┐
  │  标题 "设置"(bold) + 副标题 "LLM 配置与系统参数"            │
  │  版本预览: [微信版 active | 公众号版] (12px / 5-14px pad)   │
  ├─ 外观主题 section (settings-section-title 15px 600) ─────┤
  │  2 theme-card:  亮色(☀️ + white gradient) / 暗色(🌙 + dark) │
  │  选中态 border = primary 色 (2px)                          │
  │  跟随系统 toggle (settings-row)                             │
  ├─ LLM 配置 section ───────────────────────────────────────┤
  │  服务商 / Base URL (readonly) / API Key (show/hide)         │
  │  模型下拉 / Thinking toggle / 保存并测试连接 btn            │
  ├─ WCF 连接配置 section ───────────────────────────────────┤
  │  连接模式(下拉) / 微信版本(status) / wcferry(status) / 连接│
  ├─ 授权管理 (原型中 #section-license)                        │
  │   license-badge + 进度条 + 激活按钮                         │
  └────────────────────────────────────────────────────────────┘

执行: pytest tests/test_settings_page_pdd.py -v
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

os.environ.setdefault("QT_OPENGL", "software")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QLineEdit, QComboBox,
    QScrollArea, QFrame,
)
from PyQt6.QtTest import QTest


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
        app.setApplicationName("SCAI Settings PDD Test")
    yield app


@pytest.fixture
def sp(qapp):
    """独立 SettingsPage 实例，mock app_engine"""
    from aibridge.ui.settings_page_v2 import SettingsPage
    from aibridge.ui.theme import apply_theme

    apply_theme(None, "light")

    engine = MagicMock()
    engine.config.llm_provider = "deepseek"
    engine.config.llm_base_url = "https://api.deepseek.com"
    engine.config.llm_api_key = "sk-abcdef123456"
    engine.config.llm_model = "deepseek-v4-flash"
    engine.config.llm_thinking_enabled = False
    engine.config.get.return_value = {
        "provider": "deepseek",
        "base_url": "https://api.deepseek.com",
        "api_key": "sk-abcdef123456",
        "model": "deepseek-v4-flash",
        "thinking": False,
    }
    # SettingsPage.refresh_settings 调 get_current_settings_dict，必须返回真实 dict 避免 MagicMock 传入 setText
    engine.get_current_settings_dict.return_value = {
        "active_provider": "deepseek",
        "base_url": "https://api.deepseek.com",
        "api_key": "sk-abcdef123456",
        "model": "deepseek-v4-flash",
        "thinking": False,
    }
    engine.save_settings.return_value = True
    engine.test_llm_connection.return_value = (True, "Ping OK 120ms")

    parent = QWidget()
    parent.resize(960, 720)
    page = SettingsPage(app_engine=engine)
    page.resize(940, 700)
    page.setParent(parent)
    parent.show()
    page.show()
    QTest.qWait(60)
    yield page
    try:
        page.close()
        parent.close()
        page.deleteLater()
        parent.deleteLater()
    except RuntimeError:
        pass
    QTest.qWait(10)


# ============ SP-1: 标题 "设置" + 存在 ============
def test_sp1_title_settings(sp):
    """SP-1: 标题 "设置" 存在（bold）"""
    labels = [l for l in sp.findChildren(QLabel) if l.text().strip() == "设置"]
    assert len(labels) >= 1, "未找到 标题 '设置'"


# ============ SP-2: 副标题 "LLM 配置与系统参数" ============
def test_sp2_subtitle_llm(sp):
    """SP-2: 副标题 "LLM 配置与系统参数" 存在"""
    labels = [l for l in sp.findChildren(QLabel)
              if l.text().strip() == "LLM 配置与系统参数"]
    assert len(labels) >= 1, "未找到副标题 LLM 配置与系统参数"


# ============ SP-3: "版本预览" + "微信版"/"公众号版" 两个按钮 ============
def test_sp3_version_preview(sp):
    """SP-3: 版本预览 + 微信版 + 公众号版（3 个控件）"""
    ver_label = [l for l in sp.findChildren(QLabel) if "版本预览" in l.text()]
    assert len(ver_label) >= 1, "未找到 '版本预览' 标签"
    btn_wechat = [b for b in sp.findChildren(QPushButton) if b.text() == "微信版"]
    btn_oa = [b for b in sp.findChildren(QPushButton) if b.text() == "公众号版"]
    assert len(btn_wechat) >= 1, "未找到 微信版 按钮"
    assert len(btn_oa) >= 1, "未找到 公众号版 按钮"


# ============ SP-4: version_changed 信号（切公众号版）============
def test_sp4_version_change_signal(sp):
    """SP-4: 切公众号版 → version_changed('oa')"""
    received = []
    sp.version_changed.connect(lambda v: received.append(v))
    btn_oa = [b for b in sp.findChildren(QPushButton) if b.text() == "公众号版"]
    assert btn_oa
    btn_oa[0].click()
    assert "oa" in received, f"切公众号版应发 'oa'，实际收到: {received}"


# ============ SP-5: _ThemeCard 2 张 (亮色 / 暗色) ============
def test_sp5_two_theme_cards(sp):
    """SP-5: _tc_light + _tc_dark 存在"""
    assert sp._tc_light is not None, "_tc_light 未创建"
    assert sp._tc_dark is not None, "_tc_dark 未创建"


# ============ SP-6: 亮色卡片 label = "亮色模式" ============
def test_sp6_theme_light_label(sp):
    """SP-6: _tc_light label == '亮色模式'"""
    assert sp._tc_light.label == "亮色模式", \
        f"亮色卡片 label 应为 '亮色模式'，实际 {sp._tc_light.label}"


# ============ SP-7: 暗色卡片 label = "暗色模式" ============
def test_sp7_theme_dark_label(sp):
    """SP-7: _tc_dark label == '暗色模式'"""
    assert sp._tc_dark.label == "暗色模式", \
        f"暗色卡片 label 应为 '暗色模式'，实际 {sp._tc_dark.label}"


# ============ SP-8: 初始 light 主题 → _tc_light selected ============
def test_sp8_theme_light_selected_on_init(sp):
    """SP-8: 默认 light 主题 → tc_light.selected = True"""
    assert sp._tc_light.selected is True, "默认 light 主题时 tc_light 应 selected"
    assert sp._tc_dark.selected is False, "默认 light 主题时 tc_dark 不应 selected"


# ============ SP-9: 点击暗色卡片 → theme_changed('dark') ============
def test_sp9_theme_dark_click_emits(sp):
    """SP-9: 点击 tc_dark → theme_changed('dark')"""
    received = []
    sp.theme_changed.connect(lambda v: received.append(v))
    # 调用 tc_dark 的 clicked 发射 (click() 通过模拟 _ThemeCard emit)
    sp._tc_dark.clicked.emit("dark")
    assert "dark" in received, f"点暗色应发 theme_changed('dark')，收到 {received}"


# ============ SP-10: "外观主题" section title 15px bold/600 ============
def test_sp10_theme_section_title(sp):
    """SP-10: 外观主题 section-title 存在"""
    labels = [l for l in sp.findChildren(QLabel) if l.text() == "外观主题"]
    assert len(labels) >= 1, "未找到 '外观主题' section 标题"


# ============ SP-11: LLM 配置 section + "服务商" row + "Base URL" readonly ============
def test_sp11_llm_baseurl_readonly(sp):
    """SP-11: LLM Base URL lineedit 为只读"""
    # 找 value = "https://api.deepseek.com" 的 QLineEdit
    inputs = [x for x in sp.findChildren(QLineEdit)
              if x.text().startswith("https://") and "deepseek" in x.text()]
    assert len(inputs) >= 1, "未找到 Base URL 输入框"
    assert inputs[0].isReadOnly(), f"Base URL 应为 readonly，实际 isReadOnly={inputs[0].isReadOnly()}"


# ============ SP-12: "保存并测试连接" 按钮存在 ============
def test_sp12_save_test_btn(sp):
    """SP-12: '保存并测试连接' 按钮存在"""
    btns = [b for b in sp.findChildren(QPushButton) if "保存并测试" in b.text()]
    assert len(btns) >= 1, "未找到 '保存并测试连接' 按钮"


# ============ SP-13: API Key 初始 echo = Password mode ============
def test_sp13_api_key_echo_password(sp):
    """SP-13: API Key 行右侧的 QLineEdit 为 Password 模式

    策略：找到 text='API Key' 的 QLabel → 找其父 layout（_SettingsRow QHBoxLayout）
          → 该 _SettingsRow 的 QLineEdit 即 API Key 输入框
    """
    api_labels = [l for l in sp.findChildren(QLabel) if l.text() == "API Key"]
    assert len(api_labels) >= 1, "未找到 'API Key' 标签"

    # 向上找 _SettingsRow（_SettingsRow 是一个 QFrame，内部 HBoxLayout）
    from aibridge.ui.settings_page_v2 import _SettingsRow
    w = api_labels[0]
    row = None
    for _ in range(6):
        w = w.parent()
        if w is None:
            break
        if isinstance(w, _SettingsRow):
            row = w
            break
    assert row is not None, "未找到 API Key 所在 _SettingsRow"

    api_inputs = row.findChildren(QLineEdit)
    assert len(api_inputs) >= 1, "API Key row 中无 QLineEdit"
    assert api_inputs[0].echoMode() == QLineEdit.EchoMode.Password, \
        f"API Key 初始应为 Password 模式，实际 echoMode={api_inputs[0].echoMode()}"


# ============ SP-14: 模型下拉含 deepseek-v4-flash / deepseek-v4-pro ============
def test_sp14_model_combo_options(sp):
    """SP-14: 模型下拉至少有 deepseek-v4-flash + deepseek-v4-pro"""
    # 找模型 combobox: 含 v4-flash 或 itemText 包含 "deepseek"
    combos = []
    for c in sp.findChildren(QComboBox):
        items = [c.itemText(i) for i in range(c.count())]
        if any("deepseek" in i for i in items) and any("v4" in i for i in items):
            combos.append(c)
    assert len(combos) >= 1, "未找到 模型下拉框"
    items = [combos[0].itemText(i) for i in range(combos[0].count())]
    assert any("v4-flash" in i for i in items), f"模型列表无 v4-flash: {items}"
    assert any("v4-pro" in i for i in items), f"模型列表无 v4-pro: {items}"


# ============ SP-15: "WCF 连接配置" section ============
def test_sp15_wcf_section_title(sp):
    """SP-15: WCF 连接配置 section 标题存在"""
    labels = [l for l in sp.findChildren(QLabel) if l.text() == "WCF 连接配置"]
    assert len(labels) >= 1, "未找到 'WCF 连接配置' section 标题"


# ============ SP-16: WCF "连接模式" 下拉存在 ============
def test_sp16_wcf_connect_mode_combo(sp):
    """SP-16: WCF '连接模式' 下拉（含 '本地注入'）"""
    # 找含 "本地注入" 的 combobox
    combos = []
    for c in sp.findChildren(QComboBox):
        items = [c.itemText(i) for i in range(c.count())]
        if any("本地注入" in i for i in items):
            combos.append(c)
    assert len(combos) >= 1, "未找到 WCF 连接模式 下拉（含 '本地注入'）"


# ============ SP-17: "微信版本" 已检测 状态 存在 ============
def test_sp17_wechat_version_status(sp):
    """SP-17: 微信版本 '3.9.12.51 已检测' 文字存在（或相似 status label）"""
    labels = [l for l in sp.findChildren(QLabel)
              if "3.9.12" in l.text() or "已检测" in l.text()]
    assert len(labels) >= 1, "未找到 微信版本 已检测 status"


# ============ SP-18: LLM 配置 → 保存按钮触发 llm_saved 信号 ============
def test_sp18_llm_saved_signal(sp):
    """SP-18: 点击 '保存并测试连接' → llm_saved(dict)"""
    received = []
    sp.llm_saved.connect(lambda d: received.append(d))
    btns = [b for b in sp.findChildren(QPushButton) if "保存并测试" in b.text()]
    btns[0].click()
    assert len(received) >= 1, "点击保存按钮应触发 llm_saved"
    assert isinstance(received[0], dict), f"llm_saved payload 应为 dict，实际 {type(received[0])}"
    # dict 含 key provider / api_key / model 其中至少 2 个
    keys = set(received[0].keys())
    common = {"provider", "api_key", "model", "base_url"} & keys
    assert len(common) >= 2, f"llm_saved dict 应有至少 2 个配置键，实际 {keys}"


# ============ SP-19: 授权管理 section 中 "授权管理"/"试用中"/"激活" 任一存在 ============
def test_sp19_license_section_exists(sp):
    """SP-19: 授权管理 section 存在（标题 '授权管理' 或含 '激活'/'试用'）"""
    texts = []
    for l in sp.findChildren(QLabel):
        texts.append(l.text())
    for b in sp.findChildren(QPushButton):
        texts.append(b.text())
    any_license = any(
        ("授权" in t) or ("激活" in t) or ("试用" in t)
        for t in texts
    )
    assert any_license, f"未找到 授权/激活/试用 相关控件，找到的 QLabel+QPushButton: {[t for t in texts if t][:20]}"


# ============ SP-20: 主 QScrollArea 存在（原型 settings-body overflow-y）============
def test_sp20_scrollarea(sp):
    """SP-20: QScrollArea 存在 (settings-body overflow-y)"""
    sa = sp.findChildren(QScrollArea)
    assert len(sa) >= 1, "未找到 QScrollArea 主容器"


# ============ 主入口 ============
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
