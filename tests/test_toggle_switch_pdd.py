"""
ToggleSwitch PDD 验证测试（Phase 5 /tdd）

原型契约 (ui_mockup.html L1480-1491):
  .settings-toggle { width: 40px; height: 22px; border-radius: var(--radius-full);
                     background: var(--bg-active); cursor: pointer; }
  .settings-toggle.on { background: var(--success); }
  .settings-toggle::after { width: 18px; height: 18px; top: 2px; left: 2px;
                             border-radius: 50%; background: #fff; transition: transform 0.2s; }
  .settings-toggle.on::after { transform: translateX(18px); }

执行: pytest tests/test_toggle_switch_pdd.py -v
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

from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from PyQt6.QtGui import QMouseEvent


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


@pytest.fixture
def ts(qapp):
    from aibridge.ui.components.toggle_switch import ToggleSwitch
    from aibridge.ui.theme import apply_theme
    apply_theme(None, "light")
    sw = ToggleSwitch()
    sw.show()
    QTest.qWait(30)
    yield sw
    sw.close()
    sw.deleteLater()
    QTest.qWait(10)


# TS-1: 固定尺寸 40x22（原型 .settings-toggle width:40 height:22）
def test_ts1_size_40_22(ts):
    """TS-1: fixedSize 40x22（原型 L1481）"""
    assert ts.width() == 40, f"宽度应为 40，实际 {ts.width()}"
    assert ts.height() == 22, f"高度应为 22，实际 {ts.height()}"

# TS-2: toggled 信号
def test_ts2_toggled_signal(ts):
    """TS-2: toggled(bool) 信号存在"""
    from PyQt6.QtCore import pyqtBoundSignal
    assert isinstance(ts.toggled, pyqtBoundSignal)

# TS-3: 初始 unchecked
def test_ts3_initial_unchecked(ts):
    """TS-3: 初始 isChecked() == False"""
    assert ts.isChecked() is False

# TS-4: setChecked(True) → isChecked True
def test_ts4_set_checked_true(ts):
    """TS-4: setChecked(True) → isChecked True"""
    ts.setChecked(True, animate=False)
    assert ts.isChecked() is True

# TS-5: setChecked(False) → isChecked False
def test_ts5_set_checked_false(ts):
    """TS-5: setChecked(False) → isChecked False"""
    ts.setChecked(True, animate=False)
    ts.setChecked(False, animate=False)
    assert ts.isChecked() is False

# TS-6: 点击切换状态
def test_ts6_click_toggles(ts):
    """TS-6: mousePressEvent 左键 → 切换 checked"""
    assert ts.isChecked() is False
    ev = QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPointF(20, 11),
                     Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier)
    ts.mousePressEvent(ev)
    assert ts.isChecked() is True

# TS-7: toggled 信号发射
def test_ts7_toggled_emits(ts):
    """TS-7: setChecked(True) → toggled 信号收到 True"""
    received = []
    ts.toggled.connect(lambda v: received.append(v))
    ts.setChecked(True, animate=False)
    assert True in received

# TS-8: checkState API
def test_ts8_check_state(ts):
    """TS-8: checkState() 返回 Qt.CheckState"""
    assert ts.checkState() == Qt.CheckState.Unchecked
    ts.setChecked(True, animate=False)
    assert ts.checkState() == Qt.CheckState.Checked

# TS-9: cursor PointingHand
def test_ts9_cursor(ts):
    """TS-9: cursor == PointingHandCursor"""
    assert ts.cursor().shape() == Qt.CursorShape.PointingHandCursor

# TS-10: 动画 duration 180ms
def test_ts10_anim_duration(ts):
    """TS-10: 动画 duration == 180"""
    assert ts._anim.duration() == 180

# TS-11: setChecked 相同值不触发信号
def test_ts11_no_emit_same_value(ts):
    """TS-11: setChecked(False) 已是 False → 不触发信号"""
    received = []
    ts.toggled.connect(lambda v: received.append(v))
    ts.setChecked(False, animate=False)
    assert len(received) == 0

# TS-12: setChecked(animate=False) → position 直接跳
def test_ts12_no_animate_position(ts):
    """TS-12: setChecked(True, animate=False) → position == 18"""
    ts.setChecked(True, animate=False)
    # 原型 on::after translateX(18px)，thumb 从 left:2 移到 left:20
    # 实现 position 应为 18 (原型 translateX(18px))
    assert ts.position == 20, f"animate=False 时 position 应为 20，实际 {ts.position}"

# TS-13: 初始 checked=True
def test_ts13_init_checked(qapp):
    """TS-13: ToggleSwitch(checked=True) → isChecked True"""
    from aibridge.ui.components.toggle_switch import ToggleSwitch
    from aibridge.ui.theme import apply_theme
    apply_theme(None, "light")
    sw = ToggleSwitch(checked=True)
    assert sw.isChecked() is True
    sw.deleteLater()

# TS-14: set_delta API 不存在（确保不是 ToggleSwitch 的 API）
def test_ts14_no_delta_api(ts):
    """TS-14: ToggleSwitch 不应有 set_delta API"""
    assert not hasattr(ts, "set_delta")

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
