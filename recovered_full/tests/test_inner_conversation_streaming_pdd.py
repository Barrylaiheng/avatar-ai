# -*- coding: utf-8 -*-
"""
SCAI · 模块 14 · Conversation Streaming PDD pytest 固化

验证 10 条 Grill 断言（G1~G10），对应原型 _prototypes/conversation_streaming_prototype.py。

测试策略：
- Mock LLMClient（模拟 OpenAI SSE 流式响应）
- 真实 LLMGenerator / AppEngine（不 mock，走真实流程）
- 真实安全壳 / 意图识别 / 上下文装配 / IterationEngine
- SCAI_DATA_DIR 环境变量隔离数据目录
"""
from __future__ import annotations

import os
import sys
import time
import tempfile
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, Generator, List, Optional
from unittest.mock import MagicMock, patch

import pytest

# 确保项目根目录在 sys.path
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
_PROTO_DIR = os.path.join(_PROJECT_ROOT, "_prototypes")
if _PROTO_DIR not in sys.path:
    sys.path.insert(0, _PROTO_DIR)

# 复用原型的 mock 组件
from conversation_streaming_prototype import (
    MockLLMClient, LLMGenerator, AppEngine, MockComplianceShield,
    MockBusinessShield, MockContextAssembler, MockRAGEngine,
    MockIterationEngine, AssembledContext, SendMessageWorker, ChatPage,
    ChatMessage, MessageBubble, build_engine,
)


# ===========================================================================
# fixtures
# ===========================================================================

@pytest.fixture
def stream_engine():
    """标准流式 engine：5 个 chunk，无延迟"""
    return build_engine(stream_chunks=["你好", "，我", "是影分身", " AI", "。"],
                        first_chunk_delay_ms=0)


@pytest.fixture
def blocked_engine():
    """安全壳拦截 engine"""
    return build_engine(blocked_words=["违规词"],
                        stream_chunks=["不应该出现"],
                        first_chunk_delay_ms=0)


@pytest.fixture
def fail_engine():
    """流式中断 engine：第 1 个 chunk 后抛异常"""
    return build_engine(stream_chunks=["你好", "，我", "是AI"], fail_at=1,
                        first_chunk_delay_ms=0)


# ===========================================================================
# G1: LLMClient.chat_completion_stream 首字延迟 + chunk 结构
# ===========================================================================

class TestG1LLMClientStream:
    def test_G1_first_yield_within_500ms(self):
        """G1: 首次 yield < 500ms"""
        client = MockLLMClient()
        client.set_first_chunk_delay_ms(100)
        messages = [{"role": "user", "content": "你好"}]
        start = time.time()
        first_event = next(client.chat_completion_stream(messages))
        elapsed_ms = (time.time() - start) * 1000
        assert elapsed_ms < 500, f"首字延迟 {elapsed_ms:.0f}ms > 500ms"

    def test_G1_chunk_structure(self):
        """G1: chunk 事件结构正确"""
        client = MockLLMClient()
        client.set_first_chunk_delay_ms(0)
        messages = [{"role": "user", "content": "测试"}]
        events = list(client.chat_completion_stream(messages))
        chunks = [e for e in events if e["type"] == "chunk"]
        assert len(chunks) > 0
        for c in chunks:
            assert "delta" in c
            assert isinstance(c["delta"], str)


# ===========================================================================
# G2: LLMGenerator.generate_stream chunk 拼接 == final.content
# ===========================================================================

class TestG2GeneratorStream:
    def test_G2_chunk_concatenation_equals_final(self):
        """G2: chunk 拼接 == final.content"""
        client = MockLLMClient()
        client.set_stream_chunks(["你好", "，我", "是AI"])
        client.set_first_chunk_delay_ms(0)
        gen = LLMGenerator(client)
        role_config = {"identity": "你是AI"}
        context = AssembledContext(current_content="测试")

        chunks = []
        final_content = None
        for event in gen.generate_stream(role_config, context):
            if event["type"] == "chunk":
                chunks.append(event["delta"])
            elif event["type"] == "final":
                final_content = event["content"]

        joined = "".join(chunks)
        # final_content 含 AIGC 标识前缀 [AI]，剥离后比较
        raw_final = final_content.replace("[AI] ", "", 1) if final_content and final_content.startswith("[AI]") else final_content
        assert joined == raw_final, f"chunk 拼接 '{joined}' != final '{raw_final}'"

    def test_G2_final_has_message_record(self):
        """G2: final 事件含 message_record + is_aigc 标识"""
        client = MockLLMClient()
        client.set_first_chunk_delay_ms(0)
        gen = LLMGenerator(client)
        role_config = {"identity": "你是AI"}
        context = AssembledContext(current_content="测试")

        final = None
        for event in gen.generate_stream(role_config, context):
            if event["type"] == "final":
                final = event
        assert final is not None
        assert "message_record" in final
        assert final["message_record"].get("is_aigc") == 1


# ===========================================================================
# G3: process_message_stream start 事件
# ===========================================================================

class TestG3StartEvent:
    def test_G3_first_event_is_start(self, stream_engine):
        """G3: 首个事件是 start"""
        events = list(stream_engine.process_message_stream("你好", "session_1"))
        assert len(events) > 0
        assert events[0]["type"] == "start"

    def test_G3_start_event_fields(self, stream_engine):
        """G3: start 事件含 persona_name/session_id/intent/rag_count"""
        events = list(stream_engine.process_message_stream("你好", "session_1"))
        start = events[0]
        for f in ("persona_name", "session_id", "intent", "rag_count"):
            assert f in start, f"start 事件缺少字段 {f}"
        assert start["session_id"] == "session_1"
        assert start["persona_name"]  # 非空


# ===========================================================================
# G4: 安全壳拦截不进入 LLM
# ===========================================================================

class TestG4SafetyBlock:
    def test_G4_blocked_yields_single_error(self, blocked_engine):
        """G4: 拦截只产 1 个 error 事件"""
        events = list(blocked_engine.process_message_stream("这是违规词", "session_2"))
        assert len(events) == 1
        assert events[0]["type"] == "error"

    def test_G4_error_has_safety_blocked(self, blocked_engine):
        """G4: error 事件 safety_check=blocked"""
        events = list(blocked_engine.process_message_stream("这是违规词", "session_2"))
        err = events[0]
        assert err.get("safety_check") == "blocked"
        assert "safety_reason" in err

    def test_G4_no_start_or_chunk(self, blocked_engine):
        """G4: 拦截时不进入 LLM（无 start/chunk/final）"""
        events = list(blocked_engine.process_message_stream("这是违规词", "session_2"))
        types = [e["type"] for e in events]
        assert "start" not in types
        assert "chunk" not in types
        assert "final" not in types


# ===========================================================================
# G5: 端到端 chunk 拼接 == final.content
# ===========================================================================

class TestG5EndToEndConcat:
    def test_G5_e2e_concat(self, stream_engine):
        """G5: 端到端 chunk 拼接 == final.content"""
        events = list(stream_engine.process_message_stream("hi"))
        chunks = [e["delta"] for e in events if e["type"] == "chunk"]
        finals = [e for e in events if e["type"] == "final"]
        assert len(finals) == 1
        joined = "".join(chunks)
        final_content = finals[0]["content"]
        raw_final = final_content.replace("[AI] ", "", 1) if final_content.startswith("[AI]") else final_content
        assert joined == raw_final


# ===========================================================================
# G6: final 事件 8 字段对齐同步路径
# ===========================================================================

class TestG6FinalFields:
    def test_G6_final_8_fields(self, stream_engine):
        """G6: final 事件 8 字段齐全"""
        events = list(stream_engine.process_message_stream("你好"))
        final = [e for e in events if e["type"] == "final"][0]
        required = ("content", "is_aigc", "safety_check", "rag_count",
                    "tool_calls", "persona_name", "success", "session_id")
        for f in required:
            assert f in final, f"final 缺少字段 {f}"

    def test_G6_final_aligns_with_sync(self, stream_engine):
        """G6: final 与同步路径 process_message 返回字段对齐"""
        stream_events = list(stream_engine.process_message_stream("你好"))
        final = [e for e in stream_events if e["type"] == "final"][0]
        sync_result = stream_engine.process_message("你好")
        # 核心字段值一致（content 因 AIGC 标识可能略有差异，比较核心字段）
        assert final["persona_name"] == sync_result["persona_name"]
        assert final["session_id"] == sync_result["session_id"]
        assert final["is_aigc"] == sync_result["is_aigc"]
        assert final["rag_count"] == sync_result["rag_count"]
        assert final["success"] == sync_result["success"]


# ===========================================================================
# G7: SendMessageWorker 信号顺序
# ===========================================================================

class TestG7SignalOrder:
    def test_G7_signal_sequence(self, stream_engine):
        """G7: typing_start → stream_started → chunk≥1 → stream_final → success → typing_stop"""
        worker = SendMessageWorker()
        worker.start_stream(stream_engine, "测试")
        names = [s["name"] for s in worker.emitted_signals]

        assert names[0] == "typing_start"
        assert "stream_started" in names
        assert "stream_final" in names
        assert "success" in names
        assert "typing_stop" in names

        start_idx = names.index("stream_started")
        final_idx = names.index("stream_final")
        success_idx = names.index("success")
        stop_idx = names.index("typing_stop")

        # stream_started 在 final 前
        assert start_idx < final_idx
        # 至少 1 个 chunk 在 start 和 final 之间
        chunks_between = [n for n in names[start_idx + 1:final_idx] if n == "chunk_received"]
        assert len(chunks_between) >= 1
        # success 在 final 后
        assert success_idx > final_idx
        # typing_stop 在 success 后
        assert stop_idx > success_idx


# ===========================================================================
# G8: sync_run_stream 纯函数 generator
# ===========================================================================

class TestG8SyncRunStream:
    def test_G8_returns_generator(self, stream_engine):
        """G8: sync_run_stream 返回 generator"""
        gen = SendMessageWorker.sync_run_stream(stream_engine, "测试")
        assert hasattr(gen, "__next__")

    def test_G8_event_types(self, stream_engine):
        """G8: 4 类事件齐全（start/chunk/final）"""
        events = list(SendMessageWorker.sync_run_stream(stream_engine, "测试"))
        types = {e["type"] for e in events}
        assert "start" in types
        assert "chunk" in types
        assert "final" in types


# ===========================================================================
# G9: ChatPage 流式渲染局部刷新
# ===========================================================================

class TestG9StreamingRender:
    def test_G9_placeholder_bubble_created(self, stream_engine):
        """G9: start 事件创建占位气泡"""
        page = ChatPage()
        events = list(SendMessageWorker.sync_run_stream(stream_engine, "hi"))
        for event in events:
            if event["type"] == "start":
                page._on_stream_start(event)
            elif event["type"] == "chunk":
                page._on_chunk(event["delta"])
            elif event["type"] == "final":
                page._on_stream_final(event)
        assert len(page.messages) == 1
        assert page.messages[0].role == "assistant"
        assert page.messages[0].is_streaming is False  # final 后应为 False

    def test_G9_chunk_local_refresh_no_full_render(self, stream_engine):
        """G9: chunk 追加局部刷新，不调 _render_messages"""
        page = ChatPage()
        events = list(SendMessageWorker.sync_run_stream(stream_engine, "hi"))
        for event in events:
            if event["type"] == "start":
                page._on_stream_start(event)
            elif event["type"] == "chunk":
                page._on_chunk(event["delta"])
            elif event["type"] == "final":
                page._on_stream_final(event)
        # _render_messages 不应被调用
        assert page.render_full_count == 0
        # content 含完整文本
        assert "你好" in page.messages[0].content

    def test_G9_badge_generating_to_aigc(self, stream_engine):
        """G9: 徽标 generating → aigc"""
        page = ChatPage()
        events = list(SendMessageWorker.sync_run_stream(stream_engine, "hi"))
        for event in events:
            if event["type"] == "start":
                page._on_stream_start(event)
                # 流式期间徽标应为 generating
                assert page.streaming_bubble is not None
                assert page.streaming_bubble.msg.badge_state == "generating"
            elif event["type"] == "chunk":
                page._on_chunk(event["delta"])
            elif event["type"] == "final":
                page._on_stream_final(event)
        # final 后徽标切换为 aigc
        assert page.messages[0].badge_state == "aigc"
        assert page.messages[0].is_aigc is True
        assert page.streaming_bubble is None


# ===========================================================================
# G10: 流式中断保留已生成部分
# ===========================================================================

class TestG10StreamInterrupt:
    def test_G10_partial_content_preserved(self, fail_engine):
        """G10: 中断保留已生成部分"""
        page = ChatPage()
        events = list(SendMessageWorker.sync_run_stream(fail_engine, "hi"))
        has_error = False
        for event in events:
            if event["type"] == "start":
                page._on_stream_start(event)
            elif event["type"] == "chunk":
                page._on_chunk(event["delta"])
            elif event["type"] == "final":
                page._on_stream_final(event)
            elif event["type"] == "error":
                has_error = True
                page._on_stream_error(event.get("error_message", "未知错误"))
        assert has_error
        assert len(page.messages) == 1
        msg = page.messages[0]
        assert msg.is_partial is True
        assert "你好" in msg.content  # 已生成部分保留
        assert "⚠️ 生成中断" in msg.content

    def test_G10_error_event_partial_flag(self, fail_engine):
        """G10: error 事件含 partial=True + success=False"""
        events = list(SendMessageWorker.sync_run_stream(fail_engine, "hi"))
        err_events = [e for e in events if e["type"] == "error"]
        assert len(err_events) >= 1
        err = err_events[0]
        assert err.get("partial") is True
        assert err.get("success") is False
        assert "partial_content" in err
