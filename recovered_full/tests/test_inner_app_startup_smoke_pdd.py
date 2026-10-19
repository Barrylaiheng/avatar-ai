#!/usr/bin/env python3
"""
SCAI MVP · PDD 测试 · 模块 P1-6：App Startup Smoketest（应用启动冒烟测试）
PDD 阶段：implement + tdd（验证 8 条 Grill 断言）

覆盖 8 条 Grill：
  G1: AppEngine() + initialize() 在干净临时目录不抛异常，返回 bool
  G2: is_initialized()=bool；get_degraded_details()=list 可 JSON 序列化
  G3: process_message(user_input, session_id) 返回 dict，含 content/is_aigc 字段
  G4: 已有 QApplication 前提下，MainWindow(engine) 实例化不崩
  G5: degraded_banner 非 None；len(_pages) == len(PAGE_ORDER)
  G6: _start_auto_refresh_timer 后 timer.isActive()=True
  G7: stop → close → del 不抛异常
  G8: OACloudService.auto_bootstrap(cfg_minimal) 在临时目录下不抛异常，非 None

运行：python -m pytest tests/test_inner_app_startup_smoke_pdd.py -v
"""
import json
import os
import sys
from pathlib import Path

import pytest


# ─────────────────────────── 全局 fixture：设置 HF 离线模式避免 embedding 下载重试 ───────────────────────────

@pytest.fixture(autouse=True)
def _hf_offline_mode(monkeypatch):
    """所有本模块的测试都强制 HF 离线，让 ChromaDB embedding 加载立即 degraded（不重试 5 次）

    原因：内网或无网络时，HuggingFace 每次 HEAD 请求会等 10s × 5 次重试，5 个引擎实例就是 4+ 分钟。
    同时设置 QT_QPA_PLATFORM=offscreen 支持 headless 环境（无显示服务器）下 PyQt 实例化。
    """
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    yield


# ─────────────────────────── G1/G2/G3: AppEngine 冒烟（不依赖 PyQt） ───────────────────────────

class TestG1G2G3AppEngineSmoke:
    """隔离临时数据目录，真实创建 AppEngine 跑 initialize"""

    def _make_engine(self, tmp_path, monkeypatch):
        """辅助：设置 SCAI_DATA_DIR 并创建 AppEngine（用完记得关 scheduler）"""
        data_dir = Path(tmp_path) / "scai_data"
        data_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("SCAI_DATA_DIR", str(data_dir))

        from aibridge.app_engine import AppEngine
        engine = AppEngine()
        return engine, data_dir

    def test_G1_initialize_returns_bool_and_no_exception(self, tmp_path, monkeypatch):
        """G1: AppEngine.initialize() 不抛异常，返回 bool"""
        engine, _ = self._make_engine(tmp_path, monkeypatch)
        try:
            ok = engine.initialize()
        finally:
            # 清理：停止 ScheduleManager
            try:
                sched = getattr(engine, "_schedule_manager", None)
                if sched and hasattr(sched, "stop"):
                    sched.stop()
            except Exception:
                pass

        assert isinstance(ok, bool), f"initialize() 返回值类型={type(ok).__name__}, 期望 bool"

    def test_G2_is_initialized_and_degraded_details_jsonable(self, tmp_path, monkeypatch):
        """G2: is_initialized() 返回 bool；get_degraded_details() 返回 list 可 JSON 序列化"""
        engine, _ = self._make_engine(tmp_path, monkeypatch)
        try:
            engine.initialize()

            is_init = engine.is_initialized()
            assert isinstance(is_init, bool), "is_initialized() 必须返回 bool"

            details = engine.get_degraded_details()
            assert isinstance(details, list), f"get_degraded_details() 必须返回 list，实际={type(details).__name__}"

            # 尝试 JSON 序列化（确保没有 PyQt 对象 / 不可序列化对象）
            try:
                json.dumps(details, ensure_ascii=False)
            except (TypeError, ValueError) as e:
                pytest.fail(f"get_degraded_details() 不可 JSON 序列化: {e}")
        finally:
            try:
                sched = getattr(engine, "_schedule_manager", None)
                if sched and hasattr(sched, "stop"):
                    sched.stop()
            except Exception:
                pass

    def test_G3_process_message_returns_dict_with_content_and_is_aigc(self, tmp_path, monkeypatch):
        """G3: process_message 返回 dict，含 content(str) + is_aigc 字段（LLM 无 Key 时降级不崩）"""
        engine, _ = self._make_engine(tmp_path, monkeypatch)
        try:
            engine.initialize()

            result = engine.process_message(
                user_input="你好",
                session_id="smoke_test_session_001",
            )

            assert isinstance(result, dict), f"process_message 必须返回 dict，实际={type(result).__name__}"
            assert "content" in result, f"result 必须含 'content' 字段，keys={list(result.keys())}"
            assert isinstance(result["content"], str), f"content 必须为 str，实际={type(result['content']).__name__}"
            assert "is_aigc" in result, f"result 必须含 'is_aigc' 字段，keys={list(result.keys())}"

            # LLM 无 Key 时 content 不应为空（应该有降级提示）
            assert len(result["content"]) > 0, "content 不应为空（LLM 无 Key 时应返回降级提示）"
        finally:
            try:
                sched = getattr(engine, "_schedule_manager", None)
                if sched and hasattr(sched, "stop"):
                    sched.stop()
            except Exception:
                pass


# ─────────────────────────── G4/G5/G6/G7: MainWindow 冒烟（需 QApplication） ───────────────────────────

@pytest.fixture
def qapp():
    """本地 qapp fixture：如果 pytest-qt 未安装，自动创建 QApplication。
    设置 QT_QPA_PLATFORM=offscreen 支持 headless 环境。
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


class TestG4G5G6G7MainWindowSmoke:
    """需要 QApplication（通过本地 qapp fixture 提供）"""

    @pytest.fixture
    def _engine(self, tmp_path, monkeypatch, qapp):
        """创建并初始化 AppEngine，yield 后关闭 scheduler"""
        data_dir = Path(tmp_path) / "scai_data"
        data_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("SCAI_DATA_DIR", str(data_dir))

        from aibridge.app_engine import AppEngine
        engine = AppEngine()
        engine.initialize()
        yield engine
        try:
            sched = getattr(engine, "_schedule_manager", None)
            if sched and hasattr(sched, "stop"):
                sched.stop()
        except Exception:
            pass

    def test_G4_main_window_instantiation_no_crash(self, _engine, qapp):
        """G4: MainWindow(engine) 实例化不崩溃"""
        from aibridge.ui.main_window import MainWindow
        try:
            window = MainWindow(_engine)
            assert window is not None
            # 立即清理
            try:
                window._stop_auto_refresh_timer()
            except Exception:
                pass
            window.close()
            del window
        except Exception as e:
            pytest.fail(f"MainWindow 实例化崩溃: {e}")

    def test_G5_degraded_banner_and_pages_count(self, _engine, qapp):
        """G5: degraded_banner 非 None；len(_pages) == len(PAGE_ORDER)"""
        from aibridge.ui.main_window import MainWindow, PAGE_ORDER
        window = MainWindow(_engine)
        try:
            assert hasattr(window, "degraded_banner"), "MainWindow 必须有 degraded_banner 属性"
            assert window.degraded_banner is not None, "degraded_banner 不能为 None"

            assert hasattr(window, "_pages"), "MainWindow 必须有 _pages 属性"
            assert len(window._pages) == len(PAGE_ORDER), (
                f"_pages 数量不匹配: 期望 {len(PAGE_ORDER)}, 实际 {len(window._pages)}. "
                f"PAGE_ORDER={PAGE_ORDER}"
            )
        finally:
            try:
                window._stop_auto_refresh_timer()
            except Exception:
                pass
            window.close()
            del window

    def test_G6_start_auto_refresh_timer_is_active(self, _engine, qapp):
        """G6: _start_auto_refresh_timer() 后 _auto_refresh_timer.isActive()=True"""
        from aibridge.ui.main_window import MainWindow
        window = MainWindow(_engine)
        try:
            # 先确保停止（__init__ 里可能延迟 1500ms 后才启动，但还没到时间，所以手动启动一次）
            window._stop_auto_refresh_timer()
            # 显式启动
            window._start_auto_refresh_timer()

            timer = getattr(window, "_auto_refresh_timer", None)
            assert timer is not None, "_auto_refresh_timer 不能为 None（启动失败）"
            assert timer.isActive() is True, "_auto_refresh_timer.isActive() 必须为 True"
        finally:
            try:
                window._stop_auto_refresh_timer()
            except Exception:
                pass
            window.close()
            del window

    def test_G7_stop_close_del_no_exception(self, _engine, qapp):
        """G7: stop → close → del 顺序不抛异常"""
        from aibridge.ui.main_window import MainWindow
        window = MainWindow(_engine)
        window._start_auto_refresh_timer()

        try:
            # stop
            window._stop_auto_refresh_timer()
            # close
            window.close()
            # del（捕获外层异常）
            ref = window
            del ref
        except Exception as e:
            pytest.fail(f"stop → close → del 抛异常: {e}")


# ─────────────────────────── G8: OACloudService.auto_bootstrap 冒烟 ───────────────────────────

class TestG8OACloudBootstrapSmoke:
    def test_G8_oa_auto_bootstrap_no_exception_and_not_none(self, tmp_path, monkeypatch):
        """G8: OACloudService.auto_bootstrap(cfg_minimal) 在临时目录下不崩，service 非 None（允许 degraded）"""
        data_dir = Path(tmp_path) / "oa_data"
        data_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("SCAI_DATA_DIR", str(data_dir))

        from aibridge.oa_service.app import OACloudService

        cfg = {
            "kb_root": str(data_dir / "wiki"),
            "persona_file": str(data_dir / "persona.md"),
            "llm_base_url": "https://api.deepseek.com/v1",
            "llm_model": "deepseek-chat",
            "llm_api_key": "",  # 空 Key → degraded，合法
            "kb_enabled": True,
            "oa_token": "",
            "oa_aes_key": "",
            "oa_app_id": "",
            "oa_app_secret": "",
        }

        try:
            service = OACloudService.auto_bootstrap(cfg)
        except Exception as e:
            pytest.fail(f"OACloudService.auto_bootstrap 抛异常（不允许）: {e}")

        assert service is not None, (
            "auto_bootstrap 不能返回 None（即使 degraded，也必须返回 NullOAService 伪对象）"
        )
