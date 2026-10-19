"""
阶段2.2 冒烟测试：KnowledgePage
- 5个阶段分组渲染（含 done/active/todo 三种状态）
- 条目卡片点击展开/折叠
- 保存按钮触发 entry_saved 信号
- 对话优化按钮触发 discuss_requested 信号
- 视图切换 list/graph
- 导出按钮触发 export_requested
- 与 MainWindow 集成（knowledge 路由 → KnowledgePage）

运行：
    set QT_QPA_PLATFORM=offscreen
    python tests/test_phase2_2_knowledgepage.py
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
    from PyQt6.QtCore import QTimer, Qt

    from aibridge.ui.theme import apply_theme
    from aibridge.ui.knowledge_page import (
        KnowledgePage, StageGroupData, KnowledgeEntryData, StageGroupSection,
        KnowledgeEntryCard,
    )
    from aibridge.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    apply_theme(None, "light")

    # ---- 1) 默认 mock 数据：5 个阶段，13 条目 ----
    kp = KnowledgePage()
    kp.show()
    assert len(kp.stages()) == 5, f"阶段数: {len(kp.stages())}"
    assert kp.total_entries() == 13, f"总条目数: {kp.total_entries()}"
    # 阶段1: 3条目 done, 阶段2: 6条目 done, 阶段3: 4条目 active, 阶段4/5: 0条目 todo
    assert kp.stages()[0].count == 3 and kp.stages()[0].status == "done"
    assert kp.stages()[1].count == 6 and kp.stages()[1].status == "done"
    assert kp.stages()[2].count == 4 and kp.stages()[2].status == "active"
    assert kp.stages()[3].count == 0 and kp.stages()[3].status == "todo"
    assert kp.stages()[4].count == 0 and kp.stages()[4].status == "todo"
    print(f"[OK] mock 数据: 5阶段 / {kp.total_entries()}条目 (done/active/todo 状态齐全)")

    # ---- 2) 默认视图 = list ----
    assert kp._view == "list"
    assert kp._stack.currentIndex() == 0
    print("[OK] 默认视图 = list (stack index 0)")

    # ---- 3) 切换到 graph 视图 ----
    view_changes = []
    kp.view_changed.connect(lambda v: view_changes.append(v))
    kp._switch_view("graph")
    QApplication.processEvents()
    assert kp._view == "graph"
    assert kp._stack.currentIndex() == 1
    assert view_changes == ["graph"]
    print("[OK] 切换到 graph 视图 (stack index 1, view_changed 信号触发)")
    # 切回 list
    kp._switch_view("list")
    assert kp._view == "list" and kp._stack.currentIndex() == 0
    print("[OK] 切回 list 视图")

    # ---- 4) 找到第一张卡片，测试展开/折叠 ----
    # 阶段1 的 section 在 _list_layout 的第 0 位（stretch 是最后）
    section0 = kp._list_layout.itemAt(0).widget()
    assert isinstance(section0, StageGroupSection)
    assert len(section0.cards) == 3
    card0 = section0.cards[0]
    assert isinstance(card0, KnowledgeEntryCard)
    assert card0._expanded is False
    assert card0._detail.isVisible() is False

    # 编程式展开
    expanded_changes = []
    card0.expanded_changed.connect(lambda eid, exp: expanded_changes.append((eid, exp)))
    card0.set_expanded(True)
    QApplication.processEvents()
    assert card0._expanded is True
    assert card0._detail.isVisible() is True
    assert card0._hint.text().startswith("▾")
    assert len(expanded_changes) == 1 and expanded_changes[0][1] is True
    print(f"[OK] 卡片展开: hint='{card0._hint.text()}', detail visible={card0._detail.isVisible()}")
    # 折叠
    card0.set_expanded(False)
    assert card0._expanded is False and card0._detail.isVisible() is False
    print("[OK] 卡片折叠恢复")

    # ---- 5) 保存按钮触发 entry_saved 信号 ----
    saved = []
    kp.entry_saved.connect(lambda eid, data: saved.append((eid, data)))
    # 修改编辑器内容
    first_label = list(card0._editors.keys())[0]
    card0._editors[first_label].setPlainText("【测试】修改后的内容")
    card0._on_save()
    QApplication.processEvents()
    assert len(saved) == 1, f"entry_saved 信号数: {len(saved)}"
    assert saved[0][0] == card0.entry.id
    assert saved[0][1][first_label] == "【测试】修改后的内容"
    print(f"[OK] 保存按钮: entry_saved({saved[0][0]}, {saved[0][1]})")

    # ---- 6) 对话优化按钮触发 discuss_requested ----
    discussed = []
    kp.discuss_requested.connect(lambda eid, prompt: discussed.append((eid, prompt)))
    card0._on_discuss()
    QApplication.processEvents()
    assert len(discussed) == 1
    assert discussed[0][0] == card0.entry.id
    assert "修改" in discussed[0][1]
    print(f"[OK] 对话优化: discuss_requested({discussed[0][0]}, '{discussed[0][1]}')")

    # ---- 7) 导出按钮触发 export_requested ----
    exported = []
    kp.export_requested.connect(lambda: exported.append(True))
    kp._on_export()
    QApplication.processEvents()
    assert len(exported) == 1
    print("[OK] 导出按钮: export_requested 信号触发")

    # ---- 8) todo 阶段（stage 4）的 "开始" 链接触发 start_stage_requested ----
    starts = []
    kp.start_stage_requested.connect(lambda idx: starts.append(idx))
    # section[3] = stage 4 (todo, 0 entries)
    section3 = kp._list_layout.itemAt(3).widget()
    assert isinstance(section3, StageGroupSection)
    assert section3.stage.count == 0
    # 找到 placeholder 里的 link label 并模拟点击
    placeholder = section3._build_empty_placeholder()  # 重建一个测试
    # 直接发信号测试连接
    section3.start_stage_requested.emit(4)
    QApplication.processEvents()
    assert len(starts) == 1 and starts[0] == 4
    print(f"[OK] todo 阶段 '开始' 链接: start_stage_requested(4) 信号触发")

    # ---- 9) set_stages 外部注入数据 ----
    custom = [
        StageGroupData(stage_idx=1, title="测试阶段", status="active", entries=[
            KnowledgeEntryData(id="t1", stage_idx=1, tag="测试", title="测试条目", summary="摘要", source="测试", details=[{"label": "内容", "value": "值"}])
        ])
    ]
    kp.set_stages(custom)
    QApplication.processEvents()
    assert len(kp.stages()) == 1
    assert kp.total_entries() == 1
    assert "1 个条目" in kp._subtitle.text()
    print("[OK] set_stages 外部注入: 1阶段/1条目, 副标题更新")

    # ---- 10) MainWindow 集成 ----
    win = MainWindow(MockAppEngine())
    win.show()
    win._switch_page("knowledge", show_status=False)
    QApplication.processEvents()
    assert win.page_stack.currentIndex() == 1  # knowledge = PAGE_ORDER[1]
    # 确认是新版 KnowledgePage（有 stages() 方法）
    kp_in_win = win._pages.get("knowledge")
    from aibridge.ui.knowledge_page import KnowledgePage as KP2
    assert isinstance(kp_in_win, KP2)
    assert hasattr(kp_in_win, "stages") and hasattr(kp_in_win, "total_entries")
    print("[OK] MainWindow knowledge 路由 → 新版 KnowledgePage (index 1)")

    kp.close()
    win.close()
    QTimer.singleShot(50, app.quit)
    app.exec()

    print("\n[PASS] 阶段2.2 KnowledgePage 冒烟测试全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
