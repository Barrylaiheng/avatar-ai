"""
IterationPage PDD 验证测试（Phase 5 /tdd）

原型契约 (ui_mockup.html L2309-2382):
  ┌─ Header ──────────────────────────────────────────────────┐
  │  page-title "迭代系统" + page-subtitle "BadCase 处理与     │
  │  AI 回复质量优化 · 待处理 5 条"                             │
  ├─ stats-grid (4 列 grid, gap 14px) ───────────────────────┤
  │  stat-card × 4:                                            │
  │    总 BadCase=5 / 本周新增=3 / 已处理=12 / 处理率=71%      │
  ├─ badcase-queue (bg-base, border, radius-lg) ─────────────┤
  │  card-header: "BadCase 队列" + filter-select               │
  │    filter options: 全部类型/空回复/答非所问/信息错误/格式错误│
  │  badcase-item × 5:                                         │
  │    bc-type(80px) + bc-content + bc-actions(2 btns)         │
  │    bc-badge: empty/irrelevant/wrong/format                 │
  │    bc-question: 13px 500 / bc-answer: 12px secondary       │
  │    bc-meta: 3 items (channel/user/time)                    │
  │    bc-btn: "⚡ 一键优化"(primary) + "💬 对话优化"(discuss)  │
  └────────────────────────────────────────────────────────────┘

执行: pytest tests/test_iteration_page_pdd.py -v
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
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QFrame, QScrollArea,
    QComboBox,
)
from PyQt6.QtTest import QTest


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
        app.setApplicationName("SCAI Iteration PDD Test")
    yield app


@pytest.fixture
def ip(qapp):
    """独立 IterationPage 实例"""
    from aibridge.ui.iteration_page import IterationPage
    from aibridge.ui.theme import apply_theme

    apply_theme(None, "light")

    parent = QWidget()
    parent.resize(960, 720)
    page = IterationPage(parent)
    page.resize(940, 700)
    parent.show()
    page.show()
    QTest.qWait(80)
    yield page
    try:
        page.close()
        parent.close()
        page.deleteLater()
        parent.deleteLater()
    except RuntimeError:
        pass
    QTest.qWait(10)


# ============ IT-1: 标题 "迭代系统" 存在 ============
def test_it1_title_exists(ip):
    """IT-1: page-title '迭代系统' 存在"""
    labels = [l for l in ip.findChildren(QLabel) if l.text() == "迭代系统"]
    assert len(labels) >= 1, "未找到标题 '迭代系统'"


# ============ IT-2: 副标题含 "BadCase" + "待处理" + "0 条" (MVP 清零版) ============
def test_it2_subtitle_badcase(ip):
    """IT-2 (清零版): 副标题含 BadCase 处理 + 待处理 0 条"""
    labels = [l for l in ip.findChildren(QLabel)
              if "BadCase" in l.text() and "待处理" in l.text()]
    assert len(labels) >= 1, "未找到副标题"
    assert "0" in labels[0].text(), f"副标题应含 '0 条'，实际: {labels[0].text()}"


# ============ IT-3: 4 张 StatCard 存在 ============
def test_it3_four_stat_cards(ip):
    """IT-3: stats-grid 中有 4 张 StatCard"""
    from aibridge.ui.components.stat_card import StatCard
    cards = ip.findChildren(StatCard)
    assert len(cards) >= 4, f"应有至少 4 张 StatCard，实际 {len(cards)}"


# ============ IT-4: 总 BadCase = 0 (MVP 清零版) ============
def test_it4_stat_total_0(ip):
    """IT-4 (清零版): '总 BadCase' 卡片值为 0"""
    from aibridge.ui.components.stat_card import StatCard
    cards = ip.findChildren(StatCard)
    total_card = [c for c in cards if "总" in c._title.text() and "BadCase" in c._title.text()]
    assert len(total_card) >= 1, "未找到 '总 BadCase' 卡片"
    assert "0" in total_card[0]._value_label.text(), \
        f"总 BadCase 值应为 0，实际: {total_card[0]._value_label.text()}"


# ============ IT-5: 本周新增 = 0 (MVP 清零版) ============
def test_it5_stat_weekly_0(ip):
    """IT-5 (清零版): '本周新增' 卡片值为 0"""
    from aibridge.ui.components.stat_card import StatCard
    cards = ip.findChildren(StatCard)
    weekly = [c for c in cards if "本周新增" in c._title.text()]
    assert len(weekly) >= 1, "未找到 '本周新增' 卡片"
    assert "0" in weekly[0]._value_label.text(), \
        f"本周新增值应为 0，实际: {weekly[0]._value_label.text()}"


# ============ IT-6: 已处理 = 0 (MVP 清零版) ============
def test_it6_stat_resolved_0(ip):
    """IT-6 (清零版): '已处理' 卡片值为 0"""
    from aibridge.ui.components.stat_card import StatCard
    cards = ip.findChildren(StatCard)
    resolved = [c for c in cards if "已处理" in c._title.text()]
    assert len(resolved) >= 1, "未找到 '已处理' 卡片"
    assert "0" in resolved[0]._value_label.text(), \
        f"已处理值应为 0，实际: {resolved[0]._value_label.text()}"


# ============ IT-7: 处理率 = 0% (MVP 清零版) ============
def test_it7_stat_rate_0(ip):
    """IT-7 (清零版): '处理率' 卡片值为 0%"""
    from aibridge.ui.components.stat_card import StatCard
    cards = ip.findChildren(StatCard)
    rate = [c for c in cards if "处理率" in c._title.text()]
    assert len(rate) >= 1, "未找到 '处理率' 卡片"
    assert "0" in rate[0]._value_label.text(), \
        f"处理率值应为 0%，实际: {rate[0]._value_label.text()}"


# ============ IT-8: "BadCase 队列" 标题存在 ============
def test_it8_queue_title(ip):
    """IT-8: card-title 'BadCase 队列' 存在"""
    labels = [l for l in ip.findChildren(QLabel) if l.text() == "BadCase 队列"]
    assert len(labels) >= 1, "未找到 'BadCase 队列' 标题"


# ============ IT-9: 筛选下拉 5 项 ============
def test_it9_filter_combo_5_options(ip):
    """IT-9: 筛选下拉含 5 项（全部类型/空回复/答非所问/信息错误/格式错误）"""
    combos = ip.findChildren(QComboBox)
    assert len(combos) >= 1, "未找到筛选下拉"
    items = [combos[0].itemText(i) for i in range(combos[0].count())]
    for expected in ["全部类型", "空回复", "答非所问", "信息错误", "格式错误"]:
        assert expected in items, f"筛选下拉缺少 '{expected}'，现有: {items}"


# ============ IT-10: BadCaseItem 数量 = 0 (MVP 清零版) ============
def test_it10_zero_badcase_items(ip):
    """IT-10 (清零版): 初始渲染 0 条 BadCaseItem"""
    from aibridge.ui.iteration_page import BadCaseItem
    items = ip.findChildren(BadCaseItem)
    assert len(items) == 0, f"应为 0 条 BadCaseItem，实际 {len(items)}"


# ============ IT-11: 0 条空回复 badge (MVP 清零版) ============
def test_it11_zero_empty_badges(ip):
    """IT-11 (清零版): 0 条 bc_type=empty（无预置 BadCase）"""
    from aibridge.ui.iteration_page import BadCaseItem
    items = ip.findChildren(BadCaseItem)
    empty_items = [it for it in items if it.bc.bc_type == "empty"]
    assert len(empty_items) == 0, f"应为 0 条空回复，实际 {len(empty_items)}"


# ============ IT-12: bc_type 集合为空 (MVP 清零版) ============
def test_it12_no_bc_types(ip):
    """IT-12 (清零版): 无 BadCase，bc_type 集合为空"""
    from aibridge.ui.iteration_page import BadCaseItem
    items = ip.findChildren(BadCaseItem)
    types = set(it.bc.bc_type for it in items)
    assert types == set(), \
        f"清零后 bc_type 应为空集，实际: {types}"


# ============ IT-13: 无 BadCaseItem 时按钮遍历不报错 (MVP 清零版) ============
def test_it13_no_items_no_buttons(ip):
    """IT-13 (清零版): 0 条 BadCaseItem，遍历不报错且按钮总数为 0"""
    from aibridge.ui.iteration_page import BadCaseItem
    items = ip.findChildren(BadCaseItem)
    assert len(items) == 0, f"应为 0 条 BadCaseItem，实际 {len(items)}"
    total_btns = 0
    for it in items:
        total_btns += len(it.findChildren(QPushButton))
    assert total_btns == 0, f"无 BadCase 时按钮总数应为 0，实际 {total_btns}"


# ============ IT-14: "一键优化" 按钮数量 = 0 (MVP 清零版) ============
def test_it14_optimize_btn_zero(ip):
    """IT-14 (清零版): 无 BadCase 时无 '一键优化' 按钮"""
    btns = [b for b in ip.findChildren(QPushButton) if "一键优化" in b.text()]
    assert len(btns) == 0, f"应为 0 个 '一键优化' 按钮，实际 {len(btns)}"


# ============ IT-15: "对话优化" 按钮数量 = 0 (MVP 清零版) ============
def test_it15_discuss_btn_zero(ip):
    """IT-15 (清零版): 无 BadCase 时无 '对话优化' 按钮"""
    btns = [b for b in ip.findChildren(QPushButton) if "对话优化" in b.text()]
    assert len(btns) == 0, f"应为 0 个 '对话优化' 按钮，实际 {len(btns)}"


# ============ IT-16: 无 BadCase 时无 "客户问：" label (MVP 清零版) ============
def test_it16_no_question_prefix(ip):
    """IT-16 (清零版): 无 BadCase 时不存在 '客户问：' 开头的 label"""
    from aibridge.ui.iteration_page import BadCaseItem
    items = ip.findChildren(BadCaseItem)
    assert len(items) == 0, f"应为 0 条 BadCaseItem，实际 {len(items)}"
    q_labels = [l for l in ip.findChildren(QLabel) if l.text().startswith("客户问：")]
    assert len(q_labels) == 0, f"无 BadCase 时不应有 '客户问：' label，实际 {len(q_labels)}"


# ============ IT-17: 无 BadCase 时无 "AI 回复：" label (MVP 清零版) ============
def test_it17_no_answer_prefix(ip):
    """IT-17 (清零版): 无 BadCase 时不存在 'AI 回复：' 开头的 label"""
    from aibridge.ui.iteration_page import BadCaseItem
    items = ip.findChildren(BadCaseItem)
    assert len(items) == 0, f"应为 0 条 BadCaseItem，实际 {len(items)}"
    a_labels = [l for l in ip.findChildren(QLabel) if l.text().startswith("AI 回复：")]
    assert len(a_labels) == 0, f"无 BadCase 时不应有 'AI 回复：' label，实际 {len(a_labels)}"


# ============ IT-18: 筛选 "空回复" → 0 条 (MVP 清零版) ============
def test_it18_filter_empty_zero(ip):
    """IT-18 (清零版): 筛选 '空回复' → BadCaseItem 仍为 0 条"""
    from aibridge.ui.iteration_page import BadCaseItem
    combo = ip.findChildren(QComboBox)[0]
    combo.setCurrentText("空回复")
    QTest.qWait(50)
    items = ip.findChildren(BadCaseItem)
    assert len(items) == 0, f"筛选空回复后应为 0 条，实际 {len(items)}"


# ============ IT-19: 筛选 "全部类型" → 仍为 0 条 (MVP 清零版) ============
def test_it19_filter_all_zero(ip):
    """IT-19 (清零版): 筛选回 '全部类型' → BadCaseItem 仍为 0 条"""
    from aibridge.ui.iteration_page import BadCaseItem
    combo = ip.findChildren(QComboBox)[0]
    combo.setCurrentText("空回复")
    QTest.qWait(50)
    combo.setCurrentText("全部类型")
    QTest.qWait(50)
    items = ip.findChildren(BadCaseItem)
    assert len(items) == 0, f"筛选全部类型后仍应为 0 条，实际 {len(items)}"


# ============ IT-20: optimize_requested 信号存在 ============
def test_it20_optimize_signal(ip):
    """IT-20: optimize_requested(str) 信号可连接"""
    from PyQt6.QtCore import pyqtBoundSignal
    assert isinstance(ip.optimize_requested, pyqtBoundSignal)
    assert isinstance(ip.discuss_requested, pyqtBoundSignal)
    assert isinstance(ip.filter_changed, pyqtBoundSignal)


# ============ IT-21: set_badcases API 存在 ============
def test_it21_set_badcases_api(ip):
    """IT-21: set_badcases(badcases, stats) + badcases() + stats() API 存在"""
    from aibridge.ui.iteration_page import BadCaseData, IterationStats
    assert hasattr(ip, "set_badcases"), "缺少 set_badcases API"
    assert hasattr(ip, "badcases"), "缺少 badcases() API"
    assert hasattr(ip, "stats"), "缺少 stats() API"

    new_bcs = [BadCaseData(id="x1", bc_type="empty", question="test", answer="ans")]
    new_stats = IterationStats(total=1, weekly_new=1, resolved=0)
    ip.set_badcases(new_bcs, new_stats)
    QTest.qWait(50)
    assert len(ip.badcases()) == 1
    assert ip.stats().total == 1


# ============ 主入口 ============
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
