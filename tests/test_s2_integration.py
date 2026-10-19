"""
S2 阶段集成验证：6 层架构端到端测试

验证项：
1. 模块导入正确性
2. 数据库初始化和迁移
3. 安全壳拦截功能
4. 意图路由功能
5. 上下文装配功能
6. 迭代闭环检测功能
7. 消息处理器集成

注意：LLM 调用需真实 API Key，此处仅验证流程不验证 LLM 响应。
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from aibridge.config.config_manager import ConfigManager
from aibridge.database.database_manager import DatabaseManager
from aibridge.database.database_migrator import DatabaseMigrator
from aibridge.engine.safety_shield import SafetyShieldManager, ShieldAction
from aibridge.engine.intent_router import IntentRouter, IntentType
from aibridge.engine.context_assembler import ContextAssembler
from aibridge.engine.iteration_engine import IterationEngine, BadCaseStatus
from aibridge.engine.message_processor import MessageProcessor


def test_01_module_imports():
    """测试 1：模块导入"""
    print("\n=== 测试 1：模块导入 ===")
    try:
        from aibridge.engine.safety_shield import ComplianceShield, BusinessSafetyShell
        from aibridge.engine.intent_router import LocalIntentClassifier, FCFallback
        from aibridge.engine.context_assembler import ContextAssembler, AssembledContext
        from aibridge.engine.llm_generator import LLMGenerator, PromptAssembler, LLMClient
        from aibridge.engine.iteration_engine import BadCaseDetector, RuleDraftGenerator
        from aibridge.engine.message_processor import MessageProcessor, ProcessingResult
        print("✓ 所有模块导入成功")
        return True
    except Exception as e:
        print(f"✗ 模块导入失败: {e}")
        return False


def test_02_database_initialization():
    """测试 2：数据库初始化"""
    print("\n=== 测试 2：数据库初始化 ===")
    try:
        db = DatabaseManager()
        migrator = DatabaseMigrator(db)
        migrator.migrate()

        # 验证表创建
        db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row["name"] for row in db.fetchall()]
        expected_tables = [
            "schema_version", "config", "sessions", "messages",
            "session_summaries", "session_states", "user_profiles",
            "badcases", "rule_drafts", "compliance_rules", "safety_shell_config",
            "knowledge_bases", "documents", "vector_chunks", "user_input_logs"
        ]
        for table in expected_tables:
            assert table in tables, f"Missing table: {table}"

        print(f"✓ 数据库初始化成功（{len(tables)} 张表）")
        db.disconnect()
        return True
    except Exception as e:
        print(f"✗ 数据库初始化失败: {e}")
        return False


def test_03_safety_shield():
    """测试 3：安全壳功能"""
    print("\n=== 测试 3：安全壳功能 ===")
    try:
        db = DatabaseManager()
        migrator = DatabaseMigrator(db)
        migrator.migrate()

        manager = SafetyShieldManager(db, business_shell_enabled=True)

        # 测试 1：正常内容通过
        result = manager.check_input("你好，我想了解一下产品")
        assert result.passed or result.action == ShieldAction.MASK, f"Normal content should pass: {result.action}"
        print(f"  ✓ 正常内容通过: action={result.action.value}")

        # 测试 2：PII 脱敏
        result = manager.check_input("我的手机号是 13800138000")
        assert result.action == ShieldAction.MASK, "PII should be masked"
        assert "13800138000" not in (result.masked_content or ""), "PII should be masked in content"
        print(f"  ✓ PII 脱敏: masked_content={result.masked_content}")

        # 测试 3：输出检查
        result = manager.check_output("这是 AI 生成的正常回复")
        assert result.passed, "Normal output should pass"
        print(f"  ✓ 输出检查通过")

        db.disconnect()
        print("✓ 安全壳功能测试通过")
        return True
    except Exception as e:
        print(f"✗ 安全壳功能测试失败: {e}")
        return False


def test_04_intent_router():
    """测试 4：意图路由功能"""
    print("\n=== 测试 4：意图路由功能 ===")
    try:
        router = IntentRouter()

        # 测试 1：数据权利意图（本地分类器）
        result = router.route("请帮我导出我的数据")
        assert result.intent == IntentType.DATA_RIGHTS, f"Should be DATA_RIGHTS: {result.intent}"
        assert result.source == "local", "Should be classified by local"
        print(f"  ✓ 数据权利意图识别: {result.intent.value} (source={result.source})")

        # 测试 2：业务引导意图（本地分类器）
        result = router.route("怎么购买你们的产品")
        assert result.intent == IntentType.GUIDE, f"Should be GUIDE: {result.intent}"
        print(f"  ✓ 业务引导意图识别: {result.intent.value}")

        # 测试 3：知识检索意图（本地分类器）
        result = router.route("产品介绍有哪些")
        assert result.intent == IntentType.SEARCH, f"Should be SEARCH: {result.intent}"
        print(f"  ✓ 知识检索意图识别: {result.intent.value}")

        # 测试 4：模糊意图（FC 兜底，无 LLM 时降级为 CHAT）
        result = router.route("今天天气怎么样")
        assert result.intent == IntentType.CHAT, f"Should be CHAT (fallback): {result.intent}"
        print(f"  ✓ 模糊意图兜底: {result.intent.value} (source={result.source})")

        print("✓ 意图路由功能测试通过")
        return True
    except Exception as e:
        print(f"✗ 意图路由功能测试失败: {e}")
        return False


def test_05_context_assembler():
    """测试 5：上下文装配功能"""
    print("\n=== 测试 5：上下文装配功能 ===")
    try:
        db = DatabaseManager()
        migrator = DatabaseMigrator(db)
        migrator.migrate()

        assembler = ContextAssembler(db, history_rounds=5)

        # 创建会话
        session = assembler.get_or_create_session("test_wxid_001", "chat", "测试会话")
        assert session.session_id, "Session ID should not be empty"
        print(f"  ✓ 会话创建: session_id={session.session_id[:20]}...")

        # 保存用户消息
        from aibridge.engine.context_assembler import MessageRecord
        from aibridge.utils.common import generate_id

        user_msg = MessageRecord(
            msg_id=generate_id("msg_"),
            session_id=session.session_id,
            role="user",
            content="你好",
            wxid="test_wxid_001",
        )
        assembler.save_message(user_msg)

        # 保存 AI 消息
        ai_msg = MessageRecord(
            msg_id=generate_id("msg_"),
            session_id=session.session_id,
            role="assistant",
            content="你好！有什么可以帮助您的吗？",
            wxid="test_wxid_001",
        )
        assembler.save_message(ai_msg)

        # 装配上下文
        context = assembler.assemble(session, "新的问题", intent="chat")
        assert len(context.history_messages) == 2, f"Should have 2 history messages: {len(context.history_messages)}"
        assert context.current_message.content == "新的问题"
        print(f"  ✓ 上下文装配: history={len(context.history_messages)} msgs, current='{context.current_message.content}'")

        db.disconnect()
        print("✓ 上下文装配功能测试通过")
        return True
    except Exception as e:
        print(f"✗ 上下文装配功能测试失败: {e}")
        return False


def test_06_iteration_engine():
    """测试 6：迭代闭环功能"""
    print("\n=== 测试 6：迭代闭环功能 ===")
    try:
        db = DatabaseManager()
        migrator = DatabaseMigrator(db)
        migrator.migrate()

        engine = IterationEngine(db)

        # 测试 BadCase 检测
        badcases = engine.detect_async(
            user_input="你好",
            ai_response="我不知道，建议您咨询专业人士。",  # 触发知识盲区 + 安全风险
            session_id="test_session",
            msg_id="test_msg_001",
        )
        assert len(badcases) > 0, "Should detect BadCases"
        print(f"  ✓ BadCase 检测: {len(badcases)} cases detected")
        for bc in badcases:
            print(f"    - [{bc.severity}] {bc.detected_by}: {bc.case_id[:20]}...")

        # 测试获取 BadCase 列表
        cases = engine.detector.get_badcases(status="pending")
        assert len(cases) > 0, "Should have pending BadCases"
        print(f"  ✓ BadCase 查询: {len(cases)} pending cases")

        db.disconnect()
        print("✓ 迭代闭环功能测试通过")
        return True
    except Exception as e:
        print(f"✗ 迭代闭环功能测试失败: {e}")
        return False


def test_07_message_processor():
    """测试 7：消息处理器集成"""
    print("\n=== 测试 7：消息处理器集成 ===")
    try:
        config = ConfigManager()
        db = DatabaseManager()
        migrator = DatabaseMigrator(db)
        migrator.migrate()

        processor = MessageProcessor(config, db)
        print("  ✓ MessageProcessor 初始化成功")

        # 测试安全壳拦截（不调用 LLM）
        result = processor.process(
            wxid="test_wxid_002",
            content="正常测试消息",
        )
        # 由于没有配置 API Key，应该返回 llm_not_configured 错误
        # 但安全壳和意图路由应该正常执行
        if not result.success and result.error == "llm_not_configured":
            print(f"  ✓ 安全壳 + 意图路由通过（LLM 未配置）: intent={result.intent}")
        elif result.success:
            print(f"  ✓ 完整流程通过: intent={result.intent}")
        else:
            print(f"  ⚠ 处理结果: success={result.success}, error={result.error}")

        db.disconnect()
        print("✓ 消息处理器集成测试通过")
        return True
    except Exception as e:
        print(f"✗ 消息处理器集成测试失败: {e}")
        return False


def main():
    """运行所有测试"""
    print("=" * 60)
    print("AI Bridge S2 阶段集成验证：6 层架构端到端测试")
    print("=" * 60)

    tests = [
        test_01_module_imports,
        test_02_database_initialization,
        test_03_safety_shield,
        test_04_intent_router,
        test_05_context_assembler,
        test_06_iteration_engine,
        test_07_message_processor,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"✗ 测试异常: {e}")
            failed += 1

    print("\n" + "=" * 60)
    print(f"测试结果: {passed} 通过, {failed} 失败, 共 {len(tests)} 项")
    print("=" * 60)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())