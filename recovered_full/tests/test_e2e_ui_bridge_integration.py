# -*- coding: utf-8 -*-
"""
SCAI · 端到端 UI ↔ Engine 集成测试

验证 ChatPage 接入 UIEngineBridge 后：
1. 用户发消息 → Bridge 异步调 Engine → AI 气泡渲染 AIGC 徽标
2. RAG 命中数正确显示
3. 人设名称正确显示
4. 错误场景 → 错误气泡 + Toast

依赖：PyQt6（已安装）+ pytest-qt（已安装）
运行：python -m pytest tests/test_e2e_ui_bridge_integration.py -v
"""
from __future__ import annotations

import sys
import time
from typing import Any, Dict, List, Tuple
from pathlib import Path

# 路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "_prototypes"))

import pytest
from PyQt6.QtCore import QTimer, QEventLoop
from PyQt6.QtWidgets import QApplication

# 确保有 QApplication 实例
app = QApplication.instance() or QApplication(sys.argv)


# ===========================================================================
# MockAppEngine — 模拟真实 AppEngine 的 8 字段返回
# ===========================================================================
class MockAppEngine:
    """模拟 AppEngine：process_message / save_persona / get_channel_messages / save_settings / test_llm_connection"""

    def __init__(self):
        self._call_count = 0
        self._saved_personas: List[Dict] = []
        self._settings: Dict[str, Any] = {}
        self._persona_callbacks: List = []

    def register_persona_changed_callback(self, callback):
        """M-11 人设变更回调注册"""
        self._persona_callbacks.append(callback)

    def get_current_persona_dict(self) -> Dict[str, Any]:
        """返回当前人设字典"""
        if self._saved_personas:
            return self._saved_personas[-1]
        return {
            "name": "鲜果小助手",
            "type": "水果商家数字分身",
            "description": "帮助水果商家在微信公众号自动回复客户咨询",
            "tone": "热情、专业、耐心",
            "avatar": "🎭",
            "background_story": "",
            "language_style": "",
            "keywords": "",
        }

    def process_message(self, user_input: str, channel: str = "chat") -> Dict[str, Any]:
        self._call_count += 1
        time.sleep(0.05)  # 模拟 LLM 延迟 50ms

        # 根据 user_input 内容返回不同场景
        if "报错" in user_input or "boom" in user_input.lower():
            raise RuntimeError("模拟引擎爆炸 boom!")

        if "知识库" in user_input or "RAG" in user_input.upper():
            return {
                "content": "根据知识库记载，影分身AI 的核心架构包括供血、免疫、神经三大系统。",
                "is_aigc": True,
                "tool_calls": [{"tool": "search_kb", "result": {"success": True, "hits": 3}}],
                "rag_count": 3,
                "persona_name": "AI 实战导师",
                "success": True,
                "error_message": "",
                "session_id": "test_session_001",
            }

        # 默认正常回复
        return {
            "content": f"你好！收到你的消息：「{user_input}」。我是 AI 数字分身，很高兴为你服务。",
            "is_aigc": True,
            "tool_calls": [],
            "rag_count": 0,
            "persona_name": "水果小助手",
            "success": True,
            "error_message": "",
            "session_id": "test_session_001",
        }

    # ===== M-14 流式路径：ChatPage 优先走 start_send_message_stream → engine.process_message_stream =====
    def process_message_stream(self, user_input: str, session_id: str = None, **kwargs):
        """
        模拟真实 AppEngine.process_message_stream 的事件序列。

        Yields:
            start → chunk(s) → final   (正常路径)
            或直接抛异常               (错误路径，由 bridge 捕获并 emit error 信号)
        """
        from typing import Generator
        self._call_count += 1
        time.sleep(0.02)  # 模拟 LLM 延迟 20ms（比同步路径短，避免串跑超时）

        # 错误场景：直接抛出，由 bridge._Runner 捕获并 emit error 信号
        if "报错" in user_input or "boom" in user_input.lower():
            raise RuntimeError("模拟引擎爆炸 boom!")

        # 判断是否为 RAG 场景（与同步路径保持一致）
        is_rag = ("知识库" in user_input) or ("RAG" in user_input.upper())
        if is_rag:
            persona_name = "AI 实战导师"
            rag_count = 3
            content = "根据知识库记载，影分身AI 的核心架构包括供血、免疫、神经三大系统。"
            tool_calls = [{"tool": "search_kb", "result": {"success": True, "hits": 3}}]
            intent = "search"
        else:
            persona_name = "水果小助手"
            rag_count = 0
            content = f"你好！收到你的消息：「{user_input}」。我是 AI 数字分身，很高兴为你服务。"
            tool_calls = []
            intent = "chat"

        sid = session_id or "test_session_001"

        # 1) start 事件（G3）：ChatPage 据此创建占位气泡
        yield {
            "type": "start",
            "persona_name": persona_name,
            "session_id": sid,
            "intent": intent,
            "rag_count": rag_count,
        }

        # 2) chunk 事件（G9）：拆分为多个 delta 模拟流式追加
        chunk_size = 8
        for i in range(0, len(content), chunk_size):
            yield {"type": "chunk", "delta": content[i:i + chunk_size]}

        # 3) final 事件（G6）：8 字段对齐同步路径
        yield {
            "type": "final",
            "content": content,
            "is_aigc": True,
            "tool_calls": tool_calls,
            "rag_count": rag_count,
            "persona_name": persona_name,
            "success": True,
            "error_message": "",
            "session_id": sid,
        }

    def save_persona(self, persona_dict: Dict[str, Any]) -> bool:
        self._saved_personas.append(persona_dict)
        return True

    def get_channel_messages(self, channel: str, limit: int = 50) -> List[Dict[str, Any]]:
        return [
            {"id": "msg_001", "name": "王先生", "preview": "葡萄有货吗？", "time": "12:30", "status": "replied", "chat_type": "private"},
            {"id": "msg_002", "name": "水果群", "preview": "今天有活动吗？", "time": "12:45", "status": "replied", "chat_type": "group"},
            {"id": "msg_003", "name": "李女士", "preview": "下单一箱苹果", "time": "13:00", "status": "pending", "chat_type": "private"},
        ]

    def save_settings(self, settings_dict: Dict[str, Any]) -> bool:
        self._settings = settings_dict
        return True

    def test_llm_connection(self) -> Tuple[bool, str]:
        if self._settings.get("api_key", "").startswith("sk-"):
            return True, "Ping OK 120ms"
        return False, "401 Unauthorized"


# ===========================================================================
# 辅助：等待信号或超时
# ===========================================================================
def _wait_for_condition(check_fn, timeout_ms=3000, interval_ms=50):
    """轮询等待条件满足或超时"""
    elapsed = 0
    while elapsed < timeout_ms:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents)
        if check_fn():
            return True
        time.sleep(interval_ms / 1000.0)
        elapsed += interval_ms
    return False


# ===========================================================================
# Test Seams
# ===========================================================================

class TestE2EUIBridgeIntegration:
    """端到端 UI ↔ Engine 集成测试"""

    def test_e2e_01_normal_reply_with_aigc_badge(self):
        """E2E-01: 正常发消息 → AI 气泡显示 AIGC 徽标"""
        from aibridge.ui.chat_page import ChatPage

        engine = MockAppEngine()
        page = ChatPage(app_engine=engine)
        page.show()

        # 模拟用户输入
        page._input_edit.setPlainText("你好，介绍一下自己")
        page._on_send_click()

        # 等待异步回复（最长 3s）
        sid = page.active_session_id()
        ok = _wait_for_condition(
            lambda: len(page.sessions()[sid].messages) >= 2,
            timeout_ms=3000,
        )
        assert ok, "超时：未收到 AI 回复"

        msgs = page.sessions()[sid].messages
        assert msgs[0].role == "user"
        assert msgs[1].role == "assistant"
        assert msgs[1].is_aigc is True, "AI 回复缺少 is_aigc=True 标识"
        assert "AI 数字分身" in msgs[1].content
        assert msgs[1].persona_name == "水果小助手"
        page.close()

    def test_e2e_02_rag_hits_displayed(self):
        """E2E-02: RAG 命中时气泡显示知识库命中数"""
        from aibridge.ui.chat_page import ChatPage

        engine = MockAppEngine()
        page = ChatPage(app_engine=engine)
        page.show()

        page._input_edit.setPlainText("请查一下知识库")
        page._on_send_click()

        sid = page.active_session_id()
        ok = _wait_for_condition(
            lambda: len(page.sessions()[sid].messages) >= 2,
            timeout_ms=3000,
        )
        assert ok, "超时：未收到 AI 回复"

        reply = page.sessions()[sid].messages[1]
        assert reply.rag_count == 3, f"RAG 命中数错误: {reply.rag_count}"
        assert reply.tool_calls, "tool_calls 为空"
        assert reply.tool_calls[0]["tool"] == "search_kb"
        page.close()

    def test_e2e_03_error_handling(self):
        """E2E-03: 引擎异常 → 显示错误气泡"""
        from aibridge.ui.chat_page import ChatPage

        engine = MockAppEngine()
        page = ChatPage(app_engine=engine)
        page.show()

        page._input_edit.setPlainText("触发报错 boom")
        page._on_send_click()

        sid = page.active_session_id()
        ok = _wait_for_condition(
            lambda: len(page.sessions()[sid].messages) >= 2,
            timeout_ms=3000,
        )
        assert ok, "超时：未收到错误回复"

        reply = page.sessions()[sid].messages[1]
        assert "⚠️" in reply.content, f"错误气泡缺少 ⚠️: {reply.content}"
        assert "boom" in reply.content, f"错误气泡缺少 boom: {reply.content}"
        page.close()

    def test_e2e_04_persona_name_displayed(self):
        """E2E-04: 人设名称正确显示在气泡上"""
        from aibridge.ui.chat_page import ChatPage

        engine = MockAppEngine()
        page = ChatPage(app_engine=engine)
        page.show()

        page._input_edit.setPlainText("知识库查询")
        page._on_send_click()

        sid = page.active_session_id()
        ok = _wait_for_condition(
            lambda: len(page.sessions()[sid].messages) >= 2,
            timeout_ms=3000,
        )
        assert ok

        reply = page.sessions()[sid].messages[1]
        assert reply.persona_name == "AI 实战导师", f"人设名错误: {reply.persona_name}"
        page.close()

    def test_e2e_05_workbench_loads_from_engine(self):
        """E2E-05: Workbench 从 Engine 拉取真实消息"""
        from aibridge.ui.workspace_page import WorkspacePage

        engine = MockAppEngine()
        page = WorkspacePage(app_engine=engine)
        page.show()

        # 等待异步加载完成
        ok = _wait_for_condition(
            lambda: len(page._messages.get("wechat", [])) == 3,
            timeout_ms=3000,
        )
        assert ok, "超时：Workbench 未从引擎加载消息"

        msgs = page._messages["wechat"]
        assert msgs[0].name == "王先生"
        assert msgs[1].chat_type == "group"
        assert msgs[2].status == "pending"
        page.close()

    def test_e2e_06_settings_save_and_test_llm(self):
        """E2E-06: Settings 保存配置 → 自动测试 LLM 连接"""
        from aibridge.ui.settings_page_v2 import SettingsPage

        engine = MockAppEngine()
        page = SettingsPage(app_engine=engine)
        page.show()

        # 模拟输入 API Key
        page._apikey_edit.setText("sk-test123456")

        # 触发保存
        page._on_save_llm()

        # 等待异步保存 + 测试连接完成
        ok = _wait_for_condition(
            lambda: engine._settings.get("api_key") == "sk-test123456",
            timeout_ms=3000,
        )
        assert ok, "超时：设置未保存到引擎"
        assert engine._settings["active_provider"] == "deepseek"
        page.close()

    def test_e2e_07_backward_compatible_no_engine(self):
        """E2E-07: app_engine=None 时走 mock 回复（向后兼容）"""
        from aibridge.ui.chat_page import ChatPage

        page = ChatPage()  # 无 app_engine
        page.show()

        page._input_edit.setPlainText("测试 mock 回复")
        page._on_send_click()

        # mock 回复走 QTimer.singleShot(1200ms)
        sid = page.active_session_id()
        ok = _wait_for_condition(
            lambda: len(page.sessions()[sid].messages) >= 2,
            timeout_ms=3000,
        )
        assert ok, "超时：mock 回复未到达"

        reply = page.sessions()[sid].messages[1]
        assert reply.role == "assistant"
        assert reply.is_aigc is False  # mock 回复不走 AIGC 标记
        page.close()

    def test_e2e_08_multiple_messages_in_sequence(self):
        """E2E-08: 连续发 3 条消息，验证会话消息数累积"""
        from aibridge.ui.chat_page import ChatPage

        engine = MockAppEngine()
        page = ChatPage(app_engine=engine)
        page.show()

        messages_to_send = ["第一条", "第二条", "知识库"]
        for text in messages_to_send:
            page._input_edit.setPlainText(text)
            page._on_send_click()

            sid = page.active_session_id()
            # 等待这条回复到达
            expected = len(messages_to_send[:messages_to_send.index(text) + 1]) * 2
            ok = _wait_for_condition(
                lambda: len(page.sessions()[sid].messages) >= expected,
                timeout_ms=3000,
            )
            assert ok, f"超时：第 {messages_to_send.index(text) + 1} 条回复未到达"

        sid = page.active_session_id()
        total_msgs = len(page.sessions()[sid].messages)
        assert total_msgs == 6, f"期望 6 条消息（3 用户 + 3 AI），实际 {total_msgs}"

        # 最后一条有 RAG 命中
        last_reply = page.sessions()[sid].messages[-1]
        assert last_reply.rag_count == 3
        page.close()


if __name__ == "__main__":
    # 直接运行：python tests/test_e2e_ui_bridge_integration.py
    pytest.main([__file__, "-v", "--tb=short"])
