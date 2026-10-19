# -*- coding: utf-8 -*-
"""定时发送应用 —— LLM function calling 入口。

【双受众声明】audience = "manager"（管理者专属）。
bridge 层按 is_manager_mode 过滤 tool_def，普通用户对话时不会出现本工具。

bridge 注入的上下文（见 bridge._dispatch_tool_call）：
  __tool_name / __agent_id / __is_manager / __credentials / __app_config

business 参数（由 LLM 按 tool_def 传入）：
  mode: create / list / delete / run_now
  name / cron_expr / content_template / target{channel,peer_id,peer_type} / job_id / agent_id
"""
from __future__ import annotations

import json

from app.storage.db import get_conn, new_id, now_ts
from app.apps._scheduler_common import (
    ensure_scheduler,
    register_job,
    _fill_template,
)

APP_ID = "schedule_message"

# 必须与 app_registry.py 里 schedule_message 的 tool_def_json.function.name 一致
TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "schedule_message",
        "description": "管理者专属：定时发送消息到指定渠道。mode 可选 create 创建 / list 列出 / delete 删除 / run_now 立即执行。时间以 Asia/Shanghai 北京时间为准。",
        "parameters": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["create", "list", "delete", "run_now"],
                    "description": "操作模式",
                },
                "name": {
                    "type": "string",
                    "description": "任务名，如'每日好单推送'",
                },
                "cron_expr": {
                    "type": "string",
                    "description": "Cron 表达式，Asia/Shanghai 时区。格式：分 时 日 月 周。如'0 15 * * *'=每天15:00",
                },
                "content_template": {
                    "type": "string",
                    "description": "发送内容，可含占位符如{get_daily_earnings}",
                },
                "target": {
                    "type": "object",
                    "description": "发送目标",
                    "properties": {
                        "channel": {
                            "type": "string",
                            "enum": ["wecom", "feishu", "dingtalk", "wcf", "oa"],
                        },
                        "peer_id": {"type": "string"},
                        "peer_type": {
                            "type": "string",
                            "enum": ["friend", "group", "official"],
                        },
                    },
                    "required": ["channel", "peer_id", "peer_type"],
                },
                "job_id": {
                    "type": "string",
                    "description": "delete/run_now 时必填",
                },
                "agent_id": {
                    "type": "string",
                    "description": "关联哪个智能体，一般不需要填",
                },
            },
            "required": ["mode"],
        },
    },
}


# ============================================================
# 统一发送：内部按渠道路由
# ============================================================

def send_reply(channel: str, peer_id: str, content: str,
               peer_type: str = "friend") -> tuple[bool, str | None]:
    """统一发送消息。微信走风控串行锁（防封号），其他组织内渠道直发。

    返回 (ok, err)。所有 channel client 均在函数内懒构造，模块导入无副作用。
    """
    _need_lock = (channel == "wcf")
    _risk = None
    if _need_lock:
        try:
            from app.channel.risk_engine import get_risk_engine
            _risk = get_risk_engine()
            _risk.acquire_send_lock(min_gap=2.0)
        except Exception:
            _risk = None
    try:
        if channel == "wecom":
            from app.channel.wecom_client import WecomClient
            c = WecomClient()
            if not c.connected:
                return False, "企微 CLI 未连接"
            return (c.send_reply(peer_id, content, peer_type=peer_type) and True), None
        if channel == "feishu":
            from app.channel.feishu_client import FeishuClient
            c = FeishuClient()
            if not c.connected:
                return False, "飞书 CLI 未连接"
            return (c.send_reply(peer_id, content, peer_type=peer_type) and True), None
        if channel == "dingtalk":
            from app.channel.dingtalk_client import DingtalkClient
            c = DingtalkClient()
            if not c.connected:
                return False, "钉钉 CLI 未连接"
            return (c.send_reply(peer_id, content, peer_type=peer_type) and True), None
        if channel == "wcf":
            from app.channel.wcf_client import WcfClient
            c = WcfClient()
            if not c.connected:
                return False, "微信 CLI 未连接"
            return (c.send_reply(peer_id, content, peer_type=peer_type) and True), None
        if channel == "oa":
            from app.channel.oa_client import OaClient
            c = OaClient()
            if not c.connected:
                return False, "OA CLI 未连接"
            return (c.send_reply(peer_id, content, peer_type=peer_type) and True), None
        return False, f"未知渠道: {channel}"
    finally:
        if _risk is not None:
            try:
                _risk.release_send_lock()
            except Exception:
                pass


# ============================================================
# 各 mode 实现
# ============================================================

def _create(args: dict, agent_id: str) -> dict:
    name = (args.get("name") or "").strip()
    cron_expr = (args.get("cron_expr") or "").strip()
    content_template = args.get("content_template") or ""
    target = args.get("target") or {}

    if not name:
        return {"ok": False, "error": "缺少任务名 name"}
    if not cron_expr:
        return {"ok": False, "error": "缺少 cron_expr"}
    if not content_template:
        return {"ok": False, "error": "缺少 content_template"}
    if not isinstance(target, dict) or not target.get("channel") or not target.get("peer_id"):
        return {"ok": False, "error": "缺少有效 target（需 channel + peer_id）"}

    try:
        reg = register_job(
            new_id("job"), cron_expr, name, agent_id,
            app_id=APP_ID, content_template=content_template, target=target,
        )
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"创建失败: {e}"}

    try:
        ensure_scheduler()
    except Exception:
        pass

    return {
        "ok": True,
        "mode": "create",
        "job_id": reg.get("job_id"),
        "next_run_at": reg.get("next_run_at"),
        "message": f"定时任务「{name}」已创建",
    }


def _list(agent_id: str) -> dict:
    conn = get_conn()
    sql = ("SELECT job_id, agent_id, name, cron_expr, content_template, target_json,"
           " enabled, last_run_at, next_run_at, created_at, updated_at"
           " FROM scheduled_job WHERE app_id=?")
    params: list = [APP_ID]
    if agent_id:
        sql += " AND agent_id=?"
        params.append(agent_id)
    sql += " ORDER BY created_at DESC"
    rows = conn.execute(sql, params).fetchall()
    jobs = []
    for r in rows:
        d = dict(r)
        try:
            d["target"] = json.loads(d.pop("target_json") or "{}")
        except Exception:
            d["target"] = {}
        d["enabled"] = bool(d.get("enabled"))
        jobs.append(d)
    return {"ok": True, "mode": "list", "count": len(jobs), "jobs": jobs}


def _delete(args: dict) -> dict:
    job_id = args.get("job_id")
    if not job_id:
        return {"ok": False, "error": "delete 需要 job_id"}
    conn = get_conn()
    cur = conn.execute(
        "DELETE FROM scheduled_job WHERE job_id=? AND app_id=?", (job_id, APP_ID)
    )
    conn.commit()
    if not cur.rowcount:
        return {"ok": False, "error": f"任务不存在: {job_id}"}
    return {"ok": True, "mode": "delete", "job_id": job_id}


def _run_now(args: dict) -> dict:
    job_id = args.get("job_id")
    if not job_id:
        return {"ok": False, "error": "run_now 需要 job_id"}
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM scheduled_job WHERE job_id=? AND app_id=?", (job_id, APP_ID)
    ).fetchone()
    if not row:
        return {"ok": False, "error": f"任务不存在: {job_id}"}
    job = dict(row)

    content = _fill_template(job.get("content_template") or "")
    try:
        target = json.loads(job.get("target_json") or "{}")
        if not isinstance(target, dict):
            target = {}
    except Exception:
        target = {}
    channel = target.get("channel", "")
    peer_id = target.get("peer_id", "")
    peer_type = target.get("peer_type", "friend") or "friend"

    ok, err = send_reply(channel, peer_id, content, peer_type)
    conn.execute(
        "UPDATE scheduled_job SET last_run_at=?, updated_at=? WHERE job_id=?",
        (now_ts(), now_ts(), job_id),
    )
    conn.commit()
    if not ok:
        return {"ok": False, "error": err or "发送失败"}
    return {
        "ok": True,
        "mode": "run_now",
        "job_id": job_id,
        "channel": channel,
        "peer_id": peer_id,
        "content_preview": content[:200],
    }


# ============================================================
# LLM function calling 入口
# ============================================================

def call_tool(args: dict) -> dict:
    """bridge._dispatch_tool_call 调用的入口。"""
    args = args or {}
    if not args.get("__is_manager"):
        return {"ok": False, "error": "定时发送为管理者专属功能"}

    mode = (args.get("mode") or "").strip()
    agent_id = args.get("__agent_id") or args.get("agent_id") or ""

    if mode == "create":
        return _create(args, agent_id)
    if mode == "list":
        return _list(agent_id)
    if mode == "delete":
        return _delete(args)
    if mode == "run_now":
        return _run_now(args)
    return {"ok": False, "error": f"未知 mode: {mode or '(空)'}"}
