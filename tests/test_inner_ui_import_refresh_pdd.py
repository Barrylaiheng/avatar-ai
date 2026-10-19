# -*- coding: utf-8 -*-
"""
SCAI PDD 模块 22+23 · UI 文档导入 + BadCase 异步刷新 pytest 用例

验证 ImportDocumentWorker 和 GetBadCasesWorker 的 sync_run 纯函数接口，
以及 KnowledgePage / IterationPage 信号/方法的存在性。
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

_TEST_DATA_ROOT = tempfile.mkdtemp(prefix="scai_m22_23_pytest_")
os.environ.setdefault("SCAI_DATA_DIR", _TEST_DATA_ROOT)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


# ============== M-22: ImportDocumentWorker ==============

class TestM22ImportDocumentWorker:
    def test_sync_run_imports_txt_file(self, tmp_path):
        """M-22 G1: sync_run 成功导入 TXT 文件"""
        from aibridge.ui.ui_engine_bridge import ImportDocumentWorker

        wiki_root = tmp_path / "wiki"
        for sub in ("concepts", "entities", "architecture"):
            (wiki_root / sub).mkdir(parents=True, exist_ok=True)
        (wiki_root / "log.md").write_text("---\ntype: log\n---\n\n# Log\n", encoding="utf-8")

        txt_file = tmp_path / "test.txt"
        txt_file.write_text("这是测试内容。", encoding="utf-8")

        mock_engine = MagicMock()
        mock_engine._config = {"kb.wiki_root": str(wiki_root)}

        ok, result, signals = ImportDocumentWorker.sync_run(mock_engine, str(txt_file), "entities")
        assert ok is True
        assert "imported" in signals
        path, count = signals["imported"]
        assert count >= 1
        assert os.path.exists(path)

    def test_sync_run_nonexistent_file_returns_error(self, tmp_path):
        """M-22 G2: 不存在的文件返回 error"""
        from aibridge.ui.ui_engine_bridge import ImportDocumentWorker

        mock_engine = MagicMock()
        mock_engine._config = {"kb.wiki_root": str(tmp_path / "wiki")}

        ok, result, signals = ImportDocumentWorker.sync_run(mock_engine, "/nonexistent.pdf", "entities")
        assert ok is False
        assert "error" in signals
        assert "不存在" in signals["error"] or "not exist" in signals["error"].lower()


# ============== M-22: KnowledgePage 信号/按钮 ==============

class TestM22KnowledgePageUI:
    def test_import_requested_signal_exists(self):
        """M-22 G3: KnowledgePage 有 import_requested 信号"""
        # 不实例化（需要 Qt），只检查类属性
        from aibridge.ui.knowledge_page import KnowledgePage
        assert hasattr(KnowledgePage, "import_requested"), \
            "KnowledgePage 必须有 import_requested 信号"

    def test_on_import_method_exists(self):
        """M-22 G4: KnowledgePage 有 _on_import 方法"""
        from aibridge.ui.knowledge_page import KnowledgePage
        assert hasattr(KnowledgePage, "_on_import"), \
            "KnowledgePage 必须有 _on_import 方法"


# ============== M-22: UIEngineBridge Facade ==============

class TestM22BridgeFacade:
    def test_start_import_document_method_exists(self):
        """M-22 G5: UIEngineBridge 有 start_import_document 方法"""
        from aibridge.ui.ui_engine_bridge import UIEngineBridge
        assert hasattr(UIEngineBridge, "start_import_document"), \
            "UIEngineBridge 必须有 start_import_document 方法"


# ============== M-23: GetBadCasesWorker ==============

class TestM23GetBadCasesWorker:
    def test_sync_run_returns_list(self):
        """M-23 G1: sync_run 返回 BadCase 列表"""
        from aibridge.ui.ui_engine_bridge import GetBadCasesWorker

        mock_engine = MagicMock()
        mock_engine.get_bad_cases.return_value = [
            {"case_id": "bc1", "user_input": "你好", "ai_response": "回复"},
        ]

        ok, result, signals = GetBadCasesWorker.sync_run(mock_engine, limit=10)
        assert ok is True
        assert "loaded" in signals
        assert len(signals["loaded"]) == 1
        assert signals["loaded"][0]["case_id"] == "bc1"

    def test_sync_run_exception_returns_error(self):
        """M-23 G2: engine 抛异常时返回 error 不崩"""
        from aibridge.ui.ui_engine_bridge import GetBadCasesWorker

        mock_engine = MagicMock()
        mock_engine.get_bad_cases.side_effect = RuntimeError("DB error")

        ok, result, signals = GetBadCasesWorker.sync_run(mock_engine, limit=10)
        assert ok is False
        assert "error" in signals
        assert "DB error" in signals["error"]

    def test_sync_run_non_list_returns_empty(self):
        """M-23 G3: engine 返回非 list 时安全降级为空列表"""
        from aibridge.ui.ui_engine_bridge import GetBadCasesWorker

        mock_engine = MagicMock()
        mock_engine.get_bad_cases.return_value = None

        ok, result, signals = GetBadCasesWorker.sync_run(mock_engine, limit=10)
        assert ok is True
        assert signals["loaded"] == []


# ============== M-23: IterationPage 信号/按钮 ==============

class TestM23IterationPageUI:
    def test_refresh_requested_signal_exists(self):
        """M-23 G4: IterationPage 有 refresh_requested 信号"""
        from aibridge.ui.iteration_page import IterationPage
        assert hasattr(IterationPage, "refresh_requested"), \
            "IterationPage 必须有 refresh_requested 信号"

    def test_on_refresh_method_exists(self):
        """M-23 G5: IterationPage 有 _on_refresh 方法"""
        from aibridge.ui.iteration_page import IterationPage
        assert hasattr(IterationPage, "_on_refresh"), \
            "IterationPage 必须有 _on_refresh 方法"


# ============== M-23: UIEngineBridge Facade ==============

class TestM23BridgeFacade:
    def test_start_get_bad_cases_method_exists(self):
        """M-23 G6: UIEngineBridge 有 start_get_bad_cases 方法"""
        from aibridge.ui.ui_engine_bridge import UIEngineBridge
        assert hasattr(UIEngineBridge, "start_get_bad_cases"), \
            "UIEngineBridge 必须有 start_get_bad_cases 方法"


# ============== M-22+M-23: main_window 桥接 ==============

class TestMainWindowBridging:
    def test_on_knowledge_import_method_exists(self):
        """M-22 G6: MainWindow 有 _on_knowledge_import 方法"""
        from aibridge.ui.main_window import MainWindow
        assert hasattr(MainWindow, "_on_knowledge_import"), \
            "MainWindow 必须有 _on_knowledge_import 方法"

    def test_on_iteration_refresh_method_exists(self):
        """M-23 G7: MainWindow 有 _on_iteration_refresh 方法"""
        from aibridge.ui.main_window import MainWindow
        assert hasattr(MainWindow, "_on_iteration_refresh"), \
            "MainWindow 必须有 _on_iteration_refresh 方法"

    def test_on_iteration_badcases_loaded_method_exists(self):
        """M-23 G8: MainWindow 有 _on_iteration_badcases_loaded 方法"""
        from aibridge.ui.main_window import MainWindow
        assert hasattr(MainWindow, "_on_iteration_badcases_loaded"), \
            "MainWindow 必须有 _on_iteration_badcases_loaded 回调方法"
