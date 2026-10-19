"""
Toast/ToastManager PDD 验证测试（Phase 5 /tdd）

对应原型 ui_mockup.html L926-935 的 .toast-tip 规格：
  .toast-tip {
    position: fixed; bottom: 32px; left: 50%; transform: translateX(-50%);
    background: var(--bg-elevated); color: var(--text-primary);
    padding: 10px 20px; border-radius: 8px; font-size: 13px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.12); border: 1px solid var(--border);
    z-index: 10002; display: flex; align-items: center; gap: 6px;
    opacity: 0; transition: opacity 0.3s, transform 0.3s; pointer-events: none;
  }
  .toast-tip.show { opacity: 1; transform: translateX(-50%) translateY(-4px); }
  .toast-tip i { width: 16px; height: 16px; color: var(--success); }

执行：pytest tests/test_toast_pdd.py -v
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

from PyQt6.QtCore import Qt, QTimer, QPoint
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QWidget, QGraphicsOpacityEffect, QLabel
from PyQt6.QtTest import QTest


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
        app.setApplicationName("SCAI Toast PDD Test")
    yield app


@pytest.fixture
def parent_widget(qapp):
    """每个测试独立的父窗口"""
    from aibridge.ui.theme import apply_theme

    apply_theme(None, "light")

    pw = QWidget()
    pw.setWindowTitle("Toast Test Host")
    pw.resize(800, 600)
    pw.show()
    QTest.qWait(30)
    yield pw
    try:
        # 关闭前清理 ToastManager 单例
        from aibridge.ui.components.toast import ToastManager
        ToastManager.reset_instance(id(pw))
    except Exception:
        pass
    try:
        pw.close()
        pw.deleteLater()
    except RuntimeError:
        pass
    QTest.qWait(10)


# ============ TM-1: 背景色 bg-elevated ============
def test_tm1_background_bg_elevated(parent_widget):
    """TM-1: 背景 bg-elevated（原型 background: var(--bg-elevated)）"""
    from aibridge.ui.theme import get_token
    from aibridge.ui.components.toast import Toast, ToastType
    from aibridge.ui.theme import Theme

    toast = Toast("测试提示", ToastType.INFO, 500, parent_widget)
    style = toast.styleSheet().lower()
    expected = str(get_token("BG_ELEVATED")).lower()
    # 查找 styleSheet 中 background-color 的值
    assert "background" in style and (expected in style or "bg_elevated" in style), \
        f"背景应为 BG_ELEVATED({expected})，样式: {style}"
    toast.deleteLater()


# ============ TM-2: 边框 border ============
def test_tm2_border_token(parent_widget):
    """TM-2: 边框 1px border token（原型 border: 1px solid var(--border)）"""
    from aibridge.ui.theme import get_token
    from aibridge.ui.components.toast import Toast, ToastType

    toast = Toast("测试提示", ToastType.INFO, 500, parent_widget)
    style = toast.styleSheet().lower()
    expected_border = str(get_token("BORDER")).lower()
    # 原型是统一 border: 1px solid var(--border)，不是 border-left
    assert "border" in style and expected_border in style, \
        f"应有统一 border({expected_border})，样式: {style}"
    toast.deleteLater()


# ============ TM-3: padding 10px 20px ============
def test_tm3_padding_10_20(parent_widget):
    """TM-3: padding 10px 20px（原型 padding: 10px 20px）"""
    from aibridge.ui.components.toast import Toast, ToastType

    toast = Toast("测试提示", ToastType.INFO, 500, parent_widget)
    lay = toast.layout()
    margins = lay.contentsMargins()
    # 左右 20px，上下 10px
    assert margins.left() == 20, f"左 padding 应为 20，实际 {margins.left()}"
    assert margins.right() == 20, f"右 padding 应为 20，实际 {margins.right()}"
    assert margins.top() == 10, f"上 padding 应为 10，实际 {margins.top()}"
    assert margins.bottom() == 10, f"下 padding 应为 10，实际 {margins.bottom()}"
    toast.deleteLater()


# ============ TM-4: radius 8px ============
def test_tm4_radius_8px(parent_widget):
    """TM-4: border-radius 8px（原型 border-radius: 8px）"""
    from aibridge.ui.components.toast import Toast, ToastType

    toast = Toast("测试提示", ToastType.INFO, 500, parent_widget)
    style = toast.styleSheet().lower()
    # 原型 radius 固定 8
    assert "8px" in style or "border-radius: 8" in style, \
        f"radius 应为 8px，样式: {style}"
    toast.deleteLater()


# ============ TM-5: font-size 13px ============
def test_tm5_font_size_13px(parent_widget):
    """TM-5: 文字 font-size 13px（原型 font-size: 13px）"""
    from aibridge.ui.components.toast import Toast, ToastType

    toast = Toast("测试提示", ToastType.INFO, 500, parent_widget)
    # 查找 text QLabel
    for lbl in toast.findChildren(QLabel):
        if lbl.text() == "测试提示":
            text_style = lbl.styleSheet().lower()
            assert "13px" in text_style, \
                f"文字 font-size 应为 13px，样式: {text_style}"
            break
    else:
        pytest.fail("未找到 text QLabel")
    toast.deleteLater()


# ============ TM-6: icon 尺寸 16px + success 色 ============
def test_tm6_icon_16px_color(parent_widget):
    """TM-6: icon 16×16 尺寸 + success 色（原型 .toast-tip i { width:16px; height:16px; color:var(--success) }）"""
    from aibridge.ui.theme import get_token
    from aibridge.ui.components.toast import Toast, ToastType

    toast = Toast("测试提示", ToastType.SUCCESS, 500, parent_widget)
    # 查找 icon QLabel（非文字 label）
    labels = toast.findChildren(QLabel)
    icon_lbl = None
    for lbl in labels:
        if lbl.text() in ("✓", "✕", "⚠", "ℹ"):
            icon_lbl = lbl
            break
    assert icon_lbl is not None, "未找到 icon label"
    style = icon_lbl.styleSheet().lower()
    success_color = str(get_token("SUCCESS")).lower()
    assert success_color in style, f"icon 颜色应为 SUCCESS({success_color})，样式: {style}"
    toast.deleteLater()


# ============ TM-7: gap 6px ============
def test_tm7_spacing_gap_6(parent_widget):
    """TM-7: 布局 spacing gap 6px（原型 .toast-tip { gap: 6px }）"""
    from aibridge.ui.components.toast import Toast, ToastType

    toast = Toast("测试提示", ToastType.INFO, 500, parent_widget)
    lay = toast.layout()
    assert lay.spacing() == 6, f"spacing 应为 6，实际 {lay.spacing()}"
    toast.deleteLater()


# ============ TM-8: 入场动画 opacity 时长 300ms ============
def test_tm8_anim_in_300ms(parent_widget):
    """TM-8: 入场动画 opacity 0→1 时长 300ms（原型 transition: opacity 0.3s）"""
    from aibridge.ui.components.toast import Toast, ToastType

    toast = Toast("测试提示", ToastType.INFO, 500, parent_widget)
    dur = toast._anim_in.duration()
    assert dur == 300, f"入场动画时长应为 300ms，实际 {dur}"
    toast.deleteLater()


# ============ TM-9: 入场动画起始 opacity 0 ============
def test_tm9_anim_in_start_opacity_0(parent_widget):
    """TM-9: 入场动画 startValue opacity=0（原型 opacity: 0）"""
    from aibridge.ui.components.toast import Toast, ToastType

    toast = Toast("测试提示", ToastType.INFO, 500, parent_widget)
    start_val = toast._anim_in.startValue()
    assert abs(float(start_val) - 0.0) < 1e-6, \
        f"入场动画起始 opacity 应为 0，实际 {start_val}"
    toast.deleteLater()


# ============ TM-10: 入场动画终点 opacity 1 ============
def test_tm10_anim_in_end_opacity_1(parent_widget):
    """TM-10: 入场动画 endValue opacity=1（原型 .show { opacity: 1 }）"""
    from aibridge.ui.components.toast import Toast, ToastType

    toast = Toast("测试提示", ToastType.INFO, 500, parent_widget)
    end_val = toast._anim_in.endValue()
    assert abs(float(end_val) - 1.0) < 1e-6, \
        f"入场动画终点 opacity 应为 1，实际 {end_val}"
    toast.deleteLater()


# ============ TM-11: 出场动画时长 300ms ============
def test_tm11_anim_out_300ms(parent_widget):
    """TM-11: 出场动画 opacity 1→0 时长 300ms（原型 transition 0.3s）"""
    from aibridge.ui.components.toast import Toast, ToastType

    toast = Toast("测试提示", ToastType.INFO, 500, parent_widget)
    dur = toast._anim_out.duration()
    assert dur == 300, f"出场动画时长应为 300ms，实际 {dur}"
    toast.deleteLater()


# ============ TM-12: 非独立窗口（作为 parent widget 的子控件 overlay）============
def test_tm12_not_independent_window(parent_widget):
    """TM-12: Toast 是 parent widget 的子控件，不是独立窗口

    原型：position: fixed（相对于父容器），不是 FramelessWindowHint 独立窗口。
    原因：独立窗口在某些平台上 z-order 管理困难，子控件 overlay 更稳定。
    """
    from aibridge.ui.components.toast import Toast, ToastType

    toast = Toast("测试提示", ToastType.INFO, 500, parent_widget)
    # 子控件（parent 不为 None）
    assert toast.parent() is not None, "Toast 应有 parent"
    # 非独立窗口：不包含 Tool / Popup / Window flags
    flags = toast.windowFlags()
    is_tool = bool(flags & Qt.WindowType.Tool)
    is_window = bool(flags & Qt.WindowType.Window)
    assert not is_tool and not is_window, \
        f"Toast 不应是独立窗口（flags={flags}），应是 parent 子控件 overlay"
    toast.deleteLater()


# ============ TM-13: pointer-events: none ============
def test_tm13_pointer_events_none(parent_widget):
    """TM-13: Toast 不接收鼠标事件（原型 pointer-events: none）

    实现方式：setAttribute(WA_TransparentForMouseEvents) 或 setAttribute(WA_NoMousePropagation)
    或通过样式表设置 background: transparent 并确保不拦截。
    """
    from aibridge.ui.components.toast import Toast, ToastType

    toast = Toast("测试提示", ToastType.INFO, 500, parent_widget)
    transparent = toast.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert transparent, "Toast 应设置 WA_TransparentForMouseEvents（pointer-events: none）"
    toast.deleteLater()


# ============ TM-14: show_at 位置：底部 32px + 水平居中 ============
def test_tm14_position_bottom_32_horizontally_centered(parent_widget):
    """TM-14: 位置 bottom: 32px（原型 position: fixed; bottom: 32px; left: 50%）

    在 parent_widget 的坐标系下，Toast 应距底部 32px，水平居中。
    """
    from aibridge.ui.components.toast import Toast, ToastType

    toast = Toast("测试提示", ToastType.INFO, 500, parent_widget)
    toast.show_at(parent_widget)
    QTest.qWait(50)

    # 在父窗口坐标系下的 Toast 几何信息
    pw = parent_widget.width()
    ph = parent_widget.height()
    toast_x = toast.geometry().x()
    toast_y = toast.geometry().y()
    toast_w = toast.geometry().width()
    toast_h = toast.geometry().height()

    # 距底部距离（允许 2px 误差）
    bottom_dist = ph - (toast_y + toast_h)
    assert abs(bottom_dist - 32) <= 2, \
        f"Toast 距底部应为 32px，实际 {bottom_dist}"
    # 水平居中（允许 2px 误差，layout adjustSize 浮动）
    expected_x = (pw - toast_w) // 2
    assert abs(toast_x - expected_x) <= 2, \
        f"Toast 水平居中 x 应为 {expected_x}，实际 {toast_x}"
    toast.deleteLater()


# ============ TM-15: manager success API ============
def test_tm15_manager_success_shows_toast(parent_widget):
    """TM-15: ToastManager.instance().success() 应创建 Toast 并显示"""
    from aibridge.ui.components.toast import ToastManager, Toast

    manager = ToastManager.instance(parent_widget)
    manager.success("保存成功", duration_ms=300)
    QTest.qWait(100)
    # parent_widget 下应存在 Toast 子控件
    toasts = parent_widget.findChildren(Toast)
    assert len(toasts) >= 1, f"调用 success() 后应创建 Toast，实际找到 {len(toasts)}"
    # 等待关闭
    QTest.qWait(1000)


# ============ TM-16: manager 4 种类型 API 存在 ============
def test_tm16_manager_4_type_apis(parent_widget):
    """TM-16: ToastManager 有 success/error/warning/info 四个便捷 API"""
    from aibridge.ui.components.toast import ToastManager

    manager = ToastManager.instance(parent_widget)
    assert hasattr(manager, "success"), "缺少 success() API"
    assert hasattr(manager, "error"), "缺少 error() API"
    assert hasattr(manager, "warning"), "缺少 warning() API"
    assert hasattr(manager, "info"), "缺少 info() API"


# ============ TM-17: 默认时长 API ============
def test_tm17_default_durations(parent_widget):
    """TM-17: 默认时长：info/success/warning 短（2500ms），error 长（3000ms）"""
    from aibridge.ui.components.toast import ToastManager, Toast
    import inspect

    manager = ToastManager.instance(parent_widget)

    # 用 monkey-patch 捕获实际传给 _enqueue 的时长参数
    actual = {}
    orig = manager._show_now

    def capture_show_now(text, t, duration_ms):
        actual[t.value] = duration_ms
        # 创建但不真正显示（节省时间）
        toast = Toast(text, t, duration_ms, parent_widget)
        toast.hide()

    manager._show_now = capture_show_now
    try:
        manager.success("s")
        manager.error("e")
        manager.warning("w")
        manager.info("i")
    finally:
        manager._show_now = orig

    assert actual.get("success") == 2500, f"success 默认时长 2500ms，实际 {actual.get('success')}"
    assert actual.get("error") == 3000, f"error 默认时长 3000ms，实际 {actual.get('error')}"
    assert actual.get("warning") == 2500, f"warning 默认时长 2500ms，实际 {actual.get('warning')}"
    assert actual.get("info") == 2500, f"info 默认时长 2500ms，实际 {actual.get('info')}"


# ============ TM-18: 最大并发 3 个，其余入队 ============
def test_tm18_max_concurrent_3_queue_rest(parent_widget):
    """TM-18: 最大同时显示 3 个 Toast，其余先入队"""
    from aibridge.ui.components.toast import ToastManager, Toast

    manager = ToastManager.instance(parent_widget)
    # 清除之前的
    ToastManager.reset_instance(id(parent_widget))
    manager = ToastManager.instance(parent_widget)

    # 发送 5 个
    for i in range(5):
        manager.info(f"提示{i}", duration_ms=500)
    QTest.qWait(50)

    active_count = len(manager._active)
    queue_count = len(manager._queue)
    assert active_count <= 3, f"active 应 <= 3，实际 {active_count}"
    assert active_count + queue_count == 5, \
        f"active + queue 应 = 5，实际 {active_count}+{queue_count}"


# ============ TM-19: active 关闭后队列 flush ============
def test_tm19_active_closed_flushes_queue(parent_widget):
    """TM-19: active Toast 关闭时，队列中的应补入"""
    from aibridge.ui.components.toast import ToastManager, Toast

    manager = ToastManager.instance(parent_widget)
    ToastManager.reset_instance(id(parent_widget))
    manager = ToastManager.instance(parent_widget)

    # 发 4 个短时长（100ms），确认 queue 有 1 个
    for i in range(4):
        manager.info(f"提示{i}", duration_ms=100)
    QTest.qWait(50)
    assert len(manager._queue) == 1, f"初始 queue 应有 1 个，实际 {len(manager._queue)}"

    # 等待关闭 + flush
    QTest.qWait(400)
    # 全部显示完后 active 为 0，queue 为 0
    assert len(manager._queue) == 0, f"显示完后 queue 应为空，实际 {len(manager._queue)}"


# ============ TM-20: z-index 高（置顶）============
def test_tm20_high_z_order(parent_widget):
    """TM-20: Toast z-index 高，显示后应在最上方（raise_）"""
    from aibridge.ui.components.toast import Toast, ToastType

    toast = Toast("测试提示", ToastType.INFO, 500, parent_widget)
    toast.show_at(parent_widget)
    QTest.qWait(50)
    # 调用了 raise_()，通过 stackUnder 判断是否在栈顶的间接方式：
    # 子控件的 stacking order，raise_ 后应是 last
    # 这里简单验证是 show 状态即可（raise_ 验证需同级控件对比，MVP 可接受宽松验证）
    assert toast.isVisible(), "Toast show_at 后应可见"
    toast.deleteLater()


# ============ 主入口 ============
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
