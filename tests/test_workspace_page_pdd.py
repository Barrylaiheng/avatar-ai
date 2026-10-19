"""
WorkspacePage PDD 验证测试（Phase 5 /tdd）

原型契约 (ui_mockup.html L1920-1957):
  ┌─ Header ──────────────────────────────────────────────────┐
  │  page-title "工作台" + page-subtitle "数字分身运行管理 ·   │
  │  消息监控与定时推送"                                        │
  ├─ channel-tabs (2 tab, 各带 online dot) ──────────────────┤
  │  [● 微信(active)] [● 公众号]                               │
  ├─ channel-grid (3 stat-card, gap 14px) ───────────────────┤
  │  今日总消息=128 条 / 平均响应时间=2.3 秒 / 用户满意度=94 % │
  ├─ message-list ───────────────────────────────────────────┤
  │  header: search-box + filter-chips(全部/私聊/群聊)        │
  │         + filter-select(全部状态/已回复/待处理/失败)       │
  │  items: wechat 5 条 / oa 3 条                             │
  ├─ schedule-section ───────────────────────────────────────┤
  │  card-title "定时推送" + btn-primary "+ 新建任务"          │
  │  schedule-list: 3 条任务（早安/周五推荐/晚间特价）         │
  └────────────────────────────────────────────────────────────┘

执行: pytest tests/test_workspace_page_pdd.py -v
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
    QComboBox, QLineEdit,
)
from PyQt6.QtTest import QTest


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
        app.setApplicationName("SCAI Workspace PDD Test")
    yield app


@pytest.fixture
def wp(qapp):
    """独立 WorkspacePage 实例"""
    from aibridge.ui.workspace_page import WorkspacePage
    from aibridge.ui.theme import apply_theme

    apply_theme(None, "light")

    parent = QWidget()
    parent.resize(960, 720)
    page = WorkspacePage(parent=parent)
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


# ============ WP-1: 标题 "工作台" ============
def test_wp1_title(wp):
    """WP-1: page-title '工作台' 存在"""
    labels = [l for l in wp.findChildren(QLabel) if l.text() == "工作台"]
    assert len(labels) >= 1, "未找到标题 '工作台'"


# ============ WP-2: 副标题 ============
def test_wp2_subtitle(wp):
    """WP-2: 副标题 '数字分身运行管理 · 消息监控与定时推送'"""
    labels = [l for l in wp.findChildren(QLabel)
              if "数字分身运行管理" in l.text() and "消息监控" in l.text()]
    assert len(labels) >= 1, "未找到副标题"


# ============ WP-3: 2 个渠道 tab ============
def test_wp3_two_channel_tabs(wp):
    """WP-3: 微信 + 公众号 2 个 _ChannelTab"""
    from aibridge.ui.workspace_page import _ChannelTab
    tabs = wp.findChildren(_ChannelTab)
    assert len(tabs) >= 2, f"应有 2 个渠道 tab，实际 {len(tabs)}"


# ============ WP-4: 初始 wechat active ============
def test_wp4_wechat_active_on_init(wp):
    """WP-4: 初始 wechat tab active, oa inactive"""
    assert wp._tab_wechat._active is True, "初始 wechat tab 应 active"
    assert wp._tab_oa._active is False, "初始 oa tab 应 inactive"
    assert wp.current_channel() == "wechat"


# ============ WP-5: 切换公众号 → channel_changed('oa') ============
def test_wp5_switch_to_oa(wp):
    """WP-5: 点击公众号 tab → channel_changed('oa') + tab 状态更新"""
    received = []
    wp.channel_changed.connect(lambda ch: received.append(ch))
    wp._tab_oa.clicked.emit("oa")
    assert "oa" in received, f"切公众号应发 channel_changed('oa')，收到 {received}"
    assert wp._tab_oa._active is True, "oa tab 应 active"
    assert wp._tab_wechat._active is False, "wechat tab 应 inactive"
    assert wp.current_channel() == "oa"


# ============ WP-6: 3 张 StatCard ============
def test_wp6_three_stat_cards(wp):
    """WP-6: 3 张 StatCard"""
    from aibridge.ui.components.stat_card import StatCard
    cards = wp.findChildren(StatCard)
    assert len(cards) >= 3, f"应有至少 3 张 StatCard，实际 {len(cards)}"


# ============ WP-7: 今日总消息 = 0 (MVP 清零版) ============
def test_wp7_stat_total_0(wp):
    """WP-7 (清零版): '今日总消息' 卡片值为 0"""
    assert "0" in wp._stat_total._value_label.text(), \
        f"今日总消息应为 0，实际: {wp._stat_total._value_label.text()}"


# ============ WP-8: 平均响应时间 = — (MVP 清零版) ============
def test_wp8_stat_response_dash(wp):
    """WP-8 (清零版): '平均响应时间' 卡片值为 — (无数据占位)"""
    assert "—" in wp._stat_response._value_label.text(), \
        f"平均响应时间应为 —，实际: {wp._stat_response._value_label.text()}"


# ============ WP-9: 用户满意度 = 0 (MVP 清零版) ============
def test_wp9_stat_satisfaction_0(wp):
    """WP-9 (清零版): '用户满意度' 卡片值为 0"""
    assert "0" in wp._stat_satisfaction._value_label.text(), \
        f"用户满意度应为 0，实际: {wp._stat_satisfaction._value_label.text()}"


# ============ WP-10: 搜索框 placeholder ============
def test_wp10_search_placeholder(wp):
    """WP-10: 搜索框 placeholder 含 '搜索联系人'"""
    assert "搜索联系人" in wp._search_box.placeholderText(), \
        f"搜索框 placeholder 应含 '搜索联系人'，实际: {wp._search_box.placeholderText()}"


# ============ WP-11: 3 个 filter chips ============
def test_wp11_three_filter_chips(wp):
    """WP-11: 3 个 filter chips（全部/私聊/群聊）"""
    assert len(wp._chips) == 3, f"应有 3 个 filter chips，实际 {len(wp._chips)}"
    assert "all" in wp._chips, "缺少 'all' chip"
    assert "private" in wp._chips, "缺少 'private' chip"
    assert "group" in wp._chips, "缺少 'group' chip"
    assert wp._chips["all"].text() == "全部"
    assert wp._chips["private"].text() == "私聊"
    assert wp._chips["group"].text() == "群聊"


# ============ WP-12: 状态下拉 4 项 ============
def test_wp12_status_combo_4_options(wp):
    """WP-12: 状态下拉 4 项（全部状态/已回复/待处理/失败）"""
    items = [wp._status_combo.itemText(i) for i in range(wp._status_combo.count())]
    for expected in ["全部状态", "已回复", "待处理", "失败"]:
        assert expected in items, f"状态下拉缺少 '{expected}'，现有: {items}"


# ============ WP-13: wechat 初始 0 条消息 (MVP 清零版) ============
def test_wp13_wechat_0_messages(wp):
    """WP-13 (清零版): wechat 渠道初始渲染 0 条 _MessageItem"""
    from aibridge.ui.workspace_page import _MessageItem
    items = wp.findChildren(_MessageItem)
    assert len(items) == 0, f"wechat 初始应为 0 条消息，实际 {len(items)}"


# ============ WP-14: 筛选私聊 → 0 条 (MVP 清零版) ============
def test_wp14_filter_private_0(wp):
    """WP-14 (清零版): 筛选 '私聊' → 0 条消息"""
    from aibridge.ui.workspace_page import _MessageItem
    wp._chips["private"].click()
    QTest.qWait(50)
    items = wp.findChildren(_MessageItem)
    assert len(items) == 0, f"私聊筛选后应为 0 条，实际 {len(items)}"


# ============ WP-15: 筛选群聊 → 0 条 (MVP 清零版) ============
def test_wp15_filter_group_0(wp):
    """WP-15 (清零版): 筛选 '群聊' → 0 条消息"""
    from aibridge.ui.workspace_page import _MessageItem
    wp._chips["group"].click()
    QTest.qWait(50)
    items = wp.findChildren(_MessageItem)
    assert len(items) == 0, f"群聊筛选后应为 0 条，实际 {len(items)}"


# ============ WP-16: 搜索 "测试" → 0 条 (MVP 清零版) ============
def test_wp16_search_empty_0(wp):
    """WP-16 (清零版): 搜索 '测试' → 0 条消息（清零后任意关键词都无命中）"""
    from aibridge.ui.workspace_page import _MessageItem
    wp._chips["all"].click()  # 重置筛选
    QTest.qWait(30)
    wp._search_box.setText("测试")
    QTest.qWait(50)
    items = wp.findChildren(_MessageItem)
    assert len(items) == 0, f"搜索 '测试' 后应为 0 条，实际 {len(items)}"


# ============ WP-17: 切公众号 → 0 条消息 (MVP 清零版) ============
def test_wp17_oa_0_messages(wp):
    """WP-17 (清零版): 切到公众号渠道 → 0 条消息"""
    from aibridge.ui.workspace_page import _MessageItem
    wp._search_box.setText("")  # 清搜索
    QTest.qWait(30)
    wp._tab_oa.clicked.emit("oa")
    QTest.qWait(50)
    items = wp.findChildren(_MessageItem)
    assert len(items) == 0, f"公众号渠道应为 0 条消息，实际 {len(items)}"


# ============ WP-18: "定时推送" 标题 ============
def test_wp18_schedule_title(wp):
    """WP-18: '定时推送' 标题存在"""
    labels = [l for l in wp.findChildren(QLabel) if l.text() == "定时推送"]
    assert len(labels) >= 1, "未找到 '定时推送' 标题"


# ============ WP-19: "+ 新建任务" 按钮 ============
def test_wp19_new_schedule_btn(wp):
    """WP-19: '+ 新建任务' 按钮存在"""
    btns = [b for b in wp.findChildren(QPushButton) if "新建任务" in b.text()]
    assert len(btns) >= 1, "未找到 '+ 新建任务' 按钮"


# ============ WP-20: 0 个定时任务 (MVP 清零版) ============
def test_wp20_zero_schedule_items(wp):
    """WP-20 (清零版): 0 条 _ScheduleItem（无预置示意任务）"""
    from aibridge.ui.workspace_page import _ScheduleItem
    items = wp.findChildren(_ScheduleItem)
    assert len(items) == 0, f"应为 0 条定时任务，实际 {len(items)}"


# ============ WP-21: new_schedule_requested 信号 ============
def test_wp21_new_schedule_signal(wp):
    """WP-21: 点击 '+ 新建任务' → new_schedule_requested 信号"""
    received = []
    wp.new_schedule_requested.connect(lambda: received.append(True))
    btns = [b for b in wp.findChildren(QPushButton) if "新建任务" in b.text()]
    btns[0].click()
    assert len(received) >= 1, "点击新建任务应触发 new_schedule_requested"


# ============ WP-22: schedule_toggled 信号 (MVP 清零版) ============
def test_wp22_schedule_toggled_signal(wp):
    """WP-22 (清零版): 无定时任务时 schedule_toggled 信号可连接但不触发"""
    from aibridge.ui.workspace_page import _ScheduleItem
    received = []
    wp.schedule_toggled.connect(lambda tid, en: received.append((tid, en)))
    items = wp.findChildren(_ScheduleItem)
    # 清零后无预置任务，因此不触发 toggle 信号
    assert len(items) == 0, f"清零后应无定时任务，实际 {len(items)}"
    assert len(received) == 0, "无任务时不应触发 schedule_toggled"


# ============ WP-23: 6 个信号存在 ============
def test_wp23_all_signals(wp):
    """WP-23: 6 个信号全部存在"""
    from PyQt6.QtCore import pyqtBoundSignal
    assert isinstance(wp.channel_changed, pyqtBoundSignal)
    assert isinstance(wp.search_changed, pyqtBoundSignal)
    assert isinstance(wp.type_filter_changed, pyqtBoundSignal)
    assert isinstance(wp.status_filter_changed, pyqtBoundSignal)
    assert isinstance(wp.schedule_toggled, pyqtBoundSignal)
    assert isinstance(wp.new_schedule_requested, pyqtBoundSignal)


# ============ WP-24: set_messages / set_stats / set_schedules API ============
def test_wp24_apis(wp):
    """WP-24: set_messages / set_stats / set_schedules / current_channel API"""
    from aibridge.ui.workspace_page import MessageItemData, ChannelStats, ScheduleTaskData
    assert hasattr(wp, "set_messages"), "缺少 set_messages"
    assert hasattr(wp, "set_stats"), "缺少 set_stats"
    assert hasattr(wp, "set_schedules"), "缺少 set_schedules"
    assert hasattr(wp, "current_channel"), "缺少 current_channel"

    # 测试 set_messages
    new_msgs = [MessageItemData("x1", "测试", "👤", "wechat", "private", "测试消息", "00:00")]
    wp.set_messages("wechat", new_msgs)
    QTest.qWait(50)
    from aibridge.ui.workspace_page import _MessageItem
    items = wp.findChildren(_MessageItem)
    assert len(items) == 1, f"set_messages 后应只有 1 条，实际 {len(items)}"


# ============ 主入口 ============
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
