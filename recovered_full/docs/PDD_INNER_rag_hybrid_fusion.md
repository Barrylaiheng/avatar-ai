# PDD 规格 · 模块 16：RAG 混合融合（L1→L2 灌入管道 + 统一检索入口）

> **PDD 阶段**：grill ✅ → prototype ✅（13/13 通过）→ to-spec（本文档）→ to-tickets ⏳ → implement+tdd ⏳ → code-review ⏳
> **前置模块**：M-6 KarpathyWikiReader（L1 关键词检索）、M-15 RAG Embedding 本地缓存（L2 向量检索可用）
> **Grill 总数**：13 条 → 原型已全部通过
> **范围边界**：L1→L2 灌入管道 + 统一检索入口签名对齐 + 融合排序；**不碰** HybridRetriever 旧占位实现（标记 deprecated，后续模块清理）

---

## 0. 业务背景 + 当前痛点（大白话）

### 0.1 战略背景

基于 SCAI 知识库架构调研与战略决策（详见 `wiki/architecture/scai-knowledge-base-strategy.md`），已确立三层架构：

- **L1 知识本体层**：Markdown + YAML frontmatter（对齐 Google OKF v0.1），用户完全拥有，可 Git/导出/跨平台
- **L2 检索加速层**：ChromaDB 向量库，从 L1 灌入可重建，不可用时降级为纯 L1
- **L3 接入协议层**：MCP 协议（未来模块，不在本模块范围）

### 0.2 当前痛点

SCAI MVP 现有 RAG 路径存在 4 个核心痛点：

1. **两套并行且不连通的 RAG 路径**：
   - 路径 A：`AppEngine` → `RAGEngine.retrieve(kb_id, query, intent, top_k)` → `ChromaDBManager.retrieve`
   - 路径 B：`ContextAssemblerV2` → `KarpathyWikiReader.search(query, top_k)`
   - 两者**互不调用、结果不融合**，AppEngine 调用路径 A，ContextAssemblerV2 内部又调用路径 B，造成重复检索 + 结果割裂

2. **方法签名不匹配**：
   - `AppEngine` 调用 `_rag_engine.retrieve(user_input, limit=3)`（位置参数 + limit）
   - `RAGEngine.retrieve` 签名为 `retrieve(self, kb_id, query, intent, top_k)`（4 个位置参数）
   - **运行时 TypeError**，RAG 检索实际从未被 AppEngine 成功调用

3. **HybridRetriever 占位实现未真正融合**：
   - `_compute_vector_similarity` 用字符级 Jaccard 相似度冒充向量相似度
   - `build_index` 未真正构建向量索引
   - 整个类从未被 AppEngine 实际使用，是"死代码"

4. **ChromaDB 不可用时无降级路径**：
   - `RAGEngine.retrieve` 直接调用 `ChromaDBManager.retrieve`，ChromaDB 不可用时返回空 chunks
   - **不会回退到 L1 关键词检索**，知识库功能完全失效

### 0.3 当前 RAG 路径画像（C-1 代码审计）

```
AppEngine.process_message(user_input)
  └─ self._rag_engine.retrieve(user_input, limit=3)   ← 签名不匹配，TypeError
       └─ RAGEngine.retrieve(kb_id, query, intent, top_k)   ← 实际签名
            └─ ChromaDBManager.retrieve(kb_id, query, top_k, filters)
                 └─ if _embed_fn is None: return empty   ← 无降级

ContextAssemblerV2.assemble(session_id, user_input)
  └─ self._rag_engine.search(query, top_k=3)   ← 另一条路径
       └─ KarpathyWikiReader.search(query, top_k)   ← 纯关键词，与上面隔离
```

**4 个根因断点**：
- B1：`AppEngine` 调用 `_rag_engine.retrieve(user_input, limit=3)` 与 `RAGEngine.retrieve` 签名不匹配（`app_engine.py`）
- B2：`RAGEngine` 与 `KarpathyWikiReader` 两套路径并行，结果不融合（`rag_engine.py` / `karpathy_wiki_reader.py`）
- B3：`HybridRetriever` 占位实现（Jaccard 冒充向量），未被使用（`hybrid_retriever.py`）
- B4：ChromaDB 不可用时 `RAGEngine` 返回空，无 L1 降级（`rag_engine.py`）

---

## 1. Grill 清单（13 条用户验收问题，全部机器可断言）

| Grill | 验收问题（大白话） | 原型状态 |
|---|---|---|
| **G1** | `WikiIngestPipeline.ingest_all()` 能全量灌入：从 KarpathyWikiReader 读取所有页面，过滤后转为 chunks 写入 ChromaDB，返回灌入条数 | ✅ |
| **G2** | `WikiIngestPipeline.ingest_incremental()` 能增量灌入：只灌入新增/变更的页面（用 source 集合去重），用 upsert 避免重复 | ✅ |
| **G3** | `WikiIngestPipeline.rebuild()` 能全量重建：先 delete_collection，再 ingest_all，返回灌入条数 | ✅ |
| **G4** | 灌入时跳过缺 `type` 字段的页面（OKF v0.1 合规：`type` 是唯一必填字段） | ✅ |
| **G5** | 灌入时跳过 `status: draft` 的页面（未凝固的知识不进检索加速层） | ✅ |
| **G6** | `UnifiedRetriever.retrieve(query, limit, kb_ids)` 正常返回 L1+L2 融合结果，每条结果含 content/source/score，按 score 降序 | ✅ |
| **G7** | ChromaDB 不可用时（`chromadb_manager=None`）降级为纯 L1 关键词检索，不抛异常，返回 L1 结果 | ✅ |
| **G8** | 无关查询（如"今天天气怎么样"）返回空列表或全低分结果（score < 0.1） | ✅ |
| **G9** | 首次检索时自动触发建索引（`auto_index=True` + `pipeline.is_indexed()=False` → 自动调用 `ingest_incremental`） | ✅ |
| **G10** | `UnifiedRetriever.retrieve` 签名严格对齐 AppEngine 调用：`retrieve(self, query, limit=3, kb_ids=None) -> List[RagHit]` | ✅ |
| **G11** | `kb_ids` 参数兼容：传 `None` 或 `["some_id"]` 都不报错（MVP 阶段忽略，未来支持多知识库隔离） | ✅ |
| **G12** | 空知识库（wiki 目录无页面）检索返回空列表，不抛异常 | ✅ |
| **G13** | L1+L2 双命中加成：同一 source 在 L1 和 L2 都命中时，融合 score 高于单命中（`final = max(l1,l2) + 0.1*min(l1,l2)`） | ✅ |

---

## 2. 根因探查（4 个阻塞断点）

### 2.1 签名不匹配（B1）

- R1.1：`app_engine.py` 中 `AppEngine.process_message` 调用 `self._rag_engine.retrieve(user_input, limit=3)`，把 `user_input` 当作 `kb_id`，`limit=3` 当作 `query`，参数完全错位。
- R1.2：`rag_engine.py` 的 `RAGEngine.retrieve` 签名为 `retrieve(self, kb_id: str, query: str, intent: IntentType, top_k: int = None) -> RAGResult`，**4 个位置参数 + IntentType 类型约束**，与 AppEngine 调用方式完全不兼容。
- R1.3：实际运行时 RAG 检索**从未被成功调用**，AppEngine 拿到的 RAG 结果恒为空或异常。

### 2.2 两套路径不融合（B2）

- R2.1：`AppEngine` → `RAGEngine` → `ChromaDBManager`（向量检索）
- R2.2：`ContextAssemblerV2` → `KarpathyWikiReader.search`（关键词检索）
- R2.3：两条路径**结果不交叉、不融合、不去重**，同一查询可能产生重复 chunks，或 L1 有结果但 L2 无结果时整体丢失。

### 2.3 HybridRetriever 占位（B3）

- R3.1：`hybrid_retriever.py` 的 `_compute_vector_similarity` 用字符级 Jaccard 相似度冒充向量相似度，**不是真正的向量检索**。
- R3.2：`build_index` 方法未真正构建向量索引，只是把 entries 存到内存列表。
- R3.3：`HybridRetriever` **从未被 AppEngine 实际使用**，是"死代码"，但存在感误导开发者以为已有混合检索。

### 2.4 无 L1 降级（B4）

- R4.1：`rag_engine.py` 的 `RAGEngine.retrieve` 直接调用 `ChromaDBManager.retrieve`，ChromaDB 不可用时返回空 chunks。
- R4.2：**不会回退到 L1 关键词检索**，即使 KarpathyWikiReader 完全可用，知识库功能也完全失效。
- R4.3：与战略决策"D-2: ChromaDB 不可用时降级为纯 L1 检索"矛盾。

---

## 3. 修复方案（3 层，对应 Grill）

### 3.1 新增 WikiIngestPipeline（对应 G1-G5）

**新文件**：`src/aibridge/rag/wiki_ingest_pipeline.py`

```python
class WikiIngestPipeline:
    """L1 → L2 灌入管道

    从 KarpathyWikiReader 解析的 wiki 页面灌入 ChromaDB。
    支持全量/增量/重建三种模式。
    """

    def __init__(
        self,
        wiki_reader: KarpathyWikiReader,
        chromadb_manager: Optional[Any],  # ChromaDBManager 或 None
        collection_name: str = "llm_wiki",
    ):
        self._reader = wiki_reader
        self._chromadb = chromadb_manager
        self._collection = collection_name
        self._indexed = False
        self._indexed_sources: set = set()

    def _filter_pages(self) -> List[WikiPage]:
        """过滤可灌入的页面：跳过 draft + 跳过缺 type（OKF 合规）"""
        valid = []
        for page in self._reader.list_pages():
            if page.status == "draft":  # G5
                continue
            if not page.type:  # G4
                continue
            valid.append(page)
        return valid

    def _page_to_chunk(self, page: WikiPage) -> Chunk:
        """页面转 Chunk"""
        chunk_id = f"wiki_{page.source}"
        metadata = {
            "source": page.source,
            "type": page.type,
            "title": page.title,
            "tags": ",".join(page.tags),
            "status": page.status,
        }
        content = f"# {page.title}\n\n{page.body}"
        return Chunk(chunk_id=chunk_id, content=content, metadata=metadata)

    def ingest_all(self) -> int:  # G1
        if not self._chromadb:
            return 0
        pages = self._filter_pages()
        chunks = [self._page_to_chunk(p) for p in pages]
        if chunks:
            self._chromadb.add_chunks(self._collection, chunks)
        self._indexed = True
        self._indexed_sources = {p.source for p in pages}
        return len(chunks)

    def ingest_incremental(self) -> int:  # G2
        if not self._chromadb:
            return 0
        pages = self._filter_pages()
        new_pages = [p for p in pages if p.source not in self._indexed_sources]
        chunks = [self._page_to_chunk(p) for p in new_pages]
        if chunks:
            self._chromadb.upsert_chunks(self._collection, chunks)
        self._indexed_sources.update({p.source for p in new_pages})
        self._indexed = True
        return len(chunks)

    def rebuild(self) -> int:  # G3
        if not self._chromadb:
            return 0
        self._chromadb.delete_collection(self._collection)
        self._indexed = False
        self._indexed_sources = set()
        return self.ingest_all()

    def is_indexed(self) -> bool:
        return self._indexed
```

**关键点**：
- `_filter_pages` 同时执行 G4（OKF 合规）+ G5（draft 跳过）双重过滤
- `_page_to_chunk` 保留 source/type/title/tags/status 元数据，便于 L2 检索时回溯
- `ingest_incremental` 用 `upsert_chunks`（需 ChromaDBManager 新增此方法）避免重复
- `chromadb_manager=None` 时所有方法返回 0，不抛异常

### 3.2 新增 UnifiedRetriever（对应 G6-G13）

**新文件**：`src/aibridge/rag/unified_retriever.py`

```python
class UnifiedRetriever:
    """统一检索入口 — L1（关键词）+ L2（向量）融合

    签名对齐 AppEngine 调用：retrieve(query, limit=3, kb_ids=None) -> List[RagHit]
    """

    def __init__(
        self,
        wiki_reader: KarpathyWikiReader,
        pipeline: WikiIngestPipeline,
        chromadb_manager: Optional[Any] = None,
        auto_index: bool = True,
        collection_name: str = "llm_wiki",
    ):
        self._reader = wiki_reader
        self._pipeline = pipeline
        self._chromadb = chromadb_manager
        self._auto_index = auto_index
        self._collection = collection_name

    def retrieve(  # G10: 签名严格对齐
        self,
        query: str,
        limit: int = 3,
        kb_ids: Optional[List[str]] = None,  # G11: MVP 忽略，未来支持
    ) -> List[RagHit]:
        # G11: kb_ids 兼容
        if kb_ids is not None:
            logger.debug(f"kb_ids={kb_ids} (MVP 阶段忽略)")

        # G9: 自动建索引
        if self._chromadb and self._auto_index and not self._pipeline.is_indexed():
            self._pipeline.ingest_incremental()

        # L1 检索（KarpathyWikiReader 关键词）
        l1_results = self._reader.search(query, top_k=limit)

        # G7: ChromaDB 不可用时降级
        if not self._chromadb:
            return l1_results

        # L2 检索（ChromaDB 向量）
        l2_raw = self._chromadb.retrieve(self._collection, query, top_k=limit)
        l2_results: List[RagHit] = []
        for chunk in l2_raw.chunks:
            source = chunk.metadata.get("source", "unknown")
            # distance 越小越相似，转换为 score（1 - distance，clamp 到 [0,1]）
            distance = chunk.metadata.get("distance", 0.5)
            l2_score = max(0.0, min(1.0, 1.0 - distance))
            content = chunk.content[:500]
            l2_results.append(RagHit(content=content, source=source, score=round(l2_score, 3)))

        # G13: 融合排序
        return self._fuse(l1_results, l2_results, limit)

    def _fuse(  # G13
        self,
        l1: List[RagHit],
        l2: List[RagHit],
        limit: int,
    ) -> List[RagHit]:
        """融合 L1 + L2 结果

        策略：final_score = max(l1, l2) + 0.1 * min(l1, l2)（双命中加成）
        去重：按 source 去重，同一 source 取融合后 score
        """
        merged: Dict[str, RagHit] = {}

        for hit in l1:
            merged[hit.source] = RagHit(
                content=hit.content,
                source=hit.source,
                score=hit.score,
            )

        for hit in l2:
            if hit.source in merged:
                existing = merged[hit.source]
                # 双命中加成
                final = max(existing.score, hit.score) + 0.1 * min(existing.score, hit.score)
                merged[hit.source].score = round(min(1.0, final), 3)
            else:
                merged[hit.source] = RagHit(
                    content=hit.content,
                    source=hit.source,
                    score=hit.score,
                )

        results = sorted(merged.values(), key=lambda x: x.score, reverse=True)
        return results[:limit]

    def is_indexed(self) -> bool:
        return self._pipeline.is_indexed()
```

**关键点**：
- 签名严格对齐 AppEngine 调用（G10）
- `kb_ids` 参数兼容，MVP 阶段忽略但不报错（G11）
- `auto_index=True` 时首次检索自动触发 `ingest_incremental`（G9）
- ChromaDB 不可用时降级为纯 L1（G7）
- L2 score 从 distance 反转：`1 - distance`（真实向量检索，非 Jaccard 占位）
- 融合策略：双命中加成 `max + 0.1*min`，按 source 去重（G13）

### 3.3 AppEngine 装配 + 旧路径改造（对应 B1/B2/B4）

**`app_engine.py` 改造**：

```python
# 旧：
# self._rag_engine = RAGEngine(config_manager, chromadb_manager, rule_injector, fusion_engine)
# result = self._rag_engine.retrieve(user_input, limit=3)  # TypeError

# 新：
from aibridge.rag.unified_retriever import UnifiedRetriever
from aibridge.rag.wiki_ingest_pipeline import WikiIngestPipeline

# AppEngine.initialize() 中：
self._wiki_reader = KarpathyWikiReader(kb_root=kb_root)
self._wiki_pipeline = WikiIngestPipeline(
    wiki_reader=self._wiki_reader,
    chromadb_manager=self._chromadb_manager,  # 可能为 None
    collection_name="llm_wiki",
)
self._unified_retriever = UnifiedRetriever(
    wiki_reader=self._wiki_reader,
    pipeline=self._wiki_pipeline,
    chromadb_manager=self._chromadb_manager,
    auto_index=True,
    collection_name="llm_wiki",
)

# AppEngine.process_message() 中：
rag_hits = self._unified_retriever.retrieve(user_input, limit=3)  # 签名对齐
```

**`context_assembler_v2.py` 改造**：

```python
# 旧：
# self._rag_engine = KarpathyWikiReader(...)  # 内部独立调用
# results = self._rag_engine.search(query, top_k=3)

# 新：
# ContextAssemblerV2 不再自己创建 RAG 引擎，改由 AppEngine 注入 unified_retriever
def set_unified_retriever(self, retriever: UnifiedRetriever):
    self._unified_retriever = retriever

# assemble() 中：
rag_hits = self._unified_retriever.retrieve(query, limit=3) if self._unified_retriever else []
```

**`hybrid_retriever.py` 标记 deprecated**：

```python
"""[DEPRECATED] HybridRetriever — 被 UnifiedRetriever 替代

本模块的 _compute_vector_similarity 用 Jaccard 占位，不是真正的向量检索。
M-16 起 AppEngine 改用 UnifiedRetriever，本类保留但不再维护。
未来模块会删除。
"""
```

**`rag_engine.py` 标记 deprecated**：

```python
"""[DEPRECATED] RAGEngine — 被 UnifiedRetriever 替代

本类的 retrieve 签名与 AppEngine 调用不匹配，且不融合 L1 关键词检索。
M-16 起 AppEngine 改用 UnifiedRetriever，本类保留但不再维护。
未来模块会删除。
"""
```

### 3.4 ChromaDBManager 新增 upsert_chunks（支撑 G2）

**`chromadb_manager.py` 改造**：

```python
def upsert_chunks(self, kb_id: str, chunks: List[Chunk]) -> None:
    """upsert chunks（按 chunk_id 去重后写入）

    支撑 WikiIngestPipeline.ingest_incremental 的增量灌入。
    """
    if not self._client or self._embed_fn is None:
        # 不可用时静默返回，与 retrieve 降级策略一致
        return
    try:
        collection = self._get_collection(kb_id)
        ids = [c.chunk_id for c in chunks]
        documents = [c.content for c in chunks]
        metadatas = [c.metadata for c in chunks]
        collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
        )
        logger.info(f"Upserted {len(chunks)} chunks to kb={kb_id}")
    except Exception as e:
        logger.error(f"Upsert failed: {e}")
```

### 3.5 KarpathyWikiReader 新增 list_pages（支撑 G1）

**`karpathy_wiki_reader.py` 改造**：

```python
def list_pages(self) -> List[WikiPage]:
    """返回所有已加载的 wiki 页面（供 WikiIngestPipeline 灌入使用）

    支撑 WikiIngestPipeline.ingest_all / ingest_incremental / rebuild。
    """
    return list(self._pages)
```

> 注：原 KarpathyWikiReader 已有 `_pages` 内部缓存，只需暴露公开方法即可。

---

## 4. 技术决策（4 条，已对齐战略）

### TD-1：UnifiedRetriever 签名严格对齐 AppEngine 调用

**决策**：`retrieve(self, query: str, limit: int = 3, kb_ids: Optional[List[str]] = None) -> List[RagHit]`

**理由**：
- AppEngine 现有调用方式：`retrieve(user_input, limit=3)`
- 不强制 `intent` 参数（IntentType），由 UnifiedRetriever 内部按需路由（MVP 阶段不分场景）
- `kb_ids` 为未来多知识库隔离预留，MVP 阶段忽略但不报错
- 返回 `List[RagHit]` 而非 `RAGResult`，与 ContextAssemblerV2 期望一致

**替代方案否决**：
- ❌ 改 AppEngine 调用方式适配 RAGEngine 旧签名 → 改动面大，且 RAGEngine 不融合 L1，不符合战略
- ❌ 保留 RAGEngine + 新增适配器 → 增加一层无意义抽象

### TD-2：L2 score 从 distance 反转

**决策**：`l2_score = max(0.0, min(1.0, 1.0 - distance))`

**理由**：
- ChromaDB 返回 `distances` 字段（L2 欧氏距离），越小越相似
- 转换为 score（越大越相似）便于与 L1 score 融合
- `clamp` 到 [0, 1] 避免极端值
- 替代 HybridRetriever 的 Jaccard 占位（B3 根因）

**替代方案否决**：
- ❌ 用 cosine_similarity → ChromaDB 默认返回 L2 distance，转换需额外配置
- ❌ 保留 Jaccard 占位 → 不是真正向量检索，误导

### TD-3：融合策略 max + 0.1*min

**决策**：`final_score = max(l1, l2) + 0.1 * min(l1, l2)`

**理由**：
- 双命中（L1+L2 都返回）应比单命中 score 高
- `max` 保留较强信号的权重
- `0.1 * min` 是加成，不让弱信号喧宾夺主
- `min(1.0, final)` 防止溢出
- 按source 去重，同一 source 只保留一条融合后结果

**替代方案否决**：
- ❌ 加权和 `w1*l1 + w2*l2` → 需调参，MVP 阶段过于复杂
- ❌ 只取 max → 双命中无加成，区分度不足

### TD-4：HybridRetriever / RAGEngine 标记 deprecated，不立即删除

**决策**：在文件头部加 `[DEPRECATED]` 注释，说明被 UnifiedRetriever 替代，保留但不维护。

**理由**：
- 立即删除可能破坏其他模块的 import（如 test_inner_rag_wiki_pdd.py 可能引用）
- 标记 deprecated 让后续模块有明确的清理信号
- 符合"渐进式重构"原则，降低本模块改动面

**替代方案否决**：
- ❌ 立即删除 → 改动面大，需同步清理所有引用，超出本模块范围
- ❌ 保留并继续维护 → 与战略矛盾，"死代码"继续误导

---

## 5. 不做什么（边界）

| 不做 | 理由 |
|---|---|
| ❌ 删除 HybridRetriever / RAGEngine | 改动面大，可能破坏现有 test，留给后续模块清理 |
| ❌ 实现多知识库隔离（kb_ids 真实生效） | MVP 阶段单知识库，kb_ids 仅做参数兼容 |
| ❌ 实现 IntentType 场景路由 | MVP 阶段不分场景，所有查询走同一检索路径 |
| ❌ 实现 MCP 接入协议（L3） | 属于未来模块，本模块只做 L1→L2 灌入 + 融合检索 |
| ❌ 修改 RuleInjector / FusionEngine | 旧组件保留，不被 UnifiedRetriever 调用，但不删除 |
| ❌ 实现 Chunk 语义分割（512字符） | L1 wiki 页面已结构化，灌入时整页一个 chunk，不做语义分割 |
| ❌ 实现 Embedding 模型在线下载进度条 | M-15 已处理，本模块假设模型可用或降级 |

---

## 6. Test Seams（13 条，对应 Grill）

| Test Seam | 断言 | 验证方式 |
|---|---|---|
| **TS-G1** | `pipeline.ingest_all()` 返回 3，mock_chroma 集合有 3 条，每条 metadata 含 source 和 type | pytest + MockChromaDBManager |
| **TS-G2** | `pipeline.ingest_incremental()` 新增页面后返回 1，集合总数 4，有 upsert 调用 | pytest + MockChromaDBManager |
| **TS-G3** | `pipeline.rebuild()` 先 delete 再 ingest，delete_calls 长度 1，集合数等于有效页面数 | pytest + MockChromaDBManager |
| **TS-G4** | 缺 type 的页面 source 不在灌入结果中 | pytest + MockChromaDBManager |
| **TS-G5** | draft 页面 source 不在灌入结果中 | pytest + MockChromaDBManager |
| **TS-G6** | `retriever.retrieve("RAG vs LLM Wiki")` 返回非空，按 score 降序，每条含 content/source/score | pytest + MockChromaDBManager |
| **TS-G7** | `chromadb_manager=None` 时不抛异常，返回 L1 结果 | pytest |
| **TS-G8** | 无关查询返回空列表或全低分（score < 0.1） | pytest |
| **TS-G9** | 首次检索前 `is_indexed()=False`，检索后 `is_indexed()=True`，集合非空 | pytest + MockChromaDBManager |
| **TS-G10** | `inspect.signature(UnifiedRetriever.retrieve)` 参数为 `['self','query','limit','kb_ids']`，limit 默认 3，kb_ids 默认 None | pytest + inspect |
| **TS-G11** | `kb_ids=None` 和 `kb_ids=["some_id"]` 都不报错，都返回 list | pytest |
| **TS-G12** | 空 wiki 目录检索返回空列表 | pytest + 临时空目录 |
| **TS-G13** | L1+L2 双命中的 source score 高于单命中 | pytest + MockChromaDBManager |

---

## 7. 实现清单（to-tickets）

| Ticket | 文件 | 改动 | 对应 TS |
|---|---|---|---|
| **T-1** | `src/aibridge/rag/wiki_ingest_pipeline.py` | 新建 WikiIngestPipeline 类 | TS-G1~G5 |
| **T-2** | `src/aibridge/rag/unified_retriever.py` | 新建 UnifiedRetriever 类 | TS-G6~G13 |
| **T-3** | `src/aibridge/rag/chromadb_manager.py` | 新增 `upsert_chunks` 方法 | 支撑 T-1 |
| **T-4** | `src/aibridge/rag/karpathy_wiki_reader.py` | 新增 `list_pages` 方法 | 支撑 T-1 |
| **T-5** | `src/aibridge/engine/app_engine.py` | 装配 UnifiedRetriever，替换 RAGEngine 调用 | B1/B2 |
| **T-6** | `src/aibridge/engine/context_assembler_v2.py` | 改用注入的 UnifiedRetriever，移除内部 KarpathyWikiReader | B2 |
| **T-7** | `src/aibridge/rag/hybrid_retriever.py` | 文件头加 `[DEPRECATED]` 注释 | B3 |
| **T-8** | `src/aibridge/rag/rag_engine.py` | 文件头加 `[DEPRECATED]` 注释 | B1 |
| **T-9** | `tests/test_inner_rag_hybrid_fusion_pdd.py` | 新建 pytest 用例，覆盖 13 条 TS | 全部 |

---

## 8. 验收标准

- [ ] 13 条 Test Seams 全部通过（pytest 绿色）
- [ ] 原型脚本 13/13 通过（已完成）
- [ ] inner_* 全量回归通过（不破坏 M-6~M-15 既有功能）
- [ ] AppEngine 成功调用 `unified_retriever.retrieve(user_input, limit=3)`，无 TypeError
- [ ] ChromaDB 不可用时降级为 L1，不抛异常
- [ ] HybridRetriever / RAGEngine 标记 deprecated，不影响现有 import

---

## 9. 知识库关联

- **战略依据**：`wiki/architecture/scai-knowledge-base-strategy.md`（三层架构 D-1~D-5）
- **概念基础**：`wiki/concepts/rag-vs-wiki.md`（RAG vs LLM Wiki 对比）
- **标准对齐**：`wiki/concepts/google-okf.md`（OKF v0.1 规范，G4 合规依据）
- **Grill 源**：`raw/2026-08-12-scai-m16-wiki-ingest-pipeline-grill.md`
- **原型脚本**：`_prototypes/m16_wiki_ingest_pipeline_prototype.py`
