"""
P2-1 pytest · 人设+RAG 联合生效端到端验证（8 Grill · 8 test 用例）
============================================================

运行（MVP 全部模块完成后统一跑）：
    python -m pytest tests/test_inner_persona_rag_combined_pdd.py -v --tb=short

与 prototype 对齐：
    _prototypes/persona_rag_combined_prototype.py（21/21 PASS，已完成 throwaway 验证，
    本文件是同结构的 pytest 形式，拆分 8 个 test function / 1 个 module fixture）。

为了避免每个用例都初始化一次 AppEngine（≈ 每次首启注入 5 条 wiki + migrate DB v0→5
+ 尝试连接 ChromaDB embedding = 1~5s），使用 module-scoped fixture 共享 1 个引擎实例，
并在每个 test 之间用 fresh session_id 隔离。

注意：环境变量必须在任何 import aibridge 之前设置，所以本文件在 import aibridge 前
就设置 TRANSFORMERS_OFFLINE / HF_HUB_OFFLINE / SCAI_DATA_DIR。
"""
# -------------------- 前置环境变量（import 前必须设置） --------------------
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

_SAVED_SCAI_DATA_DIR = os.environ.get("SCAI_DATA_DIR")
_TMP = Path(tempfile.mkdtemp(prefix="scai_p21_pytest_"))
os.environ["SCAI_DATA_DIR"] = str(_TMP)

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest


# -------------------- Module-scoped fixtures --------------------

@pytest.fixture(scope="module")
def sample_doc_path():
    """临时 txt 文档，模拟用户上传的"阿克苏冰糖心苹果介绍.txt" """
    content = """# 阿克苏冰糖心苹果

产地：新疆阿克苏地区
特点：果心透明如冰糖（糖心现象），含糖量约18%
口感：脆甜多汁，果肉细腻无渣
最佳食用期：10月底~次年2月
储存建议：冷藏可放30天，常温建议15天内食用

识别方法：
1. 外形呈卵圆形，表皮有自然果蜡
2. 切开后果心部分半透明状即为糖心
3. 闻起来有自然果香，无刺激性异味
"""
    p = _TMP / "aksu_apple_source.txt"
    p.write_text(content, encoding="utf-8")
    yield str(p)


@pytest.fixture(scope="module")
def persona_input():
    """示例人设：鲜果小助手"""
    return {
        "name": "鲜果小助手",
        "description": "专注推荐新鲜水果，尤其擅长阿克苏苹果、阳光玫瑰葡萄、丹东草莓等高口碑产地的水果知识，会根据季节给出最适合的选购建议。",
        "tone": "热情亲切，像菜市场资深摊主一样，有啥说啥不绕弯子，回答里偶尔可以加一句俏皮话。",
        "type": "鲜果顾问",
    }


@pytest.fixture(scope="module")
def engine():
    """模块级共享引擎：initialize 一次，所有测试复用

    注意：我们不做 engine 的 teardown 让它的 background thread 停，
    因为 pytest 进程跑完会自动释放；ScheduleManager 本身是 daemon thread。
    """
    from aibridge.app_engine import AppEngine
    e = AppEngine()
    ok = e.initialize()
    assert ok is True, "AppEngine.initialize() failed (should be True even if degraded)"
    yield e


@pytest.fixture(scope="module")
def wiki_root_dir():
    return _TMP / "wiki"


# ============================== G1 ==============================
class TestG1SavePersona:
    """P21-G1 · save_persona → get_current_persona_dict 一致（3 核心字段 + 返回 True）"""

    def test_G1_save_persona_roundtrip(self, engine, persona_input):
        saved = engine.save_persona(persona_input)
        assert saved is True, "save_persona must return True after persist"
        got = engine.get_current_persona_dict()
        # 4 个核心字段
        assert got.get("name") == persona_input["name"], (
            f"persona.name 不一致 expect={persona_input['name']!r} got={got.get('name')!r}"
        )
        assert got.get("description") == persona_input["description"], (
            "persona.description 不一致"
        )
        assert got.get("tone") == persona_input["tone"], "persona.tone 不一致"


# ============================== G2 ==============================
class TestG2WikiImporter:
    """P21-G2 · DocumentToWikiImporter 生成 OKF MD 落盘（4 子断言合并为 1 test）"""

    def test_G2_wiki_importer_generates_okf_md(self, sample_doc_path, wiki_root_dir, engine):
        from aibridge.rag.doc_to_wiki_importer import DocumentToWikiImporter
        importer = DocumentToWikiImporter(wiki_root=str(wiki_root_dir))
        result = importer.import_document(
            sample_doc_path, category="entities", title="阿克苏冰糖心苹果"
        )
        assert result.success is True, (
            f"DocumentToWikiImporter.import_document 失败: {result.error}"
        )
        page_path = Path(result.wiki_page_path)
        assert page_path.exists(), f"wiki_page 文件不存在: {page_path}"
        md_text = page_path.read_text(encoding="utf-8")
        # OKF v0.1 前 300 字符含 --- + type: + title:
        head = md_text[:300]
        assert head.startswith("---"), "OKF MD 必须以 --- 开头（frontmatter）"
        assert "type:" in head and "title:" in head, (
            f"OKF MD 缺少 type/title 字段，前 300 字符: {head!r}"
        )
        # 正文中有原文关键词
        assert any(k in md_text for k in ["阿克苏", "冰糖心", "果心透明"]), (
            "wiki 正文未命中原文关键词（阿克苏/冰糖心/果心透明）"
        )


# ============================== G3 ==============================
class TestG3IngestIncremental:
    """P21-G3 · WikiIngestPipeline 灌入成功"""

    def test_G3_reader_and_pipeline_ok(self, wiki_root_dir, engine):
        from aibridge.rag.karpathy_wiki_reader import KarpathyWikiReader
        from aibridge.rag.wiki_ingest_pipeline import WikiIngestPipeline

        # 关键：KarpathyWikiReader 的参数是 kb_root（它内部会拼 /wiki 子目录），
        # 不是 wiki_root_dir（/wiki 目录本身）。见 KarpathyWikiReader._load_all_pages
        kb_root = _TMP
        reader = KarpathyWikiReader(str(kb_root))
        pages = reader.list_pages()
        assert len(pages) >= 1, (
            f"KarpathyWikiReader(kb_root={kb_root}) 解析 pages={len(pages)}，预期 ≥ 1"
        )
        # 尝试拿 engine 内部的 chromadb_manager，None 也 OK（允许 degraded）
        chroma_mgr = None
        try:
            kb_mgr = getattr(engine, "_kb_manager", None)
            if kb_mgr:
                chroma_mgr = getattr(kb_mgr, "_chromadb", None)
        except Exception:
            chroma_mgr = None
        pipeline = WikiIngestPipeline(reader, chroma_mgr)
        count = pipeline.ingest_incremental()
        assert isinstance(count, int) and count >= 0, (
            f"ingest_incremental 返回非 int 或 < 0: {count!r} type={type(count).__name__}"
        )


# ============================== G4/G5（共享一次 mock 调用） ==============================
class _CaptureLLMGenerate:
    """Context manager：捕获 engine._llm_generator.generate 的实参，同时返回 mock 响应

    与 prototype 保持一致的 mock 逻辑，不真实发 LLM 请求。
    """

    def __init__(self, engine):
        self.engine = engine
        self.captured = {}
        self._orig = engine._llm_generator.generate

    def __enter__(self):
        def _fake(**kwargs):
            self.captured.update(kwargs)
            return {
                "content": "Mock 响应，您好我是鲜果小助手，推荐吃阿克苏苹果哦~",
                "is_aigc": True,
                "message_record": {},
                "llm_response": {"model": "mock-p21", "tokens_in": 0, "tokens_out": 0},
                "intent": "qa",
                "rag_hits_count": len(kwargs.get("rag_result", {}).get("chunks", [])),
            }

        self.engine._llm_generator.generate = _fake
        return self

    def __exit__(self, exc_type, exc, tb):
        self.engine._llm_generator.generate = self._orig


class TestG4RoleConfigIdentity:
    """P21-G4 · role_config.identity 含人设 name + description"""

    def test_G4_identity_contains_persona_name_and_desc(self, engine, persona_input):
        with _CaptureLLMGenerate(engine) as cap:
            engine.process_message(
                user_input="你好，推荐我吃什么苹果？",
                session_id="p21_g4_session",
            )
        role_cfg = cap.captured.get("role_config", {})
        identity = role_cfg.get("identity", "")
        assert persona_input["name"] in identity, (
            f"identity 未包含 persona.name={persona_input['name']!r}，"
            f"identity={identity[:120]!r}"
        )
        # description 关键词："推荐新鲜水果"或"阿克苏苹果"
        assert "推荐新鲜水果" in identity or "阿克苏苹果" in identity, (
            f"identity 未包含 persona.description 关键词，identity={identity[:120]!r}"
        )


class TestG5RagResultChunks:
    """P21-G5 · rag_result.chunks 含关键词（或 degraded 时 identity 保留人设名）"""

    def test_G5_rag_result_chunks_has_keyword_or_fallback_identity_ok(
        self, engine, persona_input
    ):
        with _CaptureLLMGenerate(engine) as cap:
            engine.process_message(
                user_input="要甜脆的苹果有什么推荐？",
                session_id="p21_g5_session",
            )
        rag_result = cap.captured.get("rag_result", {}) or {}
        chunks = rag_result.get("chunks", []) if isinstance(rag_result, dict) else []
        # 先断言 chunks 是 list（G5-1）
        assert isinstance(chunks, list), (
            f"rag_result.chunks 不是 list: {type(chunks).__name__}"
        )
        # 拼接所有 chunk 的字符串
        joined = ""
        for c in chunks:
            if isinstance(c, dict):
                joined += " " + str(c.get("content", "") or c.get("text", "") or "")
            elif hasattr(c, "content"):
                joined += " " + str(c.content)
            else:
                joined += " " + str(c)
        # G5-2：有 chunk 则必须含关键词；没有 chunk（L2 degraded）则至少人设有效
        if len(chunks) >= 1:
            assert any(k in joined for k in ["阿克苏", "冰糖心", "果心透明"]), (
                f"RAG 命中 {len(chunks)} 个 chunk，但没有一个含"
                f"阿克苏/冰糖心/果心透明。joined 前 300 字={joined[:300]!r}"
            )
        else:
            # degraded 情况下：identity 至少保留人设名（相当于对 G4 的兜底）
            role_cfg = cap.captured.get("role_config", {})
            identity = role_cfg.get("identity", "")
            assert persona_input["name"] in identity, (
                f"RAG degraded 且 identity 也丢失了人设名，role_cfg={role_cfg!r}"
            )


# ============================== G6 ==============================
class TestG6ProcessMessageDegraded:
    """P21-G6 · 真实 process_message（允许 degraded fallback）不崩 + content 非空 + is_aigc 存在"""

    def test_G6_process_message_structure(self, engine):
        resp = engine.process_message(
            user_input="今天天气怎么样？随便聊聊天。",
            session_id="p21_g6_session",
        )
        assert isinstance(resp, dict), (
            f"process_message 没有返回 dict: {type(resp).__name__}"
        )
        content = resp.get("content")
        assert isinstance(content, str) and len(content) > 0, (
            f"content 字段为空或不是 str: {content!r}"
        )
        assert "is_aigc" in resp, (
            f"is_aigc 字段缺失，返回 keys={sorted(resp.keys())}"
        )


# ============================== G7 ==============================
def _md5_file(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest() if p.exists() else ""


class TestG7Isolation:
    """P21-G7 · 人设保存和文档导入互不污染"""

    def test_G7_isolation_between_persona_and_rag(
        self, sample_doc_path, wiki_root_dir, engine, persona_input
    ):
        # 找一个已经存在的 wiki MD 文件（应该是 P1-3 首启注入或 G2 写入的）
        existing_wiki_md = None
        for candidate in wiki_root_dir.glob("**/*.md"):
            existing_wiki_md = candidate
            break
        # 如果没有，就现场 import 一次保证有文件
        if existing_wiki_md is None:
            from aibridge.rag.doc_to_wiki_importer import DocumentToWikiImporter

            importer = DocumentToWikiImporter(wiki_root=str(wiki_root_dir))
            result = importer.import_document(
                sample_doc_path, category="entities", title="阿克苏冰糖心苹果-隔离版"
            )
            assert result.success, "为了 G7 隔离断言，导入 wiki 必须先成功"
            existing_wiki_md = Path(result.wiki_page_path)

        md5_before = _md5_file(existing_wiki_md)
        persona_before = dict(engine.get_current_persona_dict())

        # 操作 1：再调用一次 save_persona（保持相同内容或完全相同 key 集合）
        engine.save_persona(persona_input)
        md5_after_save = _md5_file(existing_wiki_md)
        assert md5_after_save == md5_before, (
            f"save_persona 后 wiki MD5 发生变更：before={md5_before} after={md5_after_save}"
        )

        # 操作 2：再 import 一个同目录的小文档
        mini = _TMP / "_g7_isolation_tiny.txt"
        mini.write_text("丹东草莓：红颜品种，春天最好吃，酸甜适中带奶香味", encoding="utf-8")
        from aibridge.rag.doc_to_wiki_importer import DocumentToWikiImporter

        importer2 = DocumentToWikiImporter(wiki_root=str(wiki_root_dir))
        importer2.import_document(str(mini), category="entities", title="丹东草莓简介")

        persona_after = dict(engine.get_current_persona_dict())
        for k in ("name", "description", "tone"):
            assert persona_before.get(k) == persona_after.get(k), (
                f"import wiki 后 persona.{k} 发生变更："
                f"before={persona_before.get(k)!r} after={persona_after.get(k)!r}"
            )


# ============================== G8 ==============================
class TestG8ReturnContract:
    """P21-G8 · process_message 返回 tool_calls（list） + rag_count（int ≥ 0）"""

    def test_G8_tool_calls_and_rag_count(self, engine):
        resp = engine.process_message(
            user_input="说一下丹东草莓怎么挑选",
            session_id="p21_g8_session",
        )
        tc = resp.get("tool_calls")
        assert isinstance(tc, list), (
            f"tool_calls 字段不是 list: type={type(tc).__name__} value={tc!r}"
        )
        rc = resp.get("rag_count")
        assert isinstance(rc, int) and rc >= 0, (
            f"rag_count 字段不是 int 或 < 0: type={type(rc).__name__} value={rc!r}"
        )


# -------------------- 清理（SCAI_DATA_DIR 还原；临时目录留着，手动清） --------------------
def pytest_sessionfinish(session, exitstatus):
    """整个 pytest session 结束时：把 SCAI_DATA_DIR 恢复原状"""
    if _SAVED_SCAI_DATA_DIR is None:
        os.environ.pop("SCAI_DATA_DIR", None)
    else:
        os.environ["SCAI_DATA_DIR"] = _SAVED_SCAI_DATA_DIR
