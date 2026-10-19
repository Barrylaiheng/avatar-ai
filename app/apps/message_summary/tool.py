"""消息摘要助手 — tool 入口。

bridge 契约：
    call_tool(args: dict) -> dict
    args 注入：__tool_name / __agent_id / __is_manager / __credentials / __app_config
    - 必须按 args.get("__tool_name") 分发，本应用工具名固定为 "message_summary"
    - 返回值必须可 json 序列化，绝不抛异常给 bridge

功能：
    汇总某智能体（__agent_id）最近 hours 小时的渠道消息；
    focus 支持 urgent（只看紧急）/ todo（只看待办）/ brief（精简版）；
    有 LLM key 时用 LLM 提炼，无 key 或调用失败时退化为规则式提炼。

模块导入零副作用：不发网络请求、不建 DB 文件、不启动线程。
"""
from __future__ import annotations


TOOL_NAME = "message_summary"
DEFAULT_HOURS = 24
MAX_HOURS = 24 * 30
DEFAULT_LIMIT = 300

# 规则式提炼用的关键词（中英文混排兜底）
URGENT_KEYWORDS = [
    "紧急", "尽快", "马上", "立刻", "截止", "今天", "急", "重要", "务必",
    "asap", "urgent",
]
TODO_KEYWORDS = [
    "待办", "请", "需要", "麻烦", "记得", "安排", "确认", "回复",
    "跟进", "处理", "完成",
]


def _to_int(value, default: int) -> int:
    """宽松地把参数转 int，失败则用默认值。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _fmt_ts(ts) -> str:
    """把 epoch 秒格式化为 '月-日 时:分'，失败返回空串。"""
    try:
        import time as _t
        v = int(ts or 0)
        if v <= 0:
            return ""
        return _t.strftime("%m-%d %H:%M", _t.localtime(v))
    except Exception:  # noqa: BLE001
        return ""


def _load_messages(agent_id: str, hours: int, limit: int) -> list[dict]:
    """拉取该智能体最近 N 小时的全部渠道消息（user + assistant）。"""
    from app.storage import msg_dao
    return msg_dao.list_recent_by_agent(agent_id, hours=hours, limit=limit) or []


def _rule_summary(messages: list[dict], focus: str) -> tuple[str, list[dict]]:
    """规则式提炼：按关键词把消息分到紧急/待办/普通，返回 (文本, 高亮项)。"""
    urgents: list[dict] = []
    todos: list[dict] = []
    infos: list[dict] = []
    channels: set[str] = set()

    for m in messages:
        content = (m.get("content") or "").strip()
        if not content:
            continue
        ch = m.get("channel") or ""
        if ch:
            channels.add(ch)
        who = m.get("peer_name") or ("用户" if m.get("role") == "user" else "AI")
        ts = _fmt_ts(m.get("created_at"))
        item = {"who": who, "text": content[:120], "ts": ts, "channel": ch}
        low = content.lower()
        if any(k in content or k in low for k in URGENT_KEYWORDS):
            urgents.append({**item, "type": "urgent"})
        elif any(k in content or k in low for k in TODO_KEYWORDS):
            todos.append({**item, "type": "todo"})
        else:
            infos.append({**item, "type": "info"})

    total = len(messages)
    ch_str = "、".join(sorted(channels)) or "未知渠道"
    lines: list[str] = []

    if focus == "urgent":
        lines.append(f"最近消息中筛选出 {len(urgents)} 条紧急/重要内容（共 {total} 条，来源：{ch_str}）：")
        lines += [f"- [{i['ts']}] {i['who']}：{i['text']}" for i in urgents[:15]]
        if not urgents:
            lines.append("- 暂未发现明显紧急事项。")
        highlights = urgents[:15]
    elif focus == "todo":
        lines.append(f"最近消息中提炼出 {len(todos)} 条待办事项（共 {total} 条，来源：{ch_str}）：")
        lines += [f"- [{i['ts']}] {i['who']}：{i['text']}" for i in todos[:15]]
        if not todos:
            lines.append("- 暂未发现明确待办。")
        highlights = todos[:15]
    elif focus == "brief":
        lines.append(f"最近共 {total} 条消息（来源：{ch_str}），摘要如下：")
        recent = infos + urgents + todos
        lines += [f"- [{i['ts']}] {i['who']}：{i['text']}" for i in recent[:8]]
        highlights = recent[:8]
    else:
        lines.append(f"最近共 {total} 条消息（来源：{ch_str}）。")
        lines.append(f"- 紧急/重要 {len(urgents)} 条，待办 {len(todos)} 条。")
        for i in urgents[:5]:
            lines.append(f"- 【紧急】[{i['ts']}] {i['who']}：{i['text']}")
        for i in todos[:8]:
            lines.append(f"- 【待办】[{i['ts']}] {i['who']}：{i['text']}")
        highlights = (urgents + todos)[:15]

    return "\n".join(lines), highlights


def _llm_summary(messages: list[dict], focus: str, hours: int) -> str | None:
    """尝试用 LLM 提炼；无 key 或调用失败返回 None（由调用方退化到规则式）。"""
    try:
        from app.storage import llm_dao
        from app.storage.llm_provider import LLMProvider

        cfg = llm_dao.get_default()
        if not cfg or not cfg.get("api_key") or not cfg.get("base_url") or not cfg.get("model"):
            return None

        # 时间正序拼接消息（DB 返回为倒序）
        lines: list[str] = []
        for m in reversed(messages):
            content = (m.get("content") or "").strip().replace("\n", " ")
            if not content:
                continue
            who = m.get("peer_name") or ("用户" if m.get("role") == "user" else "AI")
            lines.append(f"[{_fmt_ts(m.get('created_at'))}] {who}: {content[:200]}")
        if not lines:
            return None

        focus_hint = {
            "urgent": "只提炼紧急、重要、需要立刻关注的事项，忽略日常寒暄。",
            "todo": "只提炼明确的待办事项（谁需要做什么、截止时间、跟进动作）。",
            "brief": "用最精简的方式概括，控制在 5 条以内。",
        }.get(focus, "既要有整体要点，也要点出紧急项和待办项。")

        system = (
            "你是企业消息摘要助手。请阅读用户提供的渠道聊天记录，"
            "输出中文要点式摘要，分点列出，不编造记录中不存在的信息。"
        )
        user_text = (
            f"下面是某智能体最近 {hours} 小时的渠道消息记录（时间正序）：\n\n"
            + "\n".join(lines)
            + f"\n\n摘要要求：{focus_hint}"
        )

        provider = LLMProvider.from_config(cfg)
        r = provider.chat(
            [{"role": "system", "content": system},
             {"role": "user", "content": user_text}],
            temperature=0.4,
        )
        if r.get("error"):
            return None
        text = (r.get("text") or "").strip()
        return text or None
    except Exception:  # noqa: BLE001 —— LLM 任意失败都退化到规则式
        return None


def call_tool(args: dict) -> dict:
    """按 __tool_name 分发执行消息汇总。"""
    try:
        args = args or {}
        name = args.get("__tool_name") or TOOL_NAME
        if name != TOOL_NAME:
            return {"ok": False, "error": f"未知工具名: {name}"}

        agent_id = (args.get("__agent_id") or "").strip()
        hours = max(1, min(MAX_HOURS, _to_int(args.get("hours"), DEFAULT_HOURS)))
        focus = (args.get("focus") or "").strip().lower()
        if focus not in ("urgent", "todo", "brief"):
            focus = ""

        if not agent_id:
            return {"ok": False, "error": "缺少 __agent_id，无法定位消息范围"}

        messages = _load_messages(agent_id, hours, DEFAULT_LIMIT)
        if not messages:
            return {
                "ok": True,
                "summary": f"最近 {hours} 小时内没有可汇总的消息。",
                "message_count": 0,
                "hours": hours,
                "focus": focus or "all",
                "engine": "rule",
                "highlights": [],
            }

        engine = "rule"
        summary = _llm_summary(messages, focus, hours)
        if summary:
            engine = "llm"
        rule_text, highlights = _rule_summary(messages, focus)
        if not summary:
            summary = rule_text

        return {
            "ok": True,
            "summary": summary,
            "highlights": highlights,
            "message_count": len(messages),
            "hours": hours,
            "focus": focus or "all",
            "engine": engine,
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"消息摘要失败: {e}"}
