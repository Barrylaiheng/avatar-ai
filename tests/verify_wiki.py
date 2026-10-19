"""
LLM Wiki 三层架构 + 混合检索验证脚本

验证内容：
1. Wiki 三层架构（Schema/Wiki/Raw Sources）
2. 双用途知识条目（技术层 + 内容层）
3. index.md 自动维护
4. 双向链接管理
5. 混合检索（Wiki 过滤 + 向量语义）
6. Lint 健康检查
"""
import sys
import os
import tempfile
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aibridge.rag.wiki_manager import (
    LLMWikiManager, DualPurposeEntry, PageType, EntryStatus,
)
from aibridge.rag.hybrid_retriever import HybridRetriever, HybridSearchResultset


def create_test_wiki() -> tuple:
    """创建测试用 Wiki（临时目录）"""
    tmp_dir = tempfile.mkdtemp(prefix="aibridge_wiki_test_")
    wiki = LLMWikiManager(wiki_root=tmp_dir)
    return wiki, tmp_dir


def cleanup_wiki(tmp_dir: str):
    """清理临时目录"""
    if os.path.exists(tmp_dir):
        shutil.rmtree(tmp_dir)


def test_three_layer_structure():
    """测试 1: 三层架构目录结构"""
    print("\n--- 测试 1: 三层架构目录结构 ---")
    wiki, tmp_dir = create_test_wiki()

    try:
        # Schema 层
        schema_path = os.path.join(tmp_dir, "kb_schema.md")
        assert os.path.exists(schema_path), "Schema 层应存在"
        print(f"  ✓ Schema 层: kb_schema.md")

        # Wiki 层
        entries_dir = os.path.join(tmp_dir, "entries")
        index_path = os.path.join(tmp_dir, "index.md")
        log_path = os.path.join(tmp_dir, "log.md")
        assert os.path.exists(entries_dir), "entries 目录应存在"
        assert os.path.exists(index_path), "index.md 应存在"
        assert os.path.exists(log_path), "log.md 应存在"
        print(f"  ✓ Wiki 层: entries/ + index.md + log.md")

        # Raw Sources 层
        raw_dir = os.path.join(tmp_dir, "raw_sources")
        assert os.path.exists(raw_dir), "raw_sources 目录应存在"
        print(f"  ✓ Raw Sources 层: raw_sources/")

        return wiki, tmp_dir
    except Exception as e:
        cleanup_wiki(tmp_dir)
        raise e


def test_dual_purpose_entry(wiki: LLMWikiManager):
    """测试 2: 双用途知识条目"""
    print("\n--- 测试 2: 双用途知识条目 ---")

    entry = DualPurposeEntry(
        entry_id="KB-01-001",
        title="什么是 RAG 检索增强生成",
        page_type=PageType.CONCEPT,
        category="ai_engine",
        stage="stage_6",
        tags=["rag", "检索", "embedding"],
        content_body="""RAG（Retrieval-Augmented Generation）是一种结合检索和生成的技术。

## 核心原理
1. 用户提问
2. 从知识库检索相关文档
3. 将检索结果作为上下文送给 LLM
4. LLM 基于上下文生成回答

## 代码示例
```python
results = chromadb.query(query_texts=[query], n_results=3)
```

## 注意事项
- 中文场景需用 bge-small-zh-v1.5 模型
- 检索文本要去掉代码块噪音
""",
        summary="RAG 是结合检索和生成的 AI 技术，让 LLM 基于知识库回答问题",
    )

    # 验证技术层
    assert "RAG" in entry.search_text, "search_text 应包含 RAG"
    assert "```" not in entry.search_text, "search_text 应去除代码块"
    print(f"  ✓ 技术层 search_text: {len(entry.search_text)} 字符（已去代码块）")

    # 验证内容层
    assert "```python" in entry.content_body, "content_body 应保留代码块"
    assert len(entry.content_body) > len(entry.search_text), "content_body 应更长"
    print(f"  ✓ 内容层 content_body: {len(entry.content_body)} 字符（含代码块）")
    print(f"  ✓ 摘要 summary: {entry.summary[:30]}...")

    return entry


def test_ingest_and_index(wiki: LLMWikiManager, entry: DualPurposeEntry):
    """测试 3: Ingest + index.md 自动维护"""
    print("\n--- 测试 3: Ingest + index.md 自动维护 ---")

    # Ingest
    success = wiki.ingest(entry)
    assert success, "Ingest 应成功"

    # 验证 MD 文件生成
    entry_file = os.path.join(wiki.get_root_path(), "entries", "KB-01-001.md")
    assert os.path.exists(entry_file), "条目 MD 文件应生成"
    print(f"  ✓ 条目 MD 文件生成: KB-01-001.md")

    # 验证 index.md 更新
    index_content = open(os.path.join(wiki.get_root_path(), "index.md"), encoding="utf-8").read()
    assert "KB-01-001" in index_content, "index.md 应包含新条目"
    assert "什么是 RAG 检索增强生成" in index_content, "index.md 应包含标题"
    print(f"  ✓ index.md 自动更新")

    # 验证 log.md 记录
    log_content = open(os.path.join(wiki.get_root_path(), "log.md"), encoding="utf-8").read()
    assert "INGEST" in log_content, "log.md 应记录 INGEST 操作"
    assert "KB-01-001" in log_content, "log.md 应记录条目 ID"
    print(f"  ✓ log.md 操作日志记录")

    # 验证缓存
    queried = wiki.query("KB-01-001")
    assert queried is not None, "查询应返回条目"
    assert queried.title == entry.title, "标题应匹配"
    print(f"  ✓ 缓存查询成功")


def test_bilinks(wiki: LLMWikiManager):
    """测试 4: 双向链接管理"""
    print("\n--- 测试 4: 双向链接管理 ---")

    # 创建第二个条目，链接到 KB-01-001
    entry2 = DualPurposeEntry(
        entry_id="KB-01-002",
        title="Embedding 模型选型",
        page_type=PageType.METHODOLOGY,
        category="ai_engine",
        stage="stage_6",
        tags=["embedding", "模型选型"],
        related=["KB-01-001"],  # 链接到第一个条目
        content_body="bge-small-zh-v1.5 是中文 Embedding 的优选模型。",
        summary="中文 Embedding 模型选型经验",
    )

    wiki.ingest(entry2)
    print(f"  ✓ 新增条目 KB-01-002，related=[KB-01-001]")

    # 验证反向链接：KB-01-001 应自动添加 KB-01-002 到 related
    entry1 = wiki.query("KB-01-001")
    assert "KB-01-002" in entry1.related, "反向链接应自动建立"
    print(f"  ✓ 反向链接自动建立: KB-01-001.related 包含 KB-01-002")

    # 验证 get_backlinks
    backlinks = wiki.get_backlinks("KB-01-001")
    assert "KB-01-002" in backlinks, "get_backlinks 应返回反向链接"
    print(f"  ✓ get_backlinks: {backlinks}")

    # 验证 Markdown 中的双向链接格式
    entry2_md = open(
        os.path.join(wiki.get_root_path(), "entries", "KB-01-002.md"),
        encoding="utf-8"
    ).read()
    assert "[[KB-01-001]]" in entry2_md, "MD 文件应包含 [[KB-01-001]] 双向链接"
    print(f"  ✓ Markdown 双向链接格式: [[KB-01-001]]")


def test_markdown_roundtrip(wiki: LLMWikiManager):
    """测试 5: Markdown 序列化/反序列化"""
    print("\n--- 测试 5: Markdown 序列化/反序列化 ---")

    original = DualPurposeEntry(
        entry_id="KB-02-001",
        title="DeepSeek API 配置",
        page_type=PageType.PROCESS,
        category="llm",
        stage="stage_4",
        tags=["deepseek", "api", "配置"],
        related=["KB-01-001"],
        content_body="配置 DeepSeek API 需要：\n1. 申请 API Key\n2. 设置 Base URL\n3. 选择模型",
        summary="DeepSeek API 配置步骤",
    )

    # 序列化为 Markdown
    md = original.to_markdown()
    assert "---" in md, "应有 frontmatter"
    assert "id: KB-02-001" in md, "应有 ID"
    assert "page_type: process" in md, "应有 page_type"
    assert "[[KB-01-001]]" in md, "应有双向链接"
    print(f"  ✓ 序列化为 Markdown: {len(md)} 字符")

    # 反序列化
    restored = DualPurposeEntry.from_markdown(md)
    assert restored.entry_id == original.entry_id, "ID 应匹配"
    assert restored.title == original.title, "标题应匹配"
    assert restored.page_type == original.page_type, "page_type 应匹配"
    assert restored.category == original.category, "category 应匹配"
    assert restored.stage == original.stage, "stage 应匹配"
    assert "KB-01-001" in restored.related, "related 应匹配"
    print(f"  ✓ 反序列化恢复: {restored.entry_id} ({restored.title})")


def test_hybrid_retrieval(wiki: LLMWikiManager):
    """测试 6: 混合检索"""
    print("\n--- 测试 6: 混合检索 ---")

    # 添加更多测试条目
    entries = [
        DualPurposeEntry(
            entry_id="KB-03-001",
            title="服务器部署流程",
            page_type=PageType.PROCESS,
            category="deployment",
            stage="stage_3",
            tags=["部署", "服务器", "linux"],
            content_body="服务器部署需要配置 nginx、flask、ssl 证书等步骤",
            summary="服务器部署完整流程",
        ),
        DualPurposeEntry(
            entry_id="KB-04-001",
            title="WCF 微信接入",
            page_type=PageType.PROCESS,
            category="wechat",
            stage="stage_7",
            tags=["wcf", "微信", "接入"],
            content_body="WCF 接入微信需要低版本微信和 wcferry SDK",
            summary="WCF 微信接入配置",
        ),
        DualPurposeEntry(
            entry_id="KB-07-001",
            title="知识蒸馏方法论",
            page_type=PageType.METHODOLOGY,
            category="methodology",
            stage="stage_6",
            tags=["方法论", "蒸馏", "知识"],
            content_body="五步蒸馏法：盘点→分类→提炼→入库→验证",
            summary="知识蒸馏的五步方法论",
        ),
    ]
    for e in entries:
        wiki.ingest(e)

    # 创建混合检索器（无 ChromaDB，降级为关键词匹配）
    retriever = HybridRetriever(wiki_manager=wiki, chromadb_manager=None)

    # 检索 1：关于 RAG
    results = retriever.retrieve(query="RAG 检索", top_k=3)
    assert len(results.results) > 0, "应有检索结果"
    top_result = results.results[0]
    assert "RAG" in top_result.entry.title, "Top-1 应是 RAG 相关"
    print(f"  ✓ 检索 'RAG 检索': Top-1 = {top_result.entry.entry_id} (score={top_result.score})")

    # 检索 2：关于部署
    results = retriever.retrieve(query="服务器部署", top_k=3)
    top_result = results.results[0]
    assert "部署" in top_result.entry.title, "Top-1 应是部署相关"
    print(f"  ✓ 检索 '服务器部署': Top-1 = {top_result.entry.entry_id} (score={top_result.score})")

    # 检索 3：按分类过滤
    results = retriever.retrieve(query="方法论", top_k=3, category="methodology")
    for r in results.results:
        assert r.entry.category == "methodology", "应只返回 methodology 分类"
    print(f"  ✓ 按分类过滤: methodology 返回 {len(results.results)} 条")

    # 检索 4：按阶段过滤
    results = retriever.retrieve(query="配置", top_k=3, stage="stage_4")
    for r in results.results:
        assert r.entry.stage == "stage_4", "应只返回 stage_4 阶段"
    print(f"  ✓ 按阶段过滤: stage_4 返回 {len(results.results)} 条")


def test_lint(wiki: LLMWikiManager):
    """测试 7: Lint 健康检查"""
    print("\n--- 测试 7: Lint 健康检查 ---")

    # 添加一个孤儿条目（没有反向链接）
    orphan = DualPurposeEntry(
        entry_id="KB-09-001",
        title="Wiki 架构感知",
        page_type=PageType.METHODOLOGY,
        category="wiki",
        stage="stage_6",
        tags=["wiki", "架构"],
        content_body="LLM Wiki 三层架构的经验总结",
        summary="Wiki 架构设计经验",
    )
    wiki.ingest(orphan)

    # 添加一个引用不存在条目的条目
    broken_ref = DualPurposeEntry(
        entry_id="KB-09-002",
        title="测试缺失引用",
        page_type=PageType.REFERENCE,
        category="wiki",
        related=["KB-99-999"],  # 不存在的条目
        content_body="这个条目引用了不存在的 KB-99-999",
        summary="测试缺失引用",
    )
    wiki.ingest(broken_ref)

    lint_result = wiki.lint()

    print(f"  ✓ 总条目数: {lint_result['total_entries']}")
    print(f"  ✓ 孤儿条目: {lint_result['orphans']}")
    print(f"  ✓ 缺失引用: {len(lint_result['missing_refs'])} 个")
    print(f"  ✓ 过时条目: {lint_result['deprecated']}")
    print(f"  ✓ 健康状态: {'健康' if lint_result['healthy'] else '有问题'}")

    assert "KB-09-001" in lint_result["orphans"], "KB-09-001 应为孤儿"
    assert len(lint_result["missing_refs"]) > 0, "应有缺失引用"


def test_stats(wiki: LLMWikiManager):
    """测试 8: 统计信息"""
    print("\n--- 测试 8: 统计信息 ---")

    stats = wiki.get_stats()

    print(f"  ✓ 总条目数: {stats['total_entries']}")
    print(f"  ✓ 活跃条目: {stats['active_entries']}")
    print(f"  ✓ 分类: {stats['categories']}")
    print(f"  ✓ 页面类型: {stats['page_types']}")

    assert stats["total_entries"] > 0, "应有条目"
    assert "ai_engine" in stats["categories"], "应有 ai_engine 分类"


if __name__ == "__main__":
    print("=" * 60)
    print("AI Bridge - LLM Wiki 三层架构 + 混合检索 验证")
    print("=" * 60)

    wiki = None
    tmp_dir = None

    try:
        # 测试 1: 三层架构
        wiki, tmp_dir = test_three_layer_structure()

        # 测试 2: 双用途条目
        entry = test_dual_purpose_entry(wiki)

        # 测试 3: Ingest + index
        test_ingest_and_index(wiki, entry)

        # 测试 4: 双向链接
        test_bilinks(wiki)

        # 测试 5: Markdown roundtrip
        test_markdown_roundtrip(wiki)

        # 测试 6: 混合检索
        test_hybrid_retrieval(wiki)

        # 测试 7: Lint
        test_lint(wiki)

        # 测试 8: 统计
        test_stats(wiki)

        print("\n" + "=" * 60)
        print("✓ 全部验证通过")

    except AssertionError as e:
        print(f"\n✗ 验证失败: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ 异常: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        if tmp_dir:
            cleanup_wiki(tmp_dir)
            print(f"\n(已清理临时目录: {tmp_dir})")

    sys.exit(0)
