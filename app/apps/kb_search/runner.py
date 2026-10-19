"""知识库检索应用 — runner 入口。

runner_fn 契约：run(context: dict | None = None, **kwargs)
    - context 可含 query / top_k / kb_id，以及 bridge 注入的 __tool_name / __agent_id 等
    - 复用 tool.call_tool 的同一套逻辑，供后台任务 / 调试直接调用
    - 全流程异常兜底，返回可 json 序列化的 dict
"""
from __future__ import annotations

from app.apps.kb_search.tool import call_tool


def run(context: dict | None = None, **kwargs) -> dict:
    """执行一次知识库检索。

    context 里的 query 用于本次检索；kwargs 中非 None 的键会合并进 context。
    """
    try:
        ctx = dict(context or {})
        ctx.update({k: v for k, v in kwargs.items() if v is not None})
        ctx.setdefault("__tool_name", "kb_search")
        return call_tool(ctx)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"runner 执行失败: {e}"}
