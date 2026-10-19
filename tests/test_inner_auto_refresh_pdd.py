#!/usr/bin/env python3
"""
SCAI MVP · PDD 测试 · 模块 P1-5：MainWindow 60s 定时刷新工作台
PDD 阶段：implement + tdd（验证 8 条 Grill 断言）

覆盖 8 条 Grill：
  G1: MainWindow 有 AUTO_REFRESH_INTERVAL_MS=60000 类属性
  G2: MainWindow 有 _start_auto_refresh_timer() 方法
  G3: MainWindow 有 _stop_auto_refresh_timer() 方法
  G4: MainWindow 有 _on_auto_refresh_tick() 槽函数
  G5: _on_auto_refresh_tick 调用路径中包含 workspace_page.refresh_workspace_cards 判断
  G6: _on_auto_refresh_tick 调用 _refresh_degraded_banner（无论哪页）
  G7: closeEvent 中调用 _stop_auto_refresh_timer
  G8: _on_auto_refresh_tick 有 try/except 兜底（无 workspace_page 不崩）

运行：python -m pytest tests/test_inner_auto_refresh_pdd.py -v
"""
import inspect
import textwrap


# ─────────────────────────── G1/G2/G3/G4: 类属性 + 方法存在性 ───────────────────────────

class TestG1G4ClassAttributesAndMethods:
    def test_G1_AUTO_REFRESH_INTERVAL_is_60000(self):
        """G1: MainWindow.AUTO_REFRESH_INTERVAL_MS = 60000（60s）"""
        from aibridge.ui.main_window import MainWindow
        assert hasattr(MainWindow, "AUTO_REFRESH_INTERVAL_MS")
        assert MainWindow.AUTO_REFRESH_INTERVAL_MS == 60000

    def test_G2_has_start_auto_refresh_method(self):
        """G2: MainWindow 有 _start_auto_refresh_timer() 方法"""
        from aibridge.ui.main_window import MainWindow
        assert hasattr(MainWindow, "_start_auto_refresh_timer")
        assert callable(getattr(MainWindow, "_start_auto_refresh_timer"))

    def test_G3_has_stop_auto_refresh_method(self):
        """G3: MainWindow 有 _stop_auto_refresh_timer() 方法"""
        from aibridge.ui.main_window import MainWindow
        assert hasattr(MainWindow, "_stop_auto_refresh_timer")
        assert callable(getattr(MainWindow, "_stop_auto_refresh_timer"))

    def test_G4_has_on_auto_refresh_tick_method(self):
        """G4: MainWindow 有 _on_auto_refresh_tick() 槽函数"""
        from aibridge.ui.main_window import MainWindow
        assert hasattr(MainWindow, "_on_auto_refresh_tick")
        assert callable(getattr(MainWindow, "_on_auto_refresh_tick"))


# ─────────────────────────── G5/G6/G8: _on_auto_refresh_tick 源码静态分析 ───────────────────────────

class TestG5G6G8TickLogic:
    """通过 inspect.getsource 静态分析 tick 函数源码，避免实例化 QMainWindow"""

    @staticmethod
    def _get_tick_source():
        from aibridge.ui.main_window import MainWindow
        return textwrap.dedent(inspect.getsource(MainWindow._on_auto_refresh_tick))

    def test_G5_tick_contains_workspace_refresh_check(self):
        """G5: tick 时当前页为 workspace 则调用 refresh_workspace_cards"""
        src = self._get_tick_source()
        # 检查包含当前页判断 + workspace_page + refresh_workspace_cards
        assert "workspace" in src, "tick 中缺少 workspace 页面判断"
        assert "refresh_workspace_cards" in src, "tick 中缺少 refresh_workspace_cards 调用"

    def test_G6_tick_calls_refresh_degraded_banner(self):
        """G6: tick 时无论哪页都调用 _refresh_degraded_banner"""
        src = self._get_tick_source()
        assert "_refresh_degraded_banner" in src, "tick 中缺少 _refresh_degraded_banner 调用"

    def test_G8_tick_has_exception_handling(self):
        """G8: tick 中有 try/except 兜底，无 workspace_page 不崩"""
        src = self._get_tick_source()
        # 检查至少有一层 try/except
        assert "try:" in src, "tick 中缺少 try 块"
        assert "except" in src, "tick 中缺少 except 兜底"
        # 检查有 None check（wp is not None 或 getattr 安全访问）
        has_none_check = "is not None" in src or "getattr" in src
        assert has_none_check, "tick 中缺少 workspace_page 的 None 安全检查"


# ─────────────────────────── G7: closeEvent 停止定时器 ───────────────────────────

class TestG7CloseEventStopsTimer:
    def test_G7_closeEvent_calls_stop_auto_refresh(self):
        """G7: closeEvent 中调用 _stop_auto_refresh_timer"""
        from aibridge.ui.main_window import MainWindow
        src = textwrap.dedent(inspect.getsource(MainWindow.closeEvent))
        assert "_stop_auto_refresh_timer" in src, "closeEvent 中缺少 _stop_auto_refresh_timer 调用"
