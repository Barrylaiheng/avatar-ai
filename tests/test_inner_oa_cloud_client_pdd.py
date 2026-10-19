# -*- coding: utf-8 -*-
"""
SCAI PDD 模块 21 · 桌面端拉取云端 BadCase HTTP Client pytest 用例

覆盖 10 条 Grill（G1-G10）。
验证 OACloudClient 的拉取/降级/健康检查，以及 AppEngine 的本地+云端合并逻辑。
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch, Mock

import pytest

_TEST_DATA_ROOT = tempfile.mkdtemp(prefix="scai_m21_pytest_")
os.environ.setdefault("SCAI_DATA_DIR", _TEST_DATA_ROOT)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


# ============== G1: OACloudClient 可实例化 ==============

class TestG1ClientInstantiation:
    def test_client_created_with_url_and_token(self):
        """G1: OACloudClient 可用 base_url + api_token 实例化"""
        from aibridge.oa_cloud_client import OACloudClient
        client = OACloudClient(base_url="https://oa.example.com", api_token="tok123")
        assert client.is_configured is True
        assert client._base_url == "https://oa.example.com"
        assert client._api_token == "tok123"

    def test_client_empty_url_not_configured(self):
        """G1a: base_url 为空时 is_configured=False"""
        from aibridge.oa_cloud_client import OACloudClient
        client = OACloudClient(base_url="", api_token="")
        assert client.is_configured is False


# ============== G2: 未配置时 pull_badcases 返回空 ==============

class TestG2NotConfiguredReturnsEmpty:
    def test_pull_badcases_empty_when_not_configured(self):
        """G2: 未配置 base_url 时 pull_badcases 返回空列表不崩"""
        from aibridge.oa_cloud_client import OACloudClient
        client = OACloudClient(base_url="")
        cases = client.pull_badcases(limit=10)
        assert cases == []
        assert "未配置" in client.last_error


# ============== G3: 正常拉取 ==============

class TestG3NormalPull:
    def test_pull_badcases_success(self):
        """G3: 正常 HTTP 200 返回 BadCase 列表"""
        from aibridge.oa_cloud_client import OACloudClient

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "count": 2,
            "cases": [
                {"question": "你好", "reply": "AI配置中", "reasons": ["no_key"], "type": "fallback"},
                {"question": "价格", "reply": "请稍后", "reasons": ["48h_timeout"], "type": "timeout"},
            ],
        }

        with patch("aibridge.oa_cloud_client.requests") as mock_req:
            mock_req.get.return_value = mock_response
            mock_req.exceptions.Timeout = Exception
            mock_req.exceptions.ConnectionError = Exception

            client = OACloudClient(base_url="https://oa.example.com", api_token="tok")
            cases = client.pull_badcases(limit=50)

        assert len(cases) == 2
        assert cases[0]["question"] == "你好"
        assert client.last_pull_count == 2
        assert client.last_error == ""


# ============== G4: HTTP 错误返回空 ==============

class TestG4HttpErrorReturnsEmpty:
    def test_http_500_returns_empty(self):
        """G4: HTTP 500 时返回空列表"""
        from aibridge.oa_cloud_client import OACloudClient

        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch("aibridge.oa_cloud_client.requests") as mock_req:
            mock_req.get.return_value = mock_response
            mock_req.exceptions.Timeout = Exception
            mock_req.exceptions.ConnectionError = Exception

            client = OACloudClient(base_url="https://oa.example.com")
            cases = client.pull_badcases(limit=10)

        assert cases == []
        assert "500" in client.last_error


# ============== G5: 超时不崩 ==============

class TestG5TimeoutNoCrash:
    def test_timeout_returns_empty(self):
        """G5: 请求超时返回空列表不崩"""
        from aibridge.oa_cloud_client import OACloudClient

        with patch("aibridge.oa_cloud_client.requests") as mock_req:
            mock_req.exceptions.Timeout = type("Timeout", (Exception,), {})
            mock_req.exceptions.ConnectionError = type("ConnectionError", (Exception,), {})
            mock_req.get.side_effect = mock_req.exceptions.Timeout("timed out")

            client = OACloudClient(base_url="https://oa.example.com", timeout=1.0)
            cases = client.pull_badcases(limit=10)

        assert cases == []
        assert "超时" in client.last_error


# ============== G6: 连接失败不崩 ==============

class TestG6ConnectionErrorNoCrash:
    def test_connection_error_returns_empty(self):
        """G6: 连接失败返回空列表不崩"""
        from aibridge.oa_cloud_client import OACloudClient

        with patch("aibridge.oa_cloud_client.requests") as mock_req:
            mock_req.exceptions.Timeout = type("Timeout", (Exception,), {})
            mock_req.exceptions.ConnectionError = type("ConnectionError", (Exception,), {})
            mock_req.get.side_effect = mock_req.exceptions.ConnectionError("refused")

            client = OACloudClient(base_url="https://oa.example.com")
            cases = client.pull_badcases(limit=10)

        assert cases == []
        assert "连接" in client.last_error or "refused" in client.last_error


# ============== G7: API Token 在请求头中 ==============

class TestG7ApiTokenInHeader:
    def test_api_token_sent_in_header(self):
        """G7: 请求头中包含 API Token"""
        from aibridge.oa_cloud_client import OACloudClient

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"count": 0, "cases": []}

        with patch("aibridge.oa_cloud_client.requests") as mock_req:
            mock_req.get.return_value = mock_response
            mock_req.exceptions.Timeout = Exception
            mock_req.exceptions.ConnectionError = Exception

            client = OACloudClient(base_url="https://oa.example.com", api_token="secret_token_123")
            client.pull_badcases(limit=5)

            call_kwargs = mock_req.get.call_args
            headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
            assert headers.get("X-API-Token") == "secret_token_123" or \
                   headers.get("Authorization") == "Bearer secret_token_123"


# ============== G8: health_check 在线判断 ==============

class TestG8HealthCheck:
    def test_health_check_200_returns_true(self):
        """G8: health_check 返回 200 时在线"""
        from aibridge.oa_cloud_client import OACloudClient

        mock_response = Mock()
        mock_response.status_code = 200

        with patch("aibridge.oa_cloud_client.requests") as mock_req:
            mock_req.get.return_value = mock_response
            mock_req.exceptions.Timeout = Exception
            mock_req.exceptions.ConnectionError = Exception

            client = OACloudClient(base_url="https://oa.example.com")
            assert client.health_check() is True

    def test_health_check_403_returns_true(self):
        """G8a: health_check 返回 403（签名错误但服务在线）也算在线"""
        from aibridge.oa_cloud_client import OACloudClient

        mock_response = Mock()
        mock_response.status_code = 403

        with patch("aibridge.oa_cloud_client.requests") as mock_req:
            mock_req.get.return_value = mock_response
            mock_req.exceptions.Timeout = Exception
            mock_req.exceptions.ConnectionError = Exception

            client = OACloudClient(base_url="https://oa.example.com")
            assert client.health_check() is True

    def test_health_check_connection_error_returns_false(self):
        """G8b: health_check 连接失败时返回 False"""
        from aibridge.oa_cloud_client import OACloudClient

        with patch("aibridge.oa_cloud_client.requests") as mock_req:
            mock_req.exceptions.Timeout = type("Timeout", (Exception,), {})
            mock_req.exceptions.ConnectionError = type("ConnectionError", (Exception,), {})
            mock_req.get.side_effect = mock_req.exceptions.ConnectionError("refused")

            client = OACloudClient(base_url="https://oa.example.com")
            assert client.health_check() is False


# ============== G9: get_stats 返回状态信息 ==============

class TestG9GetStats:
    def test_get_stats_returns_dict(self):
        """G9: get_stats 返回包含必要字段的字典"""
        from aibridge.oa_cloud_client import OACloudClient
        client = OACloudClient(base_url="https://oa.example.com", api_token="tok")
        stats = client.get_stats()
        assert "is_configured" in stats
        assert "base_url" in stats
        assert "last_pull_count" in stats
        assert "last_error" in stats
        assert stats["is_configured"] is True
        assert stats["base_url"] == "https://oa.example.com"


# ============== G10: AppEngine 合并本地+云端 BadCase ==============

class TestG10AppEngineMerge:
    def test_get_bad_cases_merges_local_and_cloud(self):
        """G10: AppEngine.get_bad_cases 合并本地和云端 BadCase"""
        from aibridge.app_engine import AppEngine

        engine = AppEngine()
        engine._initialized = True

        # Mock 本地 iteration_engine
        local_bc = MagicMock()
        # P3-4 修复：BadCase.to_dict() 使用 created_at 字段（不是 timestamp）
        local_bc.to_dict.return_value = {
            "question": "本地问题", "reply": "本地回复",
            "created_at": "2026-08-13 00:01:00", "source": "local",
        }
        engine._iteration_engine = MagicMock()
        engine._iteration_engine.detector.get_badcases.return_value = [local_bc]

        # Mock 云端 client
        cloud_cases = [
            # 云端 created_at > 本地 → 合并后排前面
            {"question": "云端问题", "reply": "云端回复",
             "created_at": "2026-08-13 00:02:00", "source": "cloud"},
        ]
        engine._oa_cloud_client = MagicMock()
        engine._oa_cloud_client.is_configured = True
        engine._oa_cloud_client.pull_badcases.return_value = cloud_cases

        result = engine.get_bad_cases(limit=20)

        # 应合并 1 本地 + 1 云端 = 2 条
        assert len(result) == 2
        # 按 created_at 降序，云端（时间更新）应排在前面
        assert result[0].get("created_at", "") >= result[1].get("created_at", "")
        assert result[0]["source"] == "cloud", (
            f"云端 created_at 更新，应排第 1，实际: {result[0]}"
        )

    def test_get_bad_cases_cloud_unreachable_returns_local_only(self):
        """G10a: 云端不可达时只返回本地 BadCase"""
        from aibridge.app_engine import AppEngine

        engine = AppEngine()
        engine._initialized = True

        local_bc = MagicMock()
        local_bc.to_dict.return_value = {"question": "本地", "created_at": "2026-08-13 00:01:00"}
        engine._iteration_engine = MagicMock()
        engine._iteration_engine.detector.get_badcases.return_value = [local_bc]

        # 云端未配置
        engine._oa_cloud_client = None

        result = engine.get_bad_cases(limit=20)
        assert len(result) == 1
        assert result[0]["question"] == "本地"
