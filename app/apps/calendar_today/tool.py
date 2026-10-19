"""今日日程 — tool 入口（飞书 + 钉钉合并视图）。

bridge 契约：
    call_tool(args: dict) -> dict
    args 注入：__tool_name / __agent_id / __is_manager / __credentials / __app_config
    - 按 args.get("__tool_name") 分发，本应用工具名固定为 "calendar_today"
    - audience=manager：非管理者调用直接返回错误
    - 返回值必须可 json 序列化，绝不抛异常给 bridge

数据来源（本机真实 CLI，均走 `--format json`）：
    飞书：lark-cli calendar +agenda --start <ISO> --end <ISO> --as user
    钉钉：dws calendar event list --start <ISO> --end <ISO>
    连接性：lark-cli auth status --json / dws auth status --format json

模块导入零副作用：不发请求、不起线程、不建 DB。
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta

TOOL_NAME = "calendar_today"
MANAGER_ERR = "该工具仅管理者可用"
CLI_TIMEOUT = 20
_TZ = "+08:00"


# ═══════════════════════════════════════════════════════════
# 通用工具
# ═══════════════════════════════════════════════════════════

def _spawn_kwargs() -> dict:
    """Windows 下阻止 CLI 弹出黑框；其他平台返回空。"""
    kw: dict = {}
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kw["startupinfo"] = si
        kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    return kw


def _run_cli(cmd: list, timeout: int = CLI_TIMEOUT) -> tuple[dict | None, str]:
    """执行 CLI，返回 (data|None, 错误信息)。超时兜底，不抛异常。"""
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
            **_spawn_kwargs(),
        )
    except subprocess.TimeoutExpired:
        return None, f"CLI 超时（{timeout}s）"
    except Exception as e:  # noqa: BLE001
        return None, str(e)
    out = (proc.stdout or "").strip() or (proc.stderr or "").strip()
    if not out:
        return None, "CLI 无输出"
    try:
        return json.loads(out), ""
    except Exception:  # noqa: BLE001
        return None, f"非 JSON 输出：{out[:200]}"


def _to_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _fmt_ms(ms) -> str:
    """毫秒/秒时间戳 → 'MM-DD HH:MM'。"""
    try:
        v = float(ms)
    except (TypeError, ValueError):
        return str(ms)
    if v > 1e12:  # 毫秒
        v /= 1000.0
    try:
        return datetime.fromtimestamp(v).strftime("%m-%d %H:%M")
    except Exception:  # noqa: BLE001
        return str(ms)


def _fmt_point(v) -> str:
    """把时间点（str / int / dict）格式化为可读字符串。"""
    if v is None or v == "":
        return ""
    if isinstance(v, dict):
        ts = v.get("timestamp") or v.get("dateTimestamp")
        if ts:
            return _fmt_ms(ts)
        date = v.get("date")
        if date:
            return str(date)
        for k in ("dateTime", "datetime", "time"):
            if v.get(k):
                return _fmt_point(v[k])
        return ""
    if isinstance(v, (int, float)):
        return _fmt_ms(v)
    if isinstance(v, str):
        return v.replace("T", " ")[:16]
    return ""


def _time_range(start, end) -> str:
    sa, sb = _fmt_point(start), _fmt_point(end)
    if sa and sb:
        if len(sa) >= 5 and sa[:5] == sb[:5] and len(sb) > 6:  # 同一天
            return f"{sa}~{sb[6:]}"
        return f"{sa} ~ {sb}"
    return sa or sb or ""


def _dws_err(data: dict) -> str:
    e = data.get("error")
    if isinstance(e, dict):
        return e.get("message") or e.get("subtype") or ""
    return str(e or "")


# ═══════════════════════════════════════════════════════════
# 飞书
# ═══════════════════════════════════════════════════════════

def _feishu_cli() -> str:
    from app.channel.feishu_client import _lark_cli_path
    return _lark_cli_path()


def _feishu_connected() -> tuple[bool, str]:
    data, err = _run_cli([_feishu_cli(), "auth", "status", "--json"], timeout=15)
    if not data:
        return False, err or "飞书未连接"
    idents = data.get("identities") or {}
    user = idents.get("user") or {}
    bot = idents.get("bot") or {}
    if user.get("status") == "ready" or bot.get("status") == "ready":
        return True, ""
    return False, "飞书未连接"


def _norm_feishu_event(ev: dict) -> dict:
    title = ev.get("summary") or ev.get("title") or ev.get("subject") or "（无标题）"
    loc = ev.get("location")
    if isinstance(loc, dict):
        loc = loc.get("display_name") or loc.get("name") or ""
    return {
        "source": "飞书",
        "title": str(title),
        "time": _time_range(ev.get("start_time") or ev.get("start"),
                            ev.get("end_time") or ev.get("end")),
        "location": str(loc or ""),
        "link": str(ev.get("app_link") or ev.get("url") or ""),
        "id": str(ev.get("event_id") or ev.get("id") or ""),
    }


def _feishu_items(days: int) -> tuple[list[dict], str]:
    now = datetime.now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=days)
    fmt = lambda d: d.strftime("%Y-%m-%dT%H:%M:%S") + _TZ
    data, err = _run_cli([
        _feishu_cli(), "calendar", "+agenda",
        "--start", fmt(start), "--end", fmt(end),
        "--format", "json", "--as", "user",
    ])
    if not data:
        return [], err or "飞书日程查询失败"
    if data.get("ok") is False:
        return [], data.get("error", {}).get("message") if isinstance(data.get("error"), dict) else "飞书日程查询失败"
    raw = data.get("data")
    if isinstance(raw, dict):
        raw = raw.get("items") or raw.get("events") or []
    if not isinstance(raw, list):
        raw = []
    return [_norm_feishu_event(x) for x in raw if isinstance(x, dict)], ""


# ═══════════════════════════════════════════════════════════
# 钉钉
# ═══════════════════════════════════════════════════════════

def _dingtalk_cli() -> str:
    from app.channel.dingtalk_client import _dws_cli_path
    return _dws_cli_path()


def _dingtalk_connected() -> tuple[bool, str]:
    data, err = _run_cli([_dingtalk_cli(), "auth", "status", "--format", "json"], timeout=15)
    if not data:
        return False, err or "钉钉未连接"
    if data.get("authenticated") is True:
        return True, ""
    return False, "钉钉未连接"


def _norm_dingtalk_event(ev: dict) -> dict:
    title = ev.get("summary") or ev.get("title") or ev.get("subject") or "（无标题）"
    loc = ev.get("location")
    if isinstance(loc, dict):
        loc = loc.get("displayName") or loc.get("display_name") or loc.get("name") or ""
    return {
        "source": "钉钉",
        "title": str(title),
        "time": _time_range(ev.get("start") or ev.get("startTime"),
                            ev.get("end") or ev.get("endTime")),
        "location": str(loc or ""),
        "link": str(ev.get("appLink") or ev.get("url") or ev.get("shareUrl") or ""),
        "id": str(ev.get("id") or ev.get("eventId") or ""),
    }


def _dingtalk_items(days: int) -> tuple[list[dict], str]:
    now = datetime.now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=days)
    fmt = lambda d: d.strftime("%Y-%m-%dT%H:%M:%S") + _TZ
    data, err = _run_cli([
        _dingtalk_cli(), "calendar", "event", "list",
        "--start", fmt(start), "--end", fmt(end), "--format", "json",
    ])
    if not data:
        return [], err or "钉钉日程查询失败"
    if data.get("ok") is False or data.get("outcome") == "failure":
        return [], _dws_err(data) or "钉钉日程查询失败"
    events = None
    result = data.get("result")
    if isinstance(result, dict):
        events = result.get("events")
    if events is None and isinstance(data.get("data"), dict):
        events = data["data"].get("events")
    if not isinstance(events, list):
        events = []
    return [_norm_dingtalk_event(x) for x in events if isinstance(x, dict)], ""


# ═══════════════════════════════════════════════════════════
# 合并逻辑
# ═══════════════════════════════════════════════════════════

def _collect(platform: str, days: int) -> tuple[list[dict], list[str]]:
    items: list[dict] = []
    notes: list[str] = []
    if platform in ("feishu", "both"):
        ok, note = _feishu_connected()
        if not ok:
            notes.append(note or "飞书未连接")
        else:
            fi, fnote = _feishu_items(days)
            if fnote:
                notes.append(f"飞书：{fnote}")
            items.extend(fi)
    if platform in ("dingtalk", "both"):
        ok, note = _dingtalk_connected()
        if not ok:
            notes.append(note or "钉钉未连接")
        else:
            di, dnote = _dingtalk_items(days)
            if dnote:
                notes.append(f"钉钉：{dnote}")
            items.extend(di)
    return items, notes


def call_tool(args: dict) -> dict:
    """按 __tool_name 分发执行今日日程查询。"""
    try:
        args = args or {}
        if not args.get("__is_manager"):
            return {"ok": False, "error": MANAGER_ERR}
        name = args.get("__tool_name") or TOOL_NAME
        if name != TOOL_NAME:
            return {"ok": False, "error": f"未知工具名: {name}"}

        platform = (args.get("platform") or "both").strip().lower()
        if platform not in ("feishu", "dingtalk", "both"):
            platform = "both"
        days = max(1, min(31, _to_int(args.get("days"), 1)))

        items, notes = _collect(platform, days)
        items.sort(key=lambda x: x.get("time") or "")

        label = {"feishu": "飞书", "dingtalk": "钉钉"}.get(platform, "飞书+钉钉")
        if not items:
            summary = f"{label}今天没有日程安排。"
        else:
            lines = [f"{label}共 {len(items)} 项日程："]
            for it in items:
                line = f"{it['time']} {it['title']}".strip()
                if it.get("location"):
                    line += f"（{it['location']}）"
                lines.append("- " + line)
            summary = "\n".join(lines)

        res = {
            "ok": True,
            "platform": platform,
            "days": days,
            "count": len(items),
            "items": items,
            "summary": summary,
        }
        if notes:
            res["notes"] = notes
            res["note"] = "；".join(notes)
        return res
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"今日日程查询失败: {e}"}
