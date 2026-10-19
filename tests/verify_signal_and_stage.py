"""
信号检测器和阶段分类器验证脚本

直接运行验证两个组件的逻辑正确性和性能。
"""
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aibridge.engine.signal_detector import SignalDetector, SignalType
from aibridge.engine.stage_classifier import StageClassifier, DEFAULT_STAGE_CHAT


def test_signal_detector():
    """验证信号检测器"""
    print("\n" + "=" * 60)
    print("信号检测器验证")
    print("=" * 60)

    detector = SignalDetector()

    # 测试用例：(输入, 期望信号)
    cases = [
        # PROCEED
        ("继续", SignalType.PROCEED),
        ("下一个", SignalType.PROCEED),
        ("OK", SignalType.PROCEED),
        ("好的", SignalType.PROCEED),
        ("明白了", SignalType.PROCEED),
        # REPEAT
        ("再说一遍", SignalType.REPEAT),
        ("没听懂", SignalType.REPEAT),
        ("什么意思", SignalType.REPEAT),
        ("详细点", SignalType.REPEAT),
        # STUCK
        ("卡住了", SignalType.STUCK),
        ("不会做", SignalType.STUCK),
        ("报错了", SignalType.STUCK),
        ("怎么办", SignalType.STUCK),
        # CHAT
        ("你好", SignalType.CHAT),
        ("今天天气不错", SignalType.CHAT),
        ("", SignalType.CHAT),
    ]

    passed = 0
    failed = 0
    for text, expected in cases:
        result = detector.detect(text)
        status = "✓" if result.signal == expected else "✗"
        if result.signal == expected:
            passed += 1
        else:
            failed += 1
        print(f"  {status} '{text}' -> {result.signal.value} (期望: {expected.value})")

    # 优先级测试
    print("\n  优先级测试:")
    priority_cases = [
        ("卡住了，没听懂怎么办", SignalType.STUCK, "stuck > repeat"),
        ("报错了，但我想继续", SignalType.STUCK, "stuck > proceed"),
        ("没听懂，但好的继续", SignalType.REPEAT, "repeat > proceed"),
    ]
    for text, expected, desc in priority_cases:
        result = detector.detect(text)
        status = "✓" if result.signal == expected else "✗"
        if result.signal == expected:
            passed += 1
        else:
            failed += 1
        print(f"  {status} '{text}' -> {result.signal.value} ({desc})")

    # 性能测试
    print("\n  性能测试:")
    text = "我想继续下一步，但是卡住了怎么办，能不能再说一遍"
    detector.detect(text)  # 预热
    start = time.perf_counter()
    for _ in range(1000):
        detector.detect(text)
    elapsed_ms = (time.perf_counter() - start) * 1000
    avg_ms = elapsed_ms / 1000
    status = "✓" if avg_ms < 1.0 else "✗"
    if avg_ms < 1.0:
        passed += 1
    else:
        failed += 1
    print(f"  {status} 平均响应: {avg_ms:.4f}ms ({'<' if avg_ms < 1 else '>'} 1ms)")

    print(f"\n  结果: {passed} 通过, {failed} 失败")
    return failed == 0


def test_stage_classifier():
    """验证阶段分类器"""
    print("\n" + "=" * 60)
    print("阶段分类器验证")
    print("=" * 60)

    classifier = StageClassifier()

    # 测试用例：(输入, 期望阶段ID)
    cases = [
        ("我想了解一下怎么开始做数字分身", "stage_0"),
        ("服务号需要什么营业执照资质", "stage_1"),
        ("开发者平台 token url 怎么配置公众号", "stage_2"),
        ("部署到 linux 服务器 nginx 环境", "stage_3"),
        ("deepseek api 大模型怎么接入", "stage_4"),
        ("设计人设 prompt 语气风格", "stage_5"),
        ("rag 知识库 embedding chromadb 检索", "stage_6"),
        ("wcf 微信自动回复 wechat 机器人", "stage_7"),
        ("测试上线验证发布", "stage_8"),
        ("优化迭代变现运营", "stage_9"),
        # 兜底
        ("你好今天天气怎么样", DEFAULT_STAGE_CHAT),
        ("", DEFAULT_STAGE_CHAT),
    ]

    passed = 0
    failed = 0
    for text, expected in cases:
        result = classifier.classify(text)
        status = "✓" if result.stage_id == expected else "✗"
        if result.stage_id == expected:
            passed += 1
        else:
            failed += 1
        fallback_tag = " (兜底)" if result.is_fallback else ""
        print(
            f"  {status} '{text[:30]}...' -> {result.stage_id} "
            f"(conf={result.confidence}, kw={result.matched_keywords}){fallback_tag}"
        )

    # 性能测试
    print("\n  性能测试:")
    text = "我要部署 deepseek 大模型到服务器，并接入微信 wcf 自动回复"
    classifier.classify(text)  # 预热
    start = time.perf_counter()
    for _ in range(1000):
        classifier.classify(text)
    elapsed_ms = (time.perf_counter() - start) * 1000
    avg_ms = elapsed_ms / 1000
    status = "✓" if avg_ms < 1.0 else "✗"
    if avg_ms < 1.0:
        passed += 1
    else:
        failed += 1
    print(f"  {status} 平均响应: {avg_ms:.4f}ms ({'<' if avg_ms < 1 else '>'} 1ms)")

    print(f"\n  结果: {passed} 通过, {failed} 失败")
    return failed == 0


def test_integration():
    """集成测试：信号 + 阶段协同"""
    print("\n" + "=" * 60)
    print("集成测试：信号检测器 + 阶段分类器")
    print("=" * 60)

    detector = SignalDetector()
    classifier = StageClassifier()

    messages = [
        "我想开始做一个数字分身",
        "继续讲下一步",
        "卡住了，deepseek api 报错怎么办",
        "没听懂 rag 知识库怎么搭建",
        "部署到服务器怎么搞",
        "人设 prompt 怎么写",
    ]

    print()
    for text in messages:
        signal_result = detector.detect(text)
        stage_result = classifier.classify(text)
        print(f"  输入: {text}")
        print(f"    信号: {signal_result.signal.value} (kw={signal_result.matched_keyword})")
        print(f"    阶段: {stage_result.stage_id} (conf={stage_result.confidence})")
        print()

    return True


if __name__ == "__main__":
    print("AI Bridge - 信号检测器 & 阶段分类器 验证")
    print("=" * 60)

    r1 = test_signal_detector()
    r2 = test_stage_classifier()
    r3 = test_integration()

    print("\n" + "=" * 60)
    if r1 and r2 and r3:
        print("✓ 全部验证通过")
        sys.exit(0)
    else:
        print("✗ 存在验证失败")
        sys.exit(1)
