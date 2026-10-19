# -*- coding: utf-8 -*-
"""
SCAI · 里层 PDD · 模块 7' · Phase 5 TDD
模块：INNER-OA07 · 公众号云端服务
Seams: 15
规范：docs/PDD_INNER_oa_cloud_service.md
原型：_prototypes/oa_cloud_service_prototype.py（15/15 全绿）

运行：
    pytest tests/test_inner_oa_service_pdd.py -v
    # 预期：15 passed
"""
from __future__ import annotations

import hashlib
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

sys.path.insert(0, str(PROJECT_ROOT / "_prototypes"))
from oa_cloud_service_prototype import (  # noqa: E402
    OACloudService, InternalMessage, make_service,
    wechat_check_signature, parse_xml_to_msg, PLACEHOLDER_TEMPLATE,
    AccessTokenManager,
)


# ============================================================
# OA-01: GET 签名通过 → 返回 echostr
# ============================================================
def test_oa01_get_signature_ok():
    svc = make_service()
    token = svc.config["token"]
    ts, nonce, echostr = "1700000000", "nonce_123", "echo_abc"
    tmp = sorted([token, ts, nonce])
    sig = hashlib.sha1("".join(tmp).encode("utf-8")).hexdigest()
    status, body = svc.handle_get(sig, ts, nonce, echostr)
    assert status == 200
    assert body == echostr


# ============================================================
# OA-02: GET 签名失败 → 403
# ============================================================
def test_oa02_get_signature_bad():
    svc = make_service()
    status, body = svc.handle_get("WRONG_SIG", "1", "2", "echo")
    assert status == 403


# ============================================================
# OA-03: POST 解密 + XML → InternalMessage
# ============================================================
def test_oa03_post_parse_xml_to_internal_message():
    svc = make_service()
    token = svc.config["token"]
    ts, nonce = "1700000001", "nonce_xyz"
    xml = f"""<xml>
<ToUserName><![CDATA[gh_appid]]></ToUserName>
<FromUserName><![CDATA[openid_user1]]></FromUserName>
<CreateTime>1700000001</CreateTime>
<MsgType><![CDATA[text]]></MsgType>
<Content><![CDATA[你好，我的公众号有 AI 吗？]]></Content>
<MsgId>999888777</MsgId>
</xml>"""
    tmp = sorted([token, ts, nonce])
    sig = hashlib.sha1("".join(tmp).encode()).hexdigest()
    status, body = svc.handle_post(sig, ts, nonce, sig, xml)
    assert status == 200
    assert PLACEHOLDER_TEMPLATE in body
    parsed = parse_xml_to_msg(xml)
    assert parsed.sender_id == "openid_user1"
    assert "公众号有 AI 吗" in parsed.content
    assert parsed.msg_type == "text"


# ============================================================
# OA-04: 占位语 < 5s（mock 下 < 100ms）
# ============================================================
def test_oa04_placeholder_within_5s():
    svc = make_service()
    token = svc.config["token"]
    ts, nonce = "1", "2"
    xml = "<xml><ToUserName><![CDATA[gh_a]]></ToUserName><FromUserName><![CDATA[openid_b]]></FromUserName><CreateTime>1</CreateTime><MsgType><![CDATA[text]]></MsgType><Content><![CDATA[test]]></Content><MsgId>1</MsgId></xml>"
    tmp = sorted([token, ts, nonce])
    sig = hashlib.sha1("".join(tmp).encode()).hexdigest()
    t0 = time.perf_counter()
    status, body = svc.handle_post(sig, ts, nonce, sig, xml)
    dt_ms = (time.perf_counter() - t0) * 1000
    assert dt_ms < 5000, f"返回耗时 {dt_ms:.0f}ms > 5s"
    assert status == 200
    import re
    m = re.search(r"<Content><!\[CDATA\[(.*?)\]\]></Content>", body, re.DOTALL)
    assert m and m.group(1) == PLACEHOLDER_TEMPLATE


# ============================================================
# OA-05: token 首次获取 + SQLite 写入
# ============================================================
def test_oa05_token_first_fetch_store_in_db():
    svc = make_service()
    before = time.time()
    token = svc.token_mgr.get_token()
    assert token is not None and len(token) > 0
    expires_at = svc.token_mgr.get_expires_at()
    assert expires_at is not None
    assert expires_at > before
    # 未过期时再次获取应相同（稳定性）
    with sqlite3.connect(svc.token_mgr.db_path) as c:
        row = c.execute("SELECT access_token FROM oa_tokens WHERE app_id=?",
                        (svc.config["app_id"],)).fetchone()
    assert row[0] == token


# ============================================================
# OA-06: 提前 5 分钟刷新
# ============================================================
def test_oa06_token_auto_refresh_before_expire():
    svc = make_service()
    t1 = svc.token_mgr.get_token()
    near_expire = time.time() + 2 * 60
    with sqlite3.connect(svc.token_mgr.db_path) as c:
        c.execute("UPDATE oa_tokens SET expires_at=? WHERE app_id=?",
                  (near_expire, svc.config["app_id"]))
        c.commit()
    svc.token_mgr.get_token()
    new_expires = svc.token_mgr.get_expires_at()
    assert new_expires is not None
    assert (new_expires - near_expire) >= 6000


# ============================================================
# OA-07: 3 次指数退避重试
# ============================================================
def test_oa07_token_retry_3_times():
    svc = make_service(app_secret="FORCE_FAIL_2_TIMES")
    ok = svc.token_mgr.refresh()
    assert ok, "3 次重试中第 3 次应成功"
    tok = svc.token_mgr.get_token()
    assert tok is not None and len(tok) > 0


# ============================================================
# OA-08: engine.process 走精简 15 步流水线
# ============================================================
def test_oa08_engine_process_pipeline_reply():
    svc = make_service()
    msg = InternalMessage(msg_id="t1", sender_id="openid_t", content="你好，我想学做 CPS 数字分身")
    result = svc.mp.process(msg)
    assert result["action"] == "reply"
    assert isinstance(result.get("content"), str) and len(result["content"]) > 0


# ============================================================
# OA-09: 客服消息推送成功
# ============================================================
def test_oa09_cs_send_text_success():
    svc = make_service()
    svc.token_mgr.get_token()
    svc.client.set_user_last_msg("openid_ok")
    before = svc.client.get_call_count()
    r = svc.client.send_text("openid_ok", "你好，AI 分身回复")
    after = svc.client.get_call_count()
    assert r["success"] is True
    assert after == before + 1
    last = svc.client.get_last_call()
    assert last is not None and last[0] == "openid_ok"


# ============================================================
# OA-10: 48h 限制拦截
# ============================================================
def test_oa10_cs_48h_limit_triggers_bad_case():
    svc = make_service()
    svc.token_mgr.get_token()
    svc.client._tracker._records["openid_expired"] = time.time() - 49 * 3600
    r = svc.client.send_text("openid_expired", "错过的消息")
    assert r["success"] is False
    assert r.get("bad_case") is True
    assert "48" in r.get("reason", "")


# ============================================================
# OA-11: RAG 命中 rag_count
# ============================================================
def test_oa11_rag_hit_rag_count():
    svc = make_service(kb_root="/real/mock")
    msg = InternalMessage(msg_id="r1", sender_id="o1", content="PDD 是什么？")
    result = svc.mp.process(msg)
    assert result.get("rag_count", 0) >= 1


# ============================================================
# OA-12: pull_badcases 消费式拉取
# ============================================================
def test_oa12_pull_badcases_returns_and_clears():
    svc = make_service()
    # 造 48h 未送达 + 无 Key 兜底两类
    svc.bad_cases_for_pull.append({
        "type": "cs_timeout", "sender": "openid_a",
        "reply": "错过的回复", "reason": "48h 未送达",
    })
    svc_no_key = make_service(llm_key="")
    msg = InternalMessage(msg_id="b1", sender_id="o2", content="你好")
    result = svc_no_key.mp.process(msg)
    assert result.get("bad_case_written") is True
    for case in svc_no_key.mp.iteration.get_badcases():
        svc.bad_cases_for_pull.append(case)
    pulled = svc.pull_badcases(limit=10)
    assert len(pulled) >= 2
    assert len(svc.bad_cases_for_pull) == 0


# ============================================================
# OA-13: 解密失败 → 200 + "success"
# ============================================================
def test_oa13_decrypt_fail_returns_success():
    svc = make_service()
    svc.crypto.set_decrypt_fail(True)
    token = svc.config["token"]
    ts, nonce = "1", "2"
    tmp = sorted([token, ts, nonce])
    sig = hashlib.sha1("".join(tmp).encode()).hexdigest()
    status, body = svc.handle_post(sig, ts, nonce, sig, "<xml>garbage</xml>")
    assert status == 200
    assert body.strip() == "success"


# ============================================================
# OA-14: LLM 无 Key → 兜底回复 + BadCase
# ============================================================
def test_oa14_no_api_key_fallback_reply_and_badcase():
    svc = make_service(llm_key="")
    msg = InternalMessage(msg_id="f1", sender_id="openid_x", content="你好")
    result = svc.mp.process(msg)
    assert result["action"] == "fallback_reply"
    assert "AI 配置未完成" in result["content"]
    assert result.get("bad_case_written") is True
    cases = svc.mp.iteration.get_badcases()
    assert len(cases) >= 1


# ============================================================
# OA-15: 完整端到端
# ============================================================
def test_oa15_e2e_full_flow():
    svc = make_service(llm_key="sk-test", kb_root="/mock/kb")
    token = svc.config["token"]
    ts, nonce = "1700000010", "n_e2e"
    sender = "openid_e2e_user"
    xml = f"""<xml>
<ToUserName><![CDATA[gh_e2e_appid]]></ToUserName>
<FromUserName><![CDATA[{sender}]]></FromUserName>
<CreateTime>1700000010</CreateTime>
<MsgType><![CDATA[text]]></MsgType>
<Content><![CDATA[PDD 方法论具体怎么落地？]]></Content>
<MsgId>1000001</MsgId>
</xml>"""
    tmp = sorted([token, ts, nonce])
    sig = hashlib.sha1("".join(tmp).encode()).hexdigest()
    status, body = svc.handle_post(sig, ts, nonce, sig, xml)
    assert status == 200
    assert PLACEHOLDER_TEMPLATE in body
    # 等异步
    svc._wait_async(0.5)
    calls = svc.client.get_call_count()
    assert calls >= 1, f"客服消息应推送 >=1 次，实际 {calls}"
    last = svc.client.get_last_call()
    assert last is not None and last[0] == sender
    assert isinstance(last[1], str) and len(last[1]) > 0
    # Store 至少 1 条记录
    assert len(svc.mp.store._records) >= 1
