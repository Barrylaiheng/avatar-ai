"""
Sidebar PDD 验证测试（Phase 5 /tdd）

对应 Phase 3 spec 的 10 个 Test Seams：
  Seam-1: 尺寸断言（启动态）
  Seam-2: 动画断言（hover 展开）
  Seam-3: 动画断言（leave 收起）
  Seam-4: 无延迟断言
  Seam-5: 崩溃防护（快速 hover）
  Seam-6: 崩溃防护（resize）
  Seam-7: Active 蓝条断言
  Seam-8: 主题切换断言
  Seam-9: Logo 断言
  Seam-10: Footer 断言

执行：pytest tests/test_sidebar_pdd.py -v
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# 确保项目 src 在 path 中
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# 环境变量：软件渲染，避免集成显卡崩溃
os.environ.setdefault("QT_OPENGL", "software")

from PyQt6.QtCore import Qt, QEvent, QTimer
from PyQt6.QtGui import QEnterEvent, QColor, QMouseEvent
from PyQt6.QtWidgets import QApplication, QWidget, QFrame, QLabel
from PyQt6.QtTest import QTest


# ============ T1: 测试脚手架 ============

@pytest.fixture(scope="session")
def qapp():
    """会话级 QApplication 实例（整个测试会话只创建一次）"""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
        app.setApplicationName("SCAI PDD Test")
    yield app


@pytest.fixture
def sidebar(qapp):
    """每个测试独立的 Sidebar 实例（不依赖 AppEngine，纯 UI 单元测试）"""
    from aibridge.ui.sidebar import Sidebar
    from aibridge.ui.theme import apply_theme

    # 确保浅色主题
    apply_theme(None, "light")

    # 用父窗口确保布局约束生效（单独 show() 的 Sidebar 可能用 sizeHint 而非 maximumWidth）
    parent = QWidget()
    parent.resize(800, 600)
    sb = Sidebar(parent)
    # 禁用 hover 展开：防止 show 时鼠标位置在 Sidebar 区域内触发 enterEvent → expand
    # 测试中通过直接调用 expand()/collapse() 验证动画，不依赖 enterEvent
    sb._hover_expand_enabled = False
    parent.show()
    QTest.qWait(50)  # 等待渲染
    yield sb
    # 安全关闭
    try:
        parent.close()
        sb.deleteLater()
        parent.deleteLater()
    except RuntimeError:
        pass
    QTest.qWait(10)


# ============ T1 基础：Sidebar 存在 ============

def test_sidebar_exists(sidebar):
    """T1: Sidebar 能实例化且可见"""
    assert sidebar.isVisible()
    assert sidebar.objectName() == "Sidebar"


# ============ T2: Seam-1 尺寸断言 ============

def test_collapse_width_56(sidebar):
    """Seam-1: 启动态宽度 == 56"""
    assert sidebar.width() == 56, f"折叠态宽度应为 56，实际 {sidebar.width()}"


def test_logo_size_36(sidebar):
    """Seam-9: Logo 36×36"""
    logo = sidebar.findChild(QFrame, "sidebar-logo-box")
    assert logo is not None, "未找到 sidebar-logo-box"
    assert logo.width() == 36, f"Logo 宽度应为 36，实际 {logo.width()}"
    assert logo.height() == 36, f"Logo 高度应为 36，实际 {logo.height()}"


def test_nav_icon_container_24(sidebar):
    """Seam-1: 图标容器 24×24"""
    # NavItem 内部的 _icon_wrap
    from aibridge.ui.sidebar import NavItem
    nav_items = sidebar.findChildren(NavItem)
    assert len(nav_items) > 0, "未找到任何 NavItem"
    first = nav_items[0]
    assert first._icon_wrap.width() == 24, f"图标容器宽度应为 24，实际 {first._icon_wrap.width()}"
    assert first._icon_wrap.height() == 24, f"图标容器高度应为 24，实际 {first._icon_wrap.height()}"


def test_nav_item_height_42(sidebar):
    """Seam-1: 导航项高度 42"""
    from aibridge.ui.sidebar import NavItem
    nav_items = sidebar.findChildren(NavItem)
    for item in nav_items:
        assert item.height() == 42, f"导航项 {item.page_id} 高度应为 42，实际 {item.height()}"


def test_logo_bar_height_42(sidebar):
    """Seam-1: logo-bar 高度 42（原型 L171）"""
    logo_bar = sidebar.findChild(QWidget, "logo-bar")
    assert logo_bar is not None, "未找到 logo-bar"
    assert logo_bar.height() == 42, f"logo-bar 高度应为 42，实际 {logo_bar.height()}"


# ============ T2: Seam-7 Active 蓝条断言 ============

def test_active_bar_3x22(sidebar):
    """Seam-7: active 蓝条 3×22"""
    from aibridge.ui.sidebar import NavItem
    nav_items = sidebar.findChildren(NavItem)
    chat_item = next((i for i in nav_items if i.page_id == "chat"), None)
    assert chat_item is not None, "未找到 chat NavItem"
    assert chat_item.is_active(), "chat 应为 active"

    bar = chat_item._active_bar
    assert bar is not None, "未找到 active bar"
    assert bar.width() == 3, f"蓝条宽度应为 3，实际 {bar.width()}"
    assert bar.height() == 22, f"蓝条高度应为 22，实际 {bar.height()}"


def test_active_bar_visible_when_collapsed(sidebar):
    """Seam-7: 折叠态下 active 蓝条仍然显示（原型 L211 无 hover 条件）"""
    from aibridge.ui.sidebar import NavItem
    nav_items = sidebar.findChildren(NavItem)
    chat_item = next((i for i in nav_items if i.page_id == "chat"), None)
    assert sidebar.is_collapsed(), "应为折叠态"
    assert chat_item.is_active(), "chat 应为 active"
    # 当前 set_collapsed(True) 会隐藏蓝条，这是 bug
    assert chat_item._active_bar.isVisible(), "折叠态下 active 蓝条应仍显示"


def test_active_bar_color_primary(sidebar):
    """Seam-7: 蓝条颜色 #022762（浅色模式）"""
    from aibridge.ui.sidebar import NavItem
    nav_items = sidebar.findChildren(NavItem)
    chat_item = next((i for i in nav_items if i.page_id == "chat"), None)
    # 蓝条样式应包含 background-color: #022762
    style = chat_item._active_bar.styleSheet()
    assert "#022762" in style.lower(), f"蓝条颜色应为 #022762，样式: {style}"


# ============ T2: Seam-9 Logo 断言 ============

def test_logo_bg_primary_radius_8(sidebar):
    """Seam-9: Logo 背景 #022762 + 圆角 8px"""
    logo = sidebar.findChild(QFrame, "sidebar-logo-box")
    style = logo.styleSheet()
    assert "#022762" in style.lower(), f"Logo 背景应为 #022762，样式: {style}"
    assert "border-radius: 8px" in style, f"Logo 圆角应为 8px，样式: {style}"


def test_logo_has_shadow(sidebar):
    """Seam-9: Logo 有阴影效果"""
    logo = sidebar.findChild(QFrame, "sidebar-logo-box")
    effect = logo.graphicsEffect()
    assert effect is not None, "Logo 应有 QGraphicsDropShadowEffect"
    from PyQt6.QtWidgets import QGraphicsDropShadowEffect
    assert isinstance(effect, QGraphicsDropShadowEffect), "effect 应为 DropShadow"


# ============ T2: Seam-10 Footer 断言 ============

def test_footer_at_bottom(sidebar):
    """Seam-10: Footer 贴底"""
    # footer_wrap 是最后一个 addWidget
    footer = sidebar.findChild(QWidget, "logo-bar")  # 先确认 logo-bar 找得到
    # 找 footer 里的 settings nav item
    from aibridge.ui.sidebar import NavItem
    nav_items = sidebar.findChildren(NavItem)
    settings_item = next((i for i in nav_items if i.page_id == "settings"), None)
    assert settings_item is not None, "未找到 settings NavItem"
    # settings 的 y + height 应接近 sidebar 的底部
    sb_bottom = sidebar.height()
    settings_bottom = settings_item.mapTo(sidebar, settings_item.rect().bottomRight()).y()
    assert abs(sb_bottom - settings_bottom) < 50, f"Footer 应贴底，settings 底部 {settings_bottom}，sidebar 底部 {sb_bottom}"


# ============ T3: Seam-2 动画断言（hover 展开）============

def test_hover_expand_to_220(sidebar):
    """Seam-2: hover 后 260ms width == 220（±1px 浮点容差）"""
    assert sidebar.width() == 56, "起始应为折叠态 56"
    sidebar.expand()
    QTest.qWait(260)  # 动画 250ms + 10ms 容差
    # QPropertyAnimation 浮点数计算可能产生 219，允许 ±1px 容差
    actual = sidebar.width()
    assert abs(actual - 220) <= 1, f"展开后宽度应为 220±1，实际 {actual}"


def test_expand_maximum_width_220(sidebar):
    """Seam-2: 展开后 maximumWidth == 220（±1px 浮点容差）"""
    sidebar.expand()
    QTest.qWait(260)
    # QPropertyAnimation 浮点数计算可能产生 219，允许 ±1px 容差
    actual = sidebar.maximumWidth()
    assert abs(actual - 220) <= 1, f"maximumWidth 应为 220±1，实际 {actual}"


# ============ T3: Seam-3 动画断言（leave 收起）============

def test_leave_collapse_to_56(sidebar):
    """Seam-3: leave 后 260ms width == 56（±1px 浮点容差）"""
    sidebar.expand()
    QTest.qWait(260)
    # QPropertyAnimation 浮点数计算可能产生 219，允许 ±1px 容差
    expanded_w = sidebar.width()
    assert abs(expanded_w - 220) <= 1, f"展开后宽度应为 220±1，实际 {expanded_w}"
    sidebar.collapse()
    QTest.qWait(260)
    assert sidebar.width() == 56, f"收起后宽度应为 56，实际 {sidebar.width()}"


# ============ T3: Seam-4 无延迟断言 ============

def test_no_delay_on_leave(sidebar):
    """Seam-4: leave 后无延迟，动画立即启动（非 _collapse_timer 延时 300ms）

    验证两点：
    1. 调用 collapse() 后 _collapse_timer 未激活（直接收起，非延时调度）
    2. 动画 _anim 状态为 Running（立即开始，非排队等待）
    """
    from PyQt6.QtCore import QAbstractAnimation
    sidebar.expand()
    QTest.qWait(260)
    # QPropertyAnimation 浮点数计算可能产生 219，允许 ±1px 容差
    expanded_max = sidebar.maximumWidth()
    assert abs(expanded_max - 220) <= 1, f"展开后 maximumWidth 应为 220±1，实际 {expanded_max}"
    # 直接调用 collapse()（等价于 leaveEvent 的行为）
    sidebar.collapse()
    # 立刻检查（不等待）：_collapse_timer 已删除，不应存在
    assert not hasattr(sidebar, '_collapse_timer') or sidebar._collapse_timer is None, "无延迟收起：_collapse_timer 不应存在或激活"
    # 动画应处于 Running 状态（立即启动）
    assert sidebar._anim.state() == QAbstractAnimation.State.Running, (
        f"无延迟收起：动画应立即启动（Running），实际状态 {sidebar._anim.state()}"
    )


# ============ T4: Seam-5 崩溃防护（快速 hover）============

def test_rapid_hover_10x_no_crash(sidebar):
    """Seam-5: 10 次快速 enter/leave 无崩溃"""
    for i in range(10):
        sidebar.expand()
        QTest.qWait(50)
        sidebar.collapse()
        QTest.qWait(50)
    # 最终稳定
    QTest.qWait(300)
    assert sidebar.isVisible(), "10 次快速 hover 后 Sidebar 应仍可见"
    assert sidebar.width() == 56, f"最终应为折叠态 56，实际 {sidebar.width()}"


# ============ T4: Seam-6 崩溃防护（resize）============

def test_resize_no_crash(qapp, sidebar):
    """Seam-6: 极端 resize 不崩溃（sidebar 已在父窗口中）"""
    parent = sidebar.parent()

    parent.resize(400, 300)
    QTest.qWait(50)
    parent.resize(1200, 900)
    QTest.qWait(50)
    parent.resize(100, 100)
    QTest.qWait(50)

    assert sidebar.isVisible(), "resize 后 Sidebar 应仍可见"


# ============ T5: Seam-8 主题切换断言 ============

def test_dark_mode_sidebar_bg(sidebar):
    """Seam-8: 暗色模式背景 #121828"""
    from aibridge.ui.theme import apply_theme, get_current_theme
    apply_theme(sidebar.window(), "dark")
    sidebar._apply_stylesheet()
    QTest.qWait(50)
    style = sidebar.styleSheet()
    assert "#121828" in style.lower(), f"暗色模式背景应为 #121828，样式: {style}"


def test_dark_mode_active_bar_color(sidebar):
    """Seam-8: 暗色模式蓝条 #7BA0C8"""
    from aibridge.ui.theme import apply_theme
    apply_theme(sidebar.window(), "dark")
    sidebar._apply_stylesheet()
    from aibridge.ui.sidebar import NavItem
    nav_items = sidebar.findChildren(NavItem)
    chat_item = next((i for i in nav_items if i.page_id == "chat"), None)
    chat_item._apply_styles()
    chat_item._update_active_visual()
    QTest.qWait(50)
    style = chat_item._active_bar.styleSheet()
    assert "#7ba0c8" in style.lower(), f"暗色模式蓝条应为 #7BA0C8，样式: {style}"


# ============ 主入口 ============

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
