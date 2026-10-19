# -*- coding: utf-8 -*-
"""
里层 PDD 模块 16 · RAG 混合融合（L1→L2 灌入管道 + 统一检索入口）测试

13 条 Grill → pytest 用例（对齐 docs/PDD_INNER_rag_hybrid_fusion.md §6）

运行：
    cd C:\\Users\\Administrator\\Desktop\\WeChatAI_Project
    python -m pytest tests/test_inner_rag_hybrid_fusion_pdd.py -v
"""
from __future__ import annotations

import inspect
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

# 确保 src 在 PYTHONPATH
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from aibridge.rag.chromadb_manager import Chunk, RetrievalResult
from aibridge.rag.karpathy_wiki_reader import KarpathyWikiReader, RagHit, WikiPage
from aibridge.rag.wiki_ingest_pipeline import WikiIngestPipeline
from aibridge.rag.unified_retriever import UnifiedRetriever


# ============================================================================
# Mock ChromaDBManager（避免加载真实 embedding 模型）
# ============================================================================

class MockChromaDBManager:
    """Mock ChromaDB 管理器 — 记录所有调用，不真正做向量检索"""

    def __init__(self):
        self.collections: Dict[str, List[Chunk]] = {}
        self.add_calls: List[Tuple[str, List[Chunk]]] = []
        self.upsert_calls: List[Tuple[str, List[Chunk]]] = []
        self.delete_calls: List[str] = []
        self.retrieve_calls: List[Tuple[str, str, int]] = []

    def add_chunks(self, kb_id: str, chunks: List[Chunk]) -> None:
        if kb_id not in self.collections:
            self.collections[kb_id] = []
        self.collections[kb_id].extend(chunks)
        self.add_calls.append((kb_id, chunks))

    def upsert_chunks(self, kb_id: str, chunks: List[Chunk]) -> None:
        if kb_id not in self.collections:
            self.collections[kb_id] = []
        existing_ids = {c.chunk_id for c in self.collections[kb_id]}
        for chunk in chunks:
            if chunk.chunk_id in existing_ids:
                self.collections[kb_id] = [
                    c for c in self.collections[kb_id] if c.chunk_id != chunk.chunk_id
                ]
            self.collections[kb_id].append(chunk)
        self.upsert_calls.append((kb_id, chunks))

    def retrieve(self, kb_id: str, query: str, top_k: int = 3,
                 filters: Optional[Dict] = None) -> RetrievalResult:
        self.retrieve_calls.append((kb_id, query, top_k))
        if kb_id not in self.collections:
            return RetrievalResult(chunks=[], total_count=0, query=query, top_k=top_k)

        # 模拟向量检索：按 query 关键词在 content 中匹配，计算伪相似度
        query_lower = query.lower()
        scored = []
        for chunk in self.collections[kb_id]:
            content_lower = chunk.content.lower()
            if query_lower and content_lower:
                overlap = sum(1 for c in query_lower if c in content_lower)
                score = overlap / max(len(query_lower), 1)
            else:
                score = 0.0
            # 转换为 distance（score 越高 distance 越小）
            distance = 1.0 - score
            chunk.metadata["distance"] = distance
            scored.append((chunk, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        top = scored[:top_k]
        top = [(c, s) for c, s in top if s > 0]

        return RetrievalResult(
            chunks=[c for c, _ in top],
            total_count=len(top),
            query=query,
            top_k=top_k,
        )

    def get_collection_stats(self, kb_id: str) -> Dict[str, Any]:
        count = len(self.collections.get(kb_id, []))
        return {"kb_id": kb_id, "chunk_count": count}

    def delete_collection(self, kb_id: str) -> bool:
        if kb_id in self.collections:
            del self.collections[kb_id]
            self.delete_calls.append(kb_id)
            return True
        return False

    def collection_count(self, kb_id: str) -> int:
        return len(self.collections.get(kb_id, []))


# ============================================================================
# 测试工具
# ============================================================================

def _make_page(
    filename: str,
    title: str,
    page_type: str = "concept",
    tags: List[str] = None,
    status: str = "verified",
    body: str = "",
    subdir: str = "concepts",
) -> Dict:
    """构造页面数据"""
    tags_yaml = "\n".join(f"  - {t}" for t in (tags or []))
    content = f"""---
type: {page_type}
title: {title}
tags:
{tags_yaml}
status: {status}
---

# {title}

{body}
"""
    return {"filename": filename, "subdir": subdir, "content": content}


def _make_wiki_dir(base: Path, pages: List[Dict]) -> Path:
    """构造临时 wiki 目录"""
    wiki = base / "wiki"
    for subdir in ("concepts", "entities", "architecture"):
        (wiki / subdir).mkdir(parents=True, exist_ok=True)
    for p in pages:
        subdir = p.get("subdir", "concepts")
        (wiki / subdir / p["filename"]).write_text(p["content"], encoding="utf-8")
    return base


@pytest.fixture
def tmp_wiki_dir():
    """临时 wiki 目录（自动清理）"""
    tmpdir = Path(tempfile.mkdtemp(prefix="scai_m16_test_"))
    yield tmpdir
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def sample_pages():
    """3 个有效页面 + 1 个 draft + 1 个缺 type"""
    return [
        _make_page("rag-vs-wiki.md", "RAG vs LLM Wiki",
                   page_type="concept", tags=["rag", "llm-wiki"],
                   body="RAG vs LLM Wiki comparison content for testing"),
        _make_page("google-okf.md", "Google OKF v0.1",
                   page_type="concept", tags=["standard", "okf"],
                   body="OKF specification details for knowledge base"),
        _make_page("mcp-protocol.md", "MCP Protocol",
                   page_type="entity", tags=["mcp"],
                   body="MCP protocol implementation guide"),
        _make_page("draft-page.md", "Draft Page",
                   page_type="concept", status="draft",
                   body="This is a draft page"),
        _make_page("no-type-page.md", "No Type Page",
                   page_type="",
                   body="This page has no type field"),
    ]


@pytest.fixture
def reader(tmp_wiki_dir, sample_pages):
    """已加载样本页面的 KarpathyWikiReader"""
    _make_wiki_dir(tmp_wiki_dir, sample_pages)
    return KarpathyWikiReader(kb_root=str(tmp_wiki_dir))


# ============================================================================
# G1-G5: WikiIngestPipeline
# ============================================================================

class TestG1IngestAll:
    """TS-G1: 全量灌入"""

    def test_ingest_all_returns_count(self, reader):
        mock_chroma = MockChromaDBManager()
        pipeline = WikiIngestPipeline(reader, mock_chroma, "llm_wiki")

        count = pipeline.ingest_all()

        assert count == 3  # 排除 draft 和 no-type

    def test_ingest_all_chunks_in_collection(self, reader):
        mock_chroma = MockChromaDBManager()
        pipeline = WikiIngestPipeline(reader, mock_chroma, "llm_wiki")
        pipeline.ingest_all()

        stats = mock_chroma.get_collection_stats("llm_wiki")
        assert stats["chunk_count"] == 3

    def test_ingest_all_chunks_have_source_and_type(self, reader):
        mock_chroma = MockChromaDBManager()
        pipeline = WikiIngestPipeline(reader, mock_chroma, "llm_wiki")
        pipeline.ingest_all()

        for chunk in mock_chroma.collections["llm_wiki"]:
            assert chunk.metadata.get("source")
            assert chunk.metadata.get("type")

    def test_ingest_all_none_chromadb(self, reader):
        """ChromaDB=None 时返回 0，不抛异常"""
        pipeline = WikiIngestPipeline(reader, None, "llm_wiki")
        assert pipeline.ingest_all() == 0


class TestG2IngestIncremental:
    """TS-G2: 增量灌入"""

    def test_incremental_adds_only_new(self, reader, tmp_wiki_dir):
        mock_chroma = MockChromaDBManager()
        pipeline = WikiIngestPipeline(reader, mock_chroma, "llm_wiki")
        pipeline.ingest_all()  # 初始 3 条

        # 新增 1 个页面
        new_page = _make_page("new-page.md", "New Page",
                              page_type="concept", tags=["new"],
                              body="A newly added page")
        _make_wiki_dir(tmp_wiki_dir, [new_page])
        reader2 = KarpathyWikiReader(kb_root=str(tmp_wiki_dir))
        pipeline2 = WikiIngestPipeline(reader2, mock_chroma, "llm_wiki")
        pipeline2._indexed_sources = {"rag-vs-wiki", "google-okf", "mcp-protocol"}
        pipeline2._indexed = True

        added = pipeline2.ingest_incremental()

        assert added == 1
        assert mock_chroma.collection_count("llm_wiki") == 4
        assert len(mock_chroma.upsert_calls) >= 1

    def test_incremental_none_chromadb(self, reader):
        pipeline = WikiIngestPipeline(reader, None, "llm_wiki")
        assert pipeline.ingest_incremental() == 0


class TestG3Rebuild:
    """TS-G3: 全量重建"""

    def test_rebuild_deletes_then_ingests(self, reader):
        mock_chroma = MockChromaDBManager()
        pipeline = WikiIngestPipeline(reader, mock_chroma, "llm_wiki")
        pipeline.ingest_all()

        rebuild_count = pipeline.rebuild()

        assert rebuild_count == 3
        assert len(mock_chroma.delete_calls) == 1
        assert mock_chroma.collection_count("llm_wiki") == 3

    def test_rebuild_none_chromadb(self, reader):
        pipeline = WikiIngestPipeline(reader, None, "llm_wiki")
        assert pipeline.rebuild() == 0


class TestG4OKFCompliance:
    """TS-G4: 缺 type 的页面被跳过"""

    def test_no_type_page_skipped(self, reader):
        mock_chroma = MockChromaDBManager()
        pipeline = WikiIngestPipeline(reader, mock_chroma, "llm_wiki")
        pipeline.ingest_all()

        sources = [c.metadata.get("source") for c in mock_chroma.collections["llm_wiki"]]
        assert "no-type-page" not in sources


class TestG5DraftSkipped:
    """TS-G5: draft 页面被跳过"""

    def test_draft_page_skipped(self, reader):
        mock_chroma = MockChromaDBManager()
        pipeline = WikiIngestPipeline(reader, mock_chroma, "llm_wiki")
        pipeline.ingest_all()

        sources = [c.metadata.get("source") for c in mock_chroma.collections["llm_wiki"]]
        assert "draft-page" not in sources


# ============================================================================
# G6-G13: UnifiedRetriever
# ============================================================================

class TestG6NormalRetrieval:
    """TS-G6: 正常检索（L1+L2 融合）"""

    def test_returns_nonempty_results(self, reader):
        mock_chroma = MockChromaDBManager()
        pipeline = WikiIngestPipeline(reader, mock_chroma, "llm_wiki")
        pipeline.ingest_all()
        retriever = UnifiedRetriever(reader, pipeline, mock_chroma, auto_index=False)

        hits = retriever.retrieve("RAG vs LLM Wiki", limit=3)

        assert len(hits) > 0
        for h in hits:
            assert hasattr(h, "content")
            assert hasattr(h, "source")
            assert hasattr(h, "score")

    def test_results_sorted_by_score_desc(self, reader):
        mock_chroma = MockChromaDBManager()
        pipeline = WikiIngestPipeline(reader, mock_chroma, "llm_wiki")
        pipeline.ingest_all()
        retriever = UnifiedRetriever(reader, pipeline, mock_chroma, auto_index=False)

        hits = retriever.retrieve("RAG vs LLM Wiki", limit=3)

        scores = [h.score for h in hits]
        assert scores == sorted(scores, reverse=True)


class TestG7DegradedRetrieval:
    """TS-G7: ChromaDB 不可用时降级为 L1"""

    def test_none_chromadb_returns_l1(self, reader):
        mock_chroma = MockChromaDBManager()
        pipeline = WikiIngestPipeline(reader, mock_chroma, "llm_wiki")
        pipeline.ingest_all()
        retriever = UnifiedRetriever(reader, pipeline, None, auto_index=False)

        hits = retriever.retrieve("RAG", limit=3)

        assert len(hits) > 0  # L1 关键词检索应有结果

    def test_none_chromadb_no_exception(self, reader):
        pipeline = WikiIngestPipeline(reader, None, "llm_wiki")
        retriever = UnifiedRetriever(reader, pipeline, None, auto_index=False)

        # 不应抛异常
        hits = retriever.retrieve("RAG", limit=3)
        assert isinstance(hits, list)


class TestG8IrrelevantQuery:
    """TS-G8: 无关查询返回空或低分"""

    def test_irrelevant_returns_empty_or_low_score(self, reader):
        mock_chroma = MockChromaDBManager()
        pipeline = WikiIngestPipeline(reader, mock_chroma, "llm_wiki")
        pipeline.ingest_all()
        retriever = UnifiedRetriever(reader, pipeline, mock_chroma, auto_index=False)

        hits = retriever.retrieve("今天天气怎么样", limit=3)

        assert len(hits) == 0 or all(h.score < 0.1 for h in hits)


class TestG9AutoIndex:
    """TS-G9: 首次检索时自动触发建索引"""

    def test_auto_index_on_first_retrieve(self, reader):
        mock_chroma = MockChromaDBManager()
        pipeline = WikiIngestPipeline(reader, mock_chroma, "llm_wiki")
        retriever = UnifiedRetriever(reader, pipeline, mock_chroma, auto_index=True)

        assert retriever.is_indexed() is False
        retriever.retrieve("RAG", limit=3)
        assert retriever.is_indexed() is True
        assert mock_chroma.collection_count("llm_wiki") > 0


class TestG10SignatureAlignment:
    """TS-G10: 签名对齐 AppEngine 调用"""

    def test_retrieve_signature(self):
        sig = inspect.signature(UnifiedRetriever.retrieve)
        params = list(sig.parameters.keys())

        assert params == ["self", "query", "limit", "kb_ids"]
        assert sig.parameters["limit"].default == 3
        assert sig.parameters["kb_ids"].default is None


class TestG11KbIdsCompat:
    """TS-G11: kb_ids 参数兼容"""

    def test_kb_ids_none(self, reader):
        mock_chroma = MockChromaDBManager()
        pipeline = WikiIngestPipeline(reader, mock_chroma, "llm_wiki")
        pipeline.ingest_all()
        retriever = UnifiedRetriever(reader, pipeline, mock_chroma, auto_index=False)

        hits = retriever.retrieve("RAG", limit=3, kb_ids=None)
        assert isinstance(hits, list)

    def test_kb_ids_list(self, reader):
        mock_chroma = MockChromaDBManager()
        pipeline = WikiIngestPipeline(reader, mock_chroma, "llm_wiki")
        pipeline.ingest_all()
        retriever = UnifiedRetriever(reader, pipeline, mock_chroma, auto_index=False)

        hits = retriever.retrieve("RAG", limit=3, kb_ids=["some_id"])
        assert isinstance(hits, list)


class TestG12EmptyKnowledgeBase:
    """TS-G12: 空知识库返回空列表"""

    def test_empty_kb_returns_empty(self, tmp_wiki_dir):
        # 创建空 wiki 目录
        (tmp_wiki_dir / "wiki" / "concepts").mkdir(parents=True, exist_ok=True)
        reader_empty = KarpathyWikiReader(kb_root=str(tmp_wiki_dir))
        mock_chroma = MockChromaDBManager()
        pipeline = WikiIngestPipeline(reader_empty, mock_chroma, "llm_wiki")
        retriever = UnifiedRetriever(reader_empty, pipeline, mock_chroma)

        hits = retriever.retrieve("anything", limit=3)

        assert hits == []


class TestG13FusionRanking:
    """TS-G13: L1+L2 双命中加成"""

    def test_dual_hit_scores_higher(self, reader):
        mock_chroma = MockChromaDBManager()
        pipeline = WikiIngestPipeline(reader, mock_chroma, "llm_wiki")
        pipeline.ingest_all()
        retriever = UnifiedRetriever(reader, pipeline, mock_chroma, auto_index=False)

        hits = retriever.retrieve("RAG", limit=3)

        # 找到 rag-vs-wiki 的 score（应该双命中）
        rag_scores = [h.score for h in hits if h.source == "rag-vs-wiki"]
        other_scores = [h.score for h in hits if h.source != "rag-vs-wiki"]

        if rag_scores and other_scores:
            # rag-vs-wiki（双命中）应该 >= 其他单命中
            assert rag_scores[0] >= max(other_scores)
        elif rag_scores:
            # 只有 rag-vs-wiki 命中也算通过
            assert True
        else:
            pytest.fail("rag-vs-wiki 应该命中检索结果")

    def test_fuse_dual_hit_formula(self):
        """直接测试 _fuse 方法的双命中加成公式"""
        from aibridge.rag.unified_retriever import UnifiedRetriever
        # 用最小依赖构造 retriever 实例（仅测试 _fuse）
        class _Stub:
            def is_indexed(self):
                return True
        retriever = UnifiedRetriever.__new__(UnifiedRetriever)

        l1 = [RagHit(content="l1", source="shared", score=0.8)]
        l2 = [RagHit(content="l2", source="shared", score=0.6)]
        result = retriever._fuse(l1, l2, limit=3)

        assert len(result) == 1
        # final = max(0.8, 0.6) + 0.1 * min(0.8, 0.6) = 0.8 + 0.06 = 0.86
        assert result[0].score == round(0.86, 3)

    def test_fuse_single_hit_no_bonus(self):
        """单命中不加成"""
        from aibridge.rag.unified_retriever import UnifiedRetriever
        retriever = UnifiedRetriever.__new__(UnifiedRetriever)

        l1 = [RagHit(content="l1", source="only_l1", score=0.5)]
        l2 = [RagHit(content="l2", source="only_l2", score=0.7)]
        result = retriever._fuse(l1, l2, limit=3)

        assert len(result) == 2
        # 各自保留原 score
        scores = {h.source: h.score for h in result}
        assert scores["only_l1"] == 0.5
        assert scores["only_l2"] == 0.7
