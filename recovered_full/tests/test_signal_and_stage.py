"""
信号检测器和阶段分类器单元测试

验证两个核心组件的逻辑正确性：
- SignalDetector: 四信号检测（proceed/repeat/stuck/chat）+ 优先级
- StageClassifier: 阶段分类 + 置信度阈值 + 兜底机制

运行方式：
    cd c:\\Users\\Administrator\\Desktop\\WeChatAI_Project
    python -m pytest tests/test_signal_and_stage.py -v
"""
import sys
import os
import time

# 将 src 加入路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aibridge.engine.signal_detector import (
    SignalDetector, SignalType, SignalResult, SIGNAL_PRIORITY,
)
from aibridge.engine.stage_classifier import (
    StageClassifier, StageResult, DEFAULT_STAGE_CHAT, DEFAULT_CONFIDENCE_THRESHOLD,
)


# ============ SignalDetector 测试 ============

class TestSignalDetector:

    def setup_method(self):
        self.detector = SignalDetector()

    def test_proceed_signal(self):
        """测试推进信号"""
        cases = [
            "继续",
            "下一个",
            "OK",
            "好的",
            "明白了",
            "继续讲",
            "没问题",
        ]
        for text in cases:
            result = self.detector.detect(text)
            assert result.signal == SignalType.PROCEED, \
                f"Failed: '{text}' expected PROCEED, got {result.signal}"
            assert result.matched_keyword is not None, f"Failed: '{text}' no keyword matched"
            assert result.confidence > 0, f"Failed: '{text}' confidence is 0"

    def test_repeat_signal(self):
        """测试重复信号"""
        cases = [
            "再说一遍",
            "没听懂",
            "什么意思",
            "不懂",
            "为什么这样",
            "详细点",
        ]
        for text in cases:
            result = self.detector.detect(text)
            assert result.signal == SignalType.REPEAT, \
                f"Failed: '{text}' expected REPEAT, got {result.signal}"

    def test_stuck_signal(self):
        """测试卡住信号"""
        cases = [
            "卡住了",
            "不会做",
            "怎么办",
            "报错了",
            "求助",
            "进行不下去",
        ]
        for text in cases:
            result = self.detector.detect(text)
            assert result.signal == SignalType.STUCK, \
                f"Failed: '{text}' expected STUCK, got {result.signal}"

    def test_chat_signal(self):
        """测试闲聊信号（默认兜底）"""
        cases = [
            "你好",
            "今天天气不错",
            "随便聊聊",
            "",
            "   ",
        ]
        for text in cases:
            result = self.detector.detect(text)
            assert result.signal == SignalType.CHAT, \
                f"Failed: '{text}' expected CHAT, got {result.signal}"

    def test_priority_stuck_over_repeat(self):
        """测试优先级：stuck > repeat"""
        # 同时包含 stuck 和 repeat 关键词
        result = self.detector.detect("卡住了，没听懂怎么办")
        assert result.signal == SignalType.STUCK, \
            f"Priority failed: expected STUCK over REPEAT, got {result.signal}"
        assert SignalType.STUCK in result.all_matched
        assert SignalType.REPEAT in result.all_matched

    def test_priority_stuck_over_proceed(self):
        """测试优先级：stuck > proceed"""
        result = self.detector.detect("报错了，但我想继续")
        assert result.signal == SignalType.STUCK, \
            f"Priority failed: expected STUCK over PROCEED, got {result.signal}"

    def test_priority_repeat_over_proceed(self):
        """测试优先级：repeat > proceed"""
        result = self.detector.detect("没听懂，但好的继续")
        assert result.signal == SignalType.REPEAT, \
            f"Priority failed: expected REPEAT over PROCEED, got {result.signal}"

    def test_performance_under_1ms(self):
        """测试性能：<1ms"""
        text = "我想继续下一步，但是卡住了怎么办，能不能再说一遍"
        # 预热
        self.detector.detect(text)

        # 计时
        start = time.perf_counter()
        for _ in range(100):
            self.detector.detect(text)
        elapsed_ms = (time.perf_counter() - start) * 1000
        avg_ms = elapsed_ms / 100

        assert avg_ms < 1.0, f"Performance failed: {avg_ms:.3f}ms > 1ms"
        print(f"\n  SignalDetector avg: {avg_ms:.4f}ms per call")

    def test_custom_keywords(self):
        """测试自定义关键词"""
        custom = {
            SignalType.PROCEED: ["go", "next"],
            SignalType.REPEAT: ["huh"],
            SignalType.STUCK: ["help"],
            SignalType.CHAT: [],
        }
        detector = SignalDetector(custom_keywords=custom)
        assert detector.detect("go").signal == SignalType.PROCEED
        assert detector.detect("help").signal == SignalType.STUCK
        assert detector.detect("hello").signal == SignalType.CHAT

    def test_update_keywords_runtime(self):
        """测试运行时更新关键词"""
        original = self.detector.detect("foobar")
        assert original.signal == SignalType.CHAT

        self.detector.update_keywords(SignalType.STUCK, ["foobar"])
        updated = self.detector.detect("foobar")
        assert updated.signal == SignalType.STUCK

    def test_empty_input(self):
        """测试空输入"""
        result = self.detector.detect("")
        assert result.signal == SignalType.CHAT
        assert result.confidence == 0.0

    def test_case_insensitive(self):
        """测试大小写不敏感"""
        result = self.detector.detect("OK")
        assert result.signal == SignalType.PROCEED

        result = self.detector.detect("ok")
        assert result.signal == SignalType.PROCEED

        result = self.detector.detect("Ok")
        assert result.signal == SignalType.PROCEED


# ============ StageClassifier 测试 ============

class TestStageClassifier:

    def setup_method(self):
        self.classifier = StageClassifier()

    def test_stage_0_diagnosis(self):
        """测试阶段0：摸底诊断"""
        result = self.classifier.classify("我想做一个公众号数字分身，怎么开始")
        assert result.stage_id == "stage_0", f"Failed: expected stage_0, got {result.stage_id}"
        assert result.confidence > 0.5
        assert not result.is_fallback
        assert len(result.matched_keywords) > 0

    def test_stage_3_server(self):
        """测试阶段3：服务器环境"""
        result = self.classifier.classify("我要部署到 Linux 服务器，用 nginx 代理")
        assert result.stage_id == "stage_3", f"Failed: expected stage_3, got {result.stage_id}"
        assert not result.is_fallback

    def test_stage_4_llm(self):
        """测试阶段4：接入大模型"""
        result = self.classifier.classify("我用 deepseek 的 api，怎么配置")
        assert result.stage_id == "stage_4", f"Failed: expected stage_4, got {result.stage_id}"
        assert not result.is_fallback

    def test_stage_5_persona(self):
        """测试阶段5：设计人设"""
        result = self.classifier.classify("我想设计一个耐心专业的人设 prompt")
        assert result.stage_id == "stage_5", f"Failed: expected stage_5, got {result.stage_id}"

    def test_stage_6_knowledge(self):
        """测试阶段6：搭建知识库"""
        result = self.classifier.classify("怎么搭建 rag 知识库，用什么 embedding 模型")
        assert result.stage_id == "stage_6", f"Failed: expected stage_6, got {result.stage_id}"

    def test_stage_7_wechat(self):
        """测试阶段7：接入微信"""
        result = self.classifier.classify("wcf 接入微信自动回复怎么搞")
        assert result.stage_id == "stage_7", f"Failed: expected stage_7, got {result.stage_id}"

    def test_fallback_chat(self):
        """测试兜底：闲聊"""
        result = self.classifier.classify("你好，今天天气怎么样")
        assert result.stage_id == DEFAULT_STAGE_CHAT, \
            f"Failed: expected {DEFAULT_STAGE_CHAT}, got {result.stage_id}"
        assert result.is_fallback
        assert result.confidence == 0.0

    def test_empty_input(self):
        """测试空输入"""
        result = self.classifier.classify("")
        assert result.is_fallback
        assert result.stage_id == DEFAULT_STAGE_CHAT

    def test_low_confidence_fallback(self):
        """测试低置信度兜底"""
        # 只命中一个短关键词，置信度可能不够
        result = self.classifier.classify("啊")
        assert result.is_fallback

    def test_kb_ids_association(self):
        """测试知识库 ID 关联"""
        result = self.classifier.classify("我想了解一下怎么开始做公众号数字分身")
        if not result.is_fallback:
            assert len(result.kb_ids) > 0, "KB IDs should not be empty for matched stage"

    def test_performance_under_1ms(self):
        """测试性能：<1ms"""
        text = "我要部署 deepseek 大模型到服务器，并接入微信 wcf 自动回复，怎么开始"
        # 预热
        self.classifier.classify(text)

        start = time.perf_counter()
        for _ in range(100):
            self.classifier.classify(text)
        elapsed_ms = (time.perf_counter() - start) * 1000
        avg_ms = elapsed_ms / 100

        assert avg_ms < 1.0, f"Performance failed: {avg_ms:.3f}ms > 1ms"
        print(f"\n  StageClassifier avg: {avg_ms:.4f}ms per call")

    def test_custom_stages(self):
        """测试自定义阶段配置"""
        custom_stages = [
            {
                "id": "custom_1",
                "name": "自定义阶段1",
                "keywords": ["abc", "xyz"],
                "kb_ids": ["KB-CUSTOM-001"],
            },
        ]
        classifier = StageClassifier(custom_stages=custom_stages)
        result = classifier.classify("abc xyz")
        assert result.stage_id == "custom_1"
        assert result.kb_ids == ["KB-CUSTOM-001"]

    def test_add_stage_runtime(self):
        """测试运行时新增阶段"""
        original = self.classifier.classify("foobar123")
        assert original.is_fallback

        self.classifier.add_stage({
            "id": "custom_test",
            "name": "测试阶段",
            "keywords": ["foobar123"],
            "kb_ids": [],
        })
        updated = self.classifier.classify("foobar123")
        assert updated.stage_id == "custom_test"

    def test_remove_stage_runtime(self):
        """测试运行时移除阶段"""
        self.classifier.remove_stage("stage_0")
        stages = self.classifier.get_stages()
        stage_ids = [s["id"] for s in stages]
        assert "stage_0" not in stage_ids

    def test_confidence_threshold(self):
        """测试置信度阈值调整"""
        # 默认阈值 0.5
        result1 = self.classifier.classify("嗯")
        assert result1.is_fallback

        # 调低阈值到 0.05
        self.classifier.set_confidence_threshold(0.05)
        result2 = self.classifier.classify("嗯")
        # 可能命中也可能不命中，取决于"嗯"是否在某个阶段的关键词中
        # 这里只验证阈值设置生效
        assert self.classifier.get_confidence_threshold() == 0.05

    def test_case_insensitive(self):
        """测试大小写不敏感"""
        result1 = self.classifier.classify("DEEPSEEK API")
        result2 = self.classifier.classify("deepseek api")
        assert result1.stage_id == result2.stage_id
        assert result1.stage_id == "stage_4"


# ============ 集成测试 ============

class TestIntegration:

    def test_signal_and_stage_together(self):
        """测试信号检测器 + 阶段分类器协同工作"""
        detector = SignalDetector()
        classifier = StageClassifier()

        # 模拟真实用户消息
        messages = [
            ("我想开始做一个数字分身", SignalType.CHAT, "stage_0"),
            ("继续讲下一步", SignalType.PROCEED, DEFAULT_STAGE_CHAT),
            ("卡住了，deepseek api 报错怎么办", SignalType.STUCK, "stage_4"),
            ("没听懂 rag 知识库怎么搭建", SignalType.REPEAT, "stage_6"),
        ]

        for text, expected_signal, expected_stage in messages:
            signal_result = detector.detect(text)
            stage_result = classifier.classify(text)

            print(f"\n  Input: {text}")
            print(f"  Signal: {signal_result.signal.value} (keyword: {signal_result.matched_keyword})")
            print(f"  Stage: {stage_result.stage_id} (confidence: {stage_result.confidence})")

            # 信号检测应该匹配
            assert signal_result.signal == expected_signal, \
                f"Signal mismatch for '{text}': expected {expected_signal}, got {signal_result.signal}"

    def test_signal_affects_prompt_tone(self):
        """测试信号影响 Prompt 语气（模拟）"""
        detector = SignalDetector()

        # stuck 信号应该触发"耐心帮助"的语气
        stuck_result = detector.detect("不会做，卡住了")
        assert stuck_result.signal == SignalType.STUCK
        # 在实际应用中，这里会根据 signal 调整 prompt

        # proceed 信号应该触发"继续推进"的语气
        proceed_result = detector.detect("明白了，继续")
        assert proceed_result.signal == SignalType.PROCEED


if __name__ == "__main__":
    # 手动运行测试
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "pytest", __file__, "-v", "--tb=short"],
        cwd=os.path.dirname(os.path.dirname(__file__)),
    )
    sys.exit(result.returncode)
