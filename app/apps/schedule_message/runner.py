# -*- coding: utf-8 -*-
"""定时发送应用 —— runner 入口。

【双受众声明】audience = "manager"（管理者专属）。

bridge 启动时会 `from app.apps.schedule_message.runner import start_scheduler`
并调用 `start_scheduler()`（bridge.py 第 325-326 行），本模块负责把公共调度器拉起来。
"""
from __future__ import annotations

from app.apps._scheduler_common import (
    ensure_scheduler as _ensure_scheduler,
    refresh_all_jobs,
    register_job,
    _fill_template,
)
from app.apps.schedule_message.tool import call_tool

# 显式 re-export（供 mcp 生成的其它 scheduler 应用 / 其它模块复用）
__all__ = [
    "start_scheduler",
    "run",
    "register_job",
    "refresh_all_jobs",
    "_fill_template",
    "call_tool",
]


def start_scheduler(context: dict | None = None, **kwargs) -> dict:
    """启动公共调度器并重载全部任务。

    签名兼容 bridge 的两种调用：
      - bridge.start_channel_modules(): start_scheduler()
      - bridge._handle_run_app_once(): start_scheduler(context)
    返回状态 dict（bridge run_app_once 会读 items，这里为空）。

    日志模板与原版对齐（[Schedule] 前缀）：
      后台轮询线程已启动，每分钟扫一次 cron → DB 恢复 <N> 个定时任务 → 轮询循环启动；
      apscheduler 缺失时补一条 ⚠️ 提示（此时由 _scheduler_common 的原生线程兜底，功能仍可用）。
    """
    try:
        from apscheduler.schedulers.background import BackgroundScheduler  # noqa: F401
    except Exception:
        print("[Schedule] ⚠️ apscheduler 未安装，定时功能不可用。pip install apscheduler", flush=True)

    print("[Schedule] 后台轮询线程已启动，每分钟扫一次 cron", flush=True)

    _ensure_scheduler()

    try:
        jobs = refresh_all_jobs()
        print(f"[Schedule] DB 恢复 {len(jobs)} 个定时任务", flush=True)
    except Exception as e:
        print(f"[Schedule] refresh_all_jobs 失败: {e}", flush=True)

    print("[Schedule] 轮询循环启动", flush=True)
    return {"ok": True, "app_id": "schedule_message", "started": True, "items": []}


def run(context: dict | None = None, **kwargs) -> dict:
    """手动「立即运行」入口（bridge run_app_once 调）。"""
    args = (context or {}).get("args", kwargs) or kwargs
    return call_tool(args)
