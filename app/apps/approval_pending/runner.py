"""审批待办汇总 — runner 入口。

runner_fn 契约：run(context: dict | None = None, **kwargs)
    - context 可含 platform，以及 bridge 注入的 __tool_name / __is_manager / __agent_id 等
    - 复用 tool.call_tool 的同一套逻辑，供后台任务 / 调试直接调用
    - 全流程异常兜底，返回可 json 序列化的 dict
"""
from __future__ import annotations

from app.apps.approval_pending.tool import call_tool


def run(context: dict | None = None, **kwargs) -> dict:
    """执行一次审批待办汇总。"""
    try:
        ctx = dict(context or {})
        ctx.update({k: v for k, v in kwargs.items() if v is not None})
        ctx.setdefault("__tool_name", "approval_pending")
        return call_tool(ctx)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"runner 执行失败: {e}"}
