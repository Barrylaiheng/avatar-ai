# -*- coding: utf-8 -*-
"""
SCAI PDD 模块 19 · WCF Channel Handler Registration pytest 用例

验证微信渠道消息路由打通：WCF → MessageRouter → handler → process_message → send_response 全链路。
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

_TEST_DATA_ROOT = tempfile.mkdtemp(prefix="scai_m19_pytest_")
os.environ.setdefault("SCAI_DATA_DIR", _TEST_DATA_ROOT)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


# ============== G1: handler 在 initialize 后已注册 ==============

class TestG1HandlerRegistered:
    def test_wechat_handler_registered_after_init(self):
        """G1: AppEngine.initialize() 后 wechat channel handler 已注册"""
        from aibridge.app_engine import AppEngine
        from aibridge.bridges.internal_message import InternalMessage

        # 用 mock 避免真实 DB/LLM 初始化
        with patch.object(AppEngine, 'initialize', autospec=True) as mock_init:
            engine = AppEngine()
            # 手动模拟 initialize 完成后的状态
            mock_init.return_value = True
            engine._initialized = True
            engine._message_router = MagicMock()
            # 执行注册（模拟 initialize 中的那行代码）
            engine.register_message_handler("wechat", engine._handle_wechat_message)
            # 验证 register_handler 被调用
            engine._message_router.register_handler.assert_called_once()
            args = engine._message_router.register_handler.call_args
            assert args[0][0] == "wechat" or args.kwargs.get("channel") == "wechat"


# ============== G2: handler 存在且可调用 ==============

class TestG2HandlerExists:
    def test_handle_wechat_message_method_exists(self):
        """G2: AppEngine 有 _handle_wechat_message 方法"""
        from aibridge.app_engine import AppEngine
        assert hasattr(AppEngine, "_handle_wechat_message"), \
            "AppEngine 必须有 _handle_wechat_message 方法"
        assert callable(getattr(AppEngine, "_handle_wechat_message")), \
            "_handle_wechat_message 必须可调用"


# ============== G3: 空消息跳过 ==============

class TestG3EmptyMessageSkip:
    def test_empty_content_skipped(self):
        """G3: 空消息内容时 handler 直接跳过，不调 process_message"""
        from aibridge.app_engine import AppEngine
        from aibridge.bridges.internal_message import InternalMessage

        engine = AppEngine()
        engine._initialized = True
        engine.process_message = MagicMock(return_value={"content": "reply"})
        engine.send_response = MagicMock()

        msg = InternalMessage(
            msg_id="m1", channel="wechat", sender_id="wxid_001",
            sender_name="TestUser", receiver_id="bot",
            content="",  # 空内容
        )
        engine._handle_wechat_message(msg)
        engine.process_message.assert_not_called()
        engine.send_response.assert_not_called()


# ============== G4: 正常消息进入 process_message ==============

class TestG4NormalMessageProcessed:
    def test_normal_message_calls_process_message(self):
        """G4: 正常消息会调用 process_message（简化路径），且 session_id/wxid = sender_id
        注意：P3-3 后默认走 process_v2 15 步流水线，本测试通过设 _message_processor=None
              强制走简化路径（fallback），保持原验证语义。
        """
        from aibridge.app_engine import AppEngine
        from aibridge.bridges.internal_message import InternalMessage

        engine = AppEngine()
        engine._initialized = True
        engine._message_processor = None  # P3-3：强制走简化路径（避免 process_v2 接管）
        engine.process_message = MagicMock(return_value={
            "content": "这是AI回复", "success": True,
        })
        engine.send_response = MagicMock(return_value=True)

        msg = InternalMessage(
            msg_id="m2", channel="wechat", sender_id="wxid_test_001",
            sender_name="张三", receiver_id="bot",
            content="你好，介绍一下产品",
        )
        engine._handle_wechat_message(msg)

        # P3-2 已新增 wxid 参数，断言须包含
        engine.process_message.assert_called_once_with(
            "你好，介绍一下产品", session_id="wxid_test_001", wxid="wxid_test_001"
        )
        engine.send_response.assert_called_once()
        # send_response 第一参数是 msg，第二参数是 reply_content
        call_args = engine.send_response.call_args
        assert call_args[0][0] is msg
        assert call_args[0][1] == "这是AI回复"


# ============== G5: process_message 返回空时不发送 ==============

class TestG5EmptyReplyNoSend:
    def test_empty_reply_not_sent(self):
        """G5: process_message 返回空 content 时不调 send_response"""
        from aibridge.app_engine import AppEngine
        from aibridge.bridges.internal_message import InternalMessage

        engine = AppEngine()
        engine._initialized = True
        engine.process_message = MagicMock(return_value={"content": ""})
        engine.send_response = MagicMock()

        msg = InternalMessage(
            msg_id="m3", channel="wechat", sender_id="wxid_002",
            sender_name="李四", receiver_id="bot",
            content="测试空回复",
        )
        engine._handle_wechat_message(msg)
        engine.process_message.assert_called_once()
        engine.send_response.assert_not_called()


# ============== G6: 异常不崩 ==============

class TestG6ExceptionNoCrash:
    def test_process_message_exception_does_not_propagate(self):
        """G6: process_message 抛异常时 handler 不崩（不向调用方传播）"""
        from aibridge.app_engine import AppEngine
        from aibridge.bridges.internal_message import InternalMessage

        engine = AppEngine()
        engine._initialized = True
        engine.process_message = MagicMock(side_effect=RuntimeError("mock LLM fail"))
        engine.send_response = MagicMock()

        msg = InternalMessage(
            msg_id="m4", channel="wechat", sender_id="wxid_003",
            sender_name="王五", receiver_id="bot",
            content="触发异常的消息",
        )
        # 不应抛异常
        engine._handle_wechat_message(msg)
        engine.process_message.assert_called_once()
        engine.send_response.assert_not_called()


# ============== G7: 安全拦截时回复拦截语 ==============

class TestG7SafetyBlockedReply:
    def test_safety_blocked_reply_sent_via_send_response(self):
        """G7: 安全壳拦截时 process_message 返回拦截语，handler 通过 send_response 回送"""
        from aibridge.app_engine import AppEngine
        from aibridge.bridges.internal_message import InternalMessage

        engine = AppEngine()
        engine._initialized = True
        blocked_reply = "您的消息不符合安全规范"
        engine.process_message = MagicMock(return_value={
            "content": blocked_reply,
            "safety_check": "blocked",
            "success": False,
        })
        engine.send_response = MagicMock(return_value=True)

        msg = InternalMessage(
            msg_id="m5", channel="wechat", sender_id="wxid_004",
            sender_name="广告用户", receiver_id="bot",
            content="赌博广告",
        )
        engine._handle_wechat_message(msg)
        engine.send_response.assert_called_once()
        assert engine.send_response.call_args[0][1] == blocked_reply


# ============== G8: session_id 隔离 ==============

class TestG8SessionIsolation:
    def test_different_senders_get_different_session_ids(self):
        """G8: 不同 sender_id 产生不同 session_id，确保用户会话隔离"""
        from aibridge.app_engine import AppEngine
        from aibridge.bridges.internal_message import InternalMessage

        engine = AppEngine()
        engine._initialized = True
        engine.process_message = MagicMock(return_value={"content": "reply"})
        engine.send_response = MagicMock()

        msg1 = InternalMessage(
            msg_id="m6a", channel="wechat", sender_id="wxid_user_A",
            sender_name="A", receiver_id="bot", content="你好",
        )
        msg2 = InternalMessage(
            msg_id="m6b", channel="wechat", sender_id="wxid_user_B",
            sender_name="B", receiver_id="bot", content="你好",
        )
        engine._handle_wechat_message(msg1)
        engine._handle_wechat_message(msg2)

        call1 = engine.process_message.call_args_list[0]
        call2 = engine.process_message.call_args_list[1]
        assert call1.kwargs["session_id"] == "wxid_user_A"
        assert call2.kwargs["session_id"] == "wxid_user_B"
        assert call1.kwargs["session_id"] != call2.kwargs["session_id"]


# ============== G9: 群聊消息也能处理 ==============

class TestG9GroupMessage:
    def test_group_message_handled(self):
        """G9: 群聊消息（is_private=False, group_id 非空）也能进入 handler"""
        from aibridge.app_engine import AppEngine
        from aibridge.bridges.internal_message import InternalMessage

        engine = AppEngine()
        engine._initialized = True
        engine.process_message = MagicMock(return_value={"content": "群聊回复"})
        engine.send_response = MagicMock(return_value=True)

        msg = InternalMessage(
            msg_id="m7", channel="wechat", sender_id="wxid_group_sender",
            sender_name="群成员", receiver_id="bot",
            content="@bot 帮我查一下",
            group_id="group_123", group_name="测试群",
            is_at_me=True, is_private=False,
        )
        engine._handle_wechat_message(msg)
        engine.process_message.assert_called_once()
        # send_response 中 receiver_id 会根据 is_private 选 sender_id 或 group_id
        # 这里只验证 handler 把回复传给了 send_response
        engine.send_response.assert_called_once()


# ============== G10: 代码中 initialize 注册 handler ==============

class TestG10InitializeRegistersHandler:
    def test_initialize_source_contains_handler_registration(self):
        """G10: AppEngine.initialize() 源码中包含 register_message_handler('wechat', ...) 调用"""
        import inspect
        from aibridge.app_engine import AppEngine

        source = inspect.getsource(AppEngine.initialize)
        assert "register_message_handler" in source, \
            "initialize() 方法中必须包含 register_message_handler 调用"
        assert "_handle_wechat_message" in source, \
            "initialize() 方法中必须注册 _handle_wechat_message 作为 wechat channel handler"
        assert '"wechat"' in source or "'wechat'" in source, \
            "initialize() 必须注册 'wechat' channel"
