"""今日待办 — tool 入口（飞书 + 钉钉合并视图）。

bridge 契约：
    call_tool(args: dict) -> dict
    args 注入：__tool_name / __agent_id / __is_manager / __credentials / __app_config
    - 按 args.get("__tool_name") 分发，本应用工具名固定为 "tasks_today"
    - audience=manager：非管理者调用直接返回错误
    - 返回值必须可 json 序列化，绝不抛异常给 bridge

数据来源（本机真实 CLI，均走 `--format json`）：
    飞书：lark-cli task +get-my-tasks --as user（today 用 --due-start/--due-end 过滤）
    钉钉：dws todo +due-today / dws todo +get-my-tasks --status false --all
    连接性：lark-cli auth status --json / dws auth status --format json

模块导入零副作用：不发请求、不起线程、不建 DB。
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta

TOOL_NAME = "tasks_today"
MANAGER_ERR = "该工具仅管理者可用"
CLI_TIMEOUT = 20
_TZ = "+08:00"

_PRIORITY_LABEL = {"10": "低", "20": "普通", "30": "较高", "40": "紧急"}


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
            cmd, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", **_spawn_kwargs(),
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
    """把截止时间点（str / int / dict）格式化为可读字符串。"""
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


def _dws_err(data: dict) -> str:
    e = data.get("error")
    if isinstance(e, dict):
        return e.get("message") or e.get("subtype") or ""
    return str(e or "")


def _priority_label(p) -> str:
    if p is None or p == "":
        return ""
    return _PRIORITY_LABEL.get(str(p), str(p))


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


def _norm_feishu_task(t: dict) -> dict:
    title = t.get("summary") or t.get("title") or t.get("subject") or "（无标题）"
    done = bool(t.get("completed_at") or t.get("completed") or t.get("is_completed"))
    due = t.get("due") or t.get("due_time") or t.get("deadline")
    return {
        "source": "飞书",
        "title": str(title),
        "time": _fmt_point(due),
        "status": "已完成" if done else "未完成",
        "priority": "",
        "link": "",
        "id": str(t.get("guid") or t.get("task_guid") or t.get("id") or ""),
    }


def _feishu_items(scope: str) -> tuple[list[dict], str]:
    cmd = [
        _feishu_cli(), "task", "+get-my-tasks",
        "--as", "user", "--format", "json", "--page-all",
    ]
    if scope == "today":
        now = datetime.now()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        cmd += [
            "--complete=false",
            "--due-start", start.strftime("%Y-%m-%d"),
            "--due-end", end.strftime("%Y-%m-%d"),
        ]
    else:
        cmd += ["--complete=false"]

    data, err = _run_cli(cmd)
    if not data:
        return [], err or "飞书待办查询失败"
    if data.get("ok") is False:
        e = data.get("error")
        return [], (e.get("message") if isinstance(e, dict) else "飞书待办查询失败")
    raw = data.get("data")
    if isinstance(raw, dict):
        raw = raw.get("items")
    if not isinstance(raw, list):
        raw = []
    return [_norm_feishu_task(x) for x in raw if isinstance(x, dict)], ""


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


def _norm_dingtalk_task(t: dict) -> dict:
    title = t.get("subject") or t.get("title") or t.get("summary") or "（无标题）"
    due = t.get("dueTime") or t.get("planFinishDate") or t.get("due")
    stage = t.get("finalStatusStage")
    done = bool(t.get("done") or t.get("completed") or t.get("status") is True)
    if stage in (1, 2, 3):  # 钉钉 finalStatusStage：非 0 视为已推进/完成
        done = True
    return {
        "source": "钉钉",
        "title": str(title),
        "time": _fmt_point(due),
        "status": "已完成" if done else "未完成",
        "priority": _priority_label(t.get("priority")),
        "link": "",
        "id": str(t.get("taskId") or t.get("id") or ""),
    }


def _dingtalk_items(scope: str) -> tuple[list[dict], str]:
    cli = _dingtalk_cli()
    if scope == "all":
        cmd = [cli, "todo", "+get-my-tasks", "--status", "false", "--all", "--format", "json"]
    else:
        cmd = [cli, "todo", "+due-today", "--format", "json"]

    data, err = _run_cli(cmd)
    if not data:
        return [], err or "钉钉待办查询失败"
    if data.get("ok") is False or data.get("outcome") == "failure":
        return [], _dws_err(data) or "钉钉待办查询失败"
    d = data.get("data") if isinstance(data.get("data"), dict) else {}
    raw = d.get("todos") or d.get("tasks") or []
    if not isinstance(raw, list):
        raw = []
    return [_norm_dingtalk_task(x) for x in raw if isinstance(x, dict)], ""


# ═══════════════════════════════════════════════════════════
# 合并逻辑
# ═══════════════════════════════════════════════════════════

def _collect(platform: str, scope: str) -> tuple[list[dict], list[str]]:
    items: list[dict] = []
    notes: list[str] = []
    if platform in ("feishu", "both"):
        ok, note = _feishu_connected()
        if not ok:
            notes.append(note or "飞书未连接")
        else:
            fi, fnote = _feishu_items(scope)
            if fnote:
                notes.append(f"飞书：{fnote}")
            items.extend(fi)
    if platform in ("dingtalk", "both"):
        ok, note = _dingtalk_connected()
        if not ok:
            notes.append(note or "钉钉未连接")
        else:
            di, dnote = _dingtalk_items(scope)
            if dnote:
                notes.append(f"钉钉：{dnote}")
            items.extend(di)
    return items, notes


def call_tool(args: dict) -> dict:
    """按 __tool_name 分发执行今日待办查询。"""
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
        scope = (args.get("scope") or "today").strip().lower()
        if scope not in ("today", "all"):
            scope = "today"

        items, notes = _collect(platform, scope)
        items.sort(key=lambda x: x.get("time") or "")

        label = {"feishu": "飞书", "dingtalk": "钉钉"}.get(platform, "飞书+钉钉")
        scope_label = "今天到期" if scope == "today" else "全部未完成"
        if not items:
            summary = f"{label}没有{scope_label}的待办。"
        else:
            lines = [f"{label}共 {len(items)} 项{scope_label}的待办："]
            for it in items:
                parts = [it["time"], it["title"]] if it.get("time") else [it["title"]]
                line = " ".join(p for p in parts if p).strip()
                tags = [it.get("status") or "", it.get("priority") or ""]
                tags = [t for t in tags if t]
                if tags:
                    line += f"（{'/'.join(tags)}）"
                lines.append("- " + line)
            summary = "\n".join(lines)

        res = {
            "ok": True,
            "platform": platform,
            "scope": scope,
            "count": len(items),
            "items": items,
            "summary": summary,
        }
        if notes:
            res["notes"] = notes
            res["note"] = "；".join(notes)
        return res
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"今日待办查询失败: {e}"}
