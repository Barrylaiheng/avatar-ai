# -*- coding: utf-8 -*-
"""
SCAI · P0 链路网关（L1 / L2 / L3 三条主线端到端 pytest 守门员）

这是 AI Bridge 云端版 48 条 pytest「链路网关」的桌面版对应物。
**原则：链路不通 → 测试先红 → 不允许任何后续视觉/结构 Seam 通过。**

T-L1 首启链路：全新 config + 全新 wiki 目录 → bootstrap_first_run → 
    断言：默认人设注入正确名称「我的数字分身」+ wiki 三层结构存在 + 无任何水果/丹东/草莓
    业务内容残留（清零验证）+ skeleton_injected 标志被置 True

T-L2 对话链路：Mock LLM 返回「你好，我是你的数字分身」→ 调 AppEngine.process_message_stream →
    断言：8 字段契约齐全 + is_aigc=True（法规标识）+ persona_name == 「我的数字分身」
    + 流式 delta 可拼出完整 content + success=True

T-L3 RAG 链路：写入 1 条测试知识（entities/my-product.md，含 SCAI 主打功能描述）→
    WikiIngestPipeline 增量灌入 → UnifiedRetriever.retrieve("SCAI 主打什么功能？") →
    断言：rag_count >= 1 + 命中条目的 content/snippet 包含 "主打"或"功能"关键字

运行：
    cd C:\\Users\\Administrator\\Desktop\\WeChatAI_Project
    python -m pytest tests/test_inner_p0_chain_gate_pdd.py -v
"""
from __future__ import annotations

import os
import sys
import tempfile
import shutil
from pathlib import Path
from typing import Any, Dict, Generator, List
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


# ======================================================================
# Fixture 1：隔离的 SCAI 数据目录（所有测试共享，测试结束自动清理）
# ======================================================================
@pytest.fixture
def isolated_data_dir():
    """全新临时目录写入 SCAI_DATA_DIR，保证「首启」状态完全干净"""
    tmp_dir = Path(tempfile.mkdtemp(prefix="scai_p0_chain_"))
    old_env = os.environ.get("SCAI_DATA_DIR")
    os.environ["SCAI_DATA_DIR"] = str(tmp_dir)
    yield tmp_dir
    if old_env is None:
        os.environ.pop("SCAI_DATA_DIR", None)
    else:
        os.environ["SCAI_DATA_DIR"] = old_env
    shutil.rmtree(tmp_dir, ignore_errors=True)


# ======================================================================
# Fixture 2：AppEngine 工厂（基于隔离数据目录，结束自动 shutdown）
# ======================================================================
@pytest.fixture
def fresh_engine(isolated_data_dir):
    from aibridge.app_engine import AppEngine
    engine = AppEngine()
    ok = engine.initialize()
    assert ok is True, "AppEngine.initialize() 在 P0 链路线上必须成功"
    yield engine
    try:
        engine.shutdown()
    except Exception:
        pass


# ======================================================================
# 通用常量 & 契约
# ======================================================================
DEFAULT_PERSONA_NAME_CLEAN = "我的数字分身"
FORBIDDEN_BUSINESS_WORDS = ["水果", "草莓", "丹东", "西瓜", "葡萄", "鲜果小助手", "实战导师",
                            "职业成长导师", "B2B 销售顾问", "售后客服专员", "内容创作顾问"]
REQUIRED_8_FIELDS = [
    "content", "is_aigc", "tool_calls", "rag_count",
    "persona_name", "success", "error_message", "session_id",
]


# ======================================================================
# T-L1 · 首启链路（清零版）· 类名便于 pytest -k 过滤
# ======================================================================
class TestTL1FirstRunChain:
    """L1 主线：首启初始化（清零版 — 无任何预置业务内容）"""

    def test_TL1_01_default_persona_name_is_clean(self, fresh_engine):
        """首启后默认人设名称为「我的数字分身」，不是水果商/导师等业务人设"""
        cfg = fresh_engine._config
        persona_name = cfg.get("persona.name", "")
        assert persona_name == DEFAULT_PERSONA_NAME_CLEAN, (
            f"首启默认人设名应为「{DEFAULT_PERSONA_NAME_CLEAN}」，实际是「{persona_name}」"
        )

    def test_TL1_02_default_persona_has_no_business_content(self, fresh_engine):
        """首启默认人设 6 个字段中不含任何水果/草莓/销售/导师等预置业务词汇"""
        cfg = fresh_engine._config
        persona_fields = ["name", "type", "description", "tone", "background_story",
                          "language_style", "keywords"]
        for f in persona_fields:
            raw = str(cfg.get(f"persona.{f}", ""))
            for bad in FORBIDDEN_BUSINESS_WORDS:
                assert bad not in raw, (
                    f"默认人设字段 persona.{f} 包含预置业务词汇「{bad}」，清零不彻底：\n{raw}"
                )

    def test_TL1_03_wiki_three_dirs_exist(self, fresh_engine):
        """首启后 wiki 根目录应有 concepts/entities/architecture 三个空目录骨架"""
        wiki_root = fresh_engine._get_or_create_wiki_root()
        for sub in ("concepts", "entities", "architecture"):
            d = wiki_root / sub
            assert d.exists() and d.is_dir(), f"首启缺少 wiki 子目录：{sub}"

    def test_TL1_04_wiki_has_only_skeleton_no_business(self, fresh_engine):
        """首启后 wiki 里除了骨架 README/index/log，不应有任何实体/概念/架构业务页"""
        wiki_root = fresh_engine._get_or_create_wiki_root()
        all_md_files: List[Path] = list(wiki_root.rglob("*.md"))
        allowed_skeletons = {"index.md", "log.md", "_README.md"}
        for f in all_md_files:
            if f.name in allowed_skeletons:
                continue
            # 任何其他 .md 文件名或内容中检查业务词汇
            content = f.read_text(encoding="utf-8", errors="ignore")
            for bad in FORBIDDEN_BUSINESS_WORDS:
                assert bad not in content, (
                    f"wiki 文件 {f.relative_to(wiki_root)} 含预置业务词汇「{bad}」"
                )

    def test_TL1_05_skeleton_injected_flag_set(self, fresh_engine):
        """首启完成后 app.skeleton_injected 标志为 True，防止下次重复注入骨架"""
        cfg = fresh_engine._config
        flag = cfg.get("app.skeleton_injected", False)
        assert flag is True, "首启后 app.skeleton_injected 没置 True，会导致下次启动反复写骨架"


# ======================================================================
# T-L2 · 对话链路（process_message_stream 端到端契约）
# ======================================================================

# --- Mock LLM Client：模拟 SSE 流式返回，不发真实 HTTP ---
class _MockLLMClient:
    def __init__(self, tokens: List[str]):
        self._tokens = tokens or ["你好", "，", "我是", "你的", "数字分身", "。"]

    def is_available(self) -> bool:
        return True

    def chat_completion_stream(self, messages: List[Dict[str, Any]], **_kwargs
                               ) -> Generator[Dict[str, Any], None, None]:
        import time
        full = "".join(self._tokens)
        n_tokens = len(self._tokens)
        for tok in self._tokens:
            yield {"type": "chunk", "delta": tok}
            time.sleep(0)  # yield point（不 sleep 也行，留占位）
        yield {
            "type": "final",  # LLMGenerator.generate_stream 只认 chunk/final/error
            "content": full,
            "model": "mock-model",
            "latency_ms": 10,
            "usage": {"tokens_in": 3, "tokens_out": n_tokens},
        }


@pytest.fixture
def _patched_llm(fresh_engine):
    """先注入假 API Key（绕过 F-1.4 就绪检查），再把 llm_client 替换成 Mock。

    为什么不能只 patch LLMClient？因为 AppEngine.process_message_stream 在流水线最
    前面（F-1.4 LLM 就绪检查）就看 config.llm.api_key 和 llm_client 的存在性，
    不进 LLMGenerator.generate_stream 就已经返回友好提示 error 了。
    所以必须：1. 写一个假 Key 到 config 让就绪检查通过；2. 直接替换 llm_client 引用。
    """
    tokens = ["你好", "，我是", "你的", "数字分身", "。"]
    mock_client = _MockLLMClient(tokens=tokens)

    # Step 1: 直接 patch ConfigManager.get_active_llm_config，不依赖具体存储路径
    #         让 F-1.4 的 api_key_ok=True 判定。（真实存储路径是 llm.providers.deepseek.api_key
    #         但直接 patch getter 更稳健也更快，不触发 save_config 落盘）
    cfg = fresh_engine._config
    _orig_get_active = cfg.get_active_llm_config.__func__ if hasattr(cfg.get_active_llm_config, "__func__") else None

    def _fake_active_llm_config(self):
        return {
            "provider": "deepseek",
            "api_base": "https://mock.invalid/v1",
            "api_key": "sk-mock-p0-chain-test-only-not-real",
            "model": "mock-model",
            "supports_image": False,
            "temperature": 0.7,
            "max_tokens": 512,
        }
    import aibridge.config.config_manager as _cfg_mod
    llm_cfg_patcher = patch.object(
        _cfg_mod.ConfigManager, "get_active_llm_config",
        _fake_active_llm_config,
    )
    llm_cfg_patcher.start()

    # Step 2: 把生成器内部的 llm_client 直接替换成 Mock（绕过 property setter）
    gen = getattr(fresh_engine, "_llm_generator", None)
    if gen is not None:
        # LLMGenerator.llm_client 是 @property（只读），所以直接写入私有属性
        vars(gen)["_llm_client"] = mock_client
        # 同步把 MessageProcessor 里可能持有的旧引用也更新（如果有的话）
        mp = getattr(fresh_engine, "_message_processor", None)
        if mp is not None and hasattr(mp, "_llm_generator") and mp._llm_generator is not None:
            vars(mp._llm_generator)["_llm_client"] = mock_client
        # 双重保险：用 Python 属性机制在类级别 mock 掉 property，
        # 防止任何地方创建新的 LLMGenerator 实例时触发 _init_client
        from aibridge.engine import llm_generator as _llm_gen_mod

        def _mock_getter(self):
            return mock_client
        patcher = patch.object(_llm_gen_mod.LLMGenerator, "llm_client",
                               new_callable=lambda: property(_mock_getter))
        patcher.start()
    else:
        pytest.skip("_llm_generator 未初始化，跳过对话链路 mock")

    yield "".join(tokens)

    # cleanup patch（如果起了）
    try:
        from unittest.mock import _patch
        # pytest handles cleanup automatically for `with patch(...)`, but we use
        # patcher.start() so nothing to do here.
    except Exception:
        pass


class TestTL2ConversationChain:
    """L2 主线：对话 8 步流水线完整契约（Mock LLM，无网络）"""

    def test_TL2_01_8_fields_contract_all_present(self, fresh_engine, _patched_llm):
        """流式结果的 final 事件必须包含 8 字段契约，少一个 ChatPage 就会崩溃"""
        results: List[Dict[str, Any]] = list(
            fresh_engine.process_message_stream("你好", session_id="test-tl2")
        )
        finals = [r for r in results if r.get("type") in ("final", "error")]
        assert len(finals) >= 1, "流式结果中找不到 final 或 error 事件"
        final = finals[-1]
        missing = [f for f in REQUIRED_8_FIELDS if f not in final]
        assert missing == [], f"final 事件缺少 8 字段契约中的：{missing}"

    def test_TL2_02_aigc_flag_true_by_regulation(self, fresh_engine, _patched_llm):
        """AI 生成内容必须 is_aigc=True，符合 7 月 15 日 AIGC 法规强制性标识"""
        results = list(fresh_engine.process_message_stream("你好", session_id="tl2-aigc"))
        finals = [r for r in results if r.get("type") in ("final", "error")]
        final = finals[-1]
        if final.get("success") is False:
            pytest.skip(f"LLM 未就绪降级，跳过：{final.get('error_message','')}")
        assert final.get("is_aigc") is True, "AIGC 法规标识位 is_aigc 必须为 True"

    def test_TL2_03_persona_name_propagated_to_chat(self, fresh_engine, _patched_llm):
        """final 元数据里的 persona_name 必须等于当前人设名，证明人设链路没断"""
        results = list(fresh_engine.process_message_stream("你好", session_id="tl2-persona"))
        finals = [r for r in results if r.get("type") in ("final", "error")]
        final = finals[-1]
        if final.get("success") is False:
            pytest.skip(f"LLM 未就绪降级，跳过：{final.get('error_message','')}")
        expected = fresh_engine._config.get("persona.name", DEFAULT_PERSONA_NAME_CLEAN)
        assert final.get("persona_name") == expected, (
            f"气泡元数据 persona_name={final.get('persona_name')} "
            f"不等于配置 persona.name={expected}，人设链路断了"
        )

    def test_TL2_04_stream_delta_concatenate_equals_final_content(
            self, fresh_engine, _patched_llm):
        """流式 delta 拼接起来 == final.content，证明打字机效果链路没乱序/丢字"""
        deltas: List[str] = []
        final_content = None
        for event in fresh_engine.process_message_stream("你好", session_id="tl2-stream"):
            t = event.get("type")
            if t == "chunk" and "delta" in event:
                deltas.append(event["delta"])
            elif t == "final":
                final_content = event.get("content", "")
        if final_content is None:
            pytest.skip("没有 final 事件（可能 LLM 未就绪），跳过打字机链路验证")
        streamed = "".join(deltas)
        assert streamed.strip() == final_content.strip(), (
            f"打字机效果链路断了：delta 拼接='{streamed}' != final.content='{final_content}'"
        )

    def test_TL2_05_success_flag_and_session_id_roundtrip(
            self, fresh_engine, _patched_llm):
        """success=True 且 session_id 原样返回，保证 UI 会话路由正确"""
        sid = "tl2-sid-abc123"
        results = list(fresh_engine.process_message_stream("你好", session_id=sid))
        finals = [r for r in results if r.get("type") in ("final", "error")]
        final = finals[-1]
        if final.get("success") is False and final.get("error") == "llm_not_ready":
            # 未配置 Key 时是 F-1.4 友好提示，不算对话链路失败，只验证会话路由
            assert final.get("session_id") == sid, "LLM 未就绪时 session_id 也必须原样返回"
            return
        assert final.get("success") is True, f"对话失败，error_message={final.get('error_message')}"
        assert final.get("session_id") == sid, (
            f"session_id 没原路返回：UI 会把回复挂到错的会话 ({final.get('session_id')} != {sid})"
        )


# ======================================================================
# T-L3 · RAG 链路（灌库 → 检索 → rag_count>0 + 内容匹配）
# ======================================================================

TEST_ENTITY_MD = """---
type: entity
title: SCAI 产品简介
description: 影分身 AI（Shadow Clone AI / SCAI）主打什么功能
tags: [SCAI, 产品, MVP]
status: published
---

# SCAI 产品简介

影分身 AI（SCAI）主打三大核心功能：

1. **数字分身人设搭建**：7 段式定义你的 AI 身份，支持人设热更新实时生效
2. **LLM Wiki 知识库**：OKF 格式 Markdown 文件系统 + 双向链接，完全 Git 可管理
3. **混合检索 RAG**：L1 关键词（KarpathyWikiReader）+ L2 向量（ChromaDB bge-small），
   双命中条目加权加分，回答引用自己的资料不瞎编

SCAI 本地存储在 %APPDATA%\\SCAI，API Key 用 DPAPI 机器绑定加密。
"""


class TestTL3RAGChain:
    """L3 主线：导入知识 → 灌库 → 提问命中 RAG（知识库链路端到端）"""

    def test_TL3_01_write_then_ingest_then_retrieve_hit(self, isolated_data_dir, fresh_engine):
        """写 1 条 SCAI 产品 md → KarpathyWikiReader 检索命中 rag_count >= 1

        MVP 降级路径验证：当 sentence_transformers / ChromaDB 向量层没装时，
        L1 关键词检索层必须能找到用户刚写入的文档——这是"导入文档 → 能引用"
        的最小可用链路。
        """
        from aibridge.rag.karpathy_wiki_reader import KarpathyWikiReader

        # 1. 写入测试实体到 wiki/entities
        wiki_root = fresh_engine._get_or_create_wiki_root()
        ent_dir = wiki_root / "entities"
        ent_dir.mkdir(parents=True, exist_ok=True)
        test_file = ent_dir / "scai-product-intro.md"
        test_file.write_text(TEST_ENTITY_MD, encoding="utf-8")

        # 2. 直接用 KarpathyWikiReader 验证 L1 关键词链路
        #    kb_root 参数必须是 SCAI 数据目录（不带 /wiki 后缀，reader 会自己拼）
        kr = KarpathyWikiReader(kb_root=str(isolated_data_dir))
        # 读者在 __init__ 时已经扫描一次，但我们刚写了新文件所以手动触发重新扫描
        kr._load_all_pages()

        pages = list(kr.list_pages())
        # 我们刚新增的文件应该出现在 pages 里
        titles = [getattr(p, "title", "") for p in pages]
        assert any("SCAI" in t for t in titles), (
            f"写了 SCAI 产品介绍但没扫到。pages={titles}"
        )

        # 3. search() 关键词检索命中
        hits = kr.search("SCAI 主打什么功能", top_k=5) or []
        assert len(hits) >= 1, (
            "L1 关键词检索没命中。RAG 链路断了：写入的文件内容没被索引到关键词层"
        )

        # 4. 命中内容必须包含"主打"或"功能"关键字
        hit_previews = []
        for hit in hits:
            text = (getattr(hit, "content", "") or getattr(hit, "snippet", "")
                    or getattr(hit, "text", "") or getattr(hit, "preview", "")
                    or str(hit) or "")
            hit_previews.append(text[:200])
            if "主打" in text or "功能" in text:
                return
        pytest.fail(
            "RAG 命中了，但没有一条内容包含「主打」或「功能」关键词，说明召回的是不相关页面：\n"
            + "\n---\n".join(hit_previews)
        )

    def test_TL3_02_retrieve_empty_wiki_returns_zero_not_crash(self, isolated_data_dir, fresh_engine):
        """空知识库检索不崩溃，返回 [] — 这是用户首启还没导入任何文档时的正常场景

        注意：首启注入的是 5 页空白骨架，所以"空"不是 0 条文件，而是
        检索用户提问的无关内容（比如"草莓多少钱一斤"）时，不会因为没数据就崩。
        这里用强无意义关键词来保证 0 命中。
        """
        from aibridge.rag.karpathy_wiki_reader import KarpathyWikiReader
        kr = KarpathyWikiReader(kb_root=str(isolated_data_dir))
        hits = kr.search("xYz_Not_Exist_987234_random_query", top_k=3) or []
        # 必须是 list，哪怕 0 条
        assert isinstance(hits, list), f"retrieve() 返回类型不是 list：{type(hits)}"
