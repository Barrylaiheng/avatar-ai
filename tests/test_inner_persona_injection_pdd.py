# -*- coding: utf-8 -*-
"""
SCAI · 模块 11 · Persona Injection Chain · 正式 pytest 测试

覆盖 15 条 Grill Seams（P1~P15，跳过 P11：需要真实 LLM API Key）。
核心断言：PersonaEditor 保存的 name/description/tone/type 等人设字段，必须正确、完整、
按增量语义写入 ConfigManager.persona.*；并在下一次 AppEngine.process_message()
时，通过 role_config → PromptAssembler.assemble() 注入 LLM System Prompt 的
【角色身份】/【语气风格】/【角色规则】段落，最终影响 LLM 回答的口吻/自称/内容边界。
"""
from __future__ import annotations

import sys
import os
import tempfile
import shutil
from pathlib import Path
from typing import Dict

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


# ======================================================================
# Fixtures
# ======================================================================
@pytest.fixture
def scai_temp_dir():
    """隔离临时数据目录（SCAI_DATA_DIR 环境变量覆盖）"""
    tmp_dir = tempfile.mkdtemp(prefix="scai_p11_")
    old_env = os.environ.get("SCAI_DATA_DIR")
    os.environ["SCAI_DATA_DIR"] = tmp_dir
    yield tmp_dir
    if old_env is None:
        os.environ.pop("SCAI_DATA_DIR", None)
    else:
        os.environ["SCAI_DATA_DIR"] = old_env
    shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.fixture
def real_engine(scai_temp_dir):
    """真实 AppEngine，测试结束自动 shutdown"""
    from aibridge.app_engine import AppEngine
    engine = AppEngine()
    assert engine.initialize() is True
    yield engine
    try:
        engine.shutdown()
    except Exception:
        pass


# ======================================================================
# Helper：hook 住 LLMGenerator.generate 捕获传进去的 role_config
# ======================================================================
def capture_role_config(engine, user_input: str = "hi") -> Dict:
    """
    临时 hook 住 engine._llm_generator.generate，在 process_message 调用时
    捕获 role_config 参数并立即返回，避免真实 LLM 调用（不依赖 API Key 也能断言）。
    """
    captured = {}
    original_generate = engine._llm_generator.generate

    class _StopHook(Exception):
        pass

    def _hook(role_config, context, rag_result=None):
        captured["role_config"] = role_config
        raise _StopHook("stop")

    try:
        engine._llm_generator.generate = _hook
        engine.process_message(user_input)
    except Exception:
        pass
    finally:
        engine._llm_generator.generate = original_generate

    assert "role_config" in captured, "Hook 未捕获 role_config（process_message 流程可能异常）"
    return captured["role_config"]


def assemble_system_prompt(engine, role_config: Dict, rag_result=None):
    """直接调用 PromptAssembler.assemble() 产出 system prompt 文本"""
    from aibridge.engine.context_assembler import AssembledContext
    pa = engine._llm_generator.prompt_assembler
    ctx = AssembledContext(session_id="pytest", session_summary="", history_messages=[])
    msgs = pa.assemble(role_config, ctx, rag_result)
    assert msgs and msgs[0]["role"] == "system"
    return msgs[0]["content"]


# ======================================================================
# P1 热更新：save_persona 后下一条消息的 prompt 包含新人设名
# ======================================================================
class TestP1HotUpdateName:
    def test_persona_name_hot_in_system_prompt(self, real_engine):
        """save_persona → 立刻 process_message → Prompt 里必须出现新名字（不用重启）"""
        real_engine.save_persona({
            "name": "老王CPS分身",
            "type": "CPS 运营顾问",
            "description": "专注 CPS 分销 5 年"
        })
        role_cfg = capture_role_config(real_engine, "你好")
        system_text = assemble_system_prompt(real_engine, role_cfg)
        assert "老王CPS分身" in system_text, (
            f"新人设名未进入 Prompt。system_text=\n{system_text[:200]}"
        )


# ======================================================================
# P2 description 关键字必须出现在 Prompt
# ======================================================================
class TestP2DescriptionInPrompt:
    def test_description_keywords_in_system(self, real_engine):
        desc = "擅长抖音带货、快手短剧 CPS 投放，熟悉千川投流与 ROI 优化"
        real_engine.save_persona({"name": "P2", "description": desc})
        role_cfg = capture_role_config(real_engine)
        s = assemble_system_prompt(real_engine, role_cfg)
        assert "抖音带货" in s and "ROI" in s, f"description 未注入：{s[:200]}"


# ======================================================================
# P3 tone 不是硬编码默认值，而是从 config 读取的真实值
# ======================================================================
class TestP3ToneFromConfig:
    def test_custom_tone_in_role_config_and_prompt(self, real_engine):
        real_engine.save_persona({"name": "P3", "tone": "口语化、像老大哥聊天、带点东北味儿"})
        role_cfg = capture_role_config(real_engine)

        # 先断言 role_config.tone 本身不是硬编码
        assert role_cfg.get("tone") != "专业、友好、简洁", (
            f"role_config.tone 仍是默认硬编码，未从 config 读取"
        )

        s = assemble_system_prompt(real_engine, role_cfg)
        # 【语气风格】段落应该出现任意一个 tone 的关键词
        tone_words = ["东北味儿", "老大哥", "口语化"]
        assert any(w in s for w in tone_words), f"自定义 tone 没进 Prompt：{s[:200]}"


# ======================================================================
# P4 type 拼接进 identity（首句"你是一个{type}，名叫「{name}」"）
# ======================================================================
class TestP4TypeInIdentity:
    def test_type_appears_in_role_config_identity(self, real_engine):
        real_engine.save_persona({"name": "P4", "type": "情感咨询师"})
        role_cfg = capture_role_config(real_engine)
        identity = role_cfg.get("identity", "")
        assert "情感咨询师" in identity, f"type 未拼接进 identity：{identity[:200]}"
        # 首句模式匹配
        first_line = identity.splitlines()[0] if identity else ""
        assert first_line.startswith("你是一个") and "P4" in first_line


# ======================================================================
# P5 role_config 对齐 PromptAssembler 契约（identity/tone/rules 三大必需字段）
# ======================================================================
class TestP5RoleConfigContract:
    def test_required_keys_present_and_identity_nonempty(self, real_engine):
        role_cfg = capture_role_config(real_engine)
        # PromptAssembler._build_system_prompt 明确读这 3 个字段
        for k in ("identity", "tone", "rules"):
            assert k in role_cfg, f"role_config 缺少 PromptAssembler 必需字段: {k}"
        assert isinstance(role_cfg["identity"], str) and len(role_cfg["identity"]) > 0, (
            f"identity 为空或非 str: {repr(role_cfg['identity'])}"
        )
        assert "你是一个" in role_cfg["identity"], (
            f"identity 首句身份陈述缺失：{role_cfg['identity']}"
        )


# ======================================================================
# P6 未调用 save_persona 时的默认人设
# ======================================================================
class TestP6DefaultPersona:
    def test_defaults_name_type_tone(self, real_engine):
        # 注意：刻意**不**调 save_persona
        # P1-3 首启注入后默认人设为 EXAMPLE_PERSONA（鲜果小助手）
        role_cfg = capture_role_config(real_engine)
        identity = role_cfg.get("identity", "")
        assert "鲜果小助手" in identity, f"默认 name 不是 '鲜果小助手'：{identity[:100]}"
        assert "水果商家数字分身" in identity, f"默认 type 未进 identity：{identity[:100]}"
        assert role_cfg.get("tone") == "热情、专业、耐心，像邻居家的水果达人", (
            f"默认 tone 错误：'{role_cfg.get('tone')}'"
        )


# ======================================================================
# P7 空字段 / None 字段不产生空段落、不出现 None 字面量
# ======================================================================
class TestP7NoEmptyOrNoneParagraphs:
    def test_no_none_literal_and_no_three_newlines(self, real_engine):
        real_engine.save_persona({
            "name": "EmptyTest",
            "tone": "冷静",
            "description": "",  # 显式空字符串
            "type": ""
        })
        role_cfg = capture_role_config(real_engine)
        s = assemble_system_prompt(real_engine, role_cfg)
        # None 字面量不允许
        assert "None" not in s, f"Prompt 出现 'None' 字面量：{s}"
        # 3 段以上连续空行 → 段落结构异常
        assert "\n\n\n" not in s, f"Prompt 出现 3+ 连续空行：{s[:200]}"


# ======================================================================
# P8 save_persona 增量语义（只改 name → description/tone/type 保留）
# ======================================================================
class TestP8IncrementalSave:
    def test_rename_preserves_other_fields(self, real_engine):
        # Step 1: 完整人设
        real_engine.save_persona({
            "name": "原名",
            "description": "这是一条很重要的描述不能丢",
            "tone": "原语气",
            "type": "原类型"
        })
        # Step 2: 只传 name，其他字段故意不传
        ok = real_engine.save_persona({"name": "新名字"})
        assert ok is True

        role_cfg = capture_role_config(real_engine)
        identity = role_cfg.get("identity", "")
        # 新名字生效
        assert "新名字" in identity, f"新名字未生效：{identity[:100]}"
        # description 保留
        assert "这是一条很重要的描述不能丢" in identity, (
            "第二次 save_persona (仅改名) 后，原 description 被清空（应为增量语义）"
        )
        # tone 保留
        assert role_cfg.get("tone") == "原语气", (
            f"第二次 save_persona (仅改名) 后，tone 被重置：'{role_cfg.get('tone')}'"
        )


# ======================================================================
# P9 关键词命中（唯一随机字符串 → 保证是最新写的，不是历史残留）
# ======================================================================
class TestP9KeywordSearchHit:
    def test_unique_random_string_in_prompt(self, real_engine):
        import random
        unique_kw = f"猕猴桃柠檬气泡水_{os.getpid()}_{random.randint(10000, 99999)}"
        real_engine.save_persona({"name": "KWTest", "description": f"我喜欢喝 {unique_kw}"})
        role_cfg = capture_role_config(real_engine)
        s = assemble_system_prompt(real_engine, role_cfg)
        assert unique_kw in s, f"唯一关键词 '{unique_kw}' 未在 Prompt 出现（注入失败或读了旧值）"


# ======================================================================
# P10 无原 process_message 中的硬编码残留（'通用客服' / '智能客服代理系统'）
# ======================================================================
class TestP10NoHardcodeRemnants:
    def test_old_hardcode_strings_absent(self, real_engine):
        real_engine.save_persona({
            "name": "NoHardcode",
            "type": "职场导师",
            "description": "只讲职场"
        })
        role_cfg = capture_role_config(real_engine)
        identity = role_cfg.get("identity", "")
        assert "通用客服" not in identity, f"仍有原硬编码 type：{identity[:200]}"
        assert "智能客服代理系统" not in identity, f"仍有原硬编码 description：{identity[:200]}"


# ======================================================================
# P12 附加字段 background_story 进 identity（【背景】前缀）
# ======================================================================
class TestP12BackgroundStoryExtraField:
    def test_background_story_with_prefix(self, real_engine):
        bg = "我在互联网大厂做了 8 年产品经理，后来辞职做独立顾问"
        real_engine.save_persona({"name": "BGTest", "background_story": bg})
        role_cfg = capture_role_config(real_engine)
        identity = role_cfg.get("identity", "")
        assert "【背景】" in identity, f"background_story 缺少【背景】前缀：{identity[:200]}"
        assert "互联网大厂" in identity and "独立顾问" in identity, (
            f"background_story 内容未进入 identity：{identity[:300]}"
        )


# ======================================================================
# P13 连续多次 save → 最终值 = 最后一次，且无旧 name 残留
# ======================================================================
class TestP13MultipleSaveFinal:
    def test_final_values_no_residual_old_name(self, real_engine):
        real_engine.save_persona({"name": "第1版"})
        real_engine.save_persona({"tone": "热情、像朋友聊天"})
        real_engine.save_persona({"name": "最终版名字", "description": "最终版描述_DONE"})

        role_cfg = capture_role_config(real_engine)
        identity = role_cfg.get("identity", "")

        # 最终值全对
        assert "最终版名字" in identity
        assert "最终版描述_DONE" in identity
        assert role_cfg.get("tone") == "热情、像朋友聊天", (
            f"最终 tone 错误：'{role_cfg.get('tone')}'"
        )
        # 旧 name 必须消失（最后一次 save 的 name 覆盖了第 1 次的）
        assert "第1版" not in identity, (
            f"旧 name '第1版' 残留在 identity：{identity[:200]}"
        )


# ======================================================================
# P14 fallback（无 API Key）场景下，process_message 返回的 persona_name 仍正确
# ======================================================================
class TestP14FallbackStillCorrectPersona:
    def test_fallback_persona_name_and_role_config_tone(self, real_engine):
        real_engine.save_persona({"name": "FallbackUser", "tone": "淡定"})
        # 真实走 process_message（无 API Key → except 分支 → 返回 fallback 结果）
        result = real_engine.process_message("你好")
        # 返回结果 persona_name 字段必须等于保存过的
        assert result.get("persona_name") == "FallbackUser", (
            f"fallback 时 persona_name 不对，期望 'FallbackUser'，实际 "
            f"'{result.get('persona_name')}'"
        )
        # 内部 role_config.tone 也是保存过的"淡定"
        role_cfg = capture_role_config(real_engine, "x")
        assert role_cfg.get("tone") == "淡定"


# ======================================================================
# P15 全链路：save → process_message → role_config → PromptAssembler.assemble → messages[0] 含全关键字
# ======================================================================
class TestP15FullChain:
    def test_end_to_end_all_keywords_present(self, real_engine):
        full_name = "全链测试用户_P15"
        full_desc = "P15 专属描述，包含关键字 XYZZY"
        full_tone = "口语化，不打官腔"
        full_type = "私人教练"
        real_engine.save_persona({
            "name": full_name,
            "description": full_desc,
            "tone": full_tone,
            "type": full_type,
            "background_story": "P15 背景故事_ABC"
        })

        role_cfg = capture_role_config(real_engine, "你告诉我你是谁")
        s = assemble_system_prompt(real_engine, role_cfg, rag_result={"chunks": []})

        checks = {
            "名字": full_name in s,
            "description_XYZZY": "XYZZY" in s,
            "type_开头句": full_type in s,
            "tone_口语化关键词": ("不打官腔" in s or "口语化" in s),
            "背景故事_ABC": "ABC" in s,
        }
        missing = [k for k, ok in checks.items() if not ok]
        assert not missing, (
            f"全链路断言缺失 {missing}。最终 system prompt=\n{s[:400]}"
        )
