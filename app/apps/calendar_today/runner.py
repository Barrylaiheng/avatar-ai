"""今日日程 — runner 入口。

runner_fn 契约：run(context: dict | None = None, **kwargs)
    - context 可含 platform / days，以及 bridge 注入的 __is_manager 等
    - 复用 tool.call_tool 的同一套逻辑，供后台任务 / 调试直接调用
    - 全流程异常兜底，返回可 json 序列化的 dict
"""
from __future__ import annotations

from app.apps.calendar_today.tool import call_tool


def run(context: dict | None = None, **kwargs) -> dict:
    """执行一次今日日程查询。"""
    try:
        ctx = dict(context or {})
        ctx.update({k: v for k, v in kwargs.items() if v is not None})
        ctx.setdefault("__tool_name", "calendar_today")
        if "is_manager" in ctx and "__is_manager" not in ctx:
            ctx["__is_manager"] = ctx["is_manager"]
        return call_tool(ctx)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"runner 执行失败: {e}"}
