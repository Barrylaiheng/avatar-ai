# -*- coding: utf-8 -*-
"""
SCAI PDD 模块 20 · 文档导入 → Wiki Markdown 灌入管道 pytest 用例

覆盖 10 条 Grill（G1-G10）。
验证 DocumentToWikiImporter 把 PDF/Word/MD/TXT 文档导入为 OKF 合规的 Wiki Markdown 页面。
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


# ============== fixtures ==============

@pytest.fixture
def wiki_root(tmp_path) -> str:
    """每个用例独立的 wiki 根目录。"""
    d = tmp_path / "wiki"
    d.mkdir(parents=True, exist_ok=True)
    # 创建 OKF 骨架
    for sub in ("concepts", "entities", "architecture"):
        (d / sub).mkdir(exist_ok=True)
    (d / "index.md").write_text("---\ntype: index\n---\n\n# Wiki\n", encoding="utf-8")
    (d / "log.md").write_text("---\ntype: log\n---\n\n# Log\n", encoding="utf-8")
    return str(d)


@pytest.fixture
def sample_txt(tmp_path) -> str:
    """创建一个测试 TXT 文件。"""
    p = tmp_path / "产品介绍.txt"
    p.write_text(
        "SCAI 是一款智能客服 AI 系统。\n"
        "支持微信和公众号双渠道。\n"
        "核心功能包括：知识库检索、人设管理、安全拦截。\n"
        "适用于销售场景的客户咨询自动回复。",
        encoding="utf-8",
    )
    return str(p)


@pytest.fixture
def sample_md(tmp_path) -> str:
    """创建一个测试 Markdown 文件（已有 frontmatter）。"""
    p = tmp_path / "销售话术.md"
    p.write_text(
        "---\ntitle: 销售话术\ntype: guide\n---\n\n"
        "# 销售话术\n\n"
        "## 开场白\n客户你好，我是 AI 助手。\n\n"
        "## 产品介绍\nSCAI 是一款智能客服系统。\n\n"
        "## 结束语\n感谢您的咨询。\n",
        encoding="utf-8",
    )
    return str(p)


# ============== G1: TXT 文件导入生成 Wiki Markdown ==============

class TestG1TxtImport:
    def test_txt_imported_to_wiki_markdown(self, wiki_root, sample_txt):
        """G1: TXT 文件导入后生成 OKF 合规的 Wiki Markdown 页面"""
        from aibridge.rag.doc_to_wiki_importer import DocumentToWikiImporter

        importer = DocumentToWikiImporter(wiki_root=wiki_root)
        result = importer.import_document(sample_txt, category="entities")

        assert result.success, f"导入应成功: {result.error}"
        assert result.chunk_count >= 1
        assert os.path.exists(result.wiki_page_path), f"Wiki 页面文件应存在: {result.wiki_page_path}"


# ============== G2: 生成的 Markdown 有 OKF frontmatter ==============

class TestG2OKFFrontmatter:
    def test_generated_page_has_okf_frontmatter(self, wiki_root, sample_txt):
        """G2: 生成的 Markdown 页面含 YAML frontmatter + type 字段"""
        from aibridge.rag.doc_to_wiki_importer import DocumentToWikiImporter

        importer = DocumentToWikiImporter(wiki_root=wiki_root)
        result = importer.import_document(sample_txt, category="entities")

        content = Path(result.wiki_page_path).read_text(encoding="utf-8")
        assert content.startswith("---"), "必须以 YAML frontmatter 开头"
        assert "type: note" in content, "frontmatter 必须包含 type: note（OKF v0.1 必填）"
        assert "title:" in content, "frontmatter 必须包含 title"
        assert "tags:" in content, "frontmatter 必须包含 tags"
        assert "timestamp:" in content, "frontmatter 必须包含 timestamp"
        assert "source_file:" in content, "frontmatter 必须包含 source_file"


# ============== G3: 写入正确子目录 ==============

class TestG3CorrectSubdir:
    def test_entity_category_written_to_entities_dir(self, wiki_root, sample_txt):
        """G3: category=entities 时写入 entities/ 子目录"""
        from aibridge.rag.doc_to_wiki_importer import DocumentToWikiImporter

        importer = DocumentToWikiImporter(wiki_root=wiki_root)
        result = importer.import_document(sample_txt, category="entities")

        assert "entities" in result.wiki_page_path.replace("\\", "/"), \
            f"页面应写入 entities/ 子目录: {result.wiki_page_path}"

    def test_concept_category_written_to_concepts_dir(self, wiki_root, sample_txt):
        """G3a: category=concepts 时写入 concepts/ 子目录"""
        from aibridge.rag.doc_to_wiki_importer import DocumentToWikiImporter

        importer = DocumentToWikiImporter(wiki_root=wiki_root)
        result = importer.import_document(sample_txt, category="concepts")

        assert "concepts" in result.wiki_page_path.replace("\\", "/"), \
            f"页面应写入 concepts/ 子目录: {result.wiki_page_path}"


# ============== G4: log.md 更新 ==============

class TestG4LogUpdate:
    def test_log_md_updated_after_import(self, wiki_root, sample_txt):
        """G4: 导入后 log.md 追加导入记录"""
        from aibridge.rag.doc_to_wiki_importer import DocumentToWikiImporter

        log_before = Path(wiki_root, "log.md").read_text(encoding="utf-8")

        importer = DocumentToWikiImporter(wiki_root=wiki_root)
        importer.import_document(sample_txt, category="entities")

        log_after = Path(wiki_root, "log.md").read_text(encoding="utf-8")
        assert len(log_after) > len(log_before), "log.md 应追加内容"
        assert "产品介绍" in log_after, "log.md 应包含源文件名"
        assert "文档导入" in log_after, "log.md 应包含导入类型标记"


# ============== G5: 幂等（重复导入跳过或版本化） ==============

class TestG5Idempotent:
    def test_duplicate_import_skipped_or_versioned(self, wiki_root, sample_txt):
        """G5: 相同文件重复导入时不覆盖原页面（跳过或创建新版本）"""
        from aibridge.rag.doc_to_wiki_importer import DocumentToWikiImporter

        importer = DocumentToWikiImporter(wiki_root=wiki_root)
        result1 = importer.import_document(sample_txt, category="entities")
        assert result1.success

        result2 = importer.import_document(sample_txt, category="entities")
        assert result2.success, "第二次导入也应成功"
        # 要么跳过（skipped=True），要么创建新版本（路径不同）
        assert result2.skipped or result1.wiki_page_path != result2.wiki_page_path, \
            "重复导入必须跳过或创建新版本，不能覆盖原文件"


# ============== G6: Markdown 文件导入 ==============

class TestG6MarkdownImport:
    def test_markdown_imported(self, wiki_root, sample_md):
        """G6: Markdown 文件也能导入"""
        from aibridge.rag.doc_to_wiki_importer import DocumentToWikiImporter

        importer = DocumentToWikiImporter(wiki_root=wiki_root)
        result = importer.import_document(sample_md, category="concepts")

        assert result.success, f"Markdown 导入应成功: {result.error}"
        content = Path(result.wiki_page_path).read_text(encoding="utf-8")
        assert "销售话术" in content, "导入内容应包含原文标题"


# ============== G7: 文件不存在时返回错误 ==============

class TestG7FileNotFound:
    def test_nonexistent_file_returns_error(self, wiki_root):
        """G7: 文件不存在时返回 error"""
        from aibridge.rag.doc_to_wiki_importer import DocumentToWikiImporter

        importer = DocumentToWikiImporter(wiki_root=wiki_root)
        result = importer.import_document("/nonexistent/file.pdf", category="entities")

        assert not result.success
        assert "不存在" in result.error or "not exist" in result.error.lower()


# ============== G8: 非法 category 拒绝 ==============

class TestG8InvalidCategory:
    def test_invalid_category_rejected(self, wiki_root, sample_txt):
        """G8: 非法 category 返回错误"""
        from aibridge.rag.doc_to_wiki_importer import DocumentToWikiImporter

        importer = DocumentToWikiImporter(wiki_root=wiki_root)
        result = importer.import_document(sample_txt, category="invalid_category")

        assert not result.success
        assert "非法" in result.error or "invalid" in result.error.lower()


# ============== G9: 批量导入 ==============

class TestG9BatchImport:
    def test_import_directory(self, wiki_root, tmp_path):
        """G9: import_directory 批量导入目录下所有文档"""
        from aibridge.rag.doc_to_wiki_importer import DocumentToWikiImporter

        # 创建多个文件
        (tmp_path / "a.txt").write_text("文档 A 内容", encoding="utf-8")
        (tmp_path / "b.md").write_text("# 文档 B\n正文内容", encoding="utf-8")
        (tmp_path / "c.txt").write_text("文档 C 内容", encoding="utf-8")
        # 非文档文件应被忽略
        (tmp_path / "ignore.json").write_text("{}", encoding="utf-8")

        importer = DocumentToWikiImporter(wiki_root=wiki_root)
        results = importer.import_directory(str(tmp_path), category="entities")

        assert len(results) == 3, f"应导入 3 个文档（忽略 json），实际: {len(results)}"
        successful = [r for r in results if r.success]
        assert len(successful) == 3, "全部 3 个文档应导入成功"


# ============== G10: 双向链接 ==============

class TestG10BiDirectionalLinks:
    def test_page_contains_bidirectional_links(self, wiki_root, sample_txt):
        """G10: 生成的页面包含双向链接 [[index]] 和 [[log]]"""
        from aibridge.rag.doc_to_wiki_importer import DocumentToWikiImporter

        importer = DocumentToWikiImporter(wiki_root=wiki_root)
        result = importer.import_document(sample_txt, category="entities")

        content = Path(result.wiki_page_path).read_text(encoding="utf-8")
        assert "[[index]]" in content, "页面应包含 [[index]] 双向链接"
        assert "[[log]]" in content, "页面应包含 [[log]] 双向链接"
