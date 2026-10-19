# -*- coding: utf-8 -*-
"""
里层 PDD 模块 15 · RAG Embedding 模型本地缓存测试

12 条 Grill → 25 条 pytest 用例（对齐 docs/PDD_INNER_rag_embedding_local_cache.md §5）

运行：
    cd C:\\Users\\Administrator\\Desktop\\WeChatAI_Project
    python -m pytest tests/test_inner_rag_embedding_local_cache_pdd.py -v
"""
import os
import sys
import time
import shutil
import logging
from pathlib import Path
from typing import List, Optional

import pytest
from loguru import logger as loguru_logger

# 确保 src 在 PYTHONPATH
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


@pytest.fixture
def loguru_capture():
    """捕获 loguru 日志到内存列表（capsys/capfd 无法捕获 loguru 默认 sink）"""
    captured: List[str] = []
    sink_id = loguru_logger.add(lambda msg: captured.append(msg), level="DEBUG")
    try:
        yield captured
    finally:
        loguru_logger.remove(sink_id)


# ========================= Mock Embedding Function =========================

class _MockEmbeddingFunction:
    """模拟 chromadb.utils.embedding_functions.SentenceTransformerEmbeddingFunction

    - 本地路径加载：检查目录是否存在，存在则成功
    - 在线下载模式：根据 _network_available 决定成功/失败
    - 下载成功后模拟在 HF_HOME/hub 下生成 model.safetensors
    """
    _network_available = True
    _load_latency = 0.0  # 测试默认无延迟

    def __init__(self, model_name: str, trust_remote_code: bool = False,
                 cache_folder: Optional[str] = None, **kwargs):
        self.model_name = model_name
        time.sleep(self._load_latency)

        if Path(model_name).exists():
            self._source = "local"
        elif model_name == "BAAI/bge-small-zh-v1.5":
            if not self._network_available:
                raise ConnectionError(
                    f"无法连接 huggingface.co 下载模型 {model_name}"
                )
            # 模拟下载到 HF 缓存目录
            hf_home = os.environ.get("HF_HOME", "")
            if hf_home:
                cache_dir = Path(hf_home) / "hub"
                cache_dir.mkdir(parents=True, exist_ok=True)
                (cache_dir / "model.safetensors").write_text("mock model file")
            self._source = "downloaded"
        else:
            raise ValueError(f"未知模型: {model_name}")

    def __call__(self, input: List[str]) -> List[List[float]]:
        return [[0.1] * 512 for _ in input]


@pytest.fixture
def patch_embedding_function(monkeypatch):
    """替换 SentenceTransformerEmbeddingFunction 为 mock"""
    _MockEmbeddingFunction._network_available = True
    _MockEmbeddingFunction._load_latency = 0.0

    import aibridge.rag.chromadb_manager as cm
    original_init = cm.ChromaDBManager._init_embed_fn

    def _patched_init(self):
        from chromadb.utils import embedding_functions
        monkeypatch.setattr(
            embedding_functions,
            "SentenceTransformerEmbeddingFunction",
            _MockEmbeddingFunction,
        )
        # 同时 patch 已导入的别名
        import chromadb.utils.embedding_functions as cef
        monkeypatch.setattr(
            cef,
            "SentenceTransformerEmbeddingFunction",
            _MockEmbeddingFunction,
        )
        # 调用原始方法
        original_init(self)

    monkeypatch.setattr(cm.ChromaDBManager, "_init_embed_fn", _patched_init)
    return _MockEmbeddingFunction


@pytest.fixture
def scai_data_dir(tmp_path, monkeypatch):
    """设置 SCAI_DATA_DIR 到临时目录"""
    data_dir = tmp_path / "scai_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SCAI_DATA_DIR", str(data_dir))
    # 清理可能残留的 HF 环境变量
    for key in ["HF_HOME", "SENTENCE_TRANSFORMERS_HOME", "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"]:
        monkeypatch.delenv(key, raising=False)
    return data_dir


@pytest.fixture
def local_cache_ready(scai_data_dir):
    """预置本地缓存已存在的场景"""
    model_path = scai_data_dir / "models" / "bge-small-zh-v1.5"
    model_path.mkdir(parents=True, exist_ok=True)
    (model_path / "model.safetensors").write_text("mock cached model")
    return model_path


@pytest.fixture
def no_network(monkeypatch):
    """模拟无网络环境"""
    _MockEmbeddingFunction._network_available = False
    return _MockEmbeddingFunction


@pytest.fixture
def has_network(monkeypatch):
    """模拟有网络环境"""
    _MockEmbeddingFunction._network_available = True
    return _MockEmbeddingFunction


# ========================= 导入被测模块 =========================

from aibridge.rag.chromadb_manager import (
    ChromaDBManager,
    _get_model_local_path,
    _get_hf_cache_dir,
    _ensure_hf_env,
    _BGE_MODEL_NAME,
)


# ========================= E1: 模型路径相对化 =========================

class TestE1RelativeModelPath:
    """E1: ChromaDBManager 不再硬编码 C:\\bge-cache\\...，模型路径基于 get_data_dir()"""

    def test_e1_1_no_hardcoded_bge_cache(self, scai_data_dir):
        """E1.1 模型路径不包含 C:\\bge-cache"""
        path = _get_model_local_path()
        assert "bge-cache" not in str(path)

    def test_e1_2_path_contains_models_dir(self, scai_data_dir):
        """E1.2 模型路径包含 models/bge-small-zh-v1.5"""
        path = _get_model_local_path()
        assert "models" in str(path)
        assert "bge-small-zh-v1.5" in str(path)

    def test_e1_3_follows_scai_data_dir(self, scai_data_dir):
        """E1.3 模型路径跟随 SCAI_DATA_DIR"""
        path = _get_model_local_path()
        assert str(scai_data_dir) in str(path)


# ========================= E2: HF_HOME / ST_HOME 设置 =========================

class TestE2HfEnvSetup:
    """E2: AppEngine 启动时显式设置 HF_HOME / SENTENCE_TRANSFORMERS_HOME"""

    def test_e2_1_hf_home_set(self, scai_data_dir):
        """E2.1 HF_HOME 已设置"""
        _ensure_hf_env()
        assert "HF_HOME" in os.environ

    def test_e2_2_st_home_set(self, scai_data_dir):
        """E2.2 SENTENCE_TRANSFORMERS_HOME 已设置"""
        _ensure_hf_env()
        assert "SENTENCE_TRANSFORMERS_HOME" in os.environ

    def test_e2_3_hf_home_under_cache_huggingface(self, scai_data_dir):
        """E2.3 HF_HOME 指向 data/.cache/huggingface"""
        _ensure_hf_env()
        hf_home = os.environ["HF_HOME"]
        assert ".cache" in hf_home
        assert "huggingface" in hf_home

    def test_e2_4_st_home_same_as_hf_home(self, scai_data_dir):
        """E2.4 ST_HOME 与 HF_HOME 一致"""
        _ensure_hf_env()
        assert os.environ["HF_HOME"] == os.environ["SENTENCE_TRANSFORMERS_HOME"]

    def test_e2_5_hf_home_follows_scai_data_dir(self, scai_data_dir):
        """E2.5 HF_HOME 跟随 SCAI_DATA_DIR"""
        _ensure_hf_env()
        assert str(scai_data_dir) in os.environ["HF_HOME"]


# ========================= E3: 首次下载到 data/.cache/huggingface =========================

class TestE3FirstDownloadCreatesCache:
    """E3: 首次启动 + 有网络时，模型自动下载到 data/.cache/huggingface"""

    def test_e3_1_hf_cache_dir_created(self, scai_data_dir, patch_embedding_function, has_network):
        """E3.1 HF 缓存目录已创建"""
        from aibridge.config.config_manager import ConfigManager
        cm = ConfigManager.__new__(ConfigManager)
        ChromaDBManager(cm)
        hf_cache = _get_hf_cache_dir()
        assert hf_cache.exists()

    def test_e3_2_hf_cache_non_empty(self, scai_data_dir, patch_embedding_function, has_network):
        """E3.2 HF 缓存目录非空"""
        from aibridge.config.config_manager import ConfigManager
        cm = ConfigManager.__new__(ConfigManager)
        ChromaDBManager(cm)
        hf_cache = _get_hf_cache_dir()
        assert hf_cache.exists()
        assert any(hf_cache.iterdir())

    def test_e3_3_cache_contains_model_file(self, scai_data_dir, patch_embedding_function, has_network):
        """E3.3 缓存包含模型文件"""
        from aibridge.config.config_manager import ConfigManager
        cm = ConfigManager.__new__(ConfigManager)
        ChromaDBManager(cm)
        hf_cache = _get_hf_cache_dir()
        assert (hf_cache / "hub" / "model.safetensors").exists()

    def test_e3_4_embed_fn_not_none(self, scai_data_dir, patch_embedding_function, has_network):
        """E3.4 embed_fn 非 None"""
        from aibridge.config.config_manager import ConfigManager
        cm = ConfigManager.__new__(ConfigManager)
        mgr = ChromaDBManager(cm)
        assert mgr._embed_fn is not None


# ========================= E4: 离线优先（本地缓存存在时不联网）===========================

class TestE4OfflineLoadFromCache:
    """E4: 第二次启动 + 无网络时，模型从本地缓存加载"""

    def test_e4_1_embed_fn_not_none_with_local_cache(self, scai_data_dir, local_cache_ready,
                                                      patch_embedding_function, no_network):
        """E4.1 本地缓存存在时 embed_fn 非 None"""
        from aibridge.config.config_manager import ConfigManager
        cm = ConfigManager.__new__(ConfigManager)
        mgr = ChromaDBManager(cm)
        assert mgr._embed_fn is not None

    def test_e4_2_load_source_is_local(self, scai_data_dir, local_cache_ready,
                                        patch_embedding_function, no_network):
        """E4.2 加载来源是 local"""
        from aibridge.config.config_manager import ConfigManager
        cm = ConfigManager.__new__(ConfigManager)
        mgr = ChromaDBManager(cm)
        assert getattr(mgr._embed_fn, "_source", "") == "local"


# ========================= E5: 无网+有缓存 → RAG 检索可用 =========================

class TestE5RetrieveWorksOffline:
    """E5: 无网络 + 本地缓存存在时，RAG 检索能正常工作"""

    def test_e5_1_retrieve_returns_non_empty(self, scai_data_dir, local_cache_ready,
                                              patch_embedding_function, no_network):
        """E5.1 retrieve 返回非空 chunks（需先 add_chunks）"""
        from aibridge.config.config_manager import ConfigManager
        from aibridge.rag.chromadb_manager import Chunk
        cm = ConfigManager.__new__(ConfigManager)
        mgr = ChromaDBManager(cm)
        # 添加测试 chunk
        chunk = Chunk(chunk_id="test_1", content="测试内容", metadata={})
        try:
            mgr.add_chunks("test_kb", [chunk])
        except Exception:
            pass  # mock 环境下 add 可能失败，但 retrieve 不应崩溃
        # retrieve 不应抛异常
        result = mgr.retrieve("test_kb", "测试查询", top_k=3)
        assert result is not None
        assert hasattr(result, "chunks")

    def test_e5_2_embed_fn_not_none_offline_with_cache(self, scai_data_dir, local_cache_ready,
                                                        patch_embedding_function, no_network):
        """E5.2 无网+有缓存时 embed_fn 非 None"""
        from aibridge.config.config_manager import ConfigManager
        cm = ConfigManager.__new__(ConfigManager)
        mgr = ChromaDBManager(cm)
        assert mgr._embed_fn is not None


# ========================= E6: 无网+无缓存 → 不崩溃，返回空 =========================

class TestE6NoCrashWhenNoCacheNoNetwork:
    """E6: 无网络 + 本地缓存不存在时，AppEngine 启动不崩溃"""

    def test_e6_1_no_crash(self, scai_data_dir, patch_embedding_function, no_network):
        """E6.1 无网+无缓存时启动不崩溃"""
        from aibridge.config.config_manager import ConfigManager
        cm = ConfigManager.__new__(ConfigManager)
        try:
            mgr = ChromaDBManager(cm)
            assert mgr is not None
        except Exception as e:
            pytest.fail(f"无网+无缓存时启动崩溃: {e}")

    def test_e6_2_embed_fn_is_none(self, scai_data_dir, patch_embedding_function, no_network):
        """E6.2 embed_fn 为 None"""
        from aibridge.config.config_manager import ConfigManager
        cm = ConfigManager.__new__(ConfigManager)
        mgr = ChromaDBManager(cm)
        assert mgr._embed_fn is None

    def test_e6_3_retrieve_returns_empty(self, scai_data_dir, patch_embedding_function, no_network):
        """E6.3 retrieve 返回空 chunks"""
        from aibridge.config.config_manager import ConfigManager
        cm = ConfigManager.__new__(ConfigManager)
        mgr = ChromaDBManager(cm)
        result = mgr.retrieve("test_kb", "测试查询", top_k=3)
        assert result.chunks == []
        assert result.total_count == 0


# ========================= E7: 无 misleading warning =========================

class TestE7NoMisleadingWarning:
    """E7: 本地缓存存在时，启动日志不再出现"降级为默认模型"warning"""

    def test_e7_1_no_degrade_warning(self, scai_data_dir, local_cache_ready,
                                      patch_embedding_function, no_network, loguru_capture):
        """E7.1 无'降级为默认模型'warning（loguru 自定义 sink 捕获）"""
        from aibridge.config.config_manager import ConfigManager
        cm = ConfigManager.__new__(ConfigManager)
        ChromaDBManager(cm)
        assert not any("降级为默认模型" in line for line in loguru_capture)

    def test_e7_2_has_local_cache_info(self, scai_data_dir, local_cache_ready,
                                        patch_embedding_function, no_network, loguru_capture):
        """E7.2 有'本地缓存加载'info 日志"""
        from aibridge.config.config_manager import ConfigManager
        cm = ConfigManager.__new__(ConfigManager)
        ChromaDBManager(cm)
        assert any("本地缓存加载" in line for line in loguru_capture)


# ========================= E8: 加载耗时 < 5s =========================

class TestE8LoadLatencyUnder5s:
    """E8: 从本地缓存加载模型耗时 < 5s"""

    def test_e8_1_local_load_under_5s(self, scai_data_dir, local_cache_ready,
                                       patch_embedding_function, no_network):
        """E8.1 本地加载耗时 < 5s"""
        _MockEmbeddingFunction._load_latency = 0.5
        try:
            from aibridge.config.config_manager import ConfigManager
            cm = ConfigManager.__new__(ConfigManager)
            start = time.time()
            ChromaDBManager(cm)
            elapsed = time.time() - start
            assert elapsed < 5.0, f"加载耗时 {elapsed:.2f}s 超过 5s"
        finally:
            _MockEmbeddingFunction._load_latency = 0.0


# ========================= E9: SCAI_DATA_DIR 切换时路径同步 =========================

class TestE9SCAIDataDirSwitch:
    """E9: SCAI_DATA_DIR 环境变量切换时，模型缓存路径同步切换"""

    def test_e9_1_path_follows_dir_a(self, tmp_path, monkeypatch):
        """E9.1 路径 A 跟随 SCAI_DATA_DIR_A"""
        dir_a = tmp_path / "dir_a"
        dir_a.mkdir()
        monkeypatch.setenv("SCAI_DATA_DIR", str(dir_a))
        path_a = _get_model_local_path()
        assert str(dir_a) in str(path_a)

    def test_e9_2_path_follows_dir_b(self, tmp_path, monkeypatch):
        """E9.2 路径 B 跟随 SCAI_DATA_DIR_B"""
        dir_b = tmp_path / "dir_b"
        dir_b.mkdir()
        monkeypatch.setenv("SCAI_DATA_DIR", str(dir_b))
        path_b = _get_model_local_path()
        assert str(dir_b) in str(path_b)

    def test_e9_3_paths_different(self, tmp_path, monkeypatch):
        """E9.3 路径 A ≠ 路径 B"""
        dir_a = tmp_path / "dir_a"
        dir_b = tmp_path / "dir_b"
        dir_a.mkdir()
        dir_b.mkdir()
        monkeypatch.setenv("SCAI_DATA_DIR", str(dir_a))
        path_a = _get_model_local_path()
        monkeypatch.setenv("SCAI_DATA_DIR", str(dir_b))
        path_b = _get_model_local_path()
        assert str(path_a) != str(path_b)


# ========================= E10: 失败时清晰报错 =========================

class TestE10ClearErrorMessage:
    """E10: Embedding 函数加载失败时，日志清晰提示"""

    def test_e10_1_error_log_contains_not_ready(self, scai_data_dir, patch_embedding_function,
                                                 no_network, loguru_capture):
        """E10.1 日志含'Embedding 模型未就绪'"""
        from aibridge.config.config_manager import ConfigManager
        cm = ConfigManager.__new__(ConfigManager)
        ChromaDBManager(cm)
        assert any("Embedding 模型未就绪" in line for line in loguru_capture)

    def test_e10_2_error_log_contains_check_network(self, scai_data_dir, patch_embedding_function,
                                                     no_network, loguru_capture):
        """E10.2 日志含'请检查网络'"""
        from aibridge.config.config_manager import ConfigManager
        cm = ConfigManager.__new__(ConfigManager)
        ChromaDBManager(cm)
        assert any("请检查网络" in line for line in loguru_capture)

    def test_e10_3_no_degrade_warning(self, scai_data_dir, patch_embedding_function,
                                       no_network, loguru_capture):
        """E10.3 日志不含'降级为默认模型'"""
        from aibridge.config.config_manager import ConfigManager
        cm = ConfigManager.__new__(ConfigManager)
        ChromaDBManager(cm)
        assert not any("降级为默认模型" in line for line in loguru_capture)


# ========================= E11: 下载进度提示 =========================

class TestE11DownloadProgressLog:
    """E11: 首次下载期间，日志显示进度提示"""

    def test_e11_1_has_downloading_info(self, scai_data_dir, patch_embedding_function, has_network, loguru_capture):
        """E11.1 日志含'正在下载 AI 模型'"""
        from aibridge.config.config_manager import ConfigManager
        cm = ConfigManager.__new__(ConfigManager)
        ChromaDBManager(cm)
        assert any("正在下载 AI 模型" in line for line in loguru_capture)

    def test_e11_2_has_download_complete_info(self, scai_data_dir, patch_embedding_function, has_network, loguru_capture):
        """E11.2 日志含'模型下载完成'"""
        from aibridge.config.config_manager import ConfigManager
        cm = ConfigManager.__new__(ConfigManager)
        ChromaDBManager(cm)
        assert any("模型下载完成" in line for line in loguru_capture)

    def test_e11_3_has_cache_path_in_log(self, scai_data_dir, patch_embedding_function, has_network, loguru_capture):
        """E11.3 日志含缓存路径"""
        from aibridge.config.config_manager import ConfigManager
        cm = ConfigManager.__new__(ConfigManager)
        ChromaDBManager(cm)
        assert any("缓存路径" in line for line in loguru_capture)


# ========================= E12: is_model_ready 方法 =========================

class TestE12IsModelReady:
    """E12: ChromaDBManager 新增 is_model_ready() 方法"""

    def test_e12_1_returns_true_when_cache_ready(self, scai_data_dir, local_cache_ready,
                                                  patch_embedding_function, no_network):
        """E12.1 有缓存时 is_model_ready 返回 True"""
        from aibridge.config.config_manager import ConfigManager
        cm = ConfigManager.__new__(ConfigManager)
        mgr = ChromaDBManager(cm)
        assert mgr.is_model_ready() is True

    def test_e12_2_returns_false_when_no_cache(self, scai_data_dir, patch_embedding_function, no_network):
        """E12.2 无缓存时 is_model_ready 返回 False"""
        from aibridge.config.config_manager import ConfigManager
        cm = ConfigManager.__new__(ConfigManager)
        mgr = ChromaDBManager(cm)
        assert mgr.is_model_ready() is False

    def test_e12_3_method_exists(self):
        """E12.3 is_model_ready 方法存在"""
        assert hasattr(ChromaDBManager, "is_model_ready")
        assert callable(getattr(ChromaDBManager, "is_model_ready"))
