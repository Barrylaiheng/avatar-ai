"""
StatCard PDD 验证测试（Phase 5 /tdd）

原型契约 (ui_mockup.html L954-963):
  .stat-card { padding: 18px; border-radius: var(--radius-lg); border: 1px solid var(--border); }
  .stat-card-label { font-size: 12px; color: var(--text-secondary); }
  .stat-card-value { font-size: 26px; font-weight: 700; color: var(--text-primary); margin-top: 4px; }
  .stat-card-trend { font-size: 11px; margin-top: 4px; }
  .stat-card-trend.up { color: var(--success); }
  .stat-card-trend.down { color: var(--error); }

执行: pytest tests/test_stat_card_pdd.py -v
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

from PyQt6.QtWidgets import QApplication, QLabel, QFrame
from PyQt6.QtTest import QTest


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


@pytest.fixture
def sc(qapp):
    from aibridge.ui.components.stat_card import StatCard
    from aibridge.ui.theme import apply_theme
    apply_theme(None, "light")
    card = StatCard(title="知识条目", icon_svg="<svg></svg>", value=42, delta="+12%", delta_positive=True)
    card.show()
    QTest.qWait(30)
    yield card
    card.close()
    card.deleteLater()
    QTest.qWait(10)


# SC-1: QFrame 子类
def test_sc1_is_frame(sc):
    """SC-1: StatCard 是 QFrame 子类"""
    assert isinstance(sc, QFrame)

# SC-2: padding 18px
def test_sc2_padding_18(sc):
    """SC-2: contentsMargins 四边 18px"""
    m = sc.layout().contentsMargins()
    assert m.left() == 18 and m.right() == 18 and m.top() == 18 and m.bottom() == 18

# SC-3: _title label 存在 + 文字
def test_sc3_title_label(sc):
    """SC-3: _title label 文字 == '知识条目'"""
    assert sc._title.text() == "知识条目"

# SC-4: _title font-size 12px (FONT_SM)
def test_sc4_title_font_12(sc):
    """SC-4: _title 样式含 12px"""
    assert "12px" in sc._title.styleSheet()

# SC-5: _title color TEXT_SECONDARY
def test_sc5_title_color(sc):
    """SC-5: _title 样式含 TEXT_SECONDARY 色"""
    from aibridge.ui.theme import get_token
    expected = str(get_token("TEXT_SECONDARY")).lower()
    assert expected in sc._title.styleSheet().lower()

# SC-6: _value_label 存在
def test_sc6_value_label(sc):
    """SC-6: _value_label 存在"""
    assert sc._value_label is not None

# SC-7: _value_label 文字 == "42"
def test_sc7_value_text(sc):
    """SC-7: _value_label.text() == '42'"""
    assert sc._value_label.text() == "42"

# SC-8: _value_label font-size 26px (FONT_STAT_VALUE)
def test_sc8_value_font_26(sc):
    """SC-8: _value_label 样式含 26px"""
    assert "26px" in sc._value_label.styleSheet()

# SC-9: _value_label font-weight 700
def test_sc9_value_bold(sc):
    """SC-9: _value_label 样式含 700"""
    assert "700" in sc._value_label.styleSheet()

# SC-10: _value_label color TEXT_PRIMARY
def test_sc10_value_color(sc):
    """SC-10: _value_label 样式含 TEXT_PRIMARY 色"""
    from aibridge.ui.theme import get_token
    expected = str(get_token("TEXT_PRIMARY")).lower()
    assert expected in sc._value_label.styleSheet().lower()

# SC-11: set_value API
def test_sc11_set_value(sc):
    """SC-11: set_value(128) → _value_label.text() == '128'"""
    sc.set_value(128)
    assert sc._value_label.text() == "128"

# SC-12: set_value 接受 str
def test_sc12_set_value_str(sc):
    """SC-12: set_value('99%') → text == '99%'"""
    sc.set_value("99%")
    assert sc._value_label.text() == "99%"

# SC-13: delta label 存在
def test_sc13_delta_exists(sc):
    """SC-13: _delta_label 存在且 text == '+12%'"""
    assert sc._delta_label is not None
    assert sc._delta_label.text() == "+12%"

# SC-14: delta positive → SUCCESS color
def test_sc14_delta_positive_color(sc):
    """SC-14: delta_positive=True → SUCCESS 色"""
    from aibridge.ui.theme import get_token
    expected = str(get_token("SUCCESS")).lower()
    assert expected in sc._delta_label.styleSheet().lower()

# SC-15: set_delta negative → ERROR color
def test_sc15_delta_negative_color(sc):
    """SC-15: set_delta('-5%', positive=False) → ERROR 色"""
    from aibridge.ui.theme import get_token
    sc.set_delta("-5%", positive=False)
    expected = str(get_token("ERROR")).lower()
    assert expected in sc._delta_label.styleSheet().lower()

# SC-16: border-radius RADIUS_LG in stylesheet
def test_sc16_border_radius(sc):
    """SC-16: stylesheet 含 border-radius"""
    assert "border-radius" in sc.styleSheet().lower()

# SC-17: border 1px
def test_sc17_border_1px(sc):
    """SC-17: stylesheet 含 '1px solid'"""
    assert "1px solid" in sc.styleSheet().lower()

# SC-18: background BG_BASE
def test_sc18_bg_base(sc):
    """SC-18: stylesheet 含 BG_BASE 色"""
    from aibridge.ui.theme import get_token
    expected = str(get_token("BG_BASE")).lower()
    assert expected in sc.styleSheet().lower()

# SC-19: delta=None → no delta label
def test_sc19_no_delta(qapp):
    """SC-19: 不传 delta → _delta_label is None"""
    from aibridge.ui.components.stat_card import StatCard
    from aibridge.ui.theme import apply_theme
    apply_theme(None, "light")
    card = StatCard(title="测试", icon_svg="<svg></svg>", value=0)
    assert card._delta_label is None
    card.deleteLater()

# SC-20: set_delta(None) → hide delta
def test_sc20_set_delta_none_hides(sc):
    """SC-20: set_delta(None) → _delta_label 隐藏"""
    sc.set_delta(None)
    assert not sc._delta_label.isVisible()

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
