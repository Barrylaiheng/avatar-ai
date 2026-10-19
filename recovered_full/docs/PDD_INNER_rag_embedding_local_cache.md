# PDD 规格 · 模块 15：RAG Embedding 模型本地缓存

> **PDD 阶段**：grill ✅ → prototype ⏳ → to-spec（本文档）→ to-tickets ⏳ → implement+tdd ⏳ → code-review ⏳
> **前置模块**：M-10 App Bootstrap Wiring（AppEngine 装配链）、M-13 Settings Data Sync（SettingsPage 配置回显）
> **Grill 总数**：12 条 → 原型待验证
> **范围边界**：纯本地缓存改造，**不碰** HybridRetriever 的 Jaccard 占位实现（那是另一个模块）

---

## 0. 业务背景 + 当前痛点（大白话）

### 0.1 业务痛点

当前 SCAI MVP 在启动时，RAG 模块会去加载中文 Embedding 模型 `BAAI/bge-small-zh-v1.5`（约 100MB），但实现存在 4 个硬伤：

1. **硬编码绝对路径**：`_BGE_LOCAL_PATH = r"C:\bge-cache\models\BAAI--bge-small-zh-v1.5\snapshots\master"`，换机即失效，新部署的机器根本没有这个目录。
2. **未设置 HF 缓存环境变量**：未设置 `HF_HOME` / `SENTENCE_TRANSFORMERS_HOME` / `cache_folder`，文档承诺的 `data/.cache/huggingface` 缓存路径从未在代码中实现。
3. **内网无 HF 访问时崩溃链**：
   - 本地路径不存在 → 走在线下载 → 无网 → 异常 → `_embed_fn = None`
   - `_embed_fn = None` → ChromaDB 回退到默认 `all-MiniLM-L6-v2` → 仍需联网 → 二次失败
   - 最终 RAG 检索返回空 chunks，知识库功能完全失效
4. **日志误导**：加载失败时日志写"降级为默认模型"，但实际只是置空，并未主动加载任何备用模型。

### 0.2 当前初始化路径画像（C-1 代码审计）

```
AppEngine.initialize()
  └─ KnowledgeBaseManager(config_manager)
       └─ ChromaDBManager(config_manager)
            ├─ __init__
            │    ├─ _init_embed_fn()   ← 加载 BAAI/bge-small-zh-v1.5
            │    └─ _init_client()     ← PersistentClient(path=data_dir/chromadb)
            └─ _init_embed_fn
                 ├─ if os.path.exists(_BGE_LOCAL_PATH):   ← 硬编码 C:\bge-cache\...，换机即 False
                 │    SentenceTransformerEmbeddingFunction(model_name=_BGE_LOCAL_PATH)
                 ├─ else:
                 │    os.environ.setdefault("HF_HUB_OFFLINE", "1")   ← 强制离线，但本地无缓存
                 │    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
                 │    SentenceTransformerEmbeddingFunction(model_name=_BGE_MODEL_NAME)   ← 在线下载
                 └─ except Exception:
                      logger.warning("中文 Embedding 模型加载失败，降级为默认模型")   ← 误导
                      self._embed_fn = None   ← 置空，ChromaDB 会再次尝试默认模型（仍需联网）
```

**4 个根因断点**：
- B1：`_BGE_LOCAL_PATH` 硬编码绝对路径，不可移植（`chromadb_manager.py:34`）
- B2：未设置 `HF_HOME` / `SENTENCE_TRANSFORMERS_HOME`，HF 缓存目录不可控（`chromadb_manager.py:99-108`）
- B3：`_embed_fn = None` 后无真正中文 fallback，ChromaDB 默认模型仍需联网（`chromadb_manager.py:109-111`）
- B4：日志 misleading，"降级为默认模型" 实际是"完全降级到不可用"（`chromadb_manager.py:110`）

---

## 1. Grill 清单（12 条用户验收问题，全部机器可断言）

| Grill | 验收问题（大白话） |
|---|---|
| **E1** | ChromaDBManager 不再硬编码 `C:\bge-cache\...` 绝对路径，模型本地路径改为 `get_data_dir() / "models" / "bge-small-zh-v1.5"`，跟随 `SCAI_DATA_DIR` 环境变量切换 |
| **E2** | AppEngine 启动时显式设置 `HF_HOME` 和 `SENTENCE_TRANSFORMERS_HOME` 环境变量，都指向 `get_data_dir() / ".cache" / "huggingface"`，确保 HF 缓存可控 |
| **E3** | 首次启动 + 有网络时，模型自动下载到 `data/.cache/huggingface`，下载完成后该目录非空且包含 `model.safetensors` 或 `pytorch_model.bin` 模型文件 |
| **E4** | 第二次启动 + 无网络时（`HF_HUB_OFFLINE=1`），模型从本地缓存加载成功，`_embed_fn` 非 None，不触发任何 huggingface 网络请求 |
| **E5** | 无网络 + 本地缓存存在时，RAG 检索能正常工作：`ChromaDBManager.retrieve(query)` 返回非空 chunks（用预置的测试知识库验证） |
| **E6** | 无网络 + 本地缓存不存在时，AppEngine 启动**不崩溃**，`_embed_fn = None`，RAG 检索返回空 chunks（不抛异常），主流程继续 |
| **E7** | 本地缓存存在时，启动日志中**不再出现** "降级为默认模型" 或 "Embedding 模型加载失败" WARNING（用 `caplog` 断言） |
| **E8** | 从本地缓存加载模型耗时 < 5s（第二次启动，用 `time.time()` 测量 `_init_embed_fn` 耗时） |
| **E9** | `SCAI_DATA_DIR` 环境变量切换时，模型缓存路径同步切换：设置 `SCAI_DATA_DIR=/tmp/test_a` → 模型路径在 `/tmp/test_a/models/bge-small-zh-v1.5`；切换到 `/tmp/test_b` → 路径同步切换 |
| **E10** | Embedding 函数加载失败时，日志清晰提示 "Embedding 模型未就绪，请检查网络或执行 prepare-model 命令预下载"，不再误导为 "降级为默认模型" |
| **E11** | 首次下载期间，日志显示进度提示（"正在下载 AI 模型 BAAI/bge-small-zh-v1.5（约 100MB），请稍候..."），下载完成后日志显示 "模型下载完成，缓存路径：{path}" |
| **E12** | ChromaDBManager 新增 `is_model_ready() -> bool` 方法，返回本地缓存是否存在 + 模型是否可加载，供 SettingsPage 健康检查面板调用 |

---

## 2. 根因探查（4 个阻塞断点）

### 2.1 硬编码绝对路径（B1）
- R1.1：`chromadb_manager.py:34` 模块级常量 `_BGE_LOCAL_PATH = r"C:\bge-cache\models\BAAI--bge-small-zh-v1.5\snapshots\master"`，**任何非该机器的部署都失效**。
- R1.2：`build_vector_kb_updated.py:26-28` 离线建库脚本里**重复定义**了同名常量，两处不同步会出 bug。
- R1.3：路径不响应 `SCAI_DATA_DIR` 环境变量，**测试隔离失效**（pytest 跑测试时会污染生产环境的 `C:\bge-cache\...`）。

### 2.2 HF 缓存环境变量缺失（B2）
- R2.1：未设置 `HF_HOME`，huggingface_hub 默认缓存在 `~/.cache/huggingface/hub`（用户家目录），**不在数据目录内**，打包/迁移时丢失。
- R2.2：未设置 `SENTENCE_TRANSFORMERS_HOME`，sentence-transformers 库默认缓存在 `~/.cache/torch/sentence_transformers`，**与 HF 缓存分离**，导致同一份模型可能被下载两次。
- R2.3：未传 `cache_folder` 参数给 `SentenceTransformerEmbeddingFunction`，无法精确控制缓存路径。

### 2.3 无网 + 无缓存时的崩溃链（B3）
- R3.1：`chromadb_manager.py:105-106` 设置 `HF_HUB_OFFLINE=1` 后，**强制离线但本地无缓存**，`SentenceTransformerEmbeddingFunction(model_name=_BGE_MODEL_NAME)` 直接抛 `LocalEntryNotFound` 异常。
- R3.2：`chromadb_manager.py:109-111` 捕获异常后 `_embed_fn = None`，但 `_get_collection`（`:138`）以 `embedding_function=None` 创建 collection，ChromaDB **回退到默认 `all-MiniLM-L6-v2`**。
- R3.3：`all-MiniLM-L6-v2` 在无网环境下**同样无法加载**，ChromaDB 在第一次 `collection.add()` 或 `collection.query()` 时再次抛异常，导致 RAG 检索完全失效。

### 2.4 日志 misleading（B4）
- R4.1：`chromadb_manager.py:110` 日志写 "降级为默认模型"，但实际 `_embed_fn = None`，**并未主动加载任何备用模型**。
- R4.2：用户看到 "降级为默认模型" 会以为 RAG 还能用，实际 RAG 已完全失效，**故障定位困难**。
- R4.3：首次下载期间**无任何进度提示**，用户以为 App 卡死。

---

## 3. 修复方案（4 层，对应 Grill）

### 3.1 路径相对化 + 环境变量设置（对应 E1/E2/E9）

**`chromadb_manager.py` 改造**：
```python
# 旧：模块级硬编码
_BGE_LOCAL_PATH = r"C:\bge-cache\models\BAAI--bge-small-zh-v1.5\snapshots\master"
_BGE_MODEL_NAME = "BAAI/bge-small-zh-v1.5"

# 新：基于 get_data_dir() 的相对路径
def _get_model_local_path() -> Path:
    """模型本地缓存路径，跟随 SCAI_DATA_DIR 切换"""
    return get_data_dir() / "models" / "bge-small-zh-v1.5"

def _get_hf_cache_dir() -> Path:
    """HF 缓存目录，跟随 SCAI_DATA_DIR 切换"""
    return get_data_dir() / ".cache" / "huggingface"

def _ensure_hf_env() -> None:
    """设置 HF_HOME / SENTENCE_TRANSFORMERS_HOME，确保缓存可控"""
    hf_cache = _get_hf_cache_dir()
    hf_cache.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(hf_cache))
    os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", str(hf_cache))
```

### 3.2 _init_embed_fn 改造：本地优先 + 自动下载 + 离线兜底（对应 E3/E4/E6/E7/E10/E11）

```python
def _init_embed_fn(self) -> None:
    from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
    
    _ensure_hf_env()  # 设置 HF_HOME / ST_HOME
    local_path = _get_model_local_path()
    model_name = "BAAI/bge-small-zh-v1.5"
    
    # 路径 1：本地缓存已存在 → 直接加载（最快，离线可用）
    if local_path.exists() and any(local_path.iterdir()):
        try:
            self._embed_fn = SentenceTransformerEmbeddingFunction(
                model_name=str(local_path),
                trust_remote_code=True
            )
            logger.info(f"Embedding 模型从本地缓存加载: {local_path}")
            return
        except Exception as e:
            logger.warning(f"本地缓存加载失败，尝试重新下载: {e}")
    
    # 路径 2：本地缓存不存在 → 在线下载（首次启动）
    logger.info(f"正在下载 AI 模型 {model_name}（约 100MB），请稍候...")
    try:
        os.environ.pop("HF_HUB_OFFLINE", None)  # 临时允许联网
        os.environ.pop("TRANSFORMERS_OFFLINE", None)
        self._embed_fn = SentenceTransformerEmbeddingFunction(
            model_name=model_name,
            trust_remote_code=True
        )
        logger.info(f"模型下载完成，缓存路径: {_get_hf_cache_dir()}")
    except Exception as e:
        # 路径 3：下载失败（无网）→ 明确提示，不再 misleading
        self._embed_fn = None
        logger.error(
            f"Embedding 模型未就绪，请检查网络或执行 prepare-model 命令预下载。"
            f"错误详情: {e}"
        )
```

### 3.3 is_model_ready 方法（对应 E12）

```python
def is_model_ready(self) -> bool:
    """检查模型是否就绪（本地缓存存在 + 可加载）"""
    if self._embed_fn is None:
        return False
    local_path = _get_model_local_path()
    return local_path.exists() and any(local_path.iterdir())
```

### 3.4 启动时自动下载（对应 E3/E11）

- AppEngine.initialize() 调用 ChromaDBManager 时，`_init_embed_fn` 内部自动触发首次下载。
- 下载期间 logger.info 输出进度提示。
- 下载完成后 logger.info 输出缓存路径。
- **不引入独立 prepare-model 命令**（用户选择"启动时自动下载"方案）。

---

## 4. 关键技术决策（TD-10 + 新增 D15~D18）

| ID | 决策 | 为什么 |
|---|---|---|
| **D15** | 模型本地路径用 `get_data_dir() / "models" / "bge-small-zh-v1.5"`，不用 HF 默认 `~/.cache/huggingface/hub` | 跟随 `SCAI_DATA_DIR` 切换，测试隔离可用；打包/迁移时模型随数据目录一起带走 |
| **D16** | `HF_HOME` 和 `SENTENCE_TRANSFORMERS_HOME` 都指向 `get_data_dir() / ".cache" / "huggingface"` | 统一缓存路径，避免 HF 和 sentence-transformers 各存一份；显式控制便于打包 |
| **D17** | 三层加载策略：本地缓存优先 → 在线下载 → 明确报错 | 离线优先（已下载则不联网）+ 首次自动下载（用户无感）+ 失败明确提示（不再 misleading） |
| **D18** | 不引入独立 prepare-model 命令，首次下载在 AppEngine 启动时同步完成 | 用户选择"启动时自动下载"方案，简单直接；首次启动会卡 1-2 分钟，但日志有进度提示 |
| **TD-10** | 从 M-15 D17 提炼「三层加载策略」为通用原则 | 适用于所有"外部模型/资源加载"场景：本地优先 → 在线下载 → 明确报错，避免 misleading fallback |

---

## 5. pytest 映射（Grill → 测试用例）

| Grill | pytest 用例数 | 文件 |
|---|---|---|
| E1 | 3 | TestE1RelativeModelPath |
| E2 | 2 | TestE2HfEnvSetup |
| E3 | 2 | TestE3FirstDownloadCreatesCache |
| E4 | 2 | TestE4OfflineLoadFromCache |
| E5 | 2 | TestE5RetrieveWorksOffline |
| E6 | 2 | TestE6NoCrashWhenNoCacheNoNetwork |
| E7 | 2 | TestE7NoMisleadingWarning |
| E8 | 1 | TestE8LoadLatencyUnder5s |
| E9 | 3 | TestE9SCAIDataDirSwitch |
| E10 | 2 | TestE10ClearErrorMessage |
| E11 | 2 | TestE11DownloadProgressLog |
| E12 | 2 | TestE12IsModelReady |
| **合计** | **~25** | |

---

## 6. 已交付物清单

- [ ] `docs/PDD_INNER_rag_embedding_local_cache.md`（本文档）
- [ ] `_prototypes/rag_embedding_local_cache_prototype.py`（原型验证 12 条断言）
- [ ] `src/aibridge/rag/chromadb_manager.py`（路径相对化 + 三层加载策略 + is_model_ready）
- [ ] `src/aibridge/utils/common.py`（新增 `_get_hf_cache_dir` / `_ensure_hf_env` 辅助函数）
- [ ] `tests/test_inner_rag_embedding_local_cache_pdd.py`（pytest 固化 25 条用例）
- [ ] `wiki/architecture/scai-mvp-m15-rag-embedding-local-cache.md`（知识库凝固页）
- [ ] `wiki/architecture/scai-mvp-pdd-total-acceptance-v1.md` 升级到 v1.4（15 inner 模块 × 296 pytest）

---

## 7. 与其他模块关联

- **M-10 App Bootstrap Wiring**：AppEngine.initialize() 调用 ChromaDBManager，本次改造在初始化链路内完成。
- **M-13 Settings Data Sync**：SettingsPage 健康检查面板可调用 `is_model_ready()` 显示模型状态。
- **M-14 Conversation Streaming**：流式生成期间 RAG 检索仍走 ChromaDBManager，本次改造不影响流式接口。
- **后续模块（M-16 候选）**：HybridRetriever 的 Jaccard 占位实现替换为真正 ChromaDB 向量检索（本次不碰）。

---

## 8. 风险与边界

- **风险 1**：首次下载约 100MB，慢网络下可能 5-10 分钟。**缓解**：日志清晰提示 + 失败重试机制（不在 M-15 范围，后续模块加）。
- **风险 2**：模型文件可能因磁盘空间不足下载失败。**缓解**：失败时日志明确提示 "磁盘空间不足"。
- **风险 3**：ChromaDB 内部默认 embed 仍可能在 `_embed_fn=None` 时触发联网。**缓解**：`_get_collection` 在 `_embed_fn=None` 时直接返回空 collection，不调用 ChromaDB 默认 embed。
- **边界**：M-15 不碰 HybridRetriever 的 Jaccard 占位实现，不碰 RAG 检索结果排序逻辑，不碰知识库导入流程。
