"""
硬规则执行器验证脚本

验证四类硬规则的强制执行：
1. 250 字截断
2. 问句结尾强制
3. 步骤限制 1 步
4. 术语解释

运行方式：
    cd c:\\Users\\Administrator\\Desktop\\WeChatAI_Project
    python tests/verify_hard_rules.py
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aibridge.engine.hard_rules_executor import (
    HardRulesExecutor, HardRulesResult, DEFAULT_RULES_CONFIG
)


def test_char_limit():
    """测试 250 字截断"""
    print("\n--- 测试 1: 250 字截断 ---")
    executor = HardRulesExecutor()

    # 短文本：不截断
    short_text = "这是一个简短的回复。"
    result = executor.apply(short_text)
    assert not result.was_truncated, "短文本不应被截断"
    assert result.final_output == short_text + "\n\n请问这个解释清楚了吗？"
    print(f"  ✓ 短文本不截断: {result.char_count} 字")

    # 长文本：截断
    long_text = "这是一段很长的回复。" * 30  # 约 300 字
    result = executor.apply(long_text)
    assert result.was_truncated, "长文本应被截断"
    assert result.char_count <= 250, f"截断后字数应 <= 250，实际 {result.char_count}"
    assert "已截断" in result.final_output, "截断提示应存在"
    print(f"  ✓ 长文本截断: {len(long_text)} -> {result.char_count} 字")

    # 检查点问句不计入字数
    text_with_checkpoint = "正文内容。" * 50 + "\n\n请问这个解释清楚了吗？"
    result = executor.apply(text_with_checkpoint)
    print(f"  ✓ 检查点问句排除: 计数 {result.char_count} 字")


def test_question_ending():
    """测试问句结尾强制"""
    print("\n--- 测试 2: 问句结尾强制 ---")
    executor = HardRulesExecutor()

    # 已有问句结尾：不追加
    text_with_question = "这是回复内容，清楚了吗？"
    result = executor.apply(text_with_question)
    assert not result.question_appended, "不应追加问句"
    print(f"  ✓ 问句结尾不追加")

    # 无问句结尾：追加
    text_no_question = "这是回复内容，讲完了"
    result = executor.apply(text_no_question)
    assert result.question_appended, "应追加问句"
    assert result.final_output.endswith("？"), "应以问句结尾"
    print(f"  ✓ 无问句追加: '{result.final_output[-20:]}'")

    # 禁用问句强制
    executor.update_config({"force_question_ending": False})
    result = executor.apply(text_no_question)
    assert not result.question_appended, "禁用后不应追加"
    print(f"  ✓ 禁用后不追加")


def test_step_limit():
    """测试步骤限制"""
    print("\n--- 测试 3: 步骤限制 1 步 ---")
    executor = HardRulesExecutor()

    # 单步：不触发
    single_step = "步骤1：打开配置页面。"
    result = executor.apply(single_step)
    assert not result.steps_limited, "单步不应触发限制"
    print(f"  ✓ 单步不触发限制")

    # 多步：触发限制
    multi_step = """步骤1：打开配置页面。
    步骤2：填写 API Key。
    步骤3：点击保存。
    步骤4：测试连接。"""
    result = executor.apply(multi_step)
    assert result.steps_limited, "多步应触发限制"
    assert "步骤2" not in result.final_output, "应只保留第 1 步"
    print(f"  ✓ 多步触发限制: 保留第 1 步")


def test_term_explanation():
    """测试术语解释"""
    print("\n--- 测试 4: 术语解释 ---")
    executor = HardRulesExecutor()

    # 无术语：不处理
    no_term = "这是普通回复。"
    result = executor.apply(no_term)
    assert len(result.terms_checked) == 0, "无术语"
    print(f"  ✓ 无术语不处理")

    # 有术语且已解释：不追加
    explained = "API（应用程序接口）是让软件互相调用的约定。"
    result = executor.apply(explained)
    assert "API" in result.terms_checked, "应检测到 API 术语"
    print(f"  ✓ 已解释术语不追加: {result.terms_checked}")

    # 有术语但未解释：追加解释
    unexplained = "你需要配置 API 才能使用。"
    result = executor.apply(unexplained)
    assert "API" in result.terms_checked, "应检测到 API 术语"
    assert "（" in result.final_output, "应追加括号解释"
    assert "应用程序接口" in result.final_output, "应包含解释内容"
    print(f"  ✓ 未解释术语追加解释: {result.terms_checked}")


def test_combined_rules():
    """测试组合规则"""
    print("\n--- 测试 5: 组合规则 ---")
    executor = HardRulesExecutor()

    # 同时触发多条规则的输入
    bad_output = """步骤1：打开 deepseek api 配置页。
    步骤2：填写 token。
    步骤3：保存。
    """ + "这是很长的说明文字。" * 40

    result = executor.apply(bad_output)

    print(f"  原始字数: {len(bad_output)}")
    print(f"  最终字数: {result.char_count}")
    print(f"  被截断: {result.was_truncated}")
    print(f"  追加问句: {result.question_appended}")
    print(f"  步骤限制: {result.steps_limited}")
    print(f"  检测术语: {result.terms_checked}")
    print(f"  违规数: {len(result.violations)}")

    for v in result.violations:
        print(f"    - {v.rule_name}: {v.description}")

    assert len(result.violations) > 0, "应触发多条规则"
    print(f"  ✓ 组合规则触发 {len(result.violations)} 条")


def test_custom_config():
    """测试自定义配置"""
    print("\n--- 测试 6: 自定义配置 ---")

    # 自定义字数限制为 100
    executor = HardRulesExecutor({
        "max_chars": 100,
        "force_question_ending": False,
    })

    text = "这是一段中等长度的回复。" * 10  # 约 120 字
    result = executor.apply(text)

    assert result.was_truncated, "应按自定义限制截断"
    assert result.char_count <= 100, f"应 <= 100，实际 {result.char_count}"
    assert not result.question_appended, "应不追加问句"
    print(f"  ✓ 自定义字数限制 100: 截断到 {result.char_count} 字")
    print(f"  ✓ 自定义关闭问句强制")


def test_add_remove_term():
    """测试术语增删"""
    print("\n--- 测试 7: 术语增删 ---")
    executor = HardRulesExecutor()

    # 新增术语
    executor.add_term("MCP", "模型上下文协议，让 AI 调用外部工具的标准")
    terms = executor.get_terms()
    assert "MCP" in terms, "应包含 MCP"
    print(f"  ✓ 新增术语 MCP")

    # 检测新术语
    result = executor.apply("我用了 MCP 协议。")
    assert "MCP" in result.terms_checked, "应检测到 MCP"
    assert "模型上下文协议" in result.final_output, "应追加解释"
    print(f"  ✓ 检测新术语并追加解释")

    # 删除术语
    executor.remove_term("MCP")
    terms = executor.get_terms()
    assert "MCP" not in terms, "应不包含 MCP"
    print(f"  ✓ 删除术语 MCP")


def test_performance():
    """测试性能"""
    print("\n--- 测试 8: 性能 ---")
    import time
    executor = HardRulesExecutor()

    text = "步骤1：配置 API。步骤2：测试。步骤3：部署。" + "说明文字。" * 50
    executor.apply(text)  # 预热

    start = time.perf_counter()
    for _ in range(1000):
        executor.apply(text)
    elapsed_ms = (time.perf_counter() - start) * 1000
    avg_ms = elapsed_ms / 1000

    print(f"  ✓ 平均响应: {avg_ms:.4f}ms / 次 (1000 次平均)")
    assert avg_ms < 5.0, f"性能应 < 5ms，实际 {avg_ms:.4f}ms"


if __name__ == "__main__":
    print("=" * 60)
    print("AI Bridge - 硬规则执行器 验证")
    print("=" * 60)

    tests = [
        test_char_limit,
        test_question_ending,
        test_step_limit,
        test_term_explanation,
        test_combined_rules,
        test_custom_config,
        test_add_remove_term,
        test_performance,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            failed += 1
            print(f"  ✗ 失败: {e}")
        except Exception as e:
            failed += 1
            print(f"  ✗ 异常: {e}")

    print("\n" + "=" * 60)
    print(f"结果: {passed} 通过, {failed} 失败")
    if failed == 0:
        print("✓ 全部验证通过")
        sys.exit(0)
    else:
        print("✗ 存在验证失败")
        sys.exit(1)
