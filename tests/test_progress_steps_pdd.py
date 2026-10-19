"""
ProgressSteps PDD 验证测试（Phase 5 /tdd）

原型契约 (ui_mockup.html L456-480):
  .progress-steps { display: flex; flex-direction: column; gap: 4px; }
  .progress-step { padding: 8px 10px; border-radius: var(--radius-md); font-size: 12px; }
  .progress-step.done { background: var(--success-light); }
  .progress-step.active { background: var(--primary-light); }
  .progress-step.todo { background: var(--bg-subtle); }
  .progress-step-icon { width: 18px; height: 18px; border-radius: 50%; font-size: 9px; }
  .progress-step.done .progress-step-icon { background: var(--success); color: #fff; }
  .progress-step.active .progress-step-icon { background: var(--primary); color: #fff; }
  .progress-step.todo .progress-step-icon { background: var(--bg-active); color: var(--text-tertiary); }

  原型 6 步标签 (L1719-1750):
    1 目标确认 / 2 知识萃取 / 3 人格塑造 / 4 交互设计 / 5 部署交付 / 6 持续演化

执行: pytest tests/test_progress_steps_pdd.py -v
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

from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


@pytest.fixture
def ps(qapp):
    from aibridge.ui.components.progress_steps import ProgressSteps
    from aibridge.ui.theme import apply_theme
    apply_theme(None, "light")
    w = ProgressSteps()
    w.resize(600, 80)
    w.show()
    QTest.qWait(30)
    yield w
    w.close()
    w.deleteLater()
    QTest.qWait(10)


# PS-1: 6 个阶段标签
def test_ps1_six_stages(ps):
    """PS-1: STAGE_LABELS 长度 == 6"""
    from aibridge.ui.components.progress_steps import STAGE_LABELS
    assert len(STAGE_LABELS) == 6

# PS-2: 标签内容对齐原型
def test_ps2_labels_content(ps):
    """PS-2: 标签 == [目标确认, 知识萃取, 人格塑造, 交互设计, 部署交付, 持续演化]"""
    from aibridge.ui.components.progress_steps import STAGE_LABELS
    expected = ["目标确认", "知识萃取", "人格塑造", "交互设计", "部署交付", "持续演化"]
    assert STAGE_LABELS == expected, f"标签不匹配: {STAGE_LABELS}"

# PS-3: jump_requested 信号
def test_ps3_jump_signal(ps):
    """PS-3: jump_requested(int) 信号存在"""
    from PyQt6.QtCore import pyqtBoundSignal
    assert isinstance(ps.jump_requested, pyqtBoundSignal)

# PS-4: set_current API
def test_ps4_set_current(ps):
    """PS-4: set_current(3) → current_stage() == 3"""
    ps.set_current(3)
    assert ps.current_stage() == 3

# PS-5: set_current 自动标记 done
def test_ps5_set_current_auto_done(ps):
    """PS-5: set_current(3) → stages 1,2 done"""
    ps.set_current(3)
    assert ps.is_done(1) is True
    assert ps.is_done(2) is True
    assert ps.is_done(3) is False  # current 不是 done

# PS-6: set_current(1) → 无 done
def test_ps6_set_current_1_no_done(ps):
    """PS-6: set_current(1) → 无已完成步骤"""
    ps.set_current(1)
    for i in range(1, 7):
        assert ps.is_done(i) is False

# PS-7: set_current(6) → 1-5 done
def test_ps7_set_current_6(ps):
    """PS-7: set_current(6) → stages 1-5 done"""
    ps.set_current(6)
    for i in range(1, 6):
        assert ps.is_done(i) is True
    assert ps.is_done(6) is False

# PS-8: clamp 上界
def test_ps8_clamp_upper(ps):
    """PS-8: set_current(10) → current == 6"""
    ps.set_current(10)
    assert ps.current_stage() == 6

# PS-9: clamp 下界
def test_ps9_clamp_lower(ps):
    """PS-9: set_current(-1) → current == 1"""
    ps.set_current(-1)
    assert ps.current_stage() == 1

# PS-10: set_step_done 手动设置
def test_ps10_set_step_done(ps):
    """PS-10: set_step_done(4, True) → is_done(4) True"""
    ps.set_current(1)
    ps.set_step_done(4, True)
    assert ps.is_done(4) is True

# PS-11: set_step_done 取消
def test_ps11_unset_step_done(ps):
    """PS-11: set_step_done(4, False) → is_done(4) False"""
    ps.set_step_done(4, True)
    ps.set_step_done(4, False)
    assert ps.is_done(4) is False

# PS-12: set_step_done 越界不崩溃
def test_ps12_out_of_range(ps):
    """PS-12: set_step_done(0/7, True) 不崩溃"""
    ps.set_step_done(0, True)
    ps.set_step_done(7, True)
    assert ps.is_done(0) is False
    assert ps.is_done(7) is False

# PS-13: minimumHeight 存在
def test_ps13_min_height(ps):
    """PS-13: minimumHeight > 0"""
    assert ps.minimumHeight() > 0

# PS-14: 初始 current == 1
def test_ps14_initial_current_1(ps):
    """PS-14: 初始 current_stage() == 1"""
    # 新 fixture 已经创建了一个新的 ProgressSteps
    from aibridge.ui.components.progress_steps import ProgressSteps
    w = ProgressSteps()
    assert w.current_stage() == 1
    w.deleteLater()

# PS-15: mouseTracking True
def test_ps15_mouse_tracking(ps):
    """PS-15: hasMouseTracking == True"""
    assert ps.hasMouseTracking() is True

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
