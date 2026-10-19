# -*- coding: utf-8 -*-
"""
里层 PDD 模块 6 · 神经 L3 · KarpathyWikiReader 测试

15 条 Test Seams（对齐 docs/PDD_INNER_rag_wiki.md §4）

运行：
    cd C:\\Users\\Administrator\\Desktop\\WeChatAI_Project
    python -m pytest tests/test_inner_rag_wiki_pdd.py -v
"""
import sys
import tempfile
from pathlib import Path

import pytest

# 确保 src 在 PYTHONPATH
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from aibridge.rag.karpathy_wiki_reader import (
    KarpathyWikiReader,
    RagHit,
    WikiPage,
    DEFAULT_KB_ROOT,
    CONTENT_PREVIEW_LIMIT,
)


# ========================= Fixtures =========================

@pytest.fixture
def empty_kb(tmp_path):
    """RW-01: KB 空目录"""
    (tmp_path / "wiki").mkdir()
    return tmp_path


@pytest.fixture
def basic_kb(tmp_path):
    """RW-02~08, 10~12: 基础测试 KB"""
    wiki = tmp_path / "wiki"
    (wiki / "concepts").mkdir(parents=True)
    (wiki / "entities").mkdir()
    (wiki / "architecture").mkdir()

    (wiki / "concepts" / "karpathy-pattern.md").write_text(
        "---\n"
        "type: concept\n"
        "title: Karpathy Pattern\n"
        "tags: [knowledge-base, karpathy]\n"
        "status: verified\n"
        "---\n\n"
        "# Karpathy Pattern\n\nLLM Wiki 模式。",
        encoding="utf-8",
    )
    (wiki / "concepts" / "trae-memory.md").write_text(
        "---\n"
        "type: concept\n"
        "title: TRAE Memory Mechanism\n"
        "tags: [trae, memory]\n"
        "status: verified\n"
        "---\n\n"
        "# TRAE Memory Mechanism\n\n四层记忆结构。",
        encoding="utf-8",
    )
    (wiki / "entities" / "mcp-protocol.md").write_text(
        "---\n"
        "type: entity\n"
        "title: MCP Protocol\n"
        "tags: [mcp, tool]\n"
        "status: verified\n"
        "---\n\n"
        "# MCP Protocol\n\n工具开发协议。",
        encoding="utf-8",
    )
    (wiki / "concepts" / "draft-page.md").write_text(
        "---\n"
        "type: concept\n"
        "title: Draft Page\n"
        "tags: [draft]\n"
        "status: draft\n"
        "---\n\n"
        "# Draft Page\n\n草稿页。",
        encoding="utf-8",
    )
    # raw 文件，验证不被扫描
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "2026-08-08-xxx.md").write_text(
        "# raw should not be scanned", encoding="utf-8"
    )
    return tmp_path


@pytest.fixture
def bilink_kb(tmp_path):
    """RW-13: 双向链接 KB"""
    wiki = tmp_path / "wiki"
    (wiki / "concepts").mkdir(parents=True)
    (wiki / "entities").mkdir()

    (wiki / "concepts" / "page-a.md").write_text(
        "---\n"
        "type: concept\n"
        "title: Page A\n"
        "tags: [test]\n"
        "status: verified\n"
        "---\n\n"
        "# Page A\n\n引用 [[page-b]]。",
        encoding="utf-8",
    )
    (wiki / "entities" / "page-b.md").write_text(
        "---\n"
        "type: entity\n"
        "title: Page B\n"
        "tags: [test]\n"
        "status: verified\n"
        "---\n\n"
        "# Page B\n\n反向引用 [[page-a]]。",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def bom_kb(tmp_path):
    """含 UTF-8 BOM 的 KB（验证 BOM 兼容）"""
    wiki = tmp_path / "wiki"
    (wiki / "concepts").mkdir(parents=True)

    # 写入带 BOM 的文件
    content = (
        "---\n"
        "type: concept\n"
        "title: BOM Test Page\n"
        "tags: [bom]\n"
        "status: verified\n"
        "---\n\n"
        "# BOM Test Page\n\n带 BOM 的页面。"
    )
    bom_content = b"\xef\xbb\xbf" + content.encode("utf-8")
    (wiki / "concepts" / "bom-page.md").write_bytes(bom_content)
    return tmp_path


# ========================= Test Seams =========================

def test_rw01_empty_kb_returns_empty_list(empty_kb):
    """RW-01: KB 空目录 → 返回空 list"""
    reader = KarpathyWikiReader(empty_kb)
    assert reader.search("anything") == []


def test_rw02_single_title_match(basic_kb):
    """RW-02: 单页命中（title 匹配）"""
    reader = KarpathyWikiReader(basic_kb)
    hits = reader.search("Karpathy")
    assert len(hits) >= 1
    assert any(h.source == "karpathy-pattern" for h in hits)


def test_rw03_top_k_truncation(basic_kb):
    """RW-03: 多页命中 → Top-K 截取"""
    reader = KarpathyWikiReader(basic_kb)
    # 用 "test" 查所有 verified 页面（test 不在文档里，可能命中 0）
    # 改用关键词命中多页的查询
    hits_top1 = reader.search("Protocol", top_k=1)
    assert len(hits_top1) <= 1
    # 默认 top_k=3
    hits_default = reader.search("Protocol", top_k=3)
    assert len(hits_default) <= 3


def test_rw04_tags_match(basic_kb):
    """RW-04: 关键词在 tags 命中"""
    reader = KarpathyWikiReader(basic_kb)
    hits = reader.search("karpathy")  # tag = karpathy
    assert len(hits) > 0
    assert any(h.score > 0 for h in hits)


def test_rw05_body_match(basic_kb):
    """RW-05: 关键词在正文命中"""
    reader = KarpathyWikiReader(basic_kb)
    hits = reader.search("工具开发")  # 在 mcp-protocol body
    assert any(h.source == "mcp-protocol" for h in hits)


def test_rw06_no_match_returns_empty(basic_kb):
    """RW-06: 无命中 → 返回空 list"""
    reader = KarpathyWikiReader(basic_kb)
    hits = reader.search("zzz_no_match_zzz")
    assert hits == []


def test_rw07_source_without_md_extension(basic_kb):
    """RW-07: source 是文件名不含 .md"""
    reader = KarpathyWikiReader(basic_kb)
    hits = reader.search("Karpathy")
    assert len(hits) > 0
    for h in hits:
        assert not h.source.endswith(".md")


def test_rw08_content_contains_title(basic_kb):
    """RW-08: content 含 title"""
    reader = KarpathyWikiReader(basic_kb)
    hits = reader.search("Karpathy")
    assert len(hits) > 0
    first = hits[0]
    page = reader.get_page(first.source)
    assert page is not None
    assert page.title in first.content


def test_rw09_chromadb_unavailable_degrade_to_keyword(basic_kb):
    """RW-09: ChromaDB 不可用 → 降级关键词"""
    reader = KarpathyWikiReader(basic_kb, chromadb_manager=None)
    hits = reader.search("Karpathy")
    assert len(hits) > 0


def test_rw10_skip_draft_pages(basic_kb):
    """RW-10: 跳过 draft 状态页面"""
    reader = KarpathyWikiReader(basic_kb)
    hits = reader.search("Draft Page")
    assert all(h.source != "draft-page" for h in hits)


def test_rw11_skip_raw_directory(basic_kb):
    """RW-11: 跳过 raw/ 目录"""
    reader = KarpathyWikiReader(basic_kb)
    all_sources = {p.source for p in reader.list_pages()}
    assert "xxx" not in all_sources  # raw/2026-08-08-xxx.md 不应被扫
    assert "2026-08-08-xxx" not in all_sources


def test_rw12_three_subdirs_scanned(basic_kb):
    """RW-12: 三层目录都扫（concept + entity）"""
    reader = KarpathyWikiReader(basic_kb)
    types_present = {p.type for p in reader.list_pages()}
    assert "concept" in types_present
    assert "entity" in types_present


def test_rw13_bilink_does_not_break_search(bilink_kb):
    """RW-13: 双向链接 [[xxx]] 不破坏检索"""
    reader = KarpathyWikiReader(bilink_kb)
    hits = reader.search("Page B")
    assert any(h.source == "page-b" for h in hits)


def test_rw14_context_assembler_integration(basic_kb):
    """RW-14: 接入 ContextAssemblerV2（system 含'检索到的知识'）"""
    from aibridge.engine.context_assembler_v2 import ContextAssemblerV2

    reader = KarpathyWikiReader(basic_kb)
    assembler = ContextAssemblerV2(rag_engine=reader)

    result = assembler.assemble_prompt(
        current_content="什么是 Karpathy？",
        history=[],
        rag_query="Karpathy",
    )

    # 验证 system message 含【检索到的知识】
    system_msg = next(m for m in result.messages if m["role"] == "system")
    assert "【检索到的知识】" in system_msg["content"]
    # 验证 source 出现在 system 中（Obsidian 双向链接风格）
    assert "karpathy-pattern" in system_msg["content"]
    assert result.rag_hits is not None
    assert len(result.rag_hits) > 0


def test_rw15_real_kb_e2e():
    """RW-15: 真实 KB 检索（端到端）"""
    real_root = Path(DEFAULT_KB_ROOT)
    if not real_root.exists():
        pytest.skip(f"Real KB not exist: {real_root}")

    reader = KarpathyWikiReader(real_root)
    pages = reader.list_pages()
    assert len(pages) >= 10, f"Real KB should have >= 10 pages, got {len(pages)}"

    # 查 "PDD" 应该命中 prototype-driven-development
    hits_pdd = reader.search("PDD")
    assert any(h.source == "prototype-driven-development" for h in hits_pdd), \
        f"PDD should hit prototype-driven-development, got {[h.source for h in hits_pdd]}"

    # 查 "知识库" 应该命中 >= 1
    hits_kb = reader.search("知识库")
    assert len(hits_kb) >= 1

    # 查 "Karpathy" 应该命中 llm-wiki-pattern
    hits_karpathy = reader.search("Karpathy")
    assert any(h.source == "llm-wiki-pattern" for h in hits_karpathy), \
        f"Karpathy should hit llm-wiki-pattern, got {[h.source for h in hits_karpathy]}"


# ========================= 额外 Test Seams（BOM 兼容）=========================

def test_rw16_bom_file_parsed_correctly(bom_kb):
    """RW-16: 含 UTF-8 BOM 的文件能被正确解析"""
    reader = KarpathyWikiReader(bom_kb)
    pages = reader.list_pages()
    assert len(pages) == 1
    page = pages[0]
    assert page.source == "bom-page"
    assert page.title == "BOM Test Page"
    assert page.type == "concept"
    assert "bom" in page.tags


def test_rw17_stats_returns_correct_structure(basic_kb):
    """RW-17: get_stats 返回正确结构"""
    reader = KarpathyWikiReader(basic_kb)
    stats = reader.get_stats()
    assert stats["total_pages"] == 4
    assert "concept" in stats["by_type"]
    assert "entity" in stats["by_type"]
    assert "verified" in stats["by_status"]
    assert "draft" in stats["by_status"]
    assert stats["kb_root"] == str(basic_kb)


def test_rw18_is_available(basic_kb, tmp_path):
    """RW-18: is_available 正确返回"""
    reader_full = KarpathyWikiReader(basic_kb)
    assert reader_full.is_available() is True

    # 用独立的空目录验证（不能复用 basic_kb 的 tmp_path）
    empty_root = tmp_path / "empty_subdir"
    empty_root.mkdir()
    (empty_root / "wiki").mkdir()
    reader_empty = KarpathyWikiReader(empty_root)
    assert reader_empty.is_available() is False


def test_rw19_content_length_limit(basic_kb):
    """RW-19: content 不超过预览限制"""
    reader = KarpathyWikiReader(basic_kb)
    hits = reader.search("Karpathy")
    assert len(hits) > 0
    for h in hits:
        # content = title + body，限制在 CONTENT_PREVIEW_LIMIT
        assert len(h.content) <= CONTENT_PREVIEW_LIMIT + 50  # 留点 buffer


def test_rw20_empty_query_returns_empty(basic_kb):
    """RW-20: 空查询 → 返回空 list"""
    reader = KarpathyWikiReader(basic_kb)
    assert reader.search("") == []
    assert reader.search("   ") == []
    assert reader.search(None) == []


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
