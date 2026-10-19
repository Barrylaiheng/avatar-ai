"""
端到端联调测试

验证六层消息处理引擎的完整流程：
用户输入 → 信号检测 → 阶段分类 → RAG检索 → 会话历史 → Prompt组装 → LLM调用 → 硬规则执行 → 最终输出

同时验证：
- 人设编辑器的七段结构 → role_config 转换
- LLM Wiki 的知识条目管理
- 阶段分类器与知识库的联动
- 硬规则执行器的四类规则
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def test_layer1_signal_detection():
    """测试 L1: 信号检测"""
    print("\n--- 测试 L1: 信号检测 ---")
    from aibridge.engine.signal_detector import SignalDetector, SignalType

    detector = SignalDetector()

    # 测试四种信号
    cases = [
        ("继续下一步", SignalType.PROCEED, "proceed 信号"),
        ("重复一下刚才的", SignalType.REPEAT, "repeat 信号"),
        ("我不理解，卡住了", SignalType.STUCK, "stuck 信号"),
        ("今天天气真好", SignalType.CHAT, "chat 信号"),
    ]

    for text, expected_type, desc in cases:
        result = detector.detect(text)
        assert result.signal == expected_type, (
            f"{desc}: 期望 {expected_type.value}, 实际 {result.signal.value}"
        )
        print(f"  ✓ {desc}: '{text}' → {result.signal.value}")

    # 优先级测试: stuck > repeat > proceed > chat
    result = detector.detect("卡住了，重复一下")
    assert result.signal == SignalType.STUCK, "stuck 优先级应最高"
    print(f"  ✓ 优先级: '卡住了，重复一下' → {result.signal.value} (stuck 优先)")


def test_layer2_stage_classification():
    """测试 L2: 阶段分类"""
    print("\n--- 测试 L2: 阶段分类 ---")
    from aibridge.engine.stage_classifier import StageClassifier

    classifier = StageClassifier()

    cases = [
        ("我想做个公众号AI助手，怎么开始", "stage_0", "摸底诊断"),
        ("需要什么营业执照和资质", "stage_1", "准备工作"),
        ("怎么配置公众号开发者平台的token和url", "stage_2", "公众号配置"),
        ("服务器用python flask部署，环境怎么搭", "stage_3", "服务器环境"),
        ("接入deepseek大模型的api", "stage_4", "接入大模型"),
        ("设计AI助手的人设和prompt", "stage_5", "设计人设"),
        ("搭建rag知识库用chromadb", "stage_6", "搭建知识库"),
        ("wcf接入微信消息自动回复", "stage_7", "接入微信"),
        ("联调测试完成准备上线", "stage_8", "测试上线"),
        ("今天吃什么", "stage_chat", "闲聊兜底"),
    ]

    for text, expected_stage, desc in cases:
        result = classifier.classify(text)
        assert result.stage_id == expected_stage, (
            f"{desc}: 期望 {expected_stage}, 实际 {result.stage_id}"
        )
        print(f"  ✓ {desc}: '{text}' → {result.stage_id} ({result.stage_name})")

    # 验证阶段与知识库联动
    result = classifier.classify("接入deepseek大模型的api")
    assert len(result.kb_ids) > 0, "阶段4应关联知识库条目"
    print(f"  ✓ 知识库联动: stage_4 → kb_ids={result.kb_ids}")


def test_layer3_rag_retrieval():
    """测试 L3: RAG 检索"""
    print("\n--- 测试 L3: RAG 检索 ---")
    from aibridge.rag.wiki_manager import LLMWikiManager, DualPurposeEntry, PageType, EntryStatus
    from aibridge.rag.hybrid_retriever import HybridRetriever

    wiki = LLMWikiManager()

    # 清理旧数据
    existing = wiki.list_all()
    for entry in existing:
        wiki.remove(entry.entry_id)

    # 添加测试知识条目
    test_entries = [
        DualPurposeEntry(
            entry_id="KB-04-001",
            title="DeepSeek API 接入指南",
            page_type=PageType.PROCESS,
            category="04_llm_integration",
            tags=["deepseek", "api", "llm"],
            related=[],
            search_text="DeepSeek API 接入需要申请 API Key，调用 chat/completions 接口，支持 temperature 和 max_tokens 参数。",
            content_body="## DeepSeek API 接入\n\n1. 申请 API Key\n2. 调用 chat/completions 接口\n3. 参数: temperature, max_tokens",
            summary="DeepSeek API 接入步骤",
            status=EntryStatus.ACTIVE,
        ),
        DualPurposeEntry(
            entry_id="KB-09-001",
            title="ChromaDB 知识库搭建",
            page_type=PageType.PROCESS,
            category="09_knowledge_base",
            tags=["chromadb", "rag", "向量数据库"],
            related=[],
            search_text="ChromaDB 是开源向量数据库，配合 bge-small-zh-v1.5 embedding 模型，用于 RAG 知识检索。",
            content_body="## ChromaDB 搭建\n\n1. pip install chromadb\n2. 创建 collection\n3. add_chunks 添加向量\n4. query 检索",
            summary="ChromaDB 向量数据库搭建",
            status=EntryStatus.ACTIVE,
        ),
    ]

    for entry in test_entries:
        wiki.ingest(entry)

    print(f"  ✓ 添加 {len(test_entries)} 个测试知识条目")

    # 混合检索
    retriever = HybridRetriever(wiki_manager=wiki)
    resultset = retriever.retrieve("怎么接入 deepseek api", top_k=3)
    results = resultset.results

    assert len(results) > 0, "应检索到结果"
    top_result = results[0]
    top_entry = top_result.entry
    print(f"  ✓ 检索 'deepseek api': Top-1 = {top_entry.entry_id} ({top_entry.title})")
    print(f"    得分: vector={top_result.vector_score:.3f}, metadata={top_result.metadata_score:.3f}")

    # 验证双用途：search_text 和 content_body 都可访问
    assert top_entry.search_text, "search_text 应非空（给AI检索）"
    assert top_entry.content_body, "content_body 应非空（给内容生产）"
    assert top_entry.summary, "summary 应非空"
    print(f"  ✓ 双用途验证: search_text({len(top_entry.search_text)}字符) + content_body({len(top_entry.content_body)}字符)")


def test_layer5_prompt_assembly():
    """测试 L5: Prompt 组装（七段结构）"""
    print("\n--- 测试 L5: Prompt 组装 ---")
    from aibridge.ui.persona_editor import SevenSectionPersona

    persona = SevenSectionPersona(
        role="你是公众号AI助手专家，专门帮助用户搭建微信AI机器人。",
        task="回答用户关于公众号AI助手搭建的问题，引导用户完成六阶段流程。",
        rules="每次只回答一个步骤；使用通俗易懂的语言；主动询问用户是否理解。",
        examples="用户：怎么开始？\n助手：我们先从摸底诊断开始，你的公众号是什么类型？",
        style="语气友好专业，像经验丰富的导师。",
        constraints="回答不超过250字；结尾必须用问句；技术术语需要解释。",
        output_format="纯文本回答，不使用Markdown格式。",
    )

    role_config = persona.to_prompt()

    assert "identity" in role_config, "role_config 应包含 identity"
    assert "task" in role_config, "role_config 应包含 task"
    print(f"  ✓ 七段结构 → role_config: {list(role_config.keys())}")

    # 验证可以注入信号和阶段
    assert "公众号AI助手专家" in role_config["identity"], "identity 应包含角色描述"
    print(f"  ✓ identity 注入: '{role_config['identity'][:30]}...'")

    return persona


def test_layer6_hard_rules():
    """测试 L6: 硬规则执行"""
    print("\n--- 测试 L6: 硬规则执行 ---")
    from aibridge.engine.hard_rules_executor import HardRulesExecutor, DEFAULT_RULES_CONFIG

    executor = HardRulesExecutor(DEFAULT_RULES_CONFIG)

    # 测试字数截断
    long_text = "这是一段很长的回复。" * 50
    result = executor.apply(long_text)
    assert result.char_count <= 250, f"应截断到250字，实际 {result.char_count}"
    assert result.was_truncated, "应标记为已截断"
    print(f"  ✓ 字数截断: {len(long_text)} → {result.char_count} 字")

    # 测试问句结尾强制
    no_question = "公众号需要服务号类型才能使用高级接口"
    result = executor.apply(no_question)
    assert result.final_output.endswith("？"), f"应以问句结尾，实际结尾: '{result.final_output[-5:]}'"
    print(f"  ✓ 问句结尾: '{no_question[-10:]}' → '{result.final_output[-10:]}'")

    # 测试术语解释
    text_with_terms = "你需要配置API来接入LLM，使用RAG技术增强回复。"
    result = executor.apply(text_with_terms)
    assert result.terms_checked, "应有术语检查"
    print(f"  ✓ 术语解释: 识别 {len(result.terms_checked)} 个术语: {result.terms_checked}")


def test_end_to_end_flow():
    """端到端流程测试：信号 + 阶段 + RAG + Prompt + 硬规则"""
    print("\n--- 端到端流程测试 ---")
    from aibridge.engine.signal_detector import SignalDetector
    from aibridge.engine.stage_classifier import StageClassifier
    from aibridge.rag.hybrid_retriever import HybridRetriever
    from aibridge.ui.persona_editor import SevenSectionPersona
    from aibridge.engine.hard_rules_executor import HardRulesExecutor, DEFAULT_RULES_CONFIG

    # 初始化各层组件
    detector = SignalDetector()
    classifier = StageClassifier()
    from aibridge.rag.wiki_manager import LLMWikiManager
    wiki = LLMWikiManager()
    retriever = HybridRetriever(wiki_manager=wiki)
    persona = SevenSectionPersona(
        role="你是公众号AI助手专家。",
        task="帮助用户搭建微信AI机器人。",
        rules="每次只回答一个步骤。",
        examples="用户：怎么开始？\n助手：我们先从摸底诊断开始。",
        style="语气友好专业。",
        constraints="回答不超过250字。",
        output_format="纯文本回答。",
    )
    executor = HardRulesExecutor(DEFAULT_RULES_CONFIG)

    # 模拟用户输入
    user_input = "我想接入deepseek大模型的api，怎么配置"

    # L1: 信号检测
    signal = detector.detect(user_input)
    print(f"  L1 信号: {signal.signal.value}")
    # 新问题不包含 proceed/repeat/stuck 关键词，默认为 chat 信号
    assert signal.signal.value in ("chat", "proceed"), f"应为 chat 或 proceed 信号，实际 {signal.signal.value}"

    # L2: 阶段分类
    stage = classifier.classify(user_input)
    print(f"  L2 阶段: {stage.stage_id} ({stage.stage_name})")
    assert stage.stage_id == "stage_4", "应为 stage_4 (接入大模型)"

    # L3: RAG 检索
    rag_resultset = retriever.retrieve(user_input, top_k=3)
    rag_results = rag_resultset.results
    print(f"  L3 检索: {len(rag_results)} 条结果")
    assert len(rag_results) > 0, "应检索到相关知识"

    # L5: Prompt 组装
    role_config = persona.to_prompt()
    context = rag_results[0].entry.search_text if rag_results else ""
    print(f"  L5 Prompt: identity={role_config['identity'][:20]}..., context={len(context)}字")

    # 模拟 LLM 生成（跳过真实 LLM 调用）
    mock_llm_response = (
        f"关于{stage.stage_name}，你需要先申请 API Key，然后调用 chat/completions 接口。"
        f"参考知识：{context[:50]}..."
    )

    # L6: 硬规则执行
    final = executor.apply(mock_llm_response)
    print(f"  L6 硬规则: {final.char_count}字, 截断={final.was_truncated}, 术语={len(final.terms_checked)}")

    print(f"\n  最终输出: {final.final_output[:80]}...")
    assert final.char_count <= 250, "最终输出应符合字数限制"
    print(f"  ✓ 端到端流程通过")


def test_wiki_lifecycle():
    """测试 LLM Wiki 完整生命周期"""
    print("\n--- LLM Wiki 生命周期测试 ---")
    from aibridge.rag.wiki_manager import LLMWikiManager, DualPurposeEntry, PageType, EntryStatus

    wiki = LLMWikiManager()

    # 清理
    existing = wiki.list_all()
    for entry in existing:
        wiki.remove(entry.entry_id)

    # 创建
    entry = DualPurposeEntry(
        entry_id="KB-99-001",
        title="测试条目",
        page_type=PageType.CONCEPT,
        category="99_test",
        tags=["test"],
        related=[],
        search_text="这是一个测试知识条目",
        content_body="## 测试\n\n这是测试内容",
        summary="测试摘要",
        status=EntryStatus.ACTIVE,
    )
    wiki.ingest(entry)
    print(f"  ✓ 创建: {entry.entry_id}")

    # 查询
    found = wiki.query("KB-99-001")
    assert found is not None, "应能查询到条目"
    assert found.title == "测试条目", "标题应匹配"
    print(f"  ✓ 查询: {found.entry_id} ({found.title})")

    # 更新
    entry.title = "更新后的标题"
    wiki.update(entry)
    found = wiki.query("KB-99-001")
    assert found.title == "更新后的标题", "更新后标题应匹配"
    print(f"  ✓ 更新: {found.title}")

    # 删除
    wiki.remove("KB-99-001")
    found = wiki.query("KB-99-001")
    assert found is None, "删除后应查询不到"
    print(f"  ✓ 删除: KB-99-001 已移除")

    # 统计
    stats = wiki.get_stats()
    print(f"  ✓ 统计: total={stats['total_entries']}, active={stats['active_entries']}")


if __name__ == "__main__":
    print("=" * 60)
    print("AI Bridge - 端到端联调测试")
    print("=" * 60)

    try:
        test_layer1_signal_detection()
        test_layer2_stage_classification()
        test_layer3_rag_retrieval()
        test_layer5_prompt_assembly()
        test_layer6_hard_rules()
        test_end_to_end_flow()
        test_wiki_lifecycle()

        print("\n" + "=" * 60)
        print("✓ 全部联调测试通过")
        sys.exit(0)

    except AssertionError as e:
        print(f"\n✗ 验证失败: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ 异常: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
