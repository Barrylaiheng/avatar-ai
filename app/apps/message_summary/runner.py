"""消息摘要助手 — runner 入口。

runner_fn 契约：run(context: dict | None = None, **kwargs)
    - context 可含 agent_id / hours / focus，以及 bridge 注入的 __agent_id 等
    - 复用 tool.call_tool 的同一套逻辑，供后台任务 / 调试直接调用
    - 全流程异常兜底，返回可 json 序列化的 dict
"""
from __future__ import annotations

from app.apps.message_summary.tool import call_tool


def run(context: dict | None = None, **kwargs) -> dict:
    """执行一次消息汇总。

    context 里若有 agent_id，会同时映射到 __agent_id（bridge 契约字段）。
    """
    try:
        ctx = dict(context or {})
        ctx.update({k: v for k, v in kwargs.items() if v is not None})
        if ctx.get("agent_id") and not ctx.get("__agent_id"):
            ctx["__agent_id"] = ctx["agent_id"]
        ctx.setdefault("__tool_name", "message_summary")
        return call_tool(ctx)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"runner 执行失败: {e}"}
