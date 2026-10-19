"""跨渠道找人 — tool 入口。

bridge 契约：
    call_tool(args: dict) -> dict
    args 注入：__tool_name / __agent_id / __is_manager / __credentials / __app_config
    - 必须按 args.get("__tool_name") 分发，本应用工具名固定为 "contact_search"
    - 返回值必须可 json 序列化，绝不抛异常给 bridge

功能：
    按姓名/关键字在飞书与钉钉通讯录里模糊找人（platform=feishu/dingtalk/both），
    结果含姓名 / 部门 / 职位 / 渠道 / open_id（有则给）。
    单渠道未认证或调用失败时，只在该渠道返回中文 note，不影响另一渠道。

真实 CLI（本机已核验）：
    飞书：lark-cli contact +search-user --query <kw> --as user --json
          → data.users[]：open_id / localized_name / department / email
    钉钉：dws contact user search --query <kw> --format json
          → result[]：name / title（职位）/ openDingTalkId / userId
          再用 dws contact user get --ids <id,id> --format json 补部门
          → result[].orgEmployeeModel.depts[] / orgTitle

模块导入零副作用：不发网络请求、不建 DB 文件、不启动线程。
"""
from __future__ import annotations

import json
import os
import subprocess

from app.channel.feishu_client import _lark_cli_path
from app.channel.dingtalk_client import _dws_cli_path


TOOL_NAME = "contact_search"
DEFAULT_PLATFORM = "both"
MAX_RESULTS = 20            # 单渠道最多返回条数
CLI_TIMEOUT = 30            # 单次 CLI 调用超时（秒）


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
    """解析 CLI 输出为 JSON；JSON 前可能有日志行，做截取兜底。"""
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
# 飞书：通讯录搜索
# ───────────────────────────────────────────────────────────

def _feishu_search(keyword: str) -> tuple:
    """返回 (results, note)。note 非空表示该渠道不可用。"""
    cli = _lark_cli_path()
    if not _feishu_ready(cli):
        return [], "飞书未连接"

    data, err = _run_cli(
        cli,
        ["contact", "+search-user", "--query", keyword, "--as", "user", "--json"],
    )
    if not isinstance(data, dict):
        return [], f"飞书查询失败：{err or '返回异常'}"
    if data.get("ok") is False:
        e = data.get("error")
        msg = e.get("message") if isinstance(e, dict) else (e or "未知错误")
        return [], f"飞书查询失败：{msg}"

    users = ((data.get("data") or {}).get("users")) or []
    results: list = []
    for u in users:
        if not isinstance(u, dict):
            continue
        results.append({
            "name": u.get("localized_name") or u.get("name") or "",
            "department": u.get("department") or "",
            "position": u.get("position") or "",
            "platform": "feishu",
            "open_id": u.get("open_id") or "",
            "email": u.get("enterprise_email") or u.get("email") or "",
        })
        if len(results) >= MAX_RESULTS:
            break
    return results, ""


# ───────────────────────────────────────────────────────────
# 钉钉：通讯录搜索
# ───────────────────────────────────────────────────────────

def _dingtalk_search(keyword: str) -> tuple:
    """返回 (results, note)。note 非空表示该渠道不可用。"""
    cli = _dws_cli_path()
    if not _dingtalk_ready(cli):
        return [], "钉钉未连接"

    data, err = _run_cli(
        cli,
        ["contact", "user", "search", "--query", keyword, "--format", "json"],
    )
    if not isinstance(data, dict):
        return [], f"钉钉查询失败：{err or '返回异常'}"
    if data.get("success") is False or "error" in data:
        e = data.get("error")
        msg = e.get("message") if isinstance(e, dict) else (e or "未知错误")
        return [], f"钉钉查询失败：{msg}"

    users = data.get("result") or []
    if not isinstance(users, list):
        return [], ""

    # 批量补部门：一次 contact user get 拿所有命中的 userId
    user_ids = [str(u.get("userId")) for u in users
                if isinstance(u, dict) and u.get("userId")]
    dept_map = _dingtalk_dept_map(cli, user_ids)

    results: list = []
    for u in users:
        if not isinstance(u, dict):
            continue
        uid = str(u.get("userId") or "")
        results.append({
            "name": u.get("name") or u.get("nick") or "",
            "department": dept_map.get(uid, ""),
            "position": u.get("title") or "",
            "platform": "dingtalk",
            "open_id": u.get("openDingTalkId") or "",
            "email": "",
        })
        if len(results) >= MAX_RESULTS:
            break
    return results, ""


def _dingtalk_dept_map(cli: str, user_ids: list) -> dict:
    """批量取 userId → 部门名称。失败时返回空映射（部门"有则给"）。"""
    if not user_ids:
        return {}
    data, _ = _run_cli(
        cli,
        ["contact", "user", "get", "--ids", ",".join(user_ids), "--format", "json"],
    )
    if not isinstance(data, dict):
        return {}
    arr = data.get("result") or []
    if not isinstance(arr, list):
        return {}
    mapping: dict = {}
    for item in arr:
        if not isinstance(item, dict):
            continue
        model = item.get("orgEmployeeModel") or {}
        uid = str(model.get("orgUserId") or "")
        if not uid:
            continue
        depts = model.get("depts") or []
        names = [d.get("deptName", "") for d in depts
                 if isinstance(d, dict) and d.get("deptName")]
        mapping[uid] = "、".join(names)
    return mapping


# ───────────────────────────────────────────────────────────
# 入口
# ───────────────────────────────────────────────────────────

def _summary_text(keyword: str, results: list, notes: list) -> str:
    """生成给 LLM / 用户看的中文摘要。"""
    if not results:
        base = f"未找到与「{keyword}」匹配的联系人。"
    else:
        lines = [f"找到 {len(results)} 位与「{keyword}」匹配的同事："]
        for r in results[:15]:
            dept = f"（{r['department']}）" if r.get("department") else ""
            pos = f" {r['position']}" if r.get("position") else ""
            lines.append(f"- [{r['platform']}] {r['name']}{dept}{pos}")
        base = "\n".join(lines)
    if notes:
        base += "\n提示：" + "；".join(notes)
    return base


def call_tool(args: dict) -> dict:
    """按 __tool_name 分发执行通讯录搜索。"""
    try:
        args = args or {}
        name = args.get("__tool_name") or TOOL_NAME
        if name != TOOL_NAME:
            return {"ok": False, "error": f"未知工具名: {name}"}

        if not args.get("__is_manager"):
            return {"ok": False, "error": "该工具仅管理者可用"}

        keyword = (args.get("keyword") or "").strip()
        if not keyword:
            return {"ok": False, "error": "缺少 keyword 参数"}

        platform = (args.get("platform") or DEFAULT_PLATFORM).strip().lower()
        if platform not in ("feishu", "dingtalk", "both"):
            platform = DEFAULT_PLATFORM

        results: list = []
        notes: list = []

        if platform in ("feishu", "both"):
            try:
                feishu_res, note = _feishu_search(keyword)
            except Exception as e:  # noqa: BLE001
                feishu_res, note = [], f"飞书查询失败：{e}"
            results.extend(feishu_res)
            if note:
                notes.append(note)

        if platform in ("dingtalk", "both"):
            try:
                ding_res, note = _dingtalk_search(keyword)
            except Exception as e:  # noqa: BLE001
                ding_res, note = [], f"钉钉查询失败：{e}"
            results.extend(ding_res)
            if note:
                notes.append(note)

        return {
            "ok": True,
            "keyword": keyword,
            "platform": platform,
            "count": len(results),
            "results": results,
            "notes": notes,
            "summary": _summary_text(keyword, results, notes),
        }
    except Exception as e:  # noqa: BLE001 —— 绝不把异常抛回 bridge
        return {"ok": False, "error": f"通讯录搜索失败: {e}"}
