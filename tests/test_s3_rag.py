"""
S3 RAG 集成验证测试

测试场景：
1. 创建知识库
2. 上传文档
3. 添加知识条目（LLM Wiki 格式）
4. RAG 检索
5. 多知识库检索
6. LLM Wiki 格式验证
7. 测试数据清理
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from aibridge.database.database_manager import DatabaseManager
from aibridge.config.config_manager import ConfigManager
from aibridge.rag.knowledge_base_manager import KnowledgeBaseManager, KnowledgeEntry, PageType
from aibridge.rag.rag_engine import RAGEngine
from aibridge.engine.intent_router import IntentType


def _get_managers():
    """获取管理器实例"""
    db_manager = DatabaseManager()
    config_manager = ConfigManager()
    return db_manager, config_manager


def test_create_kb():
    """测试创建知识库"""
    db_manager, config_manager = _get_managers()
    kb_manager = KnowledgeBaseManager(db_manager, config_manager)

    kb_id = kb_manager.create_knowledge_base("产品知识库", "用于存储产品相关知识")
    assert kb_id is not None
    assert kb_id.startswith("kb_")

    kb_info = kb_manager.get_knowledge_base(kb_id)
    assert kb_info is not None
    assert kb_info.get("kb_name") == "产品知识库" or kb_info.get("name") == "产品知识库"

    all_kbs = kb_manager.get_knowledge_bases()
    assert len(all_kbs) >= 1

    kb_manager.delete_knowledge_base(kb_id)
    print("✓ 测试 1 通过：创建知识库")


def test_upload_document():
    """测试上传文档"""
    db_manager, config_manager = _get_managers()
    kb_manager = KnowledgeBaseManager(db_manager, config_manager)

    kb_id = kb_manager.create_knowledge_base("文档测试库", "用于测试文档上传")
    assert kb_id is not None

    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
        f.write("这是一个测试文档的内容。\n用于测试文档上传功能。")
        temp_path = f.name

    try:
        result = kb_manager.upload_document(kb_id, temp_path)
        assert result is True
        print("✓ 测试 2 通过：上传文档")
    finally:
        os.unlink(temp_path)
        kb_manager.delete_knowledge_base(kb_id)


def test_add_knowledge_entry():
    """测试添加知识条目"""
    db_manager, config_manager = _get_managers()
    kb_manager = KnowledgeBaseManager(db_manager, config_manager)

    kb_id = kb_manager.create_knowledge_base("知识条目测试库", "用于测试知识条目")
    assert kb_id is not None

    entry = KnowledgeEntry(
        entry_id="price_001",
        kb_id=kb_id,
        title="产品价格",
        content="我们的产品价格为 999 元，包含一年免费升级。",
        page_type=PageType.QUESTION,
        category="pricing"
    )

    result = kb_manager.add_knowledge_entry(kb_id, entry)
    assert result is True

    print("✓ 测试 3 通过：添加知识条目")


def test_rag_retrieval():
    """测试 RAG 检索"""
    db_manager, config_manager = _get_managers()
    kb_manager = KnowledgeBaseManager(db_manager, config_manager)
    rag_engine = RAGEngine(kb_manager, config_manager)

    kb_id = kb_manager.create_knowledge_base("检索测试库", "用于测试 RAG 检索")
    assert kb_id is not None

    entry1 = KnowledgeEntry(
        entry_id="func_001",
        kb_id=kb_id,
        title="产品功能",
        content="AI Bridge 支持自定义角色、知识库管理、RAG 检索和多模态消息处理。",
    )
    entry2 = KnowledgeEntry(
        entry_id="arch_001",
        kb_id=kb_id,
        title="技术架构",
        content="AI Bridge 采用 6 层架构：安全壳、意图路由、上下文装配、RAG 调度、LLM 生成、迭代闭环。",
    )

    kb_manager.add_knowledge_entry(kb_id, entry1)
    kb_manager.add_knowledge_entry(kb_id, entry2)

    time.sleep(0.5)

    result = rag_engine.retrieve(kb_id, "AI Bridge 有哪些功能", IntentType.SEARCH, top_k=3)
    assert result is not None

    kb_manager.delete_knowledge_base(kb_id)
    print("✓ 测试 4 通过：RAG 检索")


def test_multi_kb_retrieval():
    """测试多知识库检索"""
    db_manager, config_manager = _get_managers()
    kb_manager = KnowledgeBaseManager(db_manager, config_manager)
    rag_engine = RAGEngine(kb_manager, config_manager)

    kb_id_1 = kb_manager.create_knowledge_base("产品知识库", "产品信息")
    kb_id_2 = kb_manager.create_knowledge_base("技术知识库", "技术信息")
    assert kb_id_1 is not None
    assert kb_id_2 is not None

    entry1 = KnowledgeEntry(
        entry_id="prod_001",
        kb_id=kb_id_1,
        title="产品名称",
        content="AI Bridge 是一款智能客服工具。",
    )
    entry2 = KnowledgeEntry(
        entry_id="tech_001",
        kb_id=kb_id_2,
        title="技术栈",
        content="AI Bridge 使用 Python + PyQt6 + ChromaDB。",
    )

    kb_manager.add_knowledge_entry(kb_id_1, entry1)
    kb_manager.add_knowledge_entry(kb_id_2, entry2)

    time.sleep(0.5)

    result = rag_engine.retrieve_multi_kb([kb_id_1, kb_id_2], "AI Bridge", IntentType.SEARCH, top_k=5)
    assert result is not None

    kb_manager.delete_knowledge_base(kb_id_1)
    kb_manager.delete_knowledge_base(kb_id_2)
    print("✓ 测试 5 通过：多知识库检索")


def test_llm_wiki_format():
    """测试 LLM Wiki 格式"""
    db_manager, config_manager = _get_managers()
    kb_manager = KnowledgeBaseManager(db_manager, config_manager)

    kb_id = kb_manager.create_knowledge_base("Wiki格式测试库", "测试LLM Wiki格式")
    assert kb_id is not None

    entry = KnowledgeEntry(
        entry_id="test_entry_001",
        kb_id=kb_id,
        title="测试条目",
        content="这是测试内容。",
    )

    result = kb_manager.add_knowledge_entry(kb_id, entry)
    assert result is True

    kb_manager.delete_knowledge_base(kb_id)
    print("✓ 测试 6 通过：LLM Wiki 格式")


def test_cleanup():
    """测试数据清理"""
    db_manager, config_manager = _get_managers()
    kb_manager = KnowledgeBaseManager(db_manager, config_manager)

    kb_id = kb_manager.create_knowledge_base("待清理库", "将被删除")
    assert kb_id is not None

    entry = KnowledgeEntry(
        entry_id="temp_001",
        kb_id=kb_id,
        title="临时条目",
        content="将被删除",
    )
    kb_manager.add_knowledge_entry(kb_id, entry)

    result = kb_manager.delete_knowledge_base(kb_id)
    assert result is True

    kb_info = kb_manager.get_knowledge_base(kb_id)
    assert kb_info is None

    print("✓ 测试 7 通过：数据清理")


if __name__ == "__main__":
    print("=== S3 RAG 集成验证测试 ===")

    try:
        test_create_kb()
        test_upload_document()
        test_add_knowledge_entry()
        test_rag_retrieval()
        test_multi_kb_retrieval()
        test_llm_wiki_format()
        test_cleanup()

        print("\n=== 所有测试通过 ===")
    except Exception as e:
        print(f"\n✗ 测试失败：{e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)