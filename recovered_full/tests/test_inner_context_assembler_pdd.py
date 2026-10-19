# -*- coding: utf-8 -*-
"""
里层 PDD · 模块 3 · Phase 5 TDD · ContextAssemblerV2 测试
模块：src/aibridge/engine/context_assembler_v2.py（神经 L4）

8 Seams：
  CA-01: 基础 assemble（无 persona、无 RAG）→ system+user
  CA-02: persona 注入 → system message 含身份/语气
  CA-03: RAG 命中 → knowledge 片段注入
  CA-04: RAG 无命中 → 不注入 knowledge
  CA-05: 历史超窗口 → 截断到 N 轮
  CA-06: messages 结构 → [system, ...history, user]
  CA-07: persona 七段式结构完整
  CA-08: 空 history → 只有 system+user

执行: pytest tests/test_inner_context_assembler_pdd.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


# ---------------- Fixtures ----------------

@pytest.fixture
def rag_engine():
    from aibridge.engine.context_assembler_v2 import MockRagEngine
    return MockRagEngine({"奶茶优惠": "一点点第二杯半价，限工作日下午。"})


@pytest.fixture
def rag_empty():
    from aibridge.engine.context_assembler_v2 import MockRagEngine
    return MockRagEngine({})


@pytest.fixture
def assembler(rag_engine):
    from aibridge.engine.context_assembler_v2 import ContextAssemblerV2
    return ContextAssemblerV2(rag_engine=rag_engine)


@pytest.fixture
def assembler_empty(rag_empty):
    from aibridge.engine.context_assembler_v2 import ContextAssemblerV2
    return ContextAssemblerV2(rag_engine=rag_empty)


# ======================================================================
# CA-01 ~ CA-08
# ======================================================================

def test_ca01_basic_assemble(assembler_empty):
    """CA-01：基础 assemble（无 persona、无 RAG）→ system+user"""
    from aibridge.engine.context_assembler_v2 import PersonaTemplate
    result = assembler_empty.assemble_prompt("你好", history=[])
    assert len(result.messages) == 2
    assert result.messages[0]["role"] == "system"
    assert result.messages[1]["role"] == "user"
    assert result.messages[1]["content"] == "你好"


def test_ca02_persona_injection(assembler_empty):
    """CA-02：persona 注入 → system message 含身份/语气"""
    from aibridge.engine.context_assembler_v2 import PersonaTemplate
    p = PersonaTemplate(identity="你是测试分身", tone="严肃")
    result = assembler_empty.assemble_prompt("你好", persona=p)
    system_msg = result.messages[0]["content"]
    assert "测试分身" in system_msg
    assert "严肃" in system_msg


def test_ca03_rag_hit(assembler):
    """CA-03：RAG 命中 → knowledge 片段注入到 system"""
    result = assembler.assemble_prompt("奶茶有啥优惠", rag_query="奶茶有啥优惠")
    system_msg = result.messages[0]["content"]
    assert "检索到的知识" in system_msg
    assert "一点点" in system_msg
    assert len(result.rag_hits) > 0


def test_ca04_rag_no_hit(assembler_empty):
    """CA-04：RAG 无命中 → 不注入 knowledge"""
    result = assembler_empty.assemble_prompt("今天天气如何", rag_query="今天天气如何")
    system_msg = result.messages[0]["content"]
    assert "检索到的知识" not in system_msg
    assert len(result.rag_hits) == 0


def test_ca05_history_truncation(assembler_empty):
    """CA-05：历史超窗口 → 截断到 10 轮（20 条）"""
    long_history = []
    for i in range(15):
        long_history.append({"role": "user", "content": f"历史消息 {i}"})
        long_history.append({"role": "assistant", "content": f"回复 {i}"})
    result = assembler_empty.assemble_prompt("最新消息", history=long_history)
    assert result.truncated is True
    assert result.history_count == 20


def test_ca06_messages_structure(assembler_empty):
    """CA-06：messages 结构 → [system, user, assistant, user]"""
    result = assembler_empty.assemble_prompt("你好", history=[
        {"role": "user", "content": "之前说的"},
        {"role": "assistant", "content": "之前的回复"},
    ])
    roles = [m["role"] for m in result.messages]
    assert roles == ["system", "user", "assistant", "user"]


def test_ca07_persona_seven_sections(assembler_empty):
    """CA-07：persona 七段式结构完整"""
    from aibridge.engine.context_assembler_v2 import PersonaTemplate
    p = PersonaTemplate.default()
    prompt = p.to_system_prompt()
    for section in ["身份", "语气", "知识边界", "回复规则", "安全底线", "示例", "语言风格"]:
        assert section in prompt, f"缺少【{section}】段"


def test_ca08_empty_history(assembler_empty):
    """CA-08：空 history → 只有 system+user"""
    result = assembler_empty.assemble_prompt("你好", history=[])
    assert len(result.messages) == 2
    assert result.history_count == 0
    assert result.truncated is False
