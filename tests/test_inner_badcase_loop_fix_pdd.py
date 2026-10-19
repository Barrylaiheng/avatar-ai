# -*- coding: utf-8 -*-
"""
P3-4 · BadCase 闭环修复 pytest 测试用例
覆盖 G1~G6：review_rule_draft 方法 + metadata 持久化 + 审核流程 +
              排序 key + IterationEngine 参数 + S14 闭环

运行:
  $env:TRANSFORMERS_OFFLINE="1"; $env:HF_HUB_OFFLINE="1"
  python -m pytest tests/test_inner_badcase_loop_fix_pdd.py -v
"""
from __future__ import annotations
import os, sys, shutil, json, inspect
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


@pytest.fixture
def tmp_scai_data_dir(tmp_path):
    d = tmp_path / "tmp_p34_pytest"
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)
    old = os.environ.get("SCAI_DATA_DIR")
    os.environ["SCAI_DATA_DIR"] = str(d).replace("\\", "/")
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_OFFLINE"] = "1"
    cfg_path = d / "config.json"
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump({
            "llm_api_key": "MOCK_P34", "llm_provider": "mock", "llm_model": "auto",
            "llm_base_url": "https://test.mock/v1",
            "kb_wiki_root": str(d / "wiki").replace("\\", "/"),
            "oa_cloud_base_url": "", "master_wxid": "wxid_master_p34",
        }, f, ensure_ascii=False, indent=2)
    yield str(d).replace("\\", "/")
    if old:
        os.environ["SCAI_DATA_DIR"] = old
    else:
        os.environ.pop("SCAI_DATA_DIR", None)


@pytest.fixture
def engine(tmp_scai_data_dir):
    from aibridge.app_engine import AppEngine
    e = AppEngine()
    assert e.initialize(), "AppEngine.initialize() 必须成功"
    yield e


# --------- T1 · review_rule_draft 方法存在 ---------
def test_t1_review_rule_draft_exists(engine):
    from aibridge.engine.iteration_engine import IterationEngine
    ie = engine._iteration_engine
    assert hasattr(ie, 'review_rule_draft'), "IterationEngine 必须有 review_rule_draft 方法"
    sig = inspect.signature(ie.review_rule_draft)
    params = list(sig.parameters.keys())
    assert 'draft_id' in params, f"签名须含 draft_id，实际 {params}"
    assert 'approved' in params, f"签名须含 approved，实际 {params}"


# --------- T2 · metadata 写入后读回 ---------
def test_t2_metadata_roundtrip(engine):
    from aibridge.engine.iteration_engine import BadCase
    ie = engine._iteration_engine
    test_case = BadCase(
        case_id="case_t2_001",
        session_id="sess_t2", msg_id="msg_t2",
        user_input="测试metadata", ai_response="回复",
        detected_by="safety", severity="high", status="pending",
        metadata={"reasons": ["安全命中"], "source": "S14_auto", "key": "val"},
    )
    ie.detector._save_badcase(test_case)
    engine._db.commit()

    cases = ie.detector.get_badcases(limit=50)
    found = [c for c in cases if c.case_id == "case_t2_001"]
    assert len(found) == 1, f"应读回 1 条，实际 {len(found)}"
    bc = found[0]
    assert bc.metadata, f"metadata 不应为空：{bc.metadata}"
    assert bc.metadata.get("source") == "S14_auto", f"source 丢失：{bc.metadata}"
    assert "安全命中" in bc.metadata.get("reasons", []), f"reasons 丢失：{bc.metadata}"
    assert bc.metadata.get("key") == "val", f"自定义字段丢失：{bc.metadata}"


# --------- T3 · review_rule_draft 审核通过 ---------
def test_t3_review_approve(engine):
    from aibridge.engine.iteration_engine import BadCase
    ie = engine._iteration_engine
    # 先写入 BadCase + rule_draft
    bc = BadCase(
        case_id="case_t3_001", session_id="sess_t3", msg_id="msg_t3",
        user_input="砍价", ai_response="好的", detected_by="safety",
        severity="high", status="pending",
    )
    ie.detector._save_badcase(bc)
    engine._db.execute(
        """INSERT INTO rule_drafts (draft_id, case_id, rule_type, rule_content, source_case, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("draft_t3_001", "case_t3_001", "compliance", "规则内容", "case_t3_001", "pending", "2026-08-12T00:00:00")
    )
    engine._db.commit()

    ok = ie.review_rule_draft("draft_t3_001", approved=True)
    assert ok is True, "审核通过应返回 True"

    engine._db.execute("SELECT status FROM rule_drafts WHERE draft_id = ?", ("draft_t3_001",))
    row = engine._db.fetchone()
    assert row and row["status"] == "approved", f"状态应为 approved，实际 {row['status'] if row else 'None'}"


# --------- T4 · review_rule_draft 审核拒绝 ---------
def test_t4_review_reject(engine):
    from aibridge.engine.iteration_engine import BadCase
    ie = engine._iteration_engine
    bc = BadCase(
        case_id="case_t4_001", session_id="sess_t4", msg_id="msg_t4",
        user_input="广告", ai_response="好的", detected_by="safety",
        severity="medium", status="pending",
    )
    ie.detector._save_badcase(bc)
    engine._db.execute(
        """INSERT INTO rule_drafts (draft_id, case_id, rule_type, rule_content, source_case, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("draft_t4_001", "case_t4_001", "compliance", "规则", "case_t4_001", "pending", "2026-08-12T00:00:01")
    )
    engine._db.commit()

    ok = ie.review_rule_draft("draft_t4_001", approved=False)
    assert ok is True, "拒绝应返回 True"

    engine._db.execute("SELECT status FROM rule_drafts WHERE draft_id = ?", ("draft_t4_001",))
    row = engine._db.fetchone()
    assert row and row["status"] == "rejected", f"状态应为 rejected，实际 {row['status'] if row else 'None'}"


# --------- T5 · 不存在的 draft_id 返回 False ---------
def test_t5_nonexistent_draft(engine):
    ie = engine._iteration_engine
    ok = ie.review_rule_draft("nonexistent_draft_id", approved=True)
    assert ok is False, "不存在的 draft_id 应返回 False"


# --------- T6 · get_bad_cases 排序正确（created_at 降序） ---------
def test_t6_badcases_sorted_by_created_at(engine):
    from aibridge.engine.iteration_engine import BadCase
    ie = engine._iteration_engine
    for i in range(5):
        bc = BadCase(
            case_id=f"case_sort_t6_{i:03d}",
            session_id="sess_sort_t6", msg_id=f"msg_t6_{i}",
            user_input=f"测试{i}", ai_response=f"回复{i}",
            detected_by="user_experience", severity="low",
            status="pending", created_at=f"2026-08-1{i+1}T00:00:00",
        )
        ie.detector._save_badcase(bc)
    engine._db.commit()

    cases = engine.get_bad_cases(limit=100)
    sort_cases = [c for c in cases if c.get("case_id", "").startswith("case_sort_t6_")]
    assert len(sort_cases) == 5, f"应有 5 条，实际 {len(sort_cases)}"
    # 验证降序排列
    for i in range(len(sort_cases) - 1):
        assert sort_cases[i]["created_at"] >= sort_cases[i + 1]["created_at"], (
            f"排序错误：{sort_cases[i]['created_at']} < {sort_cases[i+1]['created_at']}"
        )


# --------- T7 · IterationEngine 初始化参数正确 ---------
def test_t7_iteration_engine_init_no_config(engine):
    from aibridge.config.config_manager import ConfigManager
    ie = engine._iteration_engine
    detector = ie._detector
    llm_c = getattr(detector, '_llm_client', None)
    assert not isinstance(llm_c, ConfigManager), (
        f"detector._llm_client 不应是 ConfigManager，实际 {type(llm_c).__name__}"
    )


# --------- T8 · S14 写入的 BadCase 通过 get_bad_cases 读回含 metadata ---------
def test_t8_s14_badcase_readable_with_metadata(engine):
    from aibridge.engine.iteration_engine import BadCase
    ie = engine._iteration_engine
    s14_case = BadCase(
        case_id="case_s14_t8_001",
        session_id="pdd_msg_t8", msg_id="msg_t8_001",
        user_input="帮我拼多多砍价", ai_response="⚠️ 检测到疑似砍价",
        detected_by="safety", severity="high", status="pending",
        metadata={"reasons": ["安全命中", "S14_auto"], "source": "S14_auto"},
    )
    ie.detector._save_badcase(s14_case)
    engine._db.commit()

    all_cases = engine.get_bad_cases(limit=100)
    found = [c for c in all_cases if c.get("case_id") == "case_s14_t8_001"]
    assert len(found) == 1, f"应读回 1 条，实际 {len(found)}"
    meta = found[0].get("metadata", {})
    assert meta, f"metadata 不应为空：{meta}"
    assert "安全命中" in meta.get("reasons", []), f"reasons 丢失：{meta}"
    assert meta.get("source") == "S14_auto", f"source 丢失：{meta}"


# --------- T9 · AppEngine.review_rule_draft 调用不抛异常 ---------
def test_t9_appengine_review_rule_draft(engine):
    from aibridge.engine.iteration_engine import BadCase
    ie = engine._iteration_engine
    bc = BadCase(
        case_id="case_t9_001", session_id="sess_t9", msg_id="msg_t9",
        user_input="广告", ai_response="好的", detected_by="safety",
        severity="medium", status="pending",
    )
    ie.detector._save_badcase(bc)
    engine._db.execute(
        """INSERT INTO rule_drafts (draft_id, case_id, rule_type, rule_content, source_case, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ("draft_t9_001", "case_t9_001", "compliance", "规则", "case_t9_001", "pending", "2026-08-12T00:00:02")
    )
    engine._db.commit()

    ok = engine.review_rule_draft("draft_t9_001", True)
    assert ok is True, "AppEngine.review_rule_draft 应返回 True"


# --------- T10 · metadata 为空时不崩溃 ---------
def test_t10_empty_metadata_safe(engine):
    from aibridge.engine.iteration_engine import BadCase
    ie = engine._iteration_engine
    bc = BadCase(
        case_id="case_t10_001", session_id="sess_t10", msg_id="msg_t10",
        user_input="测试", ai_response="回复", detected_by="user_experience",
        severity="low", status="pending",
    )
    # metadata 默认为空 dict
    ie.detector._save_badcase(bc)
    engine._db.commit()

    cases = ie.detector.get_badcases(limit=50)
    found = [c for c in cases if c.case_id == "case_t10_001"]
    assert len(found) == 1
    assert found[0].metadata == {}, f"空 metadata 应返回空 dict，实际 {found[0].metadata}"
