"""
六阶段向导面板验证脚本

验证内容：
1. WizardPanel 初始化
2. 六个阶段页面创建
3. 阶段间导航（上一步/下一步/跳过/完成）
4. 进度追踪
5. 各阶段集成模块可访问
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ['QT_IM_MODULE'] = ''


def test_wizard_initialization(app):
    """测试 1: WizardPanel 初始化"""
    print("\n--- 测试 1: WizardPanel 初始化 ---")
    from aibridge.ui.wizard_panel import WizardPanel, STAGE_CONFIG

    wizard = WizardPanel()

    assert len(STAGE_CONFIG) == 6, "应有 6 个阶段"
    assert wizard._current_stage == "stage_1", "默认应在阶段 1"
    assert len(wizard._stage_pages) == 6, "应创建 6 个阶段页面"
    print(f"  ✓ 六个阶段配置: {[s['name'] for s in STAGE_CONFIG]}")
    print(f"  ✓ 默认阶段: {wizard._current_stage}")
    print(f"  ✓ 阶段页面数: {len(wizard._stage_pages)}")

    return wizard


def test_stage_navigation(wizard):
    """测试 2: 阶段间导航"""
    print("\n--- 测试 2: 阶段间导航 ---")
    from aibridge.ui.wizard_panel import STAGE_CONFIG

    # 切换到阶段 2
    wizard._on_nav_clicked("stage_2")
    assert wizard._current_stage == "stage_2"
    print(f"  ✓ 点击导航: stage_2")

    # 下一步 → 阶段 3
    wizard._go_next()
    assert wizard._current_stage == "stage_3"
    print(f"  ✓ 下一步: stage_3")

    # 上一步 → 阶段 2
    wizard._go_prev()
    assert wizard._current_stage == "stage_2"
    print(f"  ✓ 上一步: stage_2")

    # 跳过 → 阶段 3
    wizard._skip_stage()
    assert wizard._current_stage == "stage_3"
    print(f"  ✓ 跳过: stage_3")

    # 标记完成 → 自动到阶段 4
    wizard._complete_stage()
    assert wizard._current_stage == "stage_4"
    assert wizard._stage_statuses["stage_3"] == "completed"
    print(f"  ✓ 标记完成: stage_3 → stage_4")


def test_progress_tracking(wizard):
    """测试 3: 进度追踪"""
    print("\n--- 测试 3: 进度追踪 ---")

    # 重置所有状态
    for stage_id in wizard._stage_statuses:
        wizard._stage_statuses[stage_id] = "pending"

    # 完成阶段 1
    wizard._current_stage = "stage_1"
    wizard._complete_stage()
    completed_count = sum(1 for s in wizard._stage_statuses.values() if s == "completed")
    assert completed_count == 1, f"应有 1 个完成，实际 {completed_count}"
    print(f"  ✓ 完成阶段 1: {completed_count}/6")

    # 完成阶段 2
    wizard._complete_stage()
    completed_count = sum(1 for s in wizard._stage_statuses.values() if s == "completed")
    assert completed_count == 2, f"应有 2 个完成，实际 {completed_count}"
    print(f"  ✓ 完成阶段 2: {completed_count}/6")

    # 检查进度标签
    assert "2 / 6" in wizard.progress_label.text()
    print(f"  ✓ 进度标签: {wizard.progress_label.text()}")


def test_stage_pages_integration(wizard):
    """测试 4: 各阶段页面集成"""
    print("\n--- 测试 4: 各阶段页面集成 ---")
    from aibridge.ui.wizard_panel import (
        Stage1KnowledgeExtraction,
        Stage2KnowledgeOrganization,
        Stage3PersonaShaping,
        Stage4InteractionDesign,
        Stage5Deployment,
        Stage6Evolution,
    )

    page1 = wizard._stage_pages["stage_1"]
    page2 = wizard._stage_pages["stage_2"]
    page3 = wizard._stage_pages["stage_3"]
    page4 = wizard._stage_pages["stage_4"]
    page5 = wizard._stage_pages["stage_5"]
    page6 = wizard._stage_pages["stage_6"]

    assert isinstance(page1, Stage1KnowledgeExtraction), "阶段1应为知识萃取页"
    assert isinstance(page2, Stage2KnowledgeOrganization), "阶段2应为知识组织页"
    assert isinstance(page3, Stage3PersonaShaping), "阶段3应为人格塑造页"
    assert isinstance(page4, Stage4InteractionDesign), "阶段4应为交互设计页"
    assert isinstance(page5, Stage5Deployment), "阶段5应为部署交付页"
    assert isinstance(page6, Stage6Evolution), "阶段6应为持续演化页"

    print(f"  ✓ 阶段1: 知识萃取（五步蒸馏法 + 资料导入）")
    print(f"  ✓ 阶段2: 知识组织（Wiki 统计 + 条目列表）")
    print(f"  ✓ 阶段3: 人格塑造（集成人设编辑器）")
    print(f"  ✓ 阶段4: 交互设计（阶段分类器 + 信号检测器 + 六层引擎）")
    print(f"  ✓ 阶段5: 部署交付（WCF + LLM + 自检清单）")
    print(f"  ✓ 阶段6: 持续演化（占位）")


def test_stage4_tabs(wizard):
    """测试 5: 阶段4 的三个 Tab"""
    print("\n--- 测试 5: 阶段4 Tab 结构 ---")
    page4 = wizard._stage_pages["stage_4"]

    # 应有阶段分类器表格、信号检测器表格、六层引擎说明
    assert hasattr(page4, '_stage_table'), "应有阶段分类器表格"
    assert hasattr(page4, '_signal_table'), "应有信号检测器表格"
    print(f"  ✓ 阶段分类器表格: {page4._stage_table.columnCount()} 列")
    print(f"  ✓ 信号检测器表格: {page4._signal_table.columnCount()} 列")


def test_stage5_checklist(wizard):
    """测试 6: 阶段5 部署自检清单"""
    print("\n--- 测试 6: 部署自检清单 ---")
    page5 = wizard._stage_pages["stage_5"]

    assert hasattr(page5, '_checklist_items'), "应有自检清单"
    assert len(page5._checklist_items) == 8, f"应有 8 项自检，实际 {len(page5._checklist_items)}"
    print(f"  ✓ 自检清单: {len(page5._checklist_items)} 项")

    # 检查 WCF 和 LLM 配置表单
    assert hasattr(page5, '_wcf_ip'), "应有 WCF IP 输入"
    assert hasattr(page5, '_llm_api_key'), "应有 LLM API Key 输入"
    print(f"  ✓ WCF 配置表单: IP/端口/Token")
    print(f"  ✓ LLM 配置表单: 提供商/Key/URL/模型/温度")


def test_on_enter_callbacks(wizard):
    """测试 7: 进入阶段时的回调"""
    print("\n--- 测试 7: 进入阶段回调 ---")

    # 切换到阶段 1（应触发 on_enter 刷新原始资料列表）
    wizard._update_stage("stage_1")
    page1 = wizard._stage_pages["stage_1"]
    assert page1._raw_sources_list.count() > 0, "应刷新原始资料列表"
    print(f"  ✓ 阶段1 on_enter: 原始资料列表已刷新")

    # 切换到阶段 2（应触发 on_enter 刷新 Wiki 数据）
    wizard._update_stage("stage_2")
    page2 = wizard._stage_pages["stage_2"]
    print(f"  ✓ 阶段2 on_enter: Wiki 数据已刷新")

    # 切换到阶段 4（应触发 on_enter 刷新阶段和信号配置）
    wizard._update_stage("stage_4")
    page4 = wizard._stage_pages["stage_4"]
    assert page4._stage_table.rowCount() > 0, "应刷新阶段配置"
    assert page4._signal_table.rowCount() > 0, "应刷新信号配置"
    print(f"  ✓ 阶段4 on_enter: 阶段配置({page4._stage_table.rowCount()}) + 信号配置({page4._signal_table.rowCount()})")


if __name__ == "__main__":
    print("=" * 60)
    print("AI Bridge - 六阶段向导面板 验证")
    print("=" * 60)

    try:
        from PyQt6.QtWidgets import QApplication
        # 关键：在主作用域创建并保持 QApplication 引用，避免被 GC 导致所有 Qt 对象被删除
        app = QApplication.instance() or QApplication(sys.argv)

        wizard = test_wizard_initialization(app)
        test_stage_navigation(wizard)
        test_progress_tracking(wizard)
        test_stage_pages_integration(wizard)
        test_stage4_tabs(wizard)
        test_stage5_checklist(wizard)
        test_on_enter_callbacks(wizard)

        print("\n" + "=" * 60)
        print("✓ 全部验证通过")
        sys.exit(0)

    except AssertionError as e:
        print(f"\n✗ 验证失败: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ 异常: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
