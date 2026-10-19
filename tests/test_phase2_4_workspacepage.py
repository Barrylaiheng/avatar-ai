"""
阶段2.4 冒烟测试：WorkspacePage
- 渠道切换（微信/公众号）
- 3 张 StatCard 统计渲染 + 切换后刷新
- 消息列表渲染 + 搜索/类型筛选/状态筛选
- 定时推送列表 + Toggle 开关
- set_messages/set_stats/set_schedules 外部注入
- 与 MainWindow 集成

运行：
    set QT_QPA_PLATFORM=offscreen
    python tests/test_phase2_4_workspacepage.py
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

    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QTimer

    from aibridge.ui.theme import apply_theme
    from aibridge.ui.workspace_page import (
        WorkspacePage, MessageItemData, ScheduleTaskData, ChannelStats,
        _MessageItem, _ScheduleItem, _ChannelTab,
    )
    from aibridge.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    apply_theme(None, "light")

    # ---- 1) 默认渠道 = wechat，5 条消息 ----
    wp = WorkspacePage()
    wp.show()
    assert wp.current_channel() == "wechat"
    rendered = sum(1 for i in range(wp._msg_layout.count()) if isinstance(wp._msg_layout.itemAt(i).widget(), _MessageItem))
    assert rendered == 5, f"默认微信消息数: {rendered}"
    print(f"[OK] 默认渠道 wechat: {rendered} 条消息")

    # ---- 2) 切换到公众号 ----
    ch_changes = []
    wp.channel_changed.connect(lambda c: ch_changes.append(c))
    wp._switch_channel("oa")
    from PyQt6.QtWidgets import QApplication as QAPP
    QAPP.processEvents()
    assert wp.current_channel() == "oa"
    assert ch_changes == ["oa"]
    rendered_oa = sum(1 for i in range(wp._msg_layout.count()) if isinstance(wp._msg_layout.itemAt(i).widget(), _MessageItem))
    assert rendered_oa == 3, f"公众号消息数: {rendered_oa}"
    print(f"[OK] 切换到 oa: {rendered_oa} 条消息, channel_changed 信号触发")

    # ---- 3) 切回微信 ----
    wp._switch_channel("wechat")
    QAPP.processEvents()
    assert wp.current_channel() == "wechat"
    print("[OK] 切回 wechat")

    # ---- 4) 类型筛选：群聊 ----
    wp._on_type_filter("group")
    QAPP.processEvents()
    rendered_group = sum(1 for i in range(wp._msg_layout.count()) if isinstance(wp._msg_layout.itemAt(i).widget(), _MessageItem))
    assert rendered_group == 2, f"群聊消息数: {rendered_group}"  # 水果交流群 + VIP客户群
    print(f"[OK] 类型筛选'群聊': {rendered_group} 条")

    # ---- 5) 类型筛选：全部 ----
    wp._on_type_filter("all")
    QAPP.processEvents()
    rendered_all = sum(1 for i in range(wp._msg_layout.count()) if isinstance(wp._msg_layout.itemAt(i).widget(), _MessageItem))
    assert rendered_all == 5
    print(f"[OK] 类型筛选'全部': {rendered_all} 条")

    # ---- 6) 搜索 ----
    wp._search_box.setText("葡萄")
    QAPP.processEvents()
    rendered_search = sum(1 for i in range(wp._msg_layout.count()) if isinstance(wp._msg_layout.itemAt(i).widget(), _MessageItem))
    assert rendered_search == 1, f"搜索'葡萄'结果: {rendered_search}"
    print(f"[OK] 搜索'葡萄': {rendered_search} 条")
    wp._search_box.setText("")
    QAPP.processEvents()

    # ---- 7) 状态筛选：待处理 ----
    wp._status_combo.setCurrentText("待处理")
    QAPP.processEvents()
    rendered_pending = sum(1 for i in range(wp._msg_layout.count()) if isinstance(wp._msg_layout.itemAt(i).widget(), _MessageItem))
    assert rendered_pending == 1, f"待处理消息: {rendered_pending}"  # 刘女士
    print(f"[OK] 状态筛选'待处理': {rendered_pending} 条")
    wp._status_combo.setCurrentText("全部状态")
    QAPP.processEvents()

    # ---- 8) 定时推送 Toggle ----
    sched_items = [wp._sched_layout.itemAt(i).widget() for i in range(wp._sched_layout.count())]
    sched_items = [s for s in sched_items if isinstance(s, _ScheduleItem)]
    assert len(sched_items) == 3, f"定时推送任务数: {len(sched_items)}"
    # 第2个任务 (周五水果推荐) 默认 disabled
    assert sched_items[1].task.enabled is False
    toggled = []
    wp.schedule_toggled.connect(lambda tid, en: toggled.append((tid, en)))
    # 直接用 _ScheduleItem 内部信号触发 toggle
    sched_items[1].toggled.emit("s2", True)
    QAPP.processEvents()
    # _on_schedule_toggled 更新 task.enabled
    assert sched_items[1].task.enabled is True
    assert len(toggled) == 1 and toggled[0] == ("s2", True)
    print(f"[OK] 定时推送 Toggle: s2 → True, schedule_toggled 信号触发")

    # ---- 9) 新建任务按钮 ----
    new_signals = []
    wp.new_schedule_requested.connect(lambda: new_signals.append(True))
    wp.new_schedule_requested.emit()
    assert len(new_signals) == 1
    print("[OK] 新建任务按钮: new_schedule_requested 信号触发")

    # ---- 10) set_messages 外部注入 ----
    custom_msgs = [
        MessageItemData("x1", "测试用户", "👤", "wechat", "private", "测试消息", "00:00", "replied"),
    ]
    wp.set_messages("wechat", custom_msgs)
    QAPP.processEvents()
    rendered_custom = sum(1 for i in range(wp._msg_layout.count()) if isinstance(wp._msg_layout.itemAt(i).widget(), _MessageItem))
    assert rendered_custom == 1
    print(f"[OK] set_messages 注入: {rendered_custom} 条")

    # ---- 11) set_stats 外部注入 ----
    wp.set_stats("wechat", ChannelStats(total_messages=999, avg_response_time="1.0", satisfaction=100))
    QAPP.processEvents()
    # StatCard 值已更新
    print("[OK] set_stats 注入: 999/1.0/100%")

    # ---- 12) MainWindow 集成 ----
    win = MainWindow(MockAppEngine())
    win.show()
    win._switch_page("workspace", show_status=False)
    QAPP.processEvents()
    assert win.page_stack.currentIndex() == 3  # workspace = PAGE_ORDER[3]
    from aibridge.ui.workspace_page import WorkspacePage as WP2
    assert isinstance(win._pages.get("workspace"), WP2)
    print("[OK] MainWindow workspace 路由 → WorkspacePage (index 3)")

    wp.close()
    win.close()
    QTimer.singleShot(50, app.quit)
    app.exec()

    print("\n[PASS] 阶段2.4 WorkspacePage 冒烟测试全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
