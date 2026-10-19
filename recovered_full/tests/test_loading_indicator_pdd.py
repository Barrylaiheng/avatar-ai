"""
LoadingIndicator PDD 验证测试（Phase 5 /tdd）

规格来源：组件自身定义的行为契约（原型中无 loading spinner 规格）：
  - HBoxLayout：spinner（BRAILLE PATTERN 10 帧字符）+ 提示文案
  - QTimer 80ms tick 自动播放 10 帧（⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏）
  - spinner 颜色 PRIMARY，字号 FONT_XL(16)
  - 文案颜色 TEXT_SECONDARY，字号 FONT_BASE(13)
  - spacing SPACE_SM(8)，padding SPACE_LG(16)
  - start/stop/is_running API
  - set_text 动态更新文案

执行：pytest tests/test_loading_indicator_pdd.py -v
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

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QWidget, QHBoxLayout, QLabel
from PyQt6.QtTest import QTest


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
        app.setApplicationName("SCAI LoadingIndicator PDD Test")
    yield app


@pytest.fixture
def loading(qapp):
    """每个测试独立的 LoadingIndicator 实例"""
    from aibridge.ui.components.loading_indicator import LoadingIndicator
    from aibridge.ui.theme import apply_theme

    apply_theme(None, "light")

    parent = QWidget()
    parent.resize(400, 100)
    ind = LoadingIndicator("正在加载知识库...", parent=parent)
    parent.show()
    QTest.qWait(30)
    yield ind
    try:
        ind.stop()
    except Exception:
        pass
    QTest.qWait(10)
    try:
        parent.close()
        ind.deleteLater()
        parent.deleteLater()
    except RuntimeError:
        pass
    QTest.qWait(10)


# ============ LI-1: 构造即启动动画（timer active）============
def test_li1_constructor_starts_animation(loading):
    """LI-1: 构造后 QTimer 处于激活态"""
    assert loading._timer.isActive(), "构造后 QTimer 应 active（自动播放动画）"


# ============ LI-2: 10 个 BRAILLE 帧 ============
def test_li2_spinner_10_braille_frames(loading):
    """LI-2: spinner 字符取自 10 个 BRAILLE PATTERN（⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏）"""
    from aibridge.ui.components.loading_indicator import _SPINNER_FRAMES
    assert len(_SPINNER_FRAMES) == 10, \
        f"应有 10 帧 BRAILLE 字符，实际 {len(_SPINNER_FRAMES)}"
    # 验证全是 BRAILLE PATTERN（0x2800 范围内的 Unicode）
    for c in _SPINNER_FRAMES:
        assert 0x2800 <= ord(c) <= 0x28FF, \
            f"帧 {c} 不是 BRAILLE PATTERN"


# ============ LI-3: tick 周期 80ms ============
def test_li3_timer_interval_80ms(loading):
    """LI-3: QTimer interval 为 80ms"""
    assert loading._timer.interval() == 80, \
        f"QTimer interval 应为 80ms，实际 {loading._timer.interval()}"


# ============ LI-4: tick 后帧推进 ============
def test_li4_tick_advances_frame(loading):
    """LI-4: tick 调用后 frame_index 推进 1（mod 10）"""
    prev = loading._frame_index
    loading._tick()
    assert loading._frame_index == (prev + 1) % 10, \
        f"tick 后 frame_index 应前进 1，实际 {prev} -> {loading._frame_index}"


# ============ LI-5: tick 后 spinner 文字更新 ============
def test_li5_tick_updates_spinner_text(loading):
    """LI-5: tick 后 spinner label 文字随帧更新"""
    from aibridge.ui.components.loading_indicator import _SPINNER_FRAMES
    # 确保推进到确定的帧
    loading._frame_index = 0
    loading._tick()  # 现在 frame_index=1
    expected = _SPINNER_FRAMES[1]
    assert loading._spinner_label.text() == expected, \
        f"tick 后 spinner 文字应为 {expected}，实际 {loading._spinner_label.text()}"


# ============ LI-6: 连续 10 次 tick 回到同一帧（循环）============
def test_li6_10_ticks_wraps_around(loading):
    """LI-6: 连续 10 次 tick 回到相同 frame_index（mod 10 循环）"""
    start = loading._frame_index
    for _ in range(10):
        loading._tick()
    assert loading._frame_index == start, \
        f"10 次 tick 后应回到帧 {start}，实际 {loading._frame_index}"


# ============ LI-7: stop() 停止 timer ============
def test_li7_stop_stops_timer(loading):
    """LI-7: stop() 后 QTimer.isActive() == False"""
    assert loading._timer.isActive()
    loading.stop()
    assert not loading._timer.isActive(), "stop() 后 QTimer 应 inactive"


# ============ LI-8: 重复 stop() 幂等 ============
def test_li8_stop_idempotent(loading):
    """LI-8: 连续调用 stop() 不崩溃"""
    loading.stop()
    loading.stop()
    loading.stop()  # 3 次
    assert not loading._timer.isActive(), "多次 stop 后仍应 inactive"


# ============ LI-9: is_running API ============
def test_li9_is_running_api(loading):
    """LI-9: is_running() 返回 timer 状态"""
    assert loading.is_running(), "初始 is_running() 应为 True"
    loading.stop()
    assert not loading.is_running(), "stop 后 is_running() 应为 False"


# ============ LI-10: set_text 更新文案 ============
def test_li10_set_text_updates_label(loading):
    """LI-10: set_text("x") 更新 text_label 文字"""
    loading.set_text("处理中，请稍候...")
    assert loading._text_label.text() == "处理中，请稍候...", \
        f"set_text 后应为 '处理中，请稍候...'，实际 {loading._text_label.text()}"


# ============ LI-11: spinner 颜色 PRIMARY ============
def test_li11_spinner_color_primary(loading):
    """LI-11: spinner 颜色 PRIMARY"""
    from aibridge.ui.theme import Theme
    style = loading._spinner_label.styleSheet().lower()
    primary_color = str(Theme.PRIMARY).lower()
    assert primary_color in style, \
        f"spinner 颜色应为 PRIMARY({primary_color})，样式: {style}"


# ============ LI-12: spinner 字号 FONT_XL(16) ============
def test_li12_spinner_font_size_xl(loading):
    """LI-12: spinner 字号 FONT_XL(16px)"""
    from aibridge.ui.theme import Theme
    style = loading._spinner_label.styleSheet().lower()
    # FONT_XL = 16
    assert "16px" in style, f"spinner 字号应为 16px，样式: {style}"


# ============ LI-13: 文案颜色 TEXT_SECONDARY ============
def test_li13_text_color_secondary(loading):
    """LI-13: 文案颜色 TEXT_SECONDARY"""
    from aibridge.ui.theme import Theme
    style = loading._text_label.styleSheet().lower()
    secondary_color = str(Theme.TEXT_SECONDARY).lower()
    assert secondary_color in style, \
        f"文案颜色应为 TEXT_SECONDARY({secondary_color})，样式: {style}"


# ============ LI-14: 文案字号 FONT_BASE(13) ============
def test_li14_text_font_size_base(loading):
    """LI-14: 文案字号 FONT_BASE(13px)"""
    from aibridge.ui.theme import Theme
    style = loading._text_label.styleSheet().lower()
    assert "13px" in style, f"文案字号应为 13px，样式: {style}"


# ============ LI-15: layout spacing SPACE_SM(8) ============
def test_li15_layout_spacing_8(loading):
    """LI-15: layout spacing SPACE_SM = 8px"""
    lay = loading.layout()
    assert lay.spacing() == 8, f"layout spacing 应为 8，实际 {lay.spacing()}"


# ============ LI-16: padding SPACE_LG(16) ============
def test_li16_padding_16(loading):
    """LI-16: padding SPACE_LG = 16px"""
    lay = loading.layout()
    m = lay.contentsMargins()
    assert m.left() == 16 and m.right() == 16 and m.top() == 16 and m.bottom() == 16, \
        f"padding 应为 16 四边，实际 margins=({m.left()},{m.top()},{m.right()},{m.bottom()})"


# ============ LI-17: 布局 AlignCenter ============
def test_li17_align_center(loading):
    """LI-17: layout alignment AlignCenter"""
    lay = loading.layout()
    assert lay.alignment() == Qt.AlignmentFlag.AlignCenter, \
        f"布局对齐应为 AlignCenter，实际 {lay.alignment()}"


# ============ LI-18: 背景透明 ============
def test_li18_background_transparent(loading):
    """LI-18: 容器化后背景为 BG_BASE 卡片（不再透明，改为独立容器）"""
    style = loading.styleSheet().lower()
    # 容器化优化：LoadingIndicator 现在是独立卡片容器，有背景+边框+圆角
    assert "background-color" in style or "transparent" in style, \
        f"背景应有背景色或透明，样式: {style}"
    assert "border" in style, \
        f"容器化后应有边框，样式: {style}"
    assert "border-radius" in style, \
        f"容器化后应有圆角，样式: {style}"


# ============ LI-19: start() API 重新启动 ============
def test_li19_start_restarts(loading):
    """LI-19: start() 重新启动已停止的动画"""
    loading.stop()
    assert not loading._timer.isActive(), "stop 后 timer 应 inactive"
    loading.start()
    assert loading._timer.isActive(), "start 后 timer 应 active"
    assert loading.is_running(), "start 后 is_running 应 True"


# ============ LI-20: 构造后默认文本 ============
def test_li20_default_text(qapp):
    """LI-20: 不传 text 时默认 "加载中..." """
    from aibridge.ui.components.loading_indicator import LoadingIndicator
    from aibridge.ui.theme import apply_theme

    apply_theme(None, "light")
    parent = QWidget()
    ind = LoadingIndicator(parent=parent)
    parent.show()
    QTest.qWait(30)
    assert ind._text_label.text() == "加载中...", \
        f"默认 text 应为 '加载中...'，实际 {ind._text_label.text()}"
    ind.stop()
    QTest.qWait(10)
    parent.close()
    ind.deleteLater()
    parent.deleteLater()


# ============ 主入口 ============
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
