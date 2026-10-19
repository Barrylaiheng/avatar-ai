"""会议纪要应用 — tool 入口。

bridge 契约：
    call_tool(args: dict) -> dict
    args 注入：__tool_name / __agent_id / __is_manager / __credentials / __app_config
    - 必须按 args.get("__tool_name") 分发，本应用工具名固定为 "minutes_search"
    - 返回值必须可 json 序列化，绝不抛异常给 bridge
    - audience=manager：非管理者调用直接拒绝

数据来源（双渠道合并）：
    飞书：lark-cli minutes +search（数据在 data.items），detail 时 lark-cli minutes +detail
    钉钉：dws minutes +search（数据在 data.minutes），detail 时 dws minutes +detail
    单渠道失败不影响整体，仅追加 note；未认证/无数据返回空列表 + note。

模块导入零副作用：不发网络请求、不建 DB 文件、不启动线程。
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta

from app.channel.dingtalk_client import _dws_cli_path
from app.channel.feishu_client import _lark_cli_path

TOOL_NAME = "minutes_search"
DEFAULT_PLATFORM = "both"
DEFAULT_DAYS = 7
MAX_DAYS = 90
MAX_ITEMS = 30
MAX_DETAIL = 5

# Windows 免弹黑框
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def _json_from(text: str) -> dict | None:
    """从 CLI 输出里尽力解析出一个 JSON 对象。"""
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 兼容 stdout 夹杂日志：截取首个 '{' 到最后一个 '}'
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                return None
        return None


def _run(cmd: list[str], timeout: int = 30) -> tuple[bool, dict | None, str]:
    """执行 CLI，返回 (ok, data_dict, error_msg)。"""
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", creationflags=_CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return False, None, f"CLI 超时 ({timeout}s)"
    except Exception as e:  # noqa: BLE001
        return False, None, str(e)

    out = (proc.stdout or "").strip() or (proc.stderr or "").strip()
    data = _json_from(out)
    if data is None:
        return False, None, f"非 JSON 输出: {(out or proc.stderr or '')[:200]}"

    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict):
            return False, data, err.get("message") or err.get("reason") or "CLI 返回错误"
        if data.get("ok") is False or data.get("success") is False:
            msg = data.get("message") or "CLI 调用失败"
            return False, data, str(msg)
    return True, data, ""


def _dws(*args, timeout: int = 30) -> tuple[bool, dict | None, str]:
    return _run([_dws_cli_path(), *args, "--format", "json"], timeout=timeout)


def _lark(*args, timeout: int = 30) -> tuple[bool, dict | None, str]:
    return _run([_lark_cli_path(), *args, "--json"], timeout=timeout)


def _first(d: dict, keys: list[str]) -> str:
    """按候选键顺序取第一个非空值。"""
    if not isinstance(d, dict):
        return ""
    for k in keys:
        v = d.get(k)
        if v:
            return str(v)
    return ""


def _feishu_authed() -> bool:
    """轻量检查飞书 user/bot 身份是否可用。"""
    ok, data, _ = _lark("auth", "status", timeout=10)
    if not ok or not isinstance(data, dict):
        return False
    idents = data.get("identities") or {}
    for ident in idents.values():
        if isinstance(ident, dict) and ident.get("status") == "ready":
            return True
    return False


def _feishu_search(query: str, start: str, end: str) -> tuple[list[dict], str]:
    """飞书妙记搜索，返回 (items, note)。"""
    if not _feishu_authed():
        return [], "飞书未认证，跳过妙记搜索。"
    args = ["minutes", "+search", "--start", start, "--end", end, "--page-size", "30"]
    if query:
        args += ["--query", query]
    ok, data, err = _lark(*args)
    if not ok or not isinstance(data, dict):
        return [], f"飞书妙记查询失败: {err}"
    items = (data.get("data") or {}).get("items") or []
    result: list[dict] = []
    for it in items[:MAX_ITEMS]:
        if not isinstance(it, dict):
            continue
        token = _first(it, ["minute_token", "token", "minuteToken", "url"])
        result.append({
            "platform": "feishu",
            "title": _first(it, ["title", "topic", "name"]) or "（无标题）",
            "time": _first(it, ["create_time", "start_time", "start_time_ms",
                                "createTime", "startTime"]),
            "source": "飞书妙记",
            "token": token,
            "summary": "",
        })
    note = "" if result else "飞书妙记未找到相关纪要。"
    return result, note


def _feishu_detail(token: str) -> str:
    """拉取一条飞书妙记的摘要。"""
    if not token:
        return ""
    ok, data, _ = _lark("minutes", "+detail", "--minute-tokens", token, "--summary")
    if not ok or not isinstance(data, dict):
        return ""
    return _extract_summary(data)


def _dingtalk_search(query: str, start: str, end: str) -> tuple[list[dict], str]:
    """钉钉听记搜索，返回 (items, note)。"""
    args = ["minutes", "+search", "--scope", "all", "--limit", str(MAX_ITEMS),
            "--start", start, "--end", end]
    if query:
        args += ["--query", query]
    ok, data, err = _dws(*args)
    if not ok or not isinstance(data, dict):
        return [], f"钉钉听记查询失败: {err}"
    minutes = (data.get("data") or {}).get("minutes") or []
    result: list[dict] = []
    for m in minutes[:MAX_ITEMS]:
        if not isinstance(m, dict):
            continue
        result.append({
            "platform": "dingtalk",
            "title": _first(m, ["title", "name", "subject"]) or "（无标题）",
            "time": _first(m, ["createTime", "startTime", "createdAt",
                               "create_time", "start_time"]),
            "source": "钉钉听记",
            "uuid": _first(m, ["taskUuid", "uuid", "id", "task_uuid"]),
            "summary": "",
        })
    note = "" if result else "钉钉听记未找到相关纪要。"
    return result, note


def _dingtalk_detail(uuid: str) -> str:
    """拉取一条钉钉听记的摘要。"""
    if not uuid:
        return ""
    ok, data, _ = _dws("minutes", "+detail", "--id", uuid, "--artifacts", "summary")
    if not ok or not isinstance(data, dict):
        return ""
    return _extract_summary(data)


def _extract_summary(data) -> str:
    """从 detail 返回里尽力挖出摘要文本。"""
    stack = [data]
    visited = 0
    while stack and visited < 200:
        visited += 1
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                if k.lower() in ("summary", "aisummary", "abstract") and isinstance(v, str) and v.strip():
                    return v.strip()
                if isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(cur, list):
            stack.extend(cur)
    return ""


def _rfc3339(dt: datetime) -> str:
    """本地时区 RFC3339 字符串（钉钉 +search 要求）。"""
    return dt.astimezone().replace(microsecond=0).isoformat()


def call_tool(args: dict) -> dict:
    """按 __tool_name 分发执行会议纪要检索。"""
    try:
        args = args or {}
        name = args.get("__tool_name") or TOOL_NAME
        if name != TOOL_NAME:
            return {"ok": False, "error": f"未知工具名: {name}"}

        if not args.get("__is_manager"):
            return {"ok": False, "error": "该工具仅管理者可用"}

        platform = (args.get("platform") or DEFAULT_PLATFORM).strip().lower()
        if platform not in ("feishu", "dingtalk", "both"):
            platform = DEFAULT_PLATFORM

        query = (args.get("query") or "").strip()
        try:
            days = int(args.get("days", DEFAULT_DAYS))
        except (TypeError, ValueError):
            days = DEFAULT_DAYS
        days = max(1, min(MAX_DAYS, days))
        detail = bool(args.get("detail"))

        now = datetime.now()
        # 飞书用 YYYY-MM-DD；钉钉用 RFC3339
        d_start = (now - timedelta(days=days)).strftime("%Y-%m-%d")
        d_end = now.strftime("%Y-%m-%d")
        r_start = _rfc3339(now - timedelta(days=days))
        r_end = _rfc3339(now)

        minutes: list[dict] = []
        notes: list[str] = []

        if platform in ("feishu", "both"):
            items, note = _feishu_search(query, d_start, d_end)
            minutes.extend(items)
            if note:
                notes.append(note)

        if platform in ("dingtalk", "both"):
            items, note = _dingtalk_search(query, r_start, r_end)
            minutes.extend(items)
            if note:
                notes.append(note)

        # 按时间倒序（时间字符串不可比时保持原序）
        minutes.sort(key=lambda x: x.get("time") or "", reverse=True)
        minutes = minutes[:MAX_ITEMS]

        if detail and minutes:
            for m in minutes[:MAX_DETAIL]:
                if m["platform"] == "feishu":
                    m["summary"] = _feishu_detail(m.get("token", ""))
                else:
                    m["summary"] = _dingtalk_detail(m.get("uuid", ""))

        return {
            "ok": True,
            "platform": platform,
            "query": query,
            "days": days,
            "detail": detail,
            "count": len(minutes),
            "minutes": minutes,
            "notes": notes,
        }
    except Exception as e:  # noqa: BLE001 —— 绝不把异常抛回 bridge
        return {"ok": False, "error": f"会议纪要检索失败: {e}"}
