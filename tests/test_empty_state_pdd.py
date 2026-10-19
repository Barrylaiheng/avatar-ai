"""
EmptyState PDD 验证测试（Phase 5 /tdd）

对应原型 ui_mockup.html L3937 的空状态 inline 样式规格：
  <div style="padding:30px; text-align:center; color:var(--text-tertiary); font-size:13px;">
    暂无定时任务 · 点击右上角「新建任务」创建
  </div>

扩展规格（基于原型的最小一致空状态语言）：
  - padding: 30px
  - text-align: center（垂直+水平居中）
  - color: var(--text-tertiary)
  - font-size: 13px
  - icon 可选（保持原有 emoji 36px 视觉权重，不破坏原型精神）
  - title 可选（当只有 description 时，description 即 title）
  - action 按钮可选

执行：pytest tests/test_empty_state_pdd.py -v
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
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QPushButton
from PyQt6.QtTest import QTest


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
        app.setApplicationName("SCAI EmptyState PDD Test")
    yield app


@pytest.fixture
def empty(qapp):
    """每个测试独立的 EmptyState 实例（默认带 icon/title/desc/action）"""
    from aibridge.ui.components.empty_state import EmptyState
    from aibridge.ui.theme import apply_theme

    apply_theme(None, "light")

    parent = QWidget()
    parent.resize(400, 300)
    es = EmptyState(
        icon="📭",
        title="暂无知识条目",
        description="点击「新建条目」开始构建你的知识库",
        action_text="新建条目",
        parent=parent,
    )
    parent.show()
    QTest.qWait(30)
    yield es
    try:
        parent.close()
        es.deleteLater()
        parent.deleteLater()
    except RuntimeError:
        pass
    QTest.qWait(10)


@pytest.fixture
def empty_minimal(qapp):
    """最小化空状态（只有 description，对齐原型 inline 样式）"""
    from aibridge.ui.components.empty_state import EmptyState
    from aibridge.ui.theme import apply_theme

    apply_theme(None, "light")

    parent = QWidget()
    parent.resize(400, 300)
    es = EmptyState(
        description="暂无定时任务 · 点击右上角「新建任务」创建",
        parent=parent,
    )
    parent.show()
    QTest.qWait(30)
    yield es
    try:
        parent.close()
        es.deleteLater()
        parent.deleteLater()
    except RuntimeError:
        pass
    QTest.qWait(10)


# ============ ES-1: padding 30px ============
def test_es1_padding_30px(empty):
    """ES-1: padding 30px（原型 padding:30px）"""
    lay = empty.layout()
    margins = lay.contentsMargins()
    assert margins.left() == 30, f"左 padding 应为 30，实际 {margins.left()}"
    assert margins.right() == 30, f"右 padding 应为 30，实际 {margins.right()}"
    assert margins.top() == 30, f"上 padding 应为 30，实际 {margins.top()}"
    assert margins.bottom() == 30, f"下 padding 应为 30，实际 {margins.bottom()}"


# ============ ES-2: text-align center（垂直+水平居中）============
def test_es2_align_center(empty):
    """ES-2: layout AlignCenter（原型 text-align:center）"""
    lay = empty.layout()
    alignment = lay.alignment()
    assert alignment == Qt.AlignmentFlag.AlignCenter, \
        f"layout 对齐应为 AlignCenter，实际 {alignment}"


# ============ ES-3: 描述文字颜色 text-tertiary ============
def test_es3_description_color_text_tertiary(empty):
    """ES-3: 描述文字颜色 text-tertiary（原型 color:var(--text-tertiary)）"""
    from aibridge.ui.theme import get_token

    desc_label = empty.findChild(QLabel, None)
    # 找到描述 label（包含 "知识库" 文本）
    desc_labels = [l for l in empty.findChildren(QLabel) if "知识库" in l.text()]
    assert len(desc_labels) >= 1, "未找到描述 label"
    style = desc_labels[0].styleSheet().lower()
    expected_color = str(get_token("TEXT_TERTIARY")).lower()
    assert expected_color in style, \
        f"描述颜色应为 TEXT_TERTIARY({expected_color})，样式: {style}"


# ============ ES-4: 描述文字 font-size 13px ============
def test_es4_description_font_size_13px(empty):
    """ES-4: 描述文字 font-size 13px（原型 font-size:13px）"""
    desc_labels = [l for l in empty.findChildren(QLabel) if "知识库" in l.text()]
    assert len(desc_labels) >= 1, "未找到描述 label"
    style = desc_labels[0].styleSheet().lower()
    assert "13px" in style, f"描述 font-size 应为 13px，样式: {style}"


# ============ ES-5: 标题颜色 text-tertiary（与原型一致）============
def test_es5_title_color_text_tertiary(empty):
    """ES-5: 标题颜色 text-tertiary（原型所有文字均 text-tertiary）

    原型 inline 样式作用于整个 div，所有文字（title/desc）颜色一致。
    """
    from aibridge.ui.theme import get_token

    title_labels = [l for l in empty.findChildren(QLabel) if "暂无知识条目" in l.text()]
    assert len(title_labels) >= 1, "未找到标题 label"
    style = title_labels[0].styleSheet().lower()
    expected_color = str(get_token("TEXT_TERTIARY")).lower()
    assert expected_color in style, \
        f"标题颜色应为 TEXT_TERTIARY({expected_color})，样式: {style}"


# ============ ES-6: 标题 font-size 13px ============
def test_es6_title_font_size_13px(empty):
    """ES-6: 标题 font-size 13px（原型统一 font-size:13px）"""
    title_labels = [l for l in empty.findChildren(QLabel) if "暂无知识条目" in l.text()]
    assert len(title_labels) >= 1, "未找到标题 label"
    style = title_labels[0].styleSheet().lower()
    assert "13px" in style, f"标题 font-size 应为 13px，样式: {style}"


# ============ ES-7: icon 可选（默认 📭）============
def test_es7_icon_default(empty):
    """ES-7: icon 默认 📭"""
    icon_labels = [l for l in empty.findChildren(QLabel) if l.text() == "📭"]
    assert len(icon_labels) >= 1, "应有默认 icon 📭"


# ============ ES-8: action 按钮可选（不传 action_text 时不创建）============
def test_es8_action_optional(qapp):
    """ES-8: 不传 action_text 时不创建按钮"""
    from aibridge.ui.components.empty_state import EmptyState
    from aibridge.ui.theme import apply_theme

    apply_theme(None, "light")
    parent = QWidget()
    es = EmptyState(description="无按钮空状态", parent=parent)
    buttons = es.findChildren(QPushButton)
    assert len(buttons) == 0, f"不传 action_text 时不应创建按钮，实际 {len(buttons)}"
    parent.deleteLater()


# ============ ES-9: action 按钮点击触发 action_clicked 信号 ============
def test_es9_action_clicked_signal(empty):
    """ES-9: 点击 action 按钮触发 action_clicked 信号"""
    received = []
    empty.action_clicked.connect(lambda: received.append(True))
    btn = empty.findChild(QPushButton)
    assert btn is not None, "应有 action 按钮"
    btn.click()
    assert len(received) >= 1, "点击按钮后应触发 action_clicked 信号"


# ============ ES-10: set_text 更新 title ============
def test_es10_set_text_title(empty):
    """ES-10: set_text(title=...) 更新标题"""
    empty.set_text(title="新标题")
    title_labels = [l for l in empty.findChildren(QLabel) if "新标题" in l.text()]
    assert len(title_labels) >= 1, "set_text 后应更新标题文字"


# ============ ES-11: set_text 更新 description ============
def test_es11_set_text_description(empty):
    """ES-11: set_text(description=...) 更新描述"""
    empty.set_text(description="新描述内容")
    desc_labels = [l for l in empty.findChildren(QLabel) if "新描述内容" in l.text()]
    assert len(desc_labels) >= 1, "set_text 后应更新描述文字"


# ============ ES-12: set_text description=None 隐藏描述 ============
def test_es12_set_text_description_none_hides(empty):
    """ES-12: set_text(description=None) 不影响现有描述（None 跳过）

    设计决策：None 表示"不更新"，空字符串才表示"隐藏"。
    这样调用更安全（set_text(title="x") 不会误清空 description）。
    """
    original_desc = "点击「新建条目」开始构建你的知识库"
    empty.set_text(description=None)
    # None 应跳过，描述保持原样
    desc_labels = [l for l in empty.findChildren(QLabel) if original_desc in l.text()]
    assert len(desc_labels) >= 1, "set_text(description=None) 应保留原描述"


# ============ ES-13: set_text description="" 隐藏描述 ============
def test_es13_set_text_description_empty_hides(empty):
    """ES-13: set_text(description="") 隐藏描述"""
    empty.set_text(description="")
    QTest.qWait(30)
    # 描述 label 应隐藏
    desc_labels = [l for l in empty.findChildren(QLabel) if "知识库" in l.text()]
    # 要么找不到，要么不可见
    visible = [l for l in desc_labels if l.isVisible()]
    assert len(visible) == 0, f"description='' 后描述应隐藏，仍有 {len(visible)} 个可见"


# ============ ES-14: 最小空状态（只有 description）对齐原型 ============
def test_es14_minimal_only_description(empty_minimal):
    """ES-14: 只有 description 的空状态（对齐原型 inline 样式）

    原型：单 div 包含文字，padding:30px + center + text-tertiary + 13px
    """
    # 应有 1 个 label（description）
    labels = empty_minimal.findChildren(QLabel)
    # 过滤掉 emoji icon label（默认 📭）
    text_labels = [l for l in labels if l.text() and l.text() != "📭"]
    assert len(text_labels) >= 1, f"应有至少 1 个文字 label，实际 {len(text_labels)}"


# ============ ES-15: 无 icon 时也能正常工作 ============
def test_es15_no_icon_works(qapp):
    """ES-15: icon="" 时不显示 icon label"""
    from aibridge.ui.components.empty_state import EmptyState
    from aibridge.ui.theme import apply_theme

    apply_theme(None, "light")
    parent = QWidget()
    es = EmptyState(icon="", title="无图标空状态", parent=parent)
    # 不应有 emoji icon label
    icon_labels = [l for l in es.findChildren(QLabel) if l.text() == "📭"]
    assert len(icon_labels) == 0, f"icon='' 时不应创建默认 📭 label，实际 {len(icon_labels)}"
    parent.deleteLater()


# ============ ES-16: 背景透明 ============
def test_es16_background_transparent(empty):
    """ES-16: 容器化后背景为 BG_BASE 卡片（不再透明，改为独立容器）"""
    style = empty.styleSheet().lower()
    # 容器化优化：EmptyState 现在是独立卡片容器，有背景+边框+圆角
    assert "background-color" in style or "transparent" in style, \
        f"EmptyState 应有背景色或透明，样式: {style}"
    assert "border" in style, \
        f"EmptyState 容器化后应有边框，样式: {style}"
    assert "border-radius" in style, \
        f"EmptyState 容器化后应有圆角，样式: {style}"


# ============ ES-17: layout spacing 合理（不超过 16px）============
def test_es17_layout_spacing_reasonable(empty):
    """ES-17: layout spacing 合理（≤16px，避免元素分散过开）"""
    lay = empty.layout()
    assert lay.spacing() <= 16, \
        f"layout spacing 应 ≤ 16px，实际 {lay.spacing()}"


# ============ 主入口 ============
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
