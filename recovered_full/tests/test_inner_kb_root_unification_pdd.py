"""
P2-2 · Bug #8 修复：kb_root/wiki_root 路径统一（PDD pytest 回归用例）

对应规格文档：docs/PDD_INNER_kb_root_unification.md
原型：_prototypes/kb_root_unification_prototype.py（27/27 ALL PASS）
Grill：8 条（G1-G8）
pytest 用例数：24 条 assertions（prototype = 27 条，简化掉 prototype 中 print/调试专属检查）

执行方式：
  python -m pytest tests/test_inner_kb_root_unification_pdd.py -v
  或全量回归：python -m pytest tests/ -k "pdd" --ignore=tests/test_s4_ui.py
"""
import inspect
import os
import sys
import tempfile
from pathlib import Path

import pytest


# ===========================================================================
# Fixtures：每个 test function 独立的临时 SCAI_DATA_DIR，完全隔离
# ===========================================================================

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture(autouse=True)
def _scai_env(monkeypatch, tmp_path):
    """每个用例独立的 SCAI_DATA_DIR，避免用户真实数据污染 + 测试间互不影响。"""
    monkeypatch.setenv("SCAI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    yield tmp_path


def _make_engine():
    from aibridge.app_engine import AppEngine
    engine = AppEngine()
    ok = engine.initialize()
    assert ok is True, "AppEngine.initialize() 必须返回 True（修复代码不应破坏初始化流程）"
    return engine


# ===========================================================================
# G1 · engine 有 _get_or_create_wiki_root() -> Path，自动建子目录
# ===========================================================================

class TestG1ClassAttributesAndMethods:
    def test_G1_1_has_private_get_or_create_wiki_root_method(self):
        from aibridge.ui.ui_engine_bridge import ImportDocumentWorker  # noqa: F401  预热 ui import
        from aibridge.app_engine import AppEngine
        assert hasattr(AppEngine, "_get_or_create_wiki_root")
        assert callable(getattr(AppEngine, "_get_or_create_wiki_root", None))

    def test_G1_2_has_public_get_wiki_root_method(self):
        from aibridge.app_engine import AppEngine
        assert hasattr(AppEngine, "get_wiki_root")
        assert callable(getattr(AppEngine, "get_wiki_root", None))

    def test_G1_3_returns_Path_type_and_ends_with_wiki(self, _scai_env):
        engine = _make_engine()
        root = engine._get_or_create_wiki_root()
        assert isinstance(root, Path), f"应返回 Path，实际 {type(root).__name__}"
        assert str(root).endswith("wiki"), f"路径结尾必须带 /wiki，实际 {root}"

    def test_G1_4_auto_creates_three_subdirs(self, _scai_env):
        engine = _make_engine()
        root = engine._get_or_create_wiki_root()
        for sub in ("concepts", "entities", "architecture"):
            assert (root / sub).is_dir(), f"子目录 {sub} 必须存在"


# ===========================================================================
# G2 · get_wiki_root() 返回 str 且是绝对路径，等于 get_data_dir()/wiki
# ===========================================================================

class TestG2PublicGetWikiRoot:
    def test_G2_1_returns_str(self, _scai_env):
        engine = _make_engine()
        wr = engine.get_wiki_root()
        assert isinstance(wr, str), f"应返回 str，实际 {type(wr).__name__}"

    def test_G2_2_is_absolute_path(self, _scai_env):
        engine = _make_engine()
        assert os.path.isabs(engine.get_wiki_root()), "必须是绝对路径"

    def test_G2_3_ends_with_wiki(self, _scai_env):
        engine = _make_engine()
        assert engine.get_wiki_root().endswith("wiki")

    def test_G2_4_equals_get_data_dir_slash_wiki(self, _scai_env):
        from aibridge.utils.common import get_data_dir
        engine = _make_engine()
        assert Path(engine.get_wiki_root()) == Path(get_data_dir()) / "wiki"


# ===========================================================================
# G3 · KarpathyWikiReader 绑定 kb_root = get_data_dir()
# ===========================================================================

class TestG3KarpathyWikiReaderKBRoot:
    def test_G3_1_has_wiki_reader(self, _scai_env):
        engine = _make_engine()
        assert getattr(engine, "_wiki_reader", None) is not None

    def test_G3_2_reader_root_is_Path(self, _scai_env):
        engine = _make_engine()
        r_root = getattr(engine._wiki_reader, "_root", None)
        assert isinstance(r_root, Path), f"reader._root 必须是 Path，实际 {type(r_root).__name__}"

    def test_G3_3_reader_root_equals_SCAI_DATA_DIR(self, _scai_env):
        from aibridge.utils.common import get_data_dir
        engine = _make_engine()
        reader_root = Path(getattr(engine._wiki_reader, "_root"))
        assert reader_root == Path(get_data_dir()), (
            f"KarpathyWikiReader 错误地绑定到 {reader_root}，"
            f"预期 {get_data_dir()}"
        )


# ===========================================================================
# G4 · wiki_reader.list_pages() ≥ 5（首启注入 5 条示例），标题含水果相关词
# ===========================================================================

class TestG4ListPagesAfterFirstRun:
    def test_G4_1_pages_count_ge_5(self, _scai_env):
        engine = _make_engine()
        pages = engine._wiki_reader.list_pages() if hasattr(engine._wiki_reader, "list_pages") else []
        assert len(pages) >= 5, f"首启注入后应有 ≥ 5 页，实际 {len(pages)} 页"

    def test_G4_2_titles_contain_fruit_or_grape_or_watermelon_keywords(self, _scai_env):
        engine = _make_engine()
        pages = engine._wiki_reader.list_pages() if hasattr(engine._wiki_reader, "list_pages") else []
        titles = [getattr(p, "title", "") or getattr(p, "slug", "") or getattr(p, "path", "")
                  for p in pages]
        joined = " · ".join(titles)
        hit = any(k in joined for k in ["葡萄", "西瓜", "季节", "储存", "客服", "水果"])
        assert hit, f"首启示例标题未出现水果关键词，titles = {titles[:8]}"


# ===========================================================================
# G5/G6 · ImportDocumentWorker 导入文件落到 SCAI_DATA_DIR/wiki/entities/<fname>.md
# ===========================================================================

class TestG5G6ImportDocumentToCorrectPath:
    @pytest.fixture
    def mini_doc(self, tmp_path):
        # 注意 tmp_path 与 _scai_env 的 tmp_path 不共享没关系，mini_doc 放哪里都行，只要能读
        d = tmp_path / "kb_root_unification_minidoc.txt"
        d.write_text(
            "# 丹东 99 草莓（红颜品种）\n\n"
            "产地：辽宁丹东东港\n"
            "特点：奶香味浓郁，果形圆润，表皮亮泽\n"
            "最佳食用期：12月至次年4月\n"
            "挑选技巧：选蒂部发青的，颜色均匀红润有自然光泽，闻着有奶香味的最好\n",
            encoding="utf-8",
        )
        return str(d)

    def test_G5_1_sync_run_success(self, _scai_env, mini_doc):
        engine = _make_engine()
        from aibridge.ui.ui_engine_bridge import ImportDocumentWorker
        ok, result, signals = ImportDocumentWorker.sync_run(engine, mini_doc, category="entities")
        assert ok is True, f"导入应成功，实际 signals={signals!r}"

    def test_G5_2_wiki_page_path_exists(self, _scai_env, mini_doc):
        engine = _make_engine()
        from aibridge.ui.ui_engine_bridge import ImportDocumentWorker
        ok, result, signals = ImportDocumentWorker.sync_run(engine, mini_doc, category="entities")
        path_v = None
        if ok and hasattr(result, "wiki_page_path") and result.wiki_page_path:
            path_v = Path(result.wiki_page_path)
        elif "imported" in signals:
            path_v = Path(signals["imported"][0])
        assert path_v is not None, "导入后必须返回 wiki_page_path"
        assert path_v.exists(), f"导入文件不存在：{path_v}"

    def test_G6_1_file_located_in_SCAI_DATA_DIR_wiki_entities(self, _scai_env, mini_doc):
        engine = _make_engine()
        from aibridge.ui.ui_engine_bridge import ImportDocumentWorker
        ok, result, signals = ImportDocumentWorker.sync_run(engine, mini_doc, category="entities")
        path_v = Path(result.wiki_page_path) if ok and hasattr(result, "wiki_page_path") else Path(signals["imported"][0])
        expected_parent = Path(engine.get_wiki_root()) / "entities"
        assert path_v.parent == expected_parent, (
            f"导入文件实际落盘于 {path_v.parent}，"
            f"预期 {expected_parent} （Bug #8：之前写 ./data/wiki/entities）"
        )

    def test_G6_2_filename_contains_mini_doc_slug(self, _scai_env, mini_doc):
        engine = _make_engine()
        from aibridge.ui.ui_engine_bridge import ImportDocumentWorker
        ok, result, signals = ImportDocumentWorker.sync_run(engine, mini_doc, category="entities")
        path_v = Path(result.wiki_page_path) if ok and hasattr(result, "wiki_page_path") else Path(signals["imported"][0])
        name = path_v.name.lower()
        hit = any(k in name for k in ["dandong", "strawb", "strawberry", "丹东", "草莓", "minidoc", "mini"])
        assert hit, f"文件名 {path_v.name} 不含 mini_doc slug"

    def test_G6_3_markdown_contains_imported_content(self, _scai_env, mini_doc):
        engine = _make_engine()
        from aibridge.ui.ui_engine_bridge import ImportDocumentWorker
        ok, result, signals = ImportDocumentWorker.sync_run(engine, mini_doc, category="entities")
        path_v = Path(result.wiki_page_path) if ok and hasattr(result, "wiki_page_path") else Path(signals["imported"][0])
        md_text = path_v.read_text(encoding="utf-8")
        assert any(k in md_text for k in ["丹东", "红颜", "奶香"]), (
            f"MD 正文缺失 mini_doc 内容，前 300 字符 = {md_text[:300]!r}"
        )


# ===========================================================================
# G7 · UnifiedRetriever 绑定同一 wiki_reader；mini_doc 导入 + refresh 后 pages ≥ 6
# ===========================================================================

class TestG7RetrieverSharesKBRoot:
    def test_G7_1_has_unified_retriever(self, _scai_env):
        engine = _make_engine()
        assert getattr(engine, "_unified_retriever", None) is not None, "必须有 _unified_retriever 属性"

    def test_G7_3_initial_pages_from_first_run_example_data(self, _scai_env):
        engine = _make_engine()
        unified = engine._unified_retriever
        ur_reader = getattr(unified, "_wiki_reader", None)
        if ur_reader is not None and hasattr(ur_reader, "list_pages"):
            pages = ur_reader.list_pages()
        else:
            pages = engine._wiki_reader.list_pages() if hasattr(engine._wiki_reader, "list_pages") else []
        assert len(pages) >= 5, (
            f"UnifiedRetriever 绑定的 wiki_reader 读不到首启注入的 5 条示例，"
            f"实际 pages={len(pages)}，证明 UnifiedRetriever ↔ wiki_reader 路径未统一"
        )

    @pytest.fixture
    def mini_doc(self, tmp_path):
        d = tmp_path / "p22_pytest_dandong_strawberry_doc.txt"
        d.write_text(
            "# 丹东 99 草莓 pytest\n\n产地：东港；特点：奶香味；挑选：蒂部发青、均匀红润\n",
            encoding="utf-8",
        )
        return str(d)

    def test_G7_2_refresh_pages_increases_after_new_import(self, _scai_env, mini_doc):
        engine = _make_engine()
        from aibridge.ui.ui_engine_bridge import ImportDocumentWorker
        # 1. 导入 mini_doc 之前的 pages 数（首启=5）
        before_pages = len(engine._wiki_reader.list_pages()) if hasattr(engine._wiki_reader, "list_pages") else 0
        # 2. 导入
        ok, result, _ = ImportDocumentWorker.sync_run(engine, mini_doc, category="entities")
        assert ok is True
        # 3. 模拟 P2-3 refresh_kb_index()（P2-2 里手动调）
        reader = engine._wiki_reader
        if hasattr(reader, "_load_all_pages"):
            reader._load_all_pages()
        after_pages = len(reader.list_pages()) if hasattr(reader, "list_pages") else 0
        # 4. pages 应该增加 1（5 → 6）
        assert after_pages >= max(before_pages + 1, 6), (
            f"导入 + refresh 后 pages 未增加，before={before_pages} after={after_pages}"
        )
        # 5. slug/path/title 里有 mini_doc 关键词
        titles = [getattr(p, "slug", "") or getattr(p, "path", "") or getattr(p, "title", "")
                  for p in reader.list_pages()]
        hit = any(("dandong" in (t or "").lower()) or ("strawberry" in (t or "").lower())
                  or ("丹东" in (t or "")) or ("草莓" in (t or ""))
                  for t in titles)
        assert hit, f"导入文档未出现在 wiki_reader 的 page 列表中，后 5 项 = {titles[-5:]}"


# ===========================================================================
# G8 · degraded_details 不再含 wiki_empty
# ===========================================================================

class TestG8NoWikiEmptyDegraded:
    def test_G8_1_wiki_empty_code_not_in_degraded_details(self, _scai_env):
        engine = _make_engine()
        deets = engine.get_degraded_details()
        codes = [d.get("code", "") for d in deets if isinstance(d, dict)]
        assert "wiki_empty" not in codes, (
            f"get_degraded_details() 仍出现 wiki_empty（会误导降级横幅闪烁），"
            f"实际 codes={codes}  details={deets!r}"
        )
