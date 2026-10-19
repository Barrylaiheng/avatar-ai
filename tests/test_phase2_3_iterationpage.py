"""
阶段2.3 冒烟测试：IterationPage
- 4 张 StatCard 统计渲染
- 5 条 BadCase 渲染（4 种类型 badge）
- 一键优化：optimizing → optimized 状态过渡 + 优化后回复显示
- 对话优化按钮触发 discuss_requested 信号
- 筛选下拉切换 + 列表重新渲染
- set_badcases 外部注入数据
- 与 MainWindow 集成（iteration 路由 → IterationPage）

运行：
    set QT_QPA_PLATFORM=offscreen
    python tests/test_phase2_3_iterationpage.py
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
    from aibridge.ui.iteration_page import (
        IterationPage, BadCaseData, BadCaseItem, IterationStats,
        BC_TYPE_MAP, BC_TYPE_LABELS,
    )
    from aibridge.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    apply_theme(None, "light")

    # ---- 1) 默认 mock 数据：5 条 BadCase ----
    ip = IterationPage()
    ip.show()
    assert len(ip.badcases()) == 5, f"BadCase 数: {len(ip.badcases())}"
    assert ip.stats().total == 5
    assert ip.stats().weekly_new == 3
    assert ip.stats().resolved == 12
    assert ip.stats().resolve_rate == "71%"  # 12 / (12+5) = 70.6% → round = 71%
    print(f"[OK] mock 数据: {len(ip.badcases())}条 BadCase, stats(total={ip.stats().total}, weekly={ip.stats().weekly_new}, resolved={ip.stats().resolved}, rate={ip.stats().resolve_rate})")

    # ---- 2) 4 种类型存在 ----
    types = {bc.bc_type for bc in ip.badcases()}
    assert types == {"empty", "irrelevant", "wrong", "format"}, f"类型: {types}"
    print(f"[OK] 4 种 BadCase 类型齐全: {types}")

    # ---- 3) 筛选：空回复 ----
    ip._filter_combo.setCurrentText("空回复")
    QApplication.processEvents()
    visible_empty = [bc for bc in ip.badcases() if bc.bc_type == "empty"]
    assert len(visible_empty) == 2
    # 检查 items_layout 中渲染了多少个 BadCaseItem
    rendered = sum(1 for i in range(ip._items_layout.count()) if isinstance(ip._items_layout.itemAt(i).widget(), BadCaseItem))
    assert rendered == 2, f"筛选空回复后渲染数: {rendered}"
    print(f"[OK] 筛选'空回复': 渲染 {rendered} 条")

    # ---- 4) 筛选：全部类型 ----
    ip._filter_combo.setCurrentText("全部类型")
    QApplication.processEvents()
    rendered_all = sum(1 for i in range(ip._items_layout.count()) if isinstance(ip._items_layout.itemAt(i).widget(), BadCaseItem))
    assert rendered_all == 5, f"全部类型渲染数: {rendered_all}"
    print(f"[OK] 筛选'全部类型': 渲染 {rendered_all} 条")

    # ---- 5) 一键优化：状态过渡 optimizing → optimized ----
    # 找到第一个 BadCaseItem
    item0 = ip._items_layout.itemAt(0).widget()
    assert isinstance(item0, BadCaseItem)
    assert item0.bc.optimized is False
    assert item0._optimized_label.isVisible() is False

    optimized_signals = []
    ip.optimize_requested.connect(lambda bid: optimized_signals.append(bid))

    # 触发一键优化
    item0._on_optimize()
    QApplication.processEvents()
    # 此时应该处于 optimizing 态
    assert "优化中" in item0._opt_btn.text()
    assert item0._opt_btn.isEnabled() is False
    print(f"[OK] 一键优化中态: btn='{item0._opt_btn.text()}', enabled={item0._opt_btn.isEnabled()}")

    # 等待 1.4s（mock 用 1.2s）
    finished = {"ok": False}

    def _after_opt():
        try:
            assert item0.bc.optimized is True
            assert "已优化" in item0._opt_btn.text()
            assert item0._optimized_label.isVisible() is True
            assert len(item0.bc.optimized_answer) > 0
            assert len(optimized_signals) == 1
            assert optimized_signals[0] == item0.bc.id
            finished["ok"] = True
        except AssertionError as e:
            print(f"[FAIL] 一键优化完成态断言失败: {e}", file=sys.stderr)
        finally:
            app.quit()

    QTimer.singleShot(1400, _after_opt)
    app.exec()
    assert finished["ok"], "一键优化未完成"
    print(f"[OK] 一键优化完成: btn='{item0._opt_btn.text()}', optimized_label visible={item0._optimized_label.isVisible()}")
    print(f"     优化后回复: {item0.bc.optimized_answer[:50]}…")

    # ---- 6) 对话优化按钮触发 discuss_requested ----
    discussed = []
    ip.discuss_requested.connect(lambda bid, prompt: discussed.append((bid, prompt)))
    item1 = ip._items_layout.itemAt(1).widget()
    assert isinstance(item1, BadCaseItem)
    item1._on_discuss()
    QApplication.processEvents()
    assert len(discussed) == 1
    assert discussed[0][0] == item1.bc.id
    assert "BadCase" in discussed[0][1]
    print(f"[OK] 对话优化: discuss_requested({discussed[0][0]}, '{discussed[0][1][:40]}…')")

    # ---- 7) set_badcases 外部注入 ----
    custom_bcs = [
        BadCaseData(id="c1", bc_type="empty", question="测试问题？", answer="（空）", channel="微信私聊", user="测试", time_ago="刚刚"),
    ]
    custom_stats = IterationStats(total=1, weekly_new=1, resolved=5)
    ip.set_badcases(custom_bcs, custom_stats)
    QApplication.processEvents()
    assert len(ip.badcases()) == 1
    assert ip.stats().total == 1
    assert ip.stats().resolve_rate == "83%"  # 5 / (5+1) = 83.3% → round = 83%
    assert "1 条" in ip._subtitle.text()
    print(f"[OK] set_badcases 注入: 1条, rate={ip.stats().resolve_rate}, 副标题='{ip._subtitle.text()}'")

    # ---- 8) MainWindow 集成 ----
    win = MainWindow(MockAppEngine())
    win.show()
    win._switch_page("iteration", show_status=False)
    QApplication.processEvents()
    assert win.page_stack.currentIndex() == 2  # iteration = PAGE_ORDER[2]
    from aibridge.ui.iteration_page import IterationPage as IP2
    assert isinstance(win._pages.get("iteration"), IP2)
    print("[OK] MainWindow iteration 路由 → IterationPage (index 2)")

    ip.close()
    win.close()
    QTimer.singleShot(50, app.quit)
    app.exec()

    print("\n[PASS] 阶段2.3 IterationPage 冒烟测试全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
