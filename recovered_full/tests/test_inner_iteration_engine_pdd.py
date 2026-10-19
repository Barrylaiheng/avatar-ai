# -*- coding: utf-8 -*-
"""
里层 PDD · 模块 4 · Phase 5 TDD · IterationEngine 测试
模块：src/aibridge/engine/iteration_engine.py（迭代 L7）

8 Seams：
  IE-01: BadCaseDetector — 安全合规检测（AI 暴露身份）
  IE-02: BadCaseDetector — 知识盲区检测（"我不知道"）
  IE-03: BadCaseDetector — 用户体验检测（过长回复）
  IE-04: BadCaseDetector — 正常回复不检测出 BadCase
  IE-05: get_badcases — 查询待审核列表
  IE-06: approve_badcase → 自动生成 RuleDraft
  IE-07: approve_rule_draft → 合并到正式规则表
  IE-08: message_processor S14 衔接 — bad_case_reasons → detect_async

执行: pytest tests/test_inner_iteration_engine_pdd.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


# ---------------- Fixtures ----------------

@pytest.fixture
def tmp_db(tmp_path):
    p = tmp_path / "iter_pdd_test.db"
    from aibridge.database.database_manager import DatabaseManager
    db = DatabaseManager(str(p))
    db.connect()
    try:
        from aibridge.database.database_migrator import DatabaseMigrator
        DatabaseMigrator(db).migrate()
    except Exception as e:
        pytest.fail(f"DB migration failed: {e}")
    yield db
    db.disconnect()


@pytest.fixture
def engine(tmp_db):
    from aibridge.engine.iteration_engine import IterationEngine
    return IterationEngine(tmp_db)


# ======================================================================
# IE-01 ~ IE-04：BadCaseDetector 4 条
# ======================================================================

def test_ie01_detect_safety_risk(engine):
    """IE-01：AI 回复暴露身份 → 安全合规 BadCase"""
    cases = engine.detect_async(
        user_input="你是谁",
        ai_response="我是一个AI语言模型，无法提供个人建议。",
        session_id="sess-test",
        msg_id="msg-ie01",
    )
    assert len(cases) >= 1, f"应检测出安全合规 BadCase，实={len(cases)}"
    safety_cases = [c for c in cases if c.detected_by == "safety"]
    assert len(safety_cases) >= 1, f"应有 safety 维度，实={[c.detected_by for c in cases]}"
    assert safety_cases[0].severity == "high"


def test_ie02_detect_knowledge_gap(engine):
    """IE-02：AI 回复"我不知道" → 知识盲区 BadCase"""
    cases = engine.detect_async(
        user_input="CPS 佣金比例是多少",
        ai_response="我不知道，没有相关信息。",
        session_id="sess-test",
        msg_id="msg-ie02",
    )
    gap_cases = [c for c in cases if c.detected_by == "knowledge_gap"]
    assert len(gap_cases) >= 1, f"应有 knowledge_gap 维度，实={[c.detected_by for c in cases]}"
    assert gap_cases[0].severity == "low"


def test_ie03_detect_bad_experience(engine):
    """IE-03：AI 回复过长 → 用户体验 BadCase"""
    long_reply = "非常抱歉" + "x" * 600 + "非常抱歉"
    cases = engine.detect_async(
        user_input="你好",
        ai_response=long_reply,
        session_id="sess-test",
        msg_id="msg-ie03",
    )
    ux_cases = [c for c in cases if c.detected_by == "user_experience"]
    assert len(ux_cases) >= 1, f"应有 user_experience 维度，实={[c.detected_by for c in cases]}"


def test_ie04_normal_reply_no_badcase(engine):
    """IE-04：正常回复 → 不检测出 BadCase"""
    cases = engine.detect_async(
        user_input="奶茶有啥优惠",
        ai_response="一点点今天第二杯半价，要的话我把链接发你～",
        session_id="sess-test",
        msg_id="msg-ie04",
    )
    assert len(cases) == 0, f"正常回复不应有 BadCase，实={[c.detected_by for c in cases]}"


# ======================================================================
# IE-05 ~ IE-07：审核流程 3 条
# ======================================================================

def test_ie05_get_pending_badcases(engine):
    """IE-05：查询待审核 BadCase 列表"""
    # 先造 2 条 BadCase
    engine.detect_async("你是谁", "我是一个AI", "sess-test", "msg-a")
    engine.detect_async("你好", "我不知道", "sess-test", "msg-b")
    pending = engine.detector.get_badcases(status="pending")
    assert len(pending) >= 2, f"应有至少 2 条 pending，实={len(pending)}"


def test_ie06_approve_generates_rule_draft(engine):
    """IE-06：approve BadCase → 自动生成 RuleDraft"""
    cases = engine.detect_async("你是谁", "我是一个AI", "sess-test", "msg-c")
    assert len(cases) >= 1
    case_id = cases[0].case_id
    # 审核
    ok = engine.approve_badcase(case_id, "确认暴露 AI 身份")
    assert ok is True
    # 验证 RuleDraft 生成
    drafts = engine.draft_generator.get_drafts()
    assert len(drafts) >= 1, f"应生成至少 1 条 RuleDraft，实={len(drafts)}"
    assert drafts[0].case_id == case_id


def test_ie07_approve_rule_draft_merges(engine):
    """IE-07：approve RuleDraft → 合并到 compliance_rules"""
    # 造 BadCase + 审核 + 生成 draft
    cases = engine.detect_async("你是谁", "我是一个AI", "sess-test", "msg-d")
    case_id = cases[0].case_id
    engine.approve_badcase(case_id, "确认")
    drafts = engine.draft_generator.get_drafts()
    assert len(drafts) >= 1
    draft_id = drafts[0].draft_id
    # 审核通过 draft
    ok = engine.approve_rule_draft(draft_id, "admin")
    assert ok is True
    # 验证 compliance_rules 里有新规则
    engine._db.execute("SELECT COUNT(*) AS cnt FROM compliance_rules WHERE rule_name = ?", (drafts[0].source_case,))
    row = engine._db.fetchone()
    assert row and row["cnt"] >= 1, "合并后 compliance_rules 应有新规则"


# ======================================================================
# IE-08：message_processor S14 衔接
# ======================================================================

def test_ie08_s14_badcase_reasons_to_detect(tmp_db):
    """IE-08：message_processor S14 的 bad_case_reasons → IterationEngine.detect_async"""
    from aibridge.config.config_manager import ConfigManager
    from aibridge.engine.message_processor import MessageProcessor
    cfg = ConfigManager()
    cfg.set("security.safety_shell_enabled", False)
    cfg.set("ui.aigc_stamp_enabled", True)
    cfg.set("llm.provider", "mock")
    cfg.set("llm.api_key", "MOCK_VALID_IE08")
    proc = MessageProcessor(cfg, tmp_db)

    # 模拟 LLM 兜底场景（无 API Key → no_api_key → bad_case）
    m = {
        "msg_id": "ie08-1",
        "content": "你好 __fallback_other__",
        "msg_type": "text",
        "group_name": "",
        "group_wxid": "",
        "sender_wxid": "u-ie08",
        "is_at_me": False,
        "sender_is_master": False,
        "session_type": "chat",
    }
    out = proc.process_v2(**m)
    assert out.write_bad_case is True, f"应写 bad_case，实={out.write_bad_case}"
    assert len(out.bad_case_reasons) > 0, f"应有 reasons，实={out.bad_case_reasons}"
    # 验证 reason 含 LLM兜底
    reason_str = "; ".join(out.bad_case_reasons)
    assert "LLM兜底" in reason_str or "other" in reason_str.lower(), \
        f"reason 应含 LLM兜底，实={reason_str}"
