"""
P2-3 模块 pytest：refresh_wiki 公开 API + 导入后自动刷新缓存（6 Seams）
对应 docs/PDD_INNER_wiki_refresh.md §4 的 6 条 Grill。

运行：
  $env:TRANSFORMERS_OFFLINE='1'; $env:HF_HUB_OFFLINE='1'
  python -m pytest tests/test_inner_wiki_refresh_pdd.py -v --tb=short
"""
import json
import os
import shutil
from pathlib import Path

import pytest


# -------------------- fixture：每个 test 独立 tmpdir --------------------
@pytest.fixture(autouse=True)
def _scai_env(tmp_path, monkeypatch):
    """每个 test 独立 SCAI_DATA_DIR，避免互相污染；config.json 最小配置兜底。"""
    data_dir = tmp_path / "scai_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    # chromadb embedding 离线模式
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("SCAI_DATA_DIR", str(data_dir))
    # 写最小 config.json（initialize 要读）
    with open(data_dir / "config.json", "w", encoding="utf-8") as f:
        json.dump({
            "llm_api_key": "", "llm_provider": "kimi", "llm_model": "auto",
            "oa_cloud_base_url": "",
        }, f, ensure_ascii=False, indent=2)
    yield data_dir


@pytest.fixture
def engine(_scai_env):
    from aibridge.app_engine import AppEngine
    eng = AppEngine()
    ok = eng.initialize()
    assert ok is True, f"AppEngine.initialize() 返回 {ok}"
    yield eng


# =========================================================================
# G1：refresh_wiki() 公开方法存在 + trigger 参数默认值
# =========================================================================
def test_p23_g1_refresh_wiki_api_and_trigger_default(engine):
    import inspect
    # G1-1 公开可调用
    assert hasattr(engine, "refresh_wiki") and callable(getattr(engine, "refresh_wiki")), (
        "AppEngine 缺少公开方法 refresh_wiki()"
    )
    # G1-2 trigger 参数存在
    sig = inspect.signature(engine.refresh_wiki)
    params = list(sig.parameters.keys())
    assert "trigger" in params, f"refresh_wiki 参数 {params} 不含 'trigger'"
    # G1-3 trigger 默认值
    default = sig.parameters["trigger"].default
    assert default == "user_import", f"trigger 默认值={default!r}，应为 'user_import'"


# =========================================================================
# G2：返回值契约 result / page_count / pages_diff / trigger
# =========================================================================
def test_p23_g2_return_contract(engine):
    r = engine.refresh_wiki(trigger="pytest_g2")
    # G2-1 dict
    assert isinstance(r, dict), f"返回类型 {type(r).__name__}，应为 dict"
    # G2-2 result == ok
    assert r.get("result") == "ok", f"result={r.get('result')!r}，应为 'ok'"
    # G2-3 page_count 为 int 且 ≥ 5（首启注入 5 条示例）
    pc = r.get("page_count")
    assert isinstance(pc, int) and pc >= 5, f"page_count={pc!r} 要求 int ≥ 5"
    # G2-4 pages_diff 为 int
    assert isinstance(r.get("pages_diff"), int), f"pages_diff 非 int"
    # G2-5 trigger 透传
    assert r.get("trigger") == "pytest_g2", f"trigger 未透传: {r.get('trigger')!r}"


# =========================================================================
# G3：磁盘新增 1 篇 MD → refresh → pages_diff = +1
# =========================================================================
def test_p23_g3_pages_diff_plus_one(engine, _scai_env):
    wiki_root = Path(engine.get_wiki_root())
    entities_dir = wiki_root / "entities"
    assert entities_dir.exists(), f"entities 目录不存在: {entities_dir}"

    before = engine.refresh_wiki(trigger="pytest_g3_before")

    # 手动写 1 篇 status: verified MD（跳过 search draft 过滤）
    md = entities_dir / "p23_test_kumquat.md"
    md.write_text(
        "---\n"
        "type: entity\n"
        "title: P23 Test 融安滑皮金桔\n"
        "tags: [水果, 金桔, 融安, 滑皮]\n"
        "status: verified\n"
        "---\n"
        "P23 Test 融安滑皮金桔产自广西柳州融安，甜度 18+，连皮吃无涩感。\n",
        encoding="utf-8",
    )

    after = engine.refresh_wiki(trigger="pytest_g3_after")
    # G3-1 刷新前 ≥ 5
    assert before["page_count"] >= 5, f"pages_before={before['page_count']} < 5"
    # G3-2 pages_after = pages_before + 1
    assert after["page_count"] == before["page_count"] + 1, (
        f"expected {before['page_count'] + 1}, got {after['page_count']}"
    )
    # G3-3 pages_diff = 1
    assert after["pages_diff"] == 1, f"pages_diff={after['pages_diff']}，应=1"


# =========================================================================
# G4：UnifiedRetriever._reader 与 engine._wiki_reader 同引用 + 检索命中
# =========================================================================
def test_p23_g4_retriever_shares_reader_and_search_hit(engine):
    ur = getattr(engine, "_unified_retriever", None)
    assert ur is not None, "engine 未持有 _unified_retriever 属性（AppEngine 装配可能被改）"
    # G4-1 同引用
    ur_reader = getattr(ur, "_reader", None)
    assert ur_reader is engine._wiki_reader, "UnifiedRetriever._reader 和 engine._wiki_reader 不是同一对象（refresh 后无法自动同步）"
    # G4-2 refresh 后 L1 搜索命中融安/金桔/滑皮 关键词
    #    复用 G3 写入逻辑（这个 test 独立，重新写一次保证独立性）
    md = Path(engine.get_wiki_root()) / "entities" / "p23_g4_kumquat.md"
    if not md.exists():
        md.write_text(
            "---\ntype: entity\ntitle: P23 G4 融安滑皮金桔\n"
            "tags: [金桔, 融安]\nstatus: verified\n---\n"
            "融安滑皮金桔：产自广西柳州融安县大将镇，油皮薄，连皮吃无涩感。\n",
            encoding="utf-8",
        )
    r = engine.refresh_wiki(trigger="pytest_g4")
    assert r["pages_diff"] >= 0, "refresh 不应负 diff（除非删掉，这里只新增）"
    # G4-3 wiki_reader.search 命中
    hits = engine._wiki_reader.search("融安 金桔 滑皮", top_k=3)
    assert len(hits) >= 1, f"刷新后 L1 搜索 0 条命中，期望 ≥ 1"
    hit_texts = " ".join(h.content for h in hits)
    assert any(k in hit_texts for k in ("融安", "金桔", "滑皮")), (
        f"搜索命中但正文不含融安/金桔/滑皮关键词：{hit_texts[:120]}"
    )


# =========================================================================
# G5：ImportDocumentWorker.sync_run 导入成功后自动触发 refresh（patch 捕获）
# =========================================================================
def test_p23_g5_importer_auto_triggers_refresh(engine, _scai_env, tmp_path):
    # 构造一篇 mini_doc 源文件
    inbox = tmp_path / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    src = inbox / "dandong_strawberry_g5.txt"
    src.write_text(
        "【P23 G5 丹东红颜草莓（奶香）】\n"
        "鸡心形，颜色鲜艳无空洞，香甜浓郁奶香味突出。\n"
        "冷藏 2-4℃，3 天内食用完毕最佳。\n",
        encoding="utf-8",
    )
    # monkey patch engine.refresh_wiki 捕获调用
    calls = []
    orig = engine.refresh_wiki

    def _patched(**kwargs):
        calls.append(kwargs)
        return orig(**kwargs)

    engine.refresh_wiki = _patched
    try:
        from aibridge.ui.ui_engine_bridge import ImportDocumentWorker
        ok, raw, signals = ImportDocumentWorker.sync_run(
            engine=engine,
            file_path=str(src),
            category="entities",
        )
        assert ok is True, f"导入结果 ok={ok!r} raw={raw}"
        assert "imported" in signals, "导入成功但 signals 没 imported 键"
    finally:
        engine.refresh_wiki = orig
    # G5-1 refresh 调用次数 ≥ 1
    assert len(calls) >= 1, f"导入成功但 engine.refresh_wiki 未被调用，calls={len(calls)}"
    # G5-2 某次 trigger == user_import
    assert any(c.get("trigger") == "user_import" for c in calls), (
        f"refresh 调用 trigger 不对，call_log={calls}"
    )


# =========================================================================
# G6：wiki 目录不存在 / 空目录时 refresh 安全降级
# =========================================================================
def test_p23_g6_degraded_on_missing_wiki_dir(engine):
    wiki_root = Path(engine.get_wiki_root())
    # 移动三个子目录到 .bak
    subs = ["concepts", "entities", "architecture"]
    baks = {}
    try:
        for s in subs:
            p = wiki_root / s
            bak = wiki_root / f"{s}.bak_p23g6"
            if p.exists():
                shutil.move(str(p), str(bak))
                baks[s] = bak
        # G6-1 不抛异常
        r = engine.refresh_wiki(trigger="pytest_g6_empty")
        # G6-2 返回结构正确
        assert isinstance(r, dict) and {"result", "page_count", "pages_diff", "trigger"}.issubset(r.keys()), (
            f"返回 keys 不符合契约：{list(r.keys()) if isinstance(r, dict) else r}"
        )
        # G6-3 pages_diff ≤ 0（负 = 清空了之前的缓存；0 = 本来就是空）
        assert isinstance(r["pages_diff"], int) and r["pages_diff"] <= 0, (
            f"删空目录后 pages_diff={r['pages_diff']}，应 ≤ 0"
        )
    finally:
        # 还原
        for s, bak in baks.items():
            if bak.exists():
                target = wiki_root / s
                if target.exists():
                    shutil.rmtree(target, ignore_errors=True)
                shutil.move(str(bak), str(target))
