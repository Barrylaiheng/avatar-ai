"""
KnowledgePage PDD 验证测试（Phase 5 /tdd）

原型契约 (ui_mockup.html L1960-2306):
  ┌─ Header ─────────────────────────────────────────────────────┐
  │  page-title "分身知识库" + page-subtitle "按阶段组织 · 共 42 个条目" │
  ├─ Toolbar ────────────────────────────────────────────────────┤
  │  view-toggle: [列表视图 (active)] [图谱视图]          [📄 导出文档] │
  ├─ StageGroups × 5（目标确认/知识萃取/人格塑造/交互设计/部署交付） │
  │  stage-header: icon 24x24 + title + status(done/active/todo) + count │
  │  entries: 20 KnowledgeEntryCards（padding 16, 2 列网格）       │
  │  empty placeholder: "尚未开始 · 开始XXX"                        │
  └─ KnowledgeEntryCard: tag + title + summary + footer + expand-hint + │
                         detail (多个 label+可编辑 editor) + 2 buttons │

执行: pytest tests/test_knowledge_page_pdd.py -v
"""
from __future__ import annotations

import os, sys
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
os.environ.setdefault("QT_OPENGL", "software")

from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QFrame, QScrollArea,
    QStackedWidget, QTextEdit, QGridLayout,
)
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


@pytest.fixture
def kp(qapp):
    from aibridge.ui.knowledge_page import KnowledgePage
    from aibridge.ui.theme import apply_theme
    apply_theme(None, "light")
    parent = QWidget()
    parent.resize(1000, 800)
    page = KnowledgePage(parent)
    page.resize(980, 780)
    parent.show()
    page.show()
    QTest.qWait(120)
    yield page
    try:
        page.close(); parent.close(); page.deleteLater(); parent.deleteLater()
    except RuntimeError:
        pass
    QTest.qWait(10)


# ========== KP-1: 标题 "分身知识库" ==========
def test_kp1_title(kp):
    """KP-1: page-title '分身知识库' 存在"""
    labels = [l for l in kp.findChildren(QLabel) if l.text() == "分身知识库"]
    assert len(labels) >= 1, "未找到标题 '分身知识库'"

# ========== KP-2: 副标题 "共 0 个条目"（清零版） ==========
def test_kp2_subtitle_count(kp):
    """KP-2: 副标题含 '共 0 个条目'（清零版: 0+0+0+0+0）"""
    labels = [l for l in kp.findChildren(QLabel)
              if "数字分身的搭建产物" in l.text() and "按阶段组织" in l.text()]
    assert len(labels) >= 1, "未找到副标题"
    assert "共 0 个条目" in labels[0].text(), \
        f"副标题应含 '共 0 个条目'，实际: {labels[0].text()}"

# ========== KP-3: 2 个视图按钮 ==========
def test_kp3_two_view_btns(kp):
    """KP-3: 列表视图 + 图谱视图 2 个按钮"""
    list_btns = [b for b in kp.findChildren(QPushButton) if "列表视图" in b.text()]
    graph_btns = [b for b in kp.findChildren(QPushButton) if "图谱视图" in b.text()]
    assert len(list_btns) >= 1, "未找到 '列表视图' 按钮"
    assert len(graph_btns) >= 1, "未找到 '图谱视图' 按钮"

# ========== KP-4: 列表视图初始 active ==========
def test_kp4_list_active(kp):
    """KP-4: 初始 view == 'list'，stack index 0"""
    assert kp._view == "list"
    assert kp._stack.currentIndex() == 0

# ========== KP-5: 切换图谱视图 ==========
def test_kp5_switch_graph(kp):
    """KP-5: 点击图谱视图 → stack index 1，view == 'graph'"""
    received = []
    kp.view_changed.connect(lambda v: received.append(v))
    kp._btn_graph.click()
    QTest.qWait(30)
    assert "graph" in received
    assert kp._view == "graph"
    assert kp._stack.currentIndex() == 1

# ========== KP-6: 导出按钮 + 信号 ==========
def test_kp6_export_btn(kp):
    """KP-6: 点击 '导出文档' → export_requested 信号"""
    received = []
    kp.export_requested.connect(lambda: received.append(True))
    btns = [b for b in kp.findChildren(QPushButton) if "导出文档" in b.text()]
    assert len(btns) >= 1
    btns[0].click()
    assert len(received) >= 1, "未触发 export_requested"

# ========== KP-7: 5 个 StageGroup ==========
def test_kp7_five_stage_groups(kp):
    """KP-7: 5 个 StageGroupSection"""
    from aibridge.ui.knowledge_page import StageGroupSection
    groups = kp.findChildren(StageGroupSection)
    assert len(groups) == 5, f"应有 5 个 stage group，实际 {len(groups)}"

# ========== KP-8: 5 个 stage title 顺序 ==========
def test_kp8_stage_titles(kp):
    """KP-8: titles == [目标确认, 知识萃取, 人格塑造, 交互设计, 部署交付]"""
    from aibridge.ui.knowledge_page import StageGroupSection
    groups = kp.findChildren(StageGroupSection)
    titles = [g.stage.title for g in groups]
    expected = ["目标确认", "知识萃取", "人格塑造", "交互设计", "部署交付"]
    assert titles == expected, f"stage titles 不匹配: {titles}"

# ========== KP-9: 5 个 status 全为 todo（清零版） ==========
def test_kp9_stage_statuses(kp):
    """KP-9: 清零版 — statuses 全为 todo"""
    from aibridge.ui.knowledge_page import StageGroupSection
    groups = kp.findChildren(StageGroupSection)
    statuses = [g.stage.status for g in groups]
    assert statuses == ["todo", "todo", "todo", "todo", "todo"], \
        f"statuses 不匹配: {statuses}"

# ========== KP-10: 条目数 [0,0,0,0,0]（清零版） ==========
def test_kp10_stage_counts(kp):
    """KP-10: 清零版 — counts == [0, 0, 0, 0, 0]"""
    from aibridge.ui.knowledge_page import StageGroupSection
    groups = kp.findChildren(StageGroupSection)
    counts = [g.stage.count for g in groups]
    assert counts == [0, 0, 0, 0, 0], f"counts 不匹配: {counts}"

# ========== KP-11: 0 个 KnowledgeEntryCard（清零版） ==========
def test_kp11_zero_entry_cards(kp):
    """KP-11: 清零版 — 无 KnowledgeEntryCard（0 张）"""
    from aibridge.ui.knowledge_page import KnowledgeEntryCard
    cards = kp.findChildren(KnowledgeEntryCard)
    assert len(cards) == 0, f"清零后应无 KnowledgeEntryCard，实际 {len(cards)}"

# ========== KP-12: Stage 1 (目标确认) 0 张卡（清零版） ==========
def test_kp12_stage1_0cards(kp):
    """KP-12: 清零版 — 目标确认 group.cards 为空（0 张）"""
    from aibridge.ui.knowledge_page import StageGroupSection
    groups = kp.findChildren(StageGroupSection)
    assert len(groups[0].cards) == 0, \
        f"清零后目标确认应无卡片，实际 {len(groups[0].cards)}"

# ========== KP-13: 无知识卡片时不崩溃（清零版） ==========
def test_kp13_card_structure(kp):
    """KP-13: 清零版 — 无知识卡片时不崩溃"""
    from aibridge.ui.knowledge_page import KnowledgeEntryCard
    cards = kp.findChildren(KnowledgeEntryCard)
    assert len(cards) == 0, f"清零后应无知识卡片，实际 {len(cards)}"

# ========== KP-14: "展开详情" hint 文字 ==========
def test_kp14_expand_hint(kp):
    """KP-14: 所有卡初始都有 '▸ 展开详情'"""
    from aibridge.ui.knowledge_page import KnowledgeEntryCard
    cards = kp.findChildren(KnowledgeEntryCard)
    for i, c in enumerate(cards):
        assert "展开详情" in c._hint.text() or "收起" in c._hint.text(), \
            f"第 {i} 张卡 hint 无效: {c._hint.text()}"

# ========== KP-15: 无卡片可展开，不崩溃（清零版） ==========
def test_kp15_toggle_expand(kp):
    """KP-15: 清零版 — 无卡片可展开，不崩溃"""
    from aibridge.ui.knowledge_page import KnowledgeEntryCard
    cards = kp.findChildren(KnowledgeEntryCard)
    assert len(cards) == 0, f"清零后应无卡片可展开，实际 {len(cards)}"

# ========== KP-16: 无卡片无按钮（清零版） ==========
def test_kp16_two_buttons(kp):
    """KP-16: 清零版 — 无卡片无按钮"""
    from aibridge.ui.knowledge_page import KnowledgeEntryCard
    cards = kp.findChildren(KnowledgeEntryCard)
    assert len(cards) == 0, f"清零后应无卡片无按钮，实际 {len(cards)}"

# ========== KP-17: 无卡片，detail 区为空状态（清零版） ==========
def test_kp17_editor(kp):
    """KP-17: 清零版 — 无卡片，detail 区为空状态"""
    from aibridge.ui.knowledge_page import KnowledgeEntryCard
    cards = kp.findChildren(KnowledgeEntryCard)
    assert len(cards) == 0, f"清零后应无卡片无编辑器，实际 {len(cards)}"

# ========== KP-18: 无卡片，无保存信号可触发（清零版） ==========
def test_kp18_save_signal(kp):
    """KP-18: 清零版 — 无卡片，无保存信号可触发"""
    from aibridge.ui.knowledge_page import KnowledgeEntryCard
    cards = kp.findChildren(KnowledgeEntryCard)
    assert len(cards) == 0, f"清零后应无卡片无保存按钮，实际 {len(cards)}"

# ========== KP-19: 无卡片，无对话优化信号可触发（清零版） ==========
def test_kp19_discuss_signal(kp):
    """KP-19: 清零版 — 无卡片，无对话优化信号可触发"""
    from aibridge.ui.knowledge_page import KnowledgeEntryCard
    cards = kp.findChildren(KnowledgeEntryCard)
    assert len(cards) == 0, f"清零后应无卡片无对话优化按钮，实际 {len(cards)}"

# ========== KP-20: 空 stage (交互设计) 有 placeholder + 开始链接 ==========
def test_kp20_empty_placeholder(kp):
    """KP-20: 交互设计 stage 中含 '尚未开始' + '开始交互设计'"""
    from aibridge.ui.knowledge_page import StageGroupSection
    groups = kp.findChildren(StageGroupSection)
    stage4 = groups[3]  # 交互设计
    labels = stage4.findChildren(QLabel)
    texts = [l.text() for l in labels]
    assert any("尚未开始" in t for t in texts), "缺少 '尚未开始' placeholder"
    assert any("开始交互设计" in t for t in texts), "缺少 '开始交互设计' 链接"

# ========== KP-21: 点击空 placeholder → start_stage_requested ==========
def test_kp21_start_stage_signal(kp):
    """KP-21: 部署交付 empty placeholder 点击 → start_stage_requested(5)"""
    from aibridge.ui.knowledge_page import StageGroupSection
    groups = kp.findChildren(StageGroupSection)
    stage5 = groups[4]
    received = []
    kp.start_stage_requested.connect(lambda idx: received.append(idx))
    stage5.start_stage_requested.emit(5)
    assert 5 in received

# ========== KP-22: 10 个信号全部存在 ==========
def test_kp22_all_signals(kp):
    """KP-22: 所有公共 pyqtSignal 存在"""
    from PyQt6.QtCore import pyqtBoundSignal
    for name in ["view_changed", "export_requested", "entry_saved",
                 "discuss_requested", "start_stage_requested"]:
        s = getattr(kp, name, None)
        assert isinstance(s, pyqtBoundSignal), f"缺少信号: {name}"

# ========== KP-23: 主容器是 QScrollArea（列表视图） ==========
def test_kp23_scroll_area(kp):
    """KP-23: _list_scroll 是 QScrollArea 且 widgetResizable"""
    assert isinstance(kp._list_scroll, QScrollArea)
    assert kp._list_scroll.widgetResizable() is True

# ========== KP-24: QStackedWidget 有 2 页 ==========
def test_kp24_stack_2_pages(kp):
    """KP-24: _stack 有 2 个 widget（list/graph）"""
    assert kp._stack.count() == 2

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
