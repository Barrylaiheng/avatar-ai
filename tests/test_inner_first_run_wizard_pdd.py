"""
SCAI MVP · P1-1 首次启动引导向导 · PDD Test Seams

Grill 清单（10 条）：
- G1: ConfigManager.is_first_run / mark_first_run_done（P1-3 已实现，P1-1 复用）
- G2: ui/first_run_wizard.py 含 FirstRunWizardDialog 类
- G3: Wizard 3 步流程结构（TOTAL_STEPS=3）
- G4: Step 1 LLM 配置（provider/api_key/model）
- G5: Step 2 人设确认（name/type/tone）
- G6: Step 3 完成页（example_wiki_count=5）
- G7: 完成按钮调 mark_first_run_done
- G8: 跳过按钮调 mark_first_run_done
- G9: MainWindow 有 _check_first_run 方法
- G10: AppEngine 有 is_first_run / mark_first_run_done 代理方法

运行：
  pytest tests/test_inner_first_run_wizard_pdd.py -v
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))


# ============================================================
# G1: ConfigManager.is_first_run / mark_first_run_done（P1-3 已实现）
# ============================================================

class TestG1FirstRunDetection:
    def test_G1_is_first_run_true_on_first_launch(self, tmp_path, monkeypatch):
        """G1: 首次启动 is_first_run()=True"""
        monkeypatch.setenv("SCAI_DATA_DIR", str(tmp_path))
        from aibridge.config.config_manager import ConfigManager
        cm = ConfigManager()
        assert cm.is_first_run() is True

    def test_G1_mark_first_run_done_persists(self, tmp_path, monkeypatch):
        """G1: mark_first_run_done 后 is_first_run()=False，持久化跨重启"""
        monkeypatch.setenv("SCAI_DATA_DIR", str(tmp_path))
        from aibridge.config.config_manager import ConfigManager
        cm = ConfigManager()
        cm.mark_first_run_done()
        assert cm.is_first_run() is False

        # 重启验证
        cm2 = ConfigManager()
        assert cm2.is_first_run() is False


# ============================================================
# G2: FirstRunWizardDialog 类存在
# ============================================================

class TestG2WizardClassExists:
    def test_G2_wizard_class_exists(self):
        """G2: ui/first_run_wizard.py 含 FirstRunWizardDialog 类"""
        from aibridge.ui.first_run_wizard import FirstRunWizardDialog
        assert FirstRunWizardDialog is not None
        # 继承 QDialog
        from PyQt6.QtWidgets import QDialog
        assert issubclass(FirstRunWizardDialog, QDialog)

    def test_G2_wizard_has_signals(self):
        """G2: FirstRunWizardDialog 有 wizard_completed / wizard_skipped 信号"""
        from aibridge.ui.first_run_wizard import FirstRunWizardDialog
        assert hasattr(FirstRunWizardDialog, "wizard_completed")
        assert hasattr(FirstRunWizardDialog, "wizard_skipped")


# ============================================================
# G3: Wizard 3 步流程结构
# ============================================================

class TestG3WizardSteps:
    def test_G3_total_steps_is_3(self):
        """G3: TOTAL_STEPS=3"""
        from aibridge.ui.first_run_wizard import TOTAL_STEPS
        assert TOTAL_STEPS == 3

    def test_G3_wizard_has_step_methods(self):
        """G3: Wizard 有 _on_next / _on_prev / _on_finish / _on_skip 方法"""
        from aibridge.ui.first_run_wizard import FirstRunWizardDialog
        assert hasattr(FirstRunWizardDialog, "_on_next")
        assert hasattr(FirstRunWizardDialog, "_on_prev")
        assert hasattr(FirstRunWizardDialog, "_on_finish")
        assert hasattr(FirstRunWizardDialog, "_on_skip")


# ============================================================
# G4: Step 1 LLM 配置
# ============================================================

class TestG4Step1LLMConfig:
    def test_G4_wizard_has_llm_fields(self):
        """G4: Wizard 有 _provider_combo / _apikey_edit / _model_edit 属性"""
        from aibridge.ui.first_run_wizard import FirstRunWizardDialog
        # 检查类定义中包含这些属性（通过 __init__ 中的 self.xxx 赋值）
        # 由于无法实例化 QDialog（无 QApplication），检查源码结构
        import inspect
        src = inspect.getsource(FirstRunWizardDialog)
        assert "_provider_combo" in src
        assert "_apikey_edit" in src
        assert "_model_edit" in src

    def test_G4_wizard_has_test_connection(self):
        """G4: Wizard 有 _on_test_connection 方法"""
        from aibridge.ui.first_run_wizard import FirstRunWizardDialog
        assert hasattr(FirstRunWizardDialog, "_on_test_connection")


# ============================================================
# G5: Step 2 人设确认
# ============================================================

class TestG5Step2Persona:
    def test_G5_wizard_has_persona_fields(self):
        """G5: Wizard 有 _persona_name_edit / _persona_type_edit / _persona_tone_edit"""
        import inspect
        from aibridge.ui.first_run_wizard import FirstRunWizardDialog
        src = inspect.getsource(FirstRunWizardDialog)
        assert "_persona_name_edit" in src
        assert "_persona_type_edit" in src
        assert "_persona_tone_edit" in src

    def test_G5_wizard_loads_persona_from_engine(self):
        """G5: Wizard 有 _load_engine_data 方法（从 Engine 读示例人设）"""
        from aibridge.ui.first_run_wizard import FirstRunWizardDialog
        assert hasattr(FirstRunWizardDialog, "_load_engine_data")


# ============================================================
# G6: Step 3 完成页
# ============================================================

class TestG6Step3Complete:
    def test_G6_wizard_has_complete_desc(self):
        """G6: Wizard 有 _complete_desc 属性（显示示例知识数）"""
        import inspect
        from aibridge.ui.first_run_wizard import FirstRunWizardDialog
        src = inspect.getsource(FirstRunWizardDialog)
        assert "_complete_desc" in src
        # 文案包含"5 条"
        assert "5 条" in src or "example_wiki_count" in src

    def test_G6_wizard_has_build_step3(self):
        """G6: Wizard 有 _build_step3_complete 方法"""
        from aibridge.ui.first_run_wizard import FirstRunWizardDialog
        assert hasattr(FirstRunWizardDialog, "_build_step3_complete")


# ============================================================
# G7-G8: 完成按钮 + 跳过按钮调 mark_first_run_done
# ============================================================

class TestG7G8FinishSkip:
    def test_G7_finish_calls_mark_first_run_done(self):
        """G7: _on_finish 方法存在（调用 mark_first_run_done）"""
        from aibridge.ui.first_run_wizard import FirstRunWizardDialog
        assert hasattr(FirstRunWizardDialog, "_on_finish")
        # 源码包含 mark_first_run_done 调用
        import inspect
        src = inspect.getsource(FirstRunWizardDialog._on_finish)
        assert "mark_first_run_done" in src

    def test_G7_finish_emits_completed_signal(self):
        """G7: _on_finish 发射 wizard_completed 信号"""
        import inspect
        from aibridge.ui.first_run_wizard import FirstRunWizardDialog
        src = inspect.getsource(FirstRunWizardDialog._on_finish)
        assert "wizard_completed" in src

    def test_G8_skip_calls_mark_first_run_done(self):
        """G8: _on_skip 方法存在（调用 mark_first_run_done）"""
        from aibridge.ui.first_run_wizard import FirstRunWizardDialog
        assert hasattr(FirstRunWizardDialog, "_on_skip")
        import inspect
        src = inspect.getsource(FirstRunWizardDialog._on_skip)
        assert "mark_first_run_done" in src

    def test_G8_skip_emits_skipped_signal(self):
        """G8: _on_skip 发射 wizard_skipped 信号"""
        import inspect
        from aibridge.ui.first_run_wizard import FirstRunWizardDialog
        src = inspect.getsource(FirstRunWizardDialog._on_skip)
        assert "wizard_skipped" in src


# ============================================================
# G9: MainWindow 有 _check_first_run 方法
# ============================================================

class TestG9MainWindowIntegration:
    def test_G9_main_window_has_check_first_run(self):
        """G9: MainWindow 有 _check_first_run 方法"""
        from aibridge.ui.main_window import MainWindow
        assert hasattr(MainWindow, "_check_first_run")

    def test_G9_main_window_has_wizard_callbacks(self):
        """G9: MainWindow 有 _on_wizard_completed / _on_wizard_skipped"""
        from aibridge.ui.main_window import MainWindow
        assert hasattr(MainWindow, "_on_wizard_completed")
        assert hasattr(MainWindow, "_on_wizard_skipped")


# ============================================================
# G10: AppEngine 有 is_first_run / mark_first_run_done 代理方法
# ============================================================

class TestG10AppEngineProxy:
    def test_G10_engine_has_is_first_run(self, tmp_path, monkeypatch):
        """G10: AppEngine 有 is_first_run 代理方法"""
        monkeypatch.setenv("SCAI_DATA_DIR", str(tmp_path))
        from aibridge.app_engine import AppEngine
        engine = AppEngine()
        engine.initialize()
        assert hasattr(engine, "is_first_run")
        assert callable(engine.is_first_run)

    def test_G10_engine_has_mark_first_run_done(self, tmp_path, monkeypatch):
        """G10: AppEngine 有 mark_first_run_done 代理方法"""
        monkeypatch.setenv("SCAI_DATA_DIR", str(tmp_path))
        from aibridge.app_engine import AppEngine
        engine = AppEngine()
        engine.initialize()
        assert hasattr(engine, "mark_first_run_done")
        assert callable(engine.mark_first_run_done)

    def test_G10_engine_first_run_proxy_works(self, tmp_path, monkeypatch):
        """G10: AppEngine.is_first_run 首次 True，mark_first_run_done 后 False"""
        monkeypatch.setenv("SCAI_DATA_DIR", str(tmp_path))
        from aibridge.app_engine import AppEngine
        engine = AppEngine()
        engine.initialize()

        # 首次启动
        assert engine.is_first_run() is True
        # 标记完成
        engine.mark_first_run_done()
        assert engine.is_first_run() is False

    def test_G10_engine_proxy_persists(self, tmp_path, monkeypatch):
        """G10: 代理方法持久化跨重启"""
        monkeypatch.setenv("SCAI_DATA_DIR", str(tmp_path))
        from aibridge.app_engine import AppEngine

        engine1 = AppEngine()
        engine1.initialize()
        engine1.mark_first_run_done()

        # 重启
        engine2 = AppEngine()
        engine2.initialize()
        assert engine2.is_first_run() is False


# ============================================================
# 集成：Engine + Wizard 调用链（用 Mock Engine 验证）
# ============================================================

class TestIntegration:
    def test_wizard_flow_with_real_engine(self, tmp_path, monkeypatch):
        """集成：真实 Engine + 模拟 Wizard 调用链"""
        monkeypatch.setenv("SCAI_DATA_DIR", str(tmp_path))
        from aibridge.app_engine import AppEngine

        # 首次启动
        engine = AppEngine()
        engine.initialize()
        assert engine.is_first_run() is True

        # 模拟 Wizard 完成：调 mark_first_run_done
        engine.mark_first_run_done()
        assert engine.is_first_run() is False

        # 二次启动
        engine2 = AppEngine()
        engine2.initialize()
        assert engine2.is_first_run() is False

    def test_wizard_skip_also_marks_done(self, tmp_path, monkeypatch):
        """集成：跳过 Wizard 也能标记首启完成"""
        monkeypatch.setenv("SCAI_DATA_DIR", str(tmp_path))
        from aibridge.app_engine import AppEngine

        engine = AppEngine()
        engine.initialize()
        assert engine.is_first_run() is True

        # 模拟跳过：也调 mark_first_run_done
        engine.mark_first_run_done()
        assert engine.is_first_run() is False
