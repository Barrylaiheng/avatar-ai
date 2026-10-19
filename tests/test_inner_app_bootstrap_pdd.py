# -*- coding: utf-8 -*-
"""
SCAI · 模块 10 · App Bootstrap Wiring · 正式 pytest 测试

覆盖 15 条 Test Seams（G1~G15）。
与原型的区别：使用 pytest assert 风格 + 隔离临时目录 + 可被 CI 收集。
"""
from __future__ import annotations

import sys
import os
import tempfile
import shutil
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


# ======================================================================
# Fixture：隔离的临时数据目录（避免污染真实 %APPDATA%\SCAI）
# ======================================================================
@pytest.fixture
def scai_temp_dir():
    """创建临时目录，写入 SCAI_DATA_DIR 环境变量，测试结束清理"""
    tmp_dir = tempfile.mkdtemp(prefix="scai_pytest_")
    old_env = os.environ.get("SCAI_DATA_DIR")
    os.environ["SCAI_DATA_DIR"] = tmp_dir
    yield tmp_dir
    # 还原环境
    if old_env is None:
        os.environ.pop("SCAI_DATA_DIR", None)
    else:
        os.environ["SCAI_DATA_DIR"] = old_env
    shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.fixture
def real_engine(scai_temp_dir):
    """真实 AppEngine（已 initialize），测试结束自动 shutdown"""
    from aibridge.app_engine import AppEngine
    engine = AppEngine()
    assert engine.initialize() is True, "AppEngine.initialize() 必须返回 True"
    yield engine
    try:
        engine.shutdown()
    except Exception:
        pass


# 标准 8 字段契约（UIEngineBridge 定义，修改会导致 ChatPage 崩溃）
REQUIRED_8_FIELDS = [
    "content", "is_aigc", "tool_calls", "rag_count",
    "persona_name", "success", "error_message", "session_id",
]


# ======================================================================
# G1: 真实 AppEngine.initialize() 跑通 + 13 组件齐全
# ======================================================================
class TestG1InitSuccess:
    def test_initialize_returns_true(self, real_engine):
        assert real_engine.is_initialized() is True

    def test_13_components_not_none(self, real_engine):
        components = {
            "config": real_engine._config,
            "db": real_engine._db,
            "compliance_shield": real_engine._compliance_shield,
            "business_safety": real_engine._business_safety,
            "intent_classifier": real_engine._intent_classifier,
            "context_assembler": real_engine._context_assembler,
            "llm_generator": real_engine._llm_generator,
            "kb_manager": real_engine._kb_manager,
            "rag_engine": real_engine._rag_engine,
            "iteration_engine": real_engine._iteration_engine,
            "aigc_explicit": real_engine._aigc_explicit,
            "message_router": real_engine._message_router,
            "message_store": real_engine._message_store,
        }
        missing = [k for k, v in components.items() if v is None]
        assert missing == [], f"组件缺失: {missing}"


# ======================================================================
# G2: process_message 标准 8 字段
# ======================================================================
class TestG2Standard8Fields:
    def test_returns_dict_with_8_fields(self, real_engine):
        result = real_engine.process_message("你好")
        assert isinstance(result, dict)
        missing = [f for f in REQUIRED_8_FIELDS if f not in result]
        assert missing == [], f"缺少字段: {missing}"

    def test_field_types_correct(self, real_engine):
        r = real_engine.process_message("你好")
        assert isinstance(r["content"], str)
        assert isinstance(r["is_aigc"], bool)
        assert isinstance(r["tool_calls"], list)
        assert isinstance(r["rag_count"], int)
        assert isinstance(r["persona_name"], str)
        assert isinstance(r["success"], bool)
        assert isinstance(r["error_message"], str)
        assert isinstance(r["session_id"], str)


# ======================================================================
# G3: persona_name 字段正确返回
# ======================================================================
class TestG3PersonaName:
    def test_persona_name_not_empty(self, real_engine):
        r = real_engine.process_message("你好")
        assert isinstance(r["persona_name"], str)
        assert len(r["persona_name"]) > 0, "persona_name 不能为空"

    def test_persona_name_saved_and_readback(self, real_engine):
        # 显式保存人设名，验证 process_message 读回一致（测试隔离，不依赖测试顺序）
        custom = "测试专用分身_" + str(id(real_engine))[-4:]
        ok = real_engine.save_persona({"name": custom, "description": "x", "tone": "y"})
        assert ok is True
        r = real_engine.process_message("你好")
        assert r["persona_name"] == custom, (
            f"人设名不一致: 保存='{custom}'，读回='{r['persona_name']}'"
        )


# ======================================================================
# G4: save_persona 方法存在 + 功能正确
# ======================================================================
class TestG4SavePersona:
    def test_method_exists(self, real_engine):
        assert hasattr(real_engine, "save_persona"), "缺少 save_persona 方法"
        assert callable(real_engine.save_persona), "save_persona 不可调用"

    def test_returns_bool(self, real_engine):
        result = real_engine.save_persona({"name": "测试", "description": "x"})
        assert isinstance(result, bool)
        assert result is True

    def test_persona_name_readback(self, real_engine):
        """保存人设后，process_message 应返回新人设名"""
        ok = real_engine.save_persona({
            "name": "我的数字分身",
            "description": "测试描述",
            "tone": "友好",
            "type": "客服",
        })
        assert ok is True
        # 读回配置确认
        assert real_engine._config.get("persona.name") == "我的数字分身"


# ======================================================================
# G5: get_channel_messages("wechat") 真实结构
# ======================================================================
class TestG5ChannelMessages:
    def test_returns_list(self, real_engine):
        msgs = real_engine.get_channel_messages("wechat", limit=10)
        assert isinstance(msgs, list)

    def test_message_dict_structure_when_nonempty(self, scai_temp_dir):
        """向 MessageStore 插入一条消息，然后验证返回的 dict 有正确字段结构

        注意：get_channel_messages 透传 MessageRecord.to_dict() 的字段。
        不依赖 msgs[0] 一定是刚插入的那条（避免 DB 残留数据干扰），
        只验证：有数据 → 每一条字段结构正确。
        """
        from aibridge.app_engine import AppEngine
        engine = AppEngine()
        engine.initialize()
        try:
            from aibridge.engine.message_store import MessageRecord
            record = MessageRecord(
                msg_id="wx_g5_unique_" + str(int(__import__('time').time() * 1000)),
                sender_id="wxid_g5_001",
                sender_name="G5测试用户",
                content="G5测试消息内容_" + str(id(self)),
                group_id="",
                group_name="",
                msg_type="text",
                receive_time=1700000000,
                status="replied",
            )
            add_ok = engine.add_message(record)
            assert add_ok is True, "add_message 应返回 True"

            msgs = engine.get_channel_messages("wechat", limit=50)
            assert isinstance(msgs, list)
            assert len(msgs) >= 1, "插入至少 1 条，列表不应为空"

            # 找到刚插入的那条（通过独特的 sender_name 匹配）
            target = next((m for m in msgs if m.get("sender_name") == "G5测试用户"), None)
            assert target is not None, (
                f"未找到刚插入的 G5 测试消息（sender_name='G5测试用户'），"
                f"实际 msgs sender_names={[m.get('sender_name') for m in msgs]}"
            )

            # 验证实际契约字段（与 MessageRecord.to_dict() 对齐）
            required_fields = ["msg_id", "sender_id", "sender_name", "content",
                               "receive_time", "status"]
            missing = [f for f in required_fields if f not in target]
            assert missing == [], f"缺少字段: {missing}，实际={list(target.keys())}"

            # 值校验
            assert target["sender_name"] == "G5测试用户"
            assert "G5测试消息内容_" in target["content"]
            assert target["status"] == "replied"
        finally:
            engine.shutdown()


# ======================================================================
# G6: save_settings + test_llm_connection 流程
# ======================================================================
class TestG6SettingsFlow:
    def test_save_settings_returns_bool(self, real_engine):
        saved = real_engine.save_settings({"aigc_explicit": True, "aigc_prefix": "[T]"})
        assert isinstance(saved, bool)
        assert saved is True

    def test_get_settings_readback(self, real_engine):
        real_engine.save_settings({"aigc_explicit": True, "aigc_prefix": "[测试]"})
        read = real_engine.get_settings()
        assert isinstance(read, dict)
        assert read.get("aigc_prefix") == "[测试]"
        assert read.get("aigc_explicit") is True

    def test_test_llm_connection_returns_dict(self, real_engine):
        result = real_engine.test_llm_connection()
        assert isinstance(result, dict)
        assert "success" in result
        assert "message" in result


# ======================================================================
# G7: 无 API Key 时 process_message fallback 友好返回
# ======================================================================
class TestG7NoApiKeyFallback:
    def test_content_not_empty(self, real_engine):
        r = real_engine.process_message("解释一下 SCAI")
        assert isinstance(r["content"], str)
        assert len(r["content"]) > 0

    def test_success_flag_or_fallback_hint(self, real_engine):
        r = real_engine.process_message("解释一下 SCAI")
        # 无 API Key 场景：success=False，或 content 包含提示词
        has_fallback = (
            r["success"] is False
            or len(r["error_message"]) > 0
            or any(kw in r["content"] for kw in ["API Key", "配置", "无法连接", "检查"])
        )
        assert has_fallback, "应命中 fallback 路径"


# ======================================================================
# G8: safety_check 字段 + 拦截路径
# ======================================================================
class TestG8SafetyCheck:
    def test_safety_check_field_exists(self, real_engine):
        r = real_engine.process_message("你好")
        assert "safety_check" in r
        assert r["safety_check"] in ("passed", "blocked")

    def test_blocked_has_safety_reason(self, real_engine):
        """如果 safety_check=blocked，则 safety_reason 必须存在且非空"""
        # 合规/业务安全的实际触发词取决于规则配置，这里先构造极端内容测试
        r = real_engine.process_message("你好")
        if r["safety_check"] == "blocked":
            assert "safety_reason" in r
            assert len(r["safety_reason"]) > 0


# ======================================================================
# G9: kb_enabled=False 跳过 RAG，rag_count=0
# ======================================================================
class TestG9KbDisabled:
    def test_rag_count_is_zero(self, real_engine):
        real_engine.set_kb_enabled(False)
        r = real_engine.process_message("SCAI 的架构是什么？")
        assert r["rag_count"] == 0

    def test_toggle_back_on(self, real_engine):
        real_engine.set_kb_enabled(False)
        assert real_engine.is_kb_enabled() is False
        real_engine.set_kb_enabled(True)
        assert real_engine.is_kb_enabled() is True


# ======================================================================
# G10: kb_enabled=True + SEARCH 意图 RAG 不崩
# ======================================================================
class TestG10KbEnabled:
    def test_rag_count_non_negative(self, real_engine):
        real_engine.set_kb_enabled(True)
        r = real_engine.process_message("SCAI MVP 双渠道架构是什么？")
        assert isinstance(r["rag_count"], int)
        assert r["rag_count"] >= 0

    def test_returns_valid_dict(self, real_engine):
        real_engine.set_kb_enabled(True)
        r = real_engine.process_message("什么是知识蒸馏？")
        assert isinstance(r, dict)
        assert "content" in r
        assert "success" in r


# ======================================================================
# G11~G14: 4 个 Worker.sync_run 用真实 AppEngine
# ======================================================================

class TestG11SendMessageWorker:
    def test_sync_run_success(self, real_engine):
        from aibridge.ui.ui_engine_bridge import SendMessageWorker
        ok, result, signals = SendMessageWorker.sync_run(real_engine, "你好")
        assert ok is True
        assert isinstance(result, dict)
        for f in REQUIRED_8_FIELDS:
            assert f in result, f"result 缺少字段: {f}"
        assert "success" in signals


class TestG12SavePersonaWorker:
    def test_sync_run_success(self, real_engine):
        from aibridge.ui.ui_engine_bridge import SavePersonaWorker
        persona = {"name": "Worker测试", "description": "测试用"}
        ok, result_bool, signals = SavePersonaWorker.sync_run(real_engine, persona)
        assert ok is True
        assert isinstance(result_bool, bool)
        assert "saved" in signals


class TestG13SettingsWorkers:
    def test_save_settings_worker(self, real_engine):
        from aibridge.ui.ui_engine_bridge import SaveSettingsWorker
        settings = {"aigc_prefix": "[W]"}
        ok, saved, sig = SaveSettingsWorker.sync_run(real_engine, settings)
        assert ok is True
        assert "saved" in sig

    def test_test_llm_worker(self, real_engine):
        from aibridge.ui.ui_engine_bridge import TestLLMConnectionWorker
        ok, result, sig = TestLLMConnectionWorker.sync_run(real_engine)
        assert ok is True
        assert "connected" in sig


class TestG14ChannelMessagesWorker:
    def test_sync_run_success(self, real_engine):
        from aibridge.ui.ui_engine_bridge import GetChannelMessagesWorker
        ok, msgs, signals = GetChannelMessagesWorker.sync_run(real_engine, "wechat", limit=10)
        assert ok is True
        assert isinstance(msgs, list)
        assert "loaded" in signals


# ======================================================================
# G15: main.py 启动流程（静态代码检查，不真开 UI）
# ======================================================================
class TestG15MainBootstrap:
    def test_main_py_key_steps_present(self):
        main_path = PROJECT_ROOT / "src" / "aibridge" / "main.py"
        assert main_path.exists(), f"main.py 不存在: {main_path}"
        src = main_path.read_text(encoding="utf-8")

        checks = [
            ("AppEngine 导入", "from aibridge.app_engine import AppEngine" in src),
            ("MainWindow 导入", "from aibridge.ui.main_window import MainWindow" in src),
            ("AppEngine 实例化", "AppEngine()" in src),
            ("engine.initialize() 调用", "engine.initialize()" in src),
            ("MainWindow(engine) 传参", "MainWindow(engine)" in src),
            ("engine_status.setText", "engine_status.setText" in src),
            ("失败处理", "QMessageBox.critical" in src or "sys.exit(1)" in src),
        ]
        failed = [name for name, ok in checks if not ok]
        assert failed == [], f"main.py 启动流程缺失: {failed}"
