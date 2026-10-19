"""考勤查询应用 — tool 入口。

bridge 契约：
    call_tool(args: dict) -> dict
    args 注入：__tool_name / __agent_id / __is_manager / __credentials / __app_config
    - 必须按 args.get("__tool_name") 分发，本应用工具名固定为 "attendance_check"
    - 返回值必须可 json 序列化，绝不抛异常给 bridge
    - audience=manager：非管理者调用直接拒绝

数据来源：
    钉钉 dws CLI（仅钉钉，飞书考勤无开放 CLI）。
    先 dws auth status 拿当前登录用户 user_id，
    再 dws attendance check result/record 拉取指定日期区间的打卡结果/流水，
    按 CLI 返回字段解析为「正常/迟到/早退/缺卡/未打卡」等中文结果。

模块导入零副作用：不发网络请求、不建 DB 文件、不启动线程。
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta

from app.channel.dingtalk_client import _dws_cli_path

TOOL_NAME = "attendance_check"
DEFAULT_SCOPE = "today"
MAX_RECORDS = 300

# Windows 免弹黑框（PyInstaller 打包后尤其关键）
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

# 钉钉打卡「时间结果」英文枚举 → 中文
_TIME_RESULT_CN = {
    "normal": "正常",
    "late": "迟到",
    "early": "早退",
    "absenteeism": "缺卡",
    "notsigned": "未打卡",
    "nosign": "未打卡",
}


def _cli_run(*args, timeout: int = 30) -> tuple[bool, dict | None, str]:
    """调用 dws CLI，返回 (ok, data_dict, error_msg)。

    统一追加 --format json；错误探测覆盖 dws 的两种信封：
      {"error": {...}} 与 {"ok": false, "error": {...}} 与 {"success": false, ...}
    """
    cmd = [_dws_cli_path(), *args, "--format", "json"]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
            creationflags=_CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return False, None, f"CLI 超时 ({timeout}s)"
    except Exception as e:  # noqa: BLE001
        return False, None, str(e)

    out = (proc.stdout or "").strip() or (proc.stderr or "").strip()
    if not out:
        return False, None, "CLI 无输出"
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return False, None, f"非 JSON 输出: {out[:200]}"

    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict):
            return False, data, err.get("message") or err.get("reason") or "CLI 返回错误"
        if data.get("ok") is False or data.get("success") is False:
            msg = data.get("message") or data.get("errorMessage") or "CLI 调用失败"
            return False, data, str(msg)
    return True, data, ""


def _get_self_user_id() -> tuple[str, dict]:
    """获取当前登录用户 user_id 及鉴权信息。失败返回 ("", info)。"""
    ok, data, _ = _cli_run("auth", "status", timeout=15)
    if not ok or not isinstance(data, dict):
        return "", {}
    if data.get("authenticated") is False:
        return "", data
    return str(data.get("user_id") or ""), data


def _date_range(scope: str) -> tuple[str, str]:
    """按 scope 算出 (start, end) 的 YYYY-MM-DD。"""
    today = datetime.now().date()
    if scope == "month":
        return today.replace(day=1).isoformat(), today.isoformat()
    return today.isoformat(), today.isoformat()


def _records_from(data: dict) -> list[dict]:
    """从 dws 返回里挖出记录数组。兼容 check-result / check-record 的信封。"""
    if not isinstance(data, dict):
        return []
    for key in ("result", "records", "data"):
        val = data.get(key)
        if isinstance(val, list):
            return val
        if isinstance(val, dict):
            for k2 in ("records", "result", "list"):
                if isinstance(val.get(k2), list):
                    return val[k2]
    return []


def _norm_record(rec: dict) -> dict:
    """把一条打卡结果标准化为中文可读结构。"""
    if not isinstance(rec, dict):
        return {}
    date = (rec.get("workDate") or rec.get("date") or rec.get("day")
            or rec.get("checkDate") or "")
    raw_result = (rec.get("timeResult") or rec.get("result")
                  or rec.get("status") or rec.get("checkResult") or "")
    result_txt = _TIME_RESULT_CN.get(str(raw_result).lower(), str(raw_result) or "未知")
    return {
        "date": str(date),
        "time_result": str(raw_result),
        "time_result_text": result_txt,
        "location_result": str(rec.get("locationResult") or rec.get("locResult") or ""),
        "plan_time": str(rec.get("planCheckTime") or rec.get("planTime") or ""),
        "actual_time": str(rec.get("actualCheckTime") or rec.get("actualTime")
                           or rec.get("checkTime") or ""),
        "record_id": str(rec.get("checkRecordId") or rec.get("recordId") or ""),
    }


def _summarize(records: list[dict]) -> dict:
    """按中文结果聚合计数。"""
    summary: dict[str, int] = {}
    for r in records:
        key = r.get("time_result_text") or "未知"
        summary[key] = summary.get(key, 0) + 1
    return summary


def call_tool(args: dict) -> dict:
    """按 __tool_name 分发执行考勤查询。"""
    try:
        args = args or {}
        name = args.get("__tool_name") or TOOL_NAME
        if name != TOOL_NAME:
            return {"ok": False, "error": f"未知工具名: {name}"}

        # audience=manager 强校验
        if not args.get("__is_manager"):
            return {"ok": False, "error": "该工具仅管理者可用"}

        scope = (args.get("scope") or DEFAULT_SCOPE).strip().lower()
        if scope not in ("today", "month"):
            scope = DEFAULT_SCOPE
        start, end = _date_range(scope)

        user_id, auth = _get_self_user_id()
        if not user_id:
            reason = "钉钉未认证或未绑定"
            if isinstance(auth, dict) and auth.get("authenticated") is False:
                reason = "钉钉认证已失效，请重新授权"
            return {
                "ok": True,
                "scope": scope,
                "date_range": {"start": start, "end": end},
                "count": 0,
                "summary": {},
                "records": [],
                "note": reason + "，暂无法查询考勤。",
            }

        ok, data, err = _cli_run(
            "attendance", "check", "result",
            "--users", user_id,
            "--start", start,
            "--end", end,
            "--limit", "100",
            timeout=30,
        )
        if not ok:
            return {
                "ok": True,
                "scope": scope,
                "user_id": user_id,
                "date_range": {"start": start, "end": end},
                "count": 0,
                "summary": {},
                "records": [],
                "note": f"考勤查询失败: {err}",
            }

        raw_records = _records_from(data)[:MAX_RECORDS]
        records = [r for r in (_norm_record(x) for x in raw_records) if r]

        note = ""
        if not records:
            note = "查询区间内暂无考勤打卡结果。"
        return {
            "ok": True,
            "scope": scope,
            "user_id": user_id,
            "date_range": {"start": start, "end": end},
            "count": len(records),
            "summary": _summarize(records),
            "records": records,
            "note": note,
        }
    except Exception as e:  # noqa: BLE001 —— 绝不把异常抛回 bridge
        return {"ok": False, "error": f"考勤查询失败: {e}"}
