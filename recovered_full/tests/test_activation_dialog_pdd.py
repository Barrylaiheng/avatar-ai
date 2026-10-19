"""
ActivationDialog PDD 验证测试（Phase 5 /tdd）

对应 Phase 3 spec 的 25 个 Test Seams：
  AD-1~AD-4:   遮罩 + 容器
  AD-5~AD-11:  Header
  AD-12~AD-16: QR 区 + 支付 tabs
  AD-17~AD-18: Verify 按钮
  AD-19~AD-22: Status 状态
  AD-23~AD-25: Footer + 信号机制

执行：pytest tests/test_activation_dialog_pdd.py -v
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

os.environ.setdefault("QT_OPENGL", "software")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication, QWidget, QFrame, QLabel, QPushButton,
    QLineEdit, QHBoxLayout, QVBoxLayout, QSizePolicy,
    QDialog, QGraphicsDropShadowEffect,
)
from PyQt6.QtTest import QTest


# ============ 脚手架 ============

@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
        app.setApplicationName("SCAI ActivationDialog PDD Test")
    yield app


@pytest.fixture
def dlg(qapp):
    """每个测试独立的 ActivationDialog 实例"""
    from aibridge.ui.activation_dialog import ActivationDialog
    from aibridge.ui.theme import apply_theme

    apply_theme(None, "light")

    parent = QWidget()
    parent.resize(1200, 900)
    d = ActivationDialog(parent)
    d.show()
    QTest.qWait(80)
    yield d
    try:
        d.close()
        d.deleteLater()
        parent.close()
        parent.deleteLater()
    except RuntimeError:
        pass
    QTest.qWait(10)


# ============ AD-1~AD-4: 遮罩 + 容器 ============

def test_ad1_overlay_semi_transparent_black(dlg):
    """AD-1: act-overlay 半透明黑背景 rgba(0,0,0,0.5)"""
    # ActivationDialog 自身作为 overlay（背景半透明黑）
    style = dlg.styleSheet().lower()
    assert "rgba(0, 0, 0, 0.5)" in style or "rgba(0,0,0,0.5)" in style, \
        f"overlay 背景应为 rgba(0,0,0,0.5)，样式: {style}"


def test_ad2_overlay_visibility_toggle(dlg):
    """AD-2: overlay 默认隐藏，show 时可见"""
    from aibridge.ui.activation_dialog import ActivationDialog
    parent = dlg.parent()
    # 创建时不显示
    d2 = ActivationDialog(parent)
    assert not d2.isVisible(), "新建对话框默认应不可见"
    d2.show()
    QTest.qWait(30)
    assert d2.isVisible(), "show 后应可见"
    d2.hide()
    QTest.qWait(30)
    assert not d2.isVisible(), "hide 后应不可见"
    d2.deleteLater()


def test_ad3_box_width_480_radius_16(dlg):
    """AD-3: act-box width 480px + radius 16px + bg-base"""
    box = dlg.findChild(QFrame, "act-box")
    assert box is not None, "未找到 act-box"
    assert box.maximumWidth() == 480 or box.width() <= 480, \
        f"act-box 宽度应为 480px，实际 {box.maximumWidth()}/{box.width()}"
    style = box.styleSheet().lower()
    assert "border-radius: 16px" in style, f"act-box 圆角应为 16px，样式: {style}"
    assert "#ffffff" in style or "bg-base" in style, \
        f"act-box 背景应为 bg-base，样式: {style}"


def test_ad4_box_shadow_and_border(dlg):
    """AD-4: act-box box-shadow 0 24px 80px rgba(0,0,0,0.2) + 1px border"""
    box = dlg.findChild(QFrame, "act-box")
    # 阴影通过 QGraphicsDropShadowEffect 实现
    effect = box.graphicsEffect()
    has_shadow = effect is not None and isinstance(effect, QGraphicsDropShadowEffect)
    # 或通过样式表 box-shadow
    style_shadow = "box-shadow" in box.styleSheet().lower()
    assert has_shadow or style_shadow, \
        f"act-box 应有阴影效果（QGraphicsDropShadowEffect 或 box-shadow），effect={effect}"
    style = box.styleSheet().lower()
    assert "border: 1px" in style, f"act-box 应有 1px border，样式: {style}"


# ============ AD-5~AD-11: Header ============

def test_ad5_header_padding_gradient_border(dlg):
    """AD-5: act-header padding 24px 28px 16px + 渐变背景 + border-bottom"""
    header = dlg.findChild(QFrame, "act-header")
    assert header is not None, "未找到 act-header"
    style = header.styleSheet().lower()
    assert "qlineargradient" in style or "gradient" in style, \
        f"act-header 应有渐变背景，样式: {style}"
    assert "border-bottom: 1px" in style, f"act-header 应有 border-bottom，样式: {style}"
    lay = header.layout()
    m = lay.contentsMargins()
    assert m.left() == 28 and m.top() == 24 and m.bottom() == 16, \
        f"header padding 应为 28,24,28,16，实际 ({m.left()},{m.top()},{m.right()},{m.bottom()})"


def test_ad6_header_icon_48_primary_bg(dlg):
    """AD-6: act-header-icon 48×48 + radius 12px + primary bg + 白字"""
    icon = dlg.findChild(QFrame, "act-header-icon")
    assert icon is not None, "未找到 act-header-icon"
    assert icon.width() == 48 and icon.height() == 48, \
        f"icon 尺寸应为 48×48，实际 {icon.width()}×{icon.height()}"
    style = icon.styleSheet().lower()
    assert "#022762" in style or "primary" in style, \
        f"icon 背景应为 primary，样式: {style}"
    assert "border-radius: 12px" in style, f"icon 圆角应为 12px，样式: {style}"


def test_ad7_title_17px_700(dlg):
    """AD-7: act-title 17px + 700 weight + text-primary"""
    title = dlg.findChild(QLabel, "act-title")
    assert title is not None, "未找到 act-title"
    text = title.text()
    assert "激活" in text, f"title 应含 '激活'，实际 '{text}'"
    style = title.styleSheet().lower()
    assert "font-size: 17px" in style, f"title 字号应为 17px，样式: {style}"
    assert "700" in style, f"title 应为 700 weight，样式: {style}"


def test_ad8_subtitle_13px_permanent(dlg):
    """AD-8: act-subtitle 13px + text-secondary，含'永久授权'"""
    sub = dlg.findChild(QLabel, "act-subtitle")
    assert sub is not None, "未找到 act-subtitle"
    text = sub.text()
    assert "永久" in text, f"subtitle 应含 '永久'，实际 '{text}'"
    style = sub.styleSheet().lower()
    assert "font-size: 13px" in style, f"subtitle 字号应为 13px，样式: {style}"


def test_ad9_close_button_top_right(dlg):
    """AD-9: act-close 按钮（✕）位于右上角，cursor pointer"""
    close_btn = dlg.findChild(QPushButton, "act-close")
    assert close_btn is not None, "未找到 act-close 按钮"
    assert close_btn.text() == "×" or "✕" in close_btn.text() or close_btn.text() == "✕", \
        f"close 按钮文本应为 ×/✕，实际 '{close_btn.text()}'"
    # cursor pointer
    assert close_btn.cursor().shape() == Qt.CursorShape.PointingHandCursor, \
        "close 按钮 cursor 应为 PointingHandCursor"


def test_ad10_close_button_emits_closed_signal(dlg):
    """AD-10: 点击 act-close 触发 closed 信号 + 隐藏"""
    close_btn = dlg.findChild(QPushButton, "act-close")
    received = []
    dlg.closed.connect(lambda: received.append(True))
    close_btn.click()
    QTest.qWait(30)
    assert len(received) >= 1, "点击 close 应触发 closed 信号"


def test_ad11_body_padding_24_28(dlg):
    """AD-11: act-body padding 24px 28px"""
    body = dlg.findChild(QFrame, "act-body")
    assert body is not None, "未找到 act-body"
    lay = body.layout()
    m = lay.contentsMargins()
    assert m.left() == 28 and m.top() == 24, \
        f"body padding 应为 28,24,28,28，实际 ({m.left()},{m.top()})"


# ============ AD-12~AD-16: QR 区 + 支付 tabs ============

def test_ad12_qr_area_style(dlg):
    """AD-12: act-qr-area flex + bg-subtle + 1px border + radius 8 + padding 16"""
    qr_area = dlg.findChild(QFrame, "act-qr-area")
    assert qr_area is not None, "未找到 act-qr-area"
    style = qr_area.styleSheet().lower()
    assert "bg-subtle" in style or "#f9fafb" in style, \
        f"qr-area 背景应为 bg-subtle，样式: {style}"
    assert "border: 1px" in style, f"qr-area 应有 1px border，样式: {style}"
    assert "border-radius: 8px" in style, f"qr-area 圆角应为 8px，样式: {style}"
    lay = qr_area.layout()
    m = lay.contentsMargins()
    assert m.left() == 16 and m.top() == 16, \
        f"qr-area padding 应为 16px，实际 ({m.left()},{m.top()})"


def test_ad13_qr_img_120x120(dlg):
    """AD-13: act-qr-img 120×120 + radius 8 + bg #FFF + 1px border"""
    qr_img = dlg.findChild(QFrame, "act-qr-img")
    assert qr_img is not None, "未找到 act-qr-img"
    assert qr_img.width() == 120 and qr_img.height() == 120, \
        f"qr-img 尺寸应为 120×120，实际 {qr_img.width()}×{qr_img.height()}"
    style = qr_img.styleSheet().lower()
    assert "background-color: #ffffff" in style or "background: #fff" in style, \
        f"qr-img 背景应为 #FFF，样式: {style}"
    assert "border: 1px" in style, f"qr-img 应有 1px border，样式: {style}"


def test_ad14_price_28px_700_primary(dlg):
    """AD-14: act-price 28px + 700 weight + primary + 文本 ¥299"""
    price = dlg.findChild(QLabel, "act-price")
    assert price is not None, "未找到 act-price"
    text = price.text()
    assert "299" in text, f"price 文本应含 '299'，实际 '{text}'"
    assert "¥" in text or "￥" in text, f"price 文本应含 ¥ 符号，实际 '{text}'"
    style = price.styleSheet().lower()
    assert "font-size: 28px" in style, f"price 字号应为 28px，样式: {style}"
    assert "700" in style, f"price 应为 700 weight，样式: {style}"
    assert "#022762" in style or "primary" in style, \
        f"price 颜色应为 primary，样式: {style}"


def test_ad15_price_unit_14px_permanent(dlg):
    """AD-15: act-price-unit 14px + 400 weight + text-secondary，文本 '/ 永久'"""
    unit = dlg.findChild(QLabel, "act-price-unit")
    assert unit is not None, "未找到 act-price-unit"
    text = unit.text()
    assert "永久" in text, f"price-unit 文本应含 '永久'，实际 '{text}'"
    style = unit.styleSheet().lower()
    assert "font-size: 14px" in style, f"price-unit 字号应为 14px，样式: {style}"
    # 400 weight 默认（不强制）


def test_ad16_pay_tabs_2_default_wechat_active(dlg):
    """AD-16: 2 个 act-pay-tab（微信/支付宝），默认微信 active"""
    tabs = dlg.findChildren(QPushButton, "act-pay-tab")
    # 或通过 findChildren + 文本筛选
    if len(tabs) < 2:
        all_btns = dlg.findChildren(QPushButton)
        tabs = [b for b in all_btns if "微信" in b.text() or "支付宝" in b.text()]
    assert len(tabs) >= 2, f"应有 2 个 pay-tab，实际 {len(tabs)}"

    # 默认微信 active
    wechat_tab = next((t for t in tabs if "微信" in t.text()), None)
    assert wechat_tab is not None, "应含微信 tab"
    wstyle = wechat_tab.styleSheet().lower()
    assert "#022762" in wstyle or "primary" in wstyle, \
        f"微信 tab 默认 active 应为 primary，样式: {wstyle}"

    # 支付宝非 active
    alipay_tab = next((t for t in tabs if "支付宝" in t.text()), None)
    assert alipay_tab is not None, "应含支付宝 tab"


# ============ AD-17~AD-18: Verify 按钮 ============

def test_ad17_verify_btn_style(dlg):
    """AD-17: act-verify-btn primary bg + 白字 + 14px + 600 weight + width 100%"""
    btn = dlg.findChild(QPushButton, "act-verify-btn")
    assert btn is not None, "未找到 act-verify-btn"
    text = btn.text()
    assert "付费" in text or "激活" in text, \
        f"verify-btn 文本应含 '付费' 或 '激活'，实际 '{text}'"
    style = btn.styleSheet().lower()
    assert "#022762" in style or "primary" in style, \
        f"verify-btn 背景应为 primary，样式: {style}"
    assert "#ffffff" in style or "color: #fff" in style, \
        f"verify-btn 文字应为白色，样式: {style}"
    assert "font-size: 14px" in style, f"verify-btn 字号应为 14px，样式: {style}"
    assert "600" in style, f"verify-btn 应为 600 weight，样式: {style}"


def test_ad18_verify_btn_emits_signal(dlg):
    """AD-18: 点击 verify-btn 触发 verify_requested 信号"""
    btn = dlg.findChild(QPushButton, "act-verify-btn")
    received = []
    dlg.verify_requested.connect(lambda: received.append(True))
    btn.click()
    QTest.qWait(30)
    assert len(received) >= 1, "点击 verify-btn 应触发 verify_requested 信号"


# ============ AD-19~AD-22: Status 状态 ============

def test_ad19_status_default_hidden(dlg):
    """AD-19: act-status 默认隐藏，show 时可见"""
    status = dlg.findChild(QFrame, "act-status")
    assert status is not None, "未找到 act-status"
    assert not status.isVisible(), "act-status 默认应隐藏"


def test_ad20_show_info_status(dlg):
    """AD-20: show_info() 显示 info 样式（info-light/info）"""
    status = dlg.findChild(QFrame, "act-status")
    dlg.show_info("正在验证...")
    QTest.qWait(30)
    assert status.isVisible(), "show_info 后 status 应可见"
    style = status.styleSheet().lower()
    assert "info" in style or "#dbeafe" in style or "#3b82f6" in style, \
        f"info 状态样式应含 info 色，样式: {style}"


def test_ad21_show_success_emits_activated(dlg):
    """AD-21: show_success() 显示 success 样式 + 触发 activated 信号"""
    status = dlg.findChild(QFrame, "act-status")
    received = []
    dlg.activated.connect(lambda: received.append(True))
    dlg.show_success("激活成功！")
    QTest.qWait(30)
    assert status.isVisible(), "show_success 后 status 应可见"
    style = status.styleSheet().lower()
    assert "success" in style or "#ecfdf5" in style or "#10b981" in style, \
        f"success 状态样式应含 success 色，样式: {style}"
    assert len(received) >= 1, "show_success 应触发 activated 信号"


def test_ad22_show_error_emits_failed(dlg):
    """AD-22: show_error() 显示 error 样式 + 触发 activation_failed 信号"""
    status = dlg.findChild(QFrame, "act-status")
    received = []
    dlg.activation_failed.connect(lambda msg: received.append(msg))
    dlg.show_error("激活失败：未检测到付款")
    QTest.qWait(30)
    assert status.isVisible(), "show_error 后 status 应可见"
    style = status.styleSheet().lower()
    assert "error" in style or "#fef2f2" in style or "#ef4444" in style, \
        f"error 状态样式应含 error 色，样式: {style}"
    assert len(received) >= 1, "show_error 应触发 activation_failed 信号"


# ============ AD-23~AD-25: Footer + 信号机制 ============

def test_ad23_footer_style(dlg):
    """AD-23: act-footer padding 16px 28px + border-top + 两端对齐"""
    footer = dlg.findChild(QFrame, "act-footer")
    assert footer is not None, "未找到 act-footer"
    style = footer.styleSheet().lower()
    assert "border-top: 1px" in style, f"footer 应有 border-top，样式: {style}"
    lay = footer.layout()
    m = lay.contentsMargins()
    assert m.left() == 28 and m.top() == 16, \
        f"footer padding 应为 28,16,28,16，实际 ({m.left()},{m.top()})"


def test_ad24_footer_link_discuss_signal(dlg):
    """AD-24: act-footer-link primary 色 + 文本'通过对话激活' + 点击触发 discuss_requested"""
    link_btn = dlg.findChild(QPushButton, "act-footer-link")
    assert link_btn is not None, "未找到 act-footer-link"
    text = link_btn.text()
    assert "对话" in text, f"footer-link 文本应含 '对话'，实际 '{text}'"
    style = link_btn.styleSheet().lower()
    assert "#022762" in style or "primary" in style, \
        f"footer-link 颜色应为 primary，样式: {style}"
    received = []
    dlg.discuss_requested.connect(lambda: received.append(True))
    link_btn.click()
    QTest.qWait(30)
    assert len(received) >= 1, "点击 footer-link 应触发 discuss_requested 信号"


def test_ad25_show_hide_signals(dlg):
    """AD-25: show() 触发 opened 信号，hide() 触发 closed 信号"""
    from aibridge.ui.activation_dialog import ActivationDialog
    parent = dlg.parent()
    d = ActivationDialog(parent)
    opened = []
    closed = []
    d.opened.connect(lambda: opened.append(True))
    d.closed.connect(lambda: closed.append(True))
    d.show()
    QTest.qWait(30)
    assert len(opened) >= 1, "show 应触发 opened 信号"
    d.hide()
    QTest.qWait(30)
    assert len(closed) >= 1, "hide 应触发 closed 信号"
    d.deleteLater()


# ============ 崩溃防护 ============

def test_ad26_rapid_show_hide_10x_no_crash(dlg):
    """崩溃防护：快速 show/hide 10 次不崩溃"""
    for i in range(10):
        dlg.show()
        dlg.hide()
    QTest.qWait(50)
    assert not dlg.isVisible(), "快速切换后应隐藏"


def test_ad27_rapid_status_switch_10x_no_crash(dlg):
    """崩溃防护：快速切换 status 10 次不崩溃"""
    for i in range(10):
        dlg.show_info("info")
        dlg.show_success("ok")
        dlg.show_error("err")
    QTest.qWait(50)
    status = dlg.findChild(QFrame, "act-status")
    assert status.isVisible(), "快速切换后 status 应可见"
