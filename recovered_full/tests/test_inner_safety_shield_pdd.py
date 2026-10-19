# -*- coding: utf-8 -*-
"""
里层 PDD · 模块 2 · Phase 5 TDD · SafetyShield v2 测试
模块：src/aibridge/engine/safety_shield_v2.py（免疫 L2）

10 Seams：
  SS-01~SS-03: 基础（正常不命中/砍价命中/广告命中）
  SS-04~SS-07: 三击拉黑（3次触发/黑名单前置/黑名单用户普通内容不二次命中/非黑名单放行）
  SS-08: 审计日志可查
  SS-09: 自定义关键词扩展
  SS-10: 黑名单到期自动解禁

执行: pytest tests/test_inner_safety_shield_pdd.py -v
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


# ---------------- 常量 ----------------

WARN_KANJIA = "⚠️ 检测到疑似砍价/助力链接，这类链接本群不允许发哦～请遵守群规，以免被移出群聊 🙏"
WARN_AD = "⚠️ 检测到疑似引流内容，本群禁止发广告哦～有问题直接在群里说，搭搭帮你找优惠 😊"


# ---------------- Fixtures ----------------

@pytest.fixture
def tmp_db(tmp_path):
    p = tmp_path / "safety_pdd_test.db"
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
def shield(tmp_db):
    from aibridge.engine.safety_shield_v2 import SafetyShieldV2
    return SafetyShieldV2(tmp_db)


# ======================================================================
# SS-01 ~ SS-03：基础 3 条
# ======================================================================

def test_ss01_normal_content_no_hit(shield):
    """SS-01：正常内容不命中"""
    r = shield.check_content("u1", "你好，最近有什么奶茶优惠", "m1")
    assert r.hit is False
    assert r.category == ""
    assert r.warn_message == ""


def test_ss02_kanjia_hit(shield):
    """SS-02：砍价命中"""
    r = shield.check_content("u2", "帮我砍一刀", "m2")
    assert r.hit is True
    assert r.category == "砍价"
    assert "砍价" in r.warn_message or "助力" in r.warn_message


def test_ss03_advertising_hit(shield):
    """SS-03：广告命中"""
    r = shield.check_content("u3", "加我领券", "m3")
    assert r.hit is True
    assert r.category == "广告"
    assert "引流" in r.warn_message or "禁止发广告" in r.warn_message


# ======================================================================
# SS-04 ~ SS-07：三击拉黑 4 条
# ======================================================================

def test_ss04_three_hits_blacklist_7d(shield):
    """SS-04：同一用户 3 次广告 → 第 3 击触发拉黑 7 天"""
    for i in range(3):
        r = shield.check_content("u4", f"加V拿价{i}", f"m4-{i}")
    assert r.is_third_hit is True, "第 3 击应触发 is_third_hit"
    assert r.warn_message == "", "第 3 击不应发话术（silent_drop）"


def test_ss05_blacklist_check_blocked(shield):
    """SS-05：黑名单前置检查 → u4 在黑名单，剩余时间 > 0"""
    # 先三连击拉黑
    for i in range(3):
        shield.check_content("u4", f"加V{i}", f"m5-{i}")
    bl = shield.check_blacklist("u4")
    assert bl.is_blacklisted is True
    assert bl.remain_hours > 0


def test_ss06_blacklisted_user_normal_content_no_double_hit(shield):
    """SS-06：黑名单用户的普通内容 check_content 不应二次命中（职责分离）"""
    for i in range(3):
        shield.check_content("u6", f"加V{i}", f"m6-{i}")
    # 黑名单用户发普通内容
    r = shield.check_content("u6", "你好", "m6-4")
    assert r.hit is False, "check_content 只管关键词，不查黑名单（S05 的职责）"


def test_ss07_non_blacklisted_user_pass(shield):
    """SS-07：非黑名单用户 check_blacklist 放行"""
    bl = shield.check_blacklist("u7")
    assert bl.is_blacklisted is False


# ======================================================================
# SS-08：审计日志
# ======================================================================

def test_ss08_audit_logs_queryable(shield):
    """SS-08：审计日志可查，第 3 击有 warn + blacklist_7d 两条"""
    for i in range(3):
        shield.check_content("u8", f"加V{i}", f"m8-{i}")
    logs = shield.get_audit_logs(limit=10)
    assert len(logs) >= 4, f"应有至少 4 条审计日志（3 warn + 1 blacklist_7d），实={len(logs)}"
    u8_logs = [l for l in logs if l["wxid"] == "u8"]
    actions = [l["action_taken"] for l in u8_logs]
    assert "blacklist_7d" in actions, f"应有 blacklist_7d 动作，实={actions}"
    assert "warn" in actions, f"应有 warn 动作，实={actions}"


# ======================================================================
# SS-09：自定义关键词扩展
# ======================================================================

def test_ss09_custom_keyword_extension(shield):
    """SS-09：添加自定义关键词 → 命中"""
    ok = shield.add_keyword("送红包", "广告")
    assert ok is True
    r = shield.check_content("u9", "快来送红包啦", "m9")
    assert r.hit is True
    assert r.category == "广告"


# ======================================================================
# SS-10：黑名单到期自动解禁
# ======================================================================

def test_ss10_blacklist_auto_expire(shield):
    """SS-10：blacklist_until < now → check_blacklist 自动放行"""
    # 先拉黑
    for i in range(3):
        shield.check_content("u10", f"加V{i}", f"m10-{i}")
    bl = shield.check_blacklist("u10")
    assert bl.is_blacklisted is True
    # 手动改 blacklist_until 为过去
    shield._db.execute(
        "UPDATE safety_blacklist SET blacklist_until = ? WHERE wxid = ?",
        (time.time() - 1, "u10")
    )
    shield._db.commit()
    bl2 = shield.check_blacklist("u10")
    assert bl2.is_blacklisted is False, "到期应自动解禁"
