# -*- coding: utf-8 -*-
"""
SCAI · 里层 PDD · 模块 9 · Phase 5 TDD
模块：INNER-UI09 · 表层 UI 集成桥接层（UIEngineBridge）
Seams: 12
规范：表层 UI 集成桥接层设计文档

运行：
    pytest tests/test_inner_ui_engine_bridge_pdd.py -v
    # 预期：12 passed
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "_prototypes"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import pytest  # noqa: E402
from aibridge.ui.ui_engine_bridge import (  # noqa: E402
    SendMessageWorker,
    SavePersonaWorker,
    GetChannelMessagesWorker,
    SaveSettingsWorker,
    TestLLMConnectionWorker,
)


# ===========================================================================
# MiniMockEngine：内置在本测试文件，不 import 原型中的 MockAppEngine
# ===========================================================================

class MiniMockEngine:
    """
    极简 Mock AppEngine，只实现 5 个 Worker 需要的接口：
      process_message(user_input, channel) -> Dict
      save_persona(persona_dict) -> bool
      get_channel_messages(channel, limit) -> List[Dict]
      save_settings(settings_dict) -> bool
      test_llm_connection() -> Tuple[bool, str] 或 Dict
    """

    def __init__(self):
        # 配置开关（测试用）
        self.process_raise: bool = False          # BR-05: process_message 抛异常
        self.persona_raise: bool = False          # BR-08: save_persona 抛异常
        self.persona_return_false: bool = False   # BR-07: save_persona 返回 False
        self.llm_fail: bool = False               # BR-12: test_llm_connection 返回失败
        # 调用记录（BR-10 断言参数）
        self.calls_process: List[Tuple] = []
        self.calls_persona: List[Dict] = []
        self.calls_channel: List[Tuple] = []
        self.calls_settings: List[Dict] = []
        self.calls_llm_test: int = 0

    # ------------------------------------------------------------------
    # SendMessageWorker 需要
    # ------------------------------------------------------------------
    def process_message(self, user_input: str, channel: str = "chat") -> Dict[str, Any]:
        self.calls_process.append((user_input, channel))
        if self.process_raise:
            raise RuntimeError("boom")
        return {
            "content": "你好，我是搭搭AI～",
            "is_aigc": True,
            "tool_calls": [{"name": "search_kb", "args": {"query": "PDD"}}],
            "rag_count": 3,
            "persona_name": "搭搭AI",
            "success": True,
            "error_message": "",
            "session_id": "sess_001",
        }

    # ------------------------------------------------------------------
    # SavePersonaWorker 需要
    # ------------------------------------------------------------------
    def save_persona(self, persona_dict: Dict[str, Any]) -> bool:
        self.calls_persona.append(persona_dict)
        if self.persona_raise:
            raise ValueError("persona invalid")
        if self.persona_return_false:
            return False
        return True

    # ------------------------------------------------------------------
    # GetChannelMessagesWorker 需要
    # ------------------------------------------------------------------
    def get_channel_messages(self, channel: str, limit: int = 50) -> List[Dict]:
        self.calls_channel.append((channel, limit))
        if channel == "wechat":
            return [
                {"id": "m1", "name": "张三", "preview": "你好", "status": "未读", "channel": "wechat"},
                {"id": "m2", "name": "李四", "preview": "CPS怎么搞", "status": "已回复", "channel": "wechat"},
                {"id": "m3", "name": "王五", "preview": "知识库", "status": "处理中", "channel": "wechat"},
            ]
        elif channel == "oa":
            return [
                {"id": "oa1", "name": "用户A", "preview": "OA咨询", "status": "未读", "channel": "oa"},
            ]
        return []

    # ------------------------------------------------------------------
    # SaveSettingsWorker 需要
    # ------------------------------------------------------------------
    def save_settings(self, settings_dict: Dict[str, Any]) -> bool:
        self.calls_settings.append(settings_dict)
        return True

    # ------------------------------------------------------------------
    # TestLLMConnectionWorker 需要
    # ------------------------------------------------------------------
    def test_llm_connection(self) -> Tuple[bool, str]:
        self.calls_llm_test += 1
        if self.llm_fail:
            return (False, "401 Unauthorized")
        return (True, "Ping OK 230ms")


# ===========================================================================
# BR-01: SendMessageWorker 正常流程 → 8 字段齐全
# ===========================================================================

def run_br01_sendmessage_8fields() -> Tuple[bool, str]:
    engine = MiniMockEngine()
    ok, result, signals = SendMessageWorker.sync_run(engine, "你好", channel="chat")
    if not ok:
        return False, f"ok=False, err={result}"
    if "success" not in signals:
        return False, "signals 缺少 success"
    d = signals["success"]
    required = ["content", "is_aigc", "tool_calls", "rag_count",
                "persona_name", "success", "error_message", "session_id"]
    for k in required:
        if k not in d:
            return False, f"success dict 缺少字段: {k}"
    return True, f"8 字段齐全: {list(d.keys())}"


# ===========================================================================
# BR-02: SendMessageWorker → is_aigc=True
# ===========================================================================

def run_br02_is_aigc_true() -> Tuple[bool, str]:
    engine = MiniMockEngine()
    ok, result, signals = SendMessageWorker.sync_run(engine, "hi")
    if not ok:
        return False, f"ok=False"
    d = signals["success"]
    if d["is_aigc"] is not True:
        return False, f"is_aigc={d['is_aigc']}，期望 True"
    return True, f"is_aigc=True ✓"


# ===========================================================================
# BR-03: SendMessageWorker → rag_count=3
# ===========================================================================

def run_br03_rag_count_3() -> Tuple[bool, str]:
    engine = MiniMockEngine()
    ok, result, signals = SendMessageWorker.sync_run(engine, "PDD是什么")
    if not ok:
        return False, f"ok=False"
    d = signals["success"]
    if d["rag_count"] != 3:
        return False, f"rag_count={d['rag_count']}，期望 3"
    return True, f"rag_count=3 ✓"


# ===========================================================================
# BR-04: SendMessageWorker → tool_calls 有一条 name=search_kb
# ===========================================================================

def run_br04_tool_calls_1item() -> Tuple[bool, str]:
    engine = MiniMockEngine()
    ok, result, signals = SendMessageWorker.sync_run(engine, "查知识库")
    if not ok:
        return False, f"ok=False"
    d = signals["success"]
    tc = d["tool_calls"]
    if len(tc) != 1:
        return False, f"tool_calls len={len(tc)}，期望 1"
    if tc[0].get("name") != "search_kb":
        return False, f"tool_calls[0].name={tc[0].get('name')}，期望 search_kb"
    return True, f"tool_calls 1 条, name=search_kb ✓"


# ===========================================================================
# BR-05: SendMessageWorker 异常分支 → ok=False, err 含 "boom"
# ===========================================================================

def run_br05_exception_boom() -> Tuple[bool, str]:
    engine = MiniMockEngine()
    engine.process_raise = True
    ok, result, signals = SendMessageWorker.sync_run(engine, "会报错的输入")
    if ok:
        return False, "ok=True，期望抛异常后 ok=False"
    if "error" not in signals:
        return False, "signals 缺少 error"
    if "boom" not in str(result):
        return False, f"err 文本不含 'boom': {result}"
    return True, f"捕获异常, err 含 boom: {result} ✓"


# ===========================================================================
# BR-06: SavePersonaWorker 成功 → ok=True, saved=True
# ===========================================================================

def run_br06_save_persona_ok() -> Tuple[bool, str]:
    engine = MiniMockEngine()
    persona = {"identity": "测试人设", "tone": "友好"}
    ok, saved, signals = SavePersonaWorker.sync_run(engine, persona)
    if not ok:
        return False, f"ok=False, err={saved}"
    if "saved" not in signals:
        return False, "signals 缺少 saved"
    if signals["saved"] is not True:
        return False, f"saved={signals['saved']}，期望 True"
    return True, f"save_persona 成功 saved=True ✓"


# ===========================================================================
# BR-07: SavePersonaWorker 返回 False → ok=True, saved=False
# ===========================================================================

def run_br07_save_persona_false() -> Tuple[bool, str]:
    engine = MiniMockEngine()
    engine.persona_return_false = True
    ok, saved, signals = SavePersonaWorker.sync_run(engine, {})
    if not ok:
        return False, f"ok=False, 期望 ok=True（引擎正常返回 False 不算异常）"
    if signals["saved"] is not False:
        return False, f"saved={signals['saved']}，期望 False"
    return True, f"save_persona 返回 False 正常传达 saved=False ✓"


# ===========================================================================
# BR-08: SavePersonaWorker 抛异常 → ok=False
# ===========================================================================

def run_br08_save_persona_exception() -> Tuple[bool, str]:
    engine = MiniMockEngine()
    engine.persona_raise = True
    ok, err, signals = SavePersonaWorker.sync_run(engine, {})
    if ok:
        return False, "ok=True，期望抛异常后 ok=False"
    if "error" not in signals:
        return False, "signals 缺少 error"
    return True, f"save_persona 抛异常 ok=False, err={err} ✓"


# ===========================================================================
# BR-09: GetChannelMessagesWorker 正常 → 3 条 wechat，第一条 channel=wechat
# ===========================================================================

def run_br09_get_wechat_3msgs() -> Tuple[bool, str]:
    engine = MiniMockEngine()
    ok, msgs, signals = GetChannelMessagesWorker.sync_run(engine, "wechat", limit=50)
    if not ok:
        return False, f"ok=False, err={msgs}"
    if len(msgs) != 3:
        return False, f"len(msgs)={len(msgs)}，期望 3"
    first = msgs[0]
    if first.get("channel") != "wechat":
        return False, f"第一条 channel={first.get('channel')}，期望 wechat"
    for k in ["id", "name", "preview", "status"]:
        if k not in first:
            return False, f"第一条缺少字段 {k}"
    return True, f"3 条 wechat 消息，第一条 id={first['id']}, channel=wechat ✓"


# ===========================================================================
# BR-10: GetChannelMessagesWorker 渠道参数 → capture_args 验证
# ===========================================================================

def run_br10_channel_args_capture() -> Tuple[bool, str]:
    engine = MiniMockEngine()
    # 先查 wechat，再查 oa
    GetChannelMessagesWorker.sync_run(engine, "wechat", limit=10)
    GetChannelMessagesWorker.sync_run(engine, "oa", limit=20)
    calls = engine.calls_channel
    if len(calls) != 2:
        return False, f"调用次数={len(calls)}，期望 2"
    if calls[0] != ("wechat", 10):
        return False, f"第1次调用参数={calls[0]}，期望 ('wechat', 10)"
    if calls[1] != ("oa", 20):
        return False, f"第2次调用参数={calls[1]}，期望 ('oa', 20)"
    return True, f"参数正确传入: calls={calls} ✓"


# ===========================================================================
# BR-11: SaveSettingsWorker 正常 + LLM Test 正常
# ===========================================================================

def run_br11_settings_and_llm_test_ok() -> Tuple[bool, str]:
    engine = MiniMockEngine()
    settings = {"provider": "deepseek", "api_key": "sk-xxx"}
    ok1, saved1, sig1 = SaveSettingsWorker.sync_run(engine, settings)
    if not ok1 or sig1.get("saved") is not True:
        return False, f"SaveSettings 失败: ok={ok1}, saved={sig1.get('saved')}"
    ok2, conn2, sig2 = TestLLMConnectionWorker.sync_run(engine)
    if not ok2:
        return False, f"LLM Test 异常: {conn2}"
    ok_flag, msg = sig2["connected"]
    if ok_flag is not True:
        return False, f"LLM connected ok_flag={ok_flag}，期望 True"
    if msg != "Ping OK 230ms":
        return False, f"LLM message={msg}，期望 'Ping OK 230ms'"
    return True, f"settings_saved=True, llm_test=(True, '{msg}') ✓"


# ===========================================================================
# BR-12: LLM Test 失败 → (False, "401 Unauthorized")
# ===========================================================================

def run_br12_llm_test_fail() -> Tuple[bool, str]:
    engine = MiniMockEngine()
    engine.llm_fail = True
    ok, result, signals = TestLLMConnectionWorker.sync_run(engine)
    if not ok:
        return False, f"ok=False（引擎返回失败元组不应算 worker 异常）"
    ok_flag, msg = signals["connected"]
    if ok_flag is not False:
        return False, f"connected ok_flag={ok_flag}，期望 False"
    if msg != "401 Unauthorized":
        return False, f"message={msg}，期望 '401 Unauthorized'"
    return True, f"LLM 失败传达: (False, '{msg}') ✓"


# ===========================================================================
# 主运行器：收集 12 条结果
# ===========================================================================

ALL_SEAMS = [
    ("BR-01", "SendMessageWorker 正常流程 8 字段", run_br01_sendmessage_8fields),
    ("BR-02", "SendMessageWorker is_aigc=True", run_br02_is_aigc_true),
    ("BR-03", "SendMessageWorker rag_count=3", run_br03_rag_count_3),
    ("BR-04", "SendMessageWorker tool_calls 1条 search_kb", run_br04_tool_calls_1item),
    ("BR-05", "SendMessageWorker 异常捕获 boom", run_br05_exception_boom),
    ("BR-06", "SavePersonaWorker 成功 saved=True", run_br06_save_persona_ok),
    ("BR-07", "SavePersonaWorker 返回 False saved=False", run_br07_save_persona_false),
    ("BR-08", "SavePersonaWorker 抛异常 ok=False", run_br08_save_persona_exception),
    ("BR-09", "GetChannelMessagesWorker 3 条 wechat", run_br09_get_wechat_3msgs),
    ("BR-10", "GetChannelMessagesWorker 参数捕获", run_br10_channel_args_capture),
    ("BR-11", "SaveSettings + LLM Test 均正常", run_br11_settings_and_llm_test_ok),
    ("BR-12", "LLM Test 失败 401 Unauthorized", run_br12_llm_test_fail),
]


def run_all_seams() -> int:
    """主收集函数：打印每条结果，返回通过数量"""
    passed = 0
    total = len(ALL_SEAMS)
    print(f"\n{'='*60}")
    print(f"  UIEngineBridge PDD 测试报告  ({total} Seams)")
    print(f"{'='*60}")
    for code, name, fn in ALL_SEAMS:
        try:
            ok, desc = fn()
        except Exception as e:
            ok, desc = False, f"Seam 函数本身抛异常: {type(e).__name__}: {e}"
        status = "✓ PASS" if ok else "✗ FAIL"
        print(f"  [{code}] {status}  {name}")
        print(f"          → {desc}")
        if ok:
            passed += 1
    print(f"{'-'*60}")
    print(f"  测试报告  {passed}/{total} 通过")
    print(f"{'='*60}\n")
    return passed


# ===========================================================================
# pytest 测试（每条一个 test_ 函数）
# ===========================================================================

def test_br01_sendmessage_8fields():
    ok, _ = run_br01_sendmessage_8fields()
    assert ok

def test_br02_is_aigc_true():
    ok, _ = run_br02_is_aigc_true()
    assert ok

def test_br03_rag_count_3():
    ok, _ = run_br03_rag_count_3()
    assert ok

def test_br04_tool_calls_1item():
    ok, _ = run_br04_tool_calls_1item()
    assert ok

def test_br05_exception_boom():
    ok, _ = run_br05_exception_boom()
    assert ok

def test_br06_save_persona_ok():
    ok, _ = run_br06_save_persona_ok()
    assert ok

def test_br07_save_persona_false():
    ok, _ = run_br07_save_persona_false()
    assert ok

def test_br08_save_persona_exception():
    ok, _ = run_br08_save_persona_exception()
    assert ok

def test_br09_get_wechat_3msgs():
    ok, _ = run_br09_get_wechat_3msgs()
    assert ok

def test_br10_channel_args_capture():
    ok, _ = run_br10_channel_args_capture()
    assert ok

def test_br11_settings_and_llm_test_ok():
    ok, _ = run_br11_settings_and_llm_test_ok()
    assert ok

def test_br12_llm_test_fail():
    ok, _ = run_br12_llm_test_fail()
    assert ok


# ===========================================================================
# 直接运行：python tests/test_inner_ui_engine_bridge_pdd.py
# ===========================================================================

if __name__ == "__main__":
    passed_count = run_all_seams()
    assert passed_count == 12, f"期望 12/12 全绿，实际 {passed_count}/12"
    print("🎉 12/12 全部通过！")
