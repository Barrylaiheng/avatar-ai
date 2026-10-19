"""审批待办汇总 — tool 入口。

bridge 契约：
    call_tool(args: dict) -> dict
    args 注入：__tool_name / __agent_id / __is_manager / __credentials / __app_config
    - 必须按 args.get("__tool_name") 分发，本应用工具名固定为 "approval_pending"
    - 返回值必须可 json 序列化，绝不抛异常给 bridge

功能：
    跨飞书 / 钉钉拉「待我审批」的任务清单并合并；platform 支持 feishu/dingtalk/both。
    单渠道未认证或调用失败时，只在该渠道返回中文 note，不影响另一渠道。

真实 CLI（本机已核验）：
    飞书：lark-cli approval tasks query --topic 1 --as user --page-all --json
    钉钉：dws oa approval list-pending --start <ISO> --end <ISO> --page 1 --limit 50 --format json

模块导入零副作用：不发网络请求、不建 DB 文件、不启动线程。
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta

from app.channel.feishu_client import _lark_cli_path
from app.channel.dingtalk_client import _dws_cli_path


TOOL_NAME = "approval_pending"
DEFAULT_PLATFORM = "both"
LOOKBACK_DAYS = 30          # 钉钉按时间范围查询，默认回看 30 天
CLI_TIMEOUT = 45            # 单次 CLI 调用超时（秒）

# 飞书审批实例状态码 → 中文
_FEISHU_STATUS = {
    "0": "未知",
    "1": "审批中",
    "2": "已通过",
    "3": "已拒绝",
    "4": "已撤销",
    "5": "已终止",
}


# ───────────────────────────────────────────────────────────
# CLI 调用基础设施
# ───────────────────────────────────────────────────────────

def _popen_kwargs() -> dict:
    """Windows 下隐藏子进程窗口，避免弹黑框（参考 app/storage/machine.py）。"""
    kw: dict = {}
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kw["startupinfo"] = si
        kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    return kw


def _parse_json(text: str):
    """解析 CLI 输出为 JSON。CLI 可能在 JSON 前打印日志行，做一次"截取首尾花括号"兜底。"""
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            return None
    return None


def _run_cli(cli: str, args: list, timeout: int = CLI_TIMEOUT) -> tuple:
    """调用 CLI，返回 (data_or_None, error_str)。不抛异常。"""
    cmd = [cli] + list(args)
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, **_popen_kwargs(),
        )
    except subprocess.TimeoutExpired:
        return None, f"CLI 超时（{timeout}s）"
    except Exception as e:  # noqa: BLE001
        return None, str(e)

    out = (proc.stdout or "").strip() or (proc.stderr or "").strip()
    if not out:
        return None, "CLI 无输出"
    data = _parse_json(out)
    if data is None:
        return None, f"非 JSON 输出：{out[:200]}"
    return data, ""


# ───────────────────────────────────────────────────────────
# 连接状态
# ───────────────────────────────────────────────────────────

def _feishu_ready(cli: str) -> bool:
    """飞书是否已认证：auth status 里任一身份可用即为已连接。"""
    data, _ = _run_cli(cli, ["auth", "status", "--json"], timeout=15)
    if not isinstance(data, dict):
        return False
    idents = data.get("identities") or {}
    for key in ("user", "bot"):
        ident = idents.get(key) or {}
        if ident.get("status") in ("ready", "needs_refresh") or ident.get("available"):
            return True
    return False


def _dingtalk_ready(cli: str) -> bool:
    """钉钉是否已认证：auth status 的 authenticated 为真。"""
    data, _ = _run_cli(cli, ["auth", "status", "--format", "json"], timeout=15)
    if not isinstance(data, dict):
        return False
    return bool(data.get("authenticated"))


# ───────────────────────────────────────────────────────────
# 飞书：待我审批
# ───────────────────────────────────────────────────────────

def _feishu_pending()-> tuple:
    """返回 (items, note)。note 非空表示该渠道不可用。"""
    cli = _lark_cli_path()
    if not _feishu_ready(cli):
        return [], "飞书未连接"

    data, err = _run_cli(
        cli,
        ["approval", "tasks", "query", "--topic", "1",
         "--as", "user", "--page-all", "--json"],
    )
    if not isinstance(data, dict):
        return [], f"飞书查询失败：{err or '返回异常'}"
    if data.get("ok") is False:
        e = data.get("error")
        msg = e.get("message") if isinstance(e, dict) else (e or "未知错误")
        return [], f"飞书查询失败：{msg}"

    tasks = ((data.get("data") or {}).get("tasks")) or []
    items: list = []
    for t in tasks:
        if not isinstance(t, dict):
            continue
        status_code = str(t.get("instance_status") or "")
        summaries = t.get("summaries") or []
        summary_txt = "；".join(
            f"{s.get('key', '')}:{s.get('value', '')}"
            for s in summaries
            if isinstance(s, dict) and s.get("value")
        )
        items.append({
            "platform": "feishu",
            "id": t.get("task_id") or t.get("instance_code") or "",
            "title": t.get("title") or t.get("definition_name") or "审批",
            "definition": t.get("definition_name") or "",
            "initiator": t.get("initiator_name") or "",
            "status": _FEISHU_STATUS.get(status_code, status_code),
            "summary": summary_txt,
            "link": t.get("link") or "",
        })
    return items, ""


# ───────────────────────────────────────────────────────────
# 钉钉：待我审批
# ───────────────────────────────────────────────────────────

def _iso_local(dt: datetime) -> str:
    """格式化为钉钉要求的 ISO-8601 北京时间。"""
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + "+08:00"


def _dingtalk_item(it: dict) -> dict:
    """把钉钉审批实例映射为统一结构（字段名做多路兼容）。"""
    return {
        "platform": "dingtalk",
        "id": (it.get("processInstanceId") or it.get("instanceId")
               or it.get("id") or ""),
        "title": (it.get("title") or it.get("instanceTitle") or it.get("name")
                  or it.get("processName") or "审批"),
        "definition": it.get("processName") or it.get("processCode") or "",
        "initiator": (it.get("originatorName") or it.get("originator")
                      or it.get("creatorName") or ""),
        "status": str(it.get("status") or it.get("instanceStatus") or ""),
        "summary": it.get("summary") or "",
        "link": it.get("url") or it.get("link") or it.get("detailUrl") or "",
        "create_time": it.get("createTime") or it.get("startTime") or "",
    }


def _dingtalk_pending() -> tuple:
    """返回 (items, note)。note 非空表示该渠道不可用。"""
    cli = _dws_cli_path()
    if not _dingtalk_ready(cli):
        return [], "钉钉未连接"

    now = datetime.now()
    start = now - timedelta(days=LOOKBACK_DAYS)
    data, err = _run_cli(
        cli,
        ["oa", "approval", "list-pending",
         "--start", _iso_local(start), "--end", _iso_local(now),
         "--page", "1", "--limit", "50", "--format", "json"],
    )
    if not isinstance(data, dict):
        return [], f"钉钉查询失败：{err or '返回异常'}"
    if data.get("success") is False or "error" in data:
        e = data.get("error")
        msg = e.get("message") if isinstance(e, dict) else (e or "未知错误")
        return [], f"钉钉查询失败：{msg}"

    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    raw = result.get("processInstanceList") or data.get("processInstanceList") or []
    items = [_dingtalk_item(it) for it in raw if isinstance(it, dict)]
    return items, ""


# ───────────────────────────────────────────────────────────
# 入口
# ───────────────────────────────────────────────────────────

def _summary_text(items: list, notes: list) -> str:
    """生成给 LLM / 用户看的中文摘要。"""
    if not items:
        base = "当前没有需要你处理的审批待办。"
    else:
        lines = [f"共 {len(items)} 条待你审批："]
        for it in items[:15]:
            who = f"（{it['initiator']}发起）" if it.get("initiator") else ""
            lines.append(f"- [{it['platform']}] {it['title']}{who} {it.get('status', '')}")
        base = "\n".join(lines)
    if notes:
        base += "\n提示：" + "；".join(notes)
    return base


def call_tool(args: dict) -> dict:
    """按 __tool_name 分发执行审批待办汇总。"""
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

        items: list = []
        notes: list = []

        if platform in ("feishu", "both"):
            try:
                feishu_items, note = _feishu_pending()
            except Exception as e:  # noqa: BLE001
                feishu_items, note = [], f"飞书查询失败：{e}"
            items.extend(feishu_items)
            if note:
                notes.append(note)

        if platform in ("dingtalk", "both"):
            try:
                ding_items, note = _dingtalk_pending()
            except Exception as e:  # noqa: BLE001
                ding_items, note = [], f"钉钉查询失败：{e}"
            items.extend(ding_items)
            if note:
                notes.append(note)

        return {
            "ok": True,
            "platform": platform,
            "count": len(items),
            "items": items,
            "notes": notes,
            "summary": _summary_text(items, notes),
        }
    except Exception as e:  # noqa: BLE001 —— 绝不把异常抛回 bridge
        return {"ok": False, "error": f"审批待办汇总失败: {e}"}
