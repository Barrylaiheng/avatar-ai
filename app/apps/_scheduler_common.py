# -*- coding: utf-8 -*-
"""应用市场 · 公共定时调度器（原版日志前缀 [SchedulerCommon]）。

所有需要「定时任务」能力的应用共用这一个模块（原版称谓「公共轮询线程」）：
  - 全进程只启动一个后台轮询线程（幂等，多次 ensure_scheduler() 只会起一个）
  - 周期扫描 scheduled_job 表（enabled=1 且 next_run_at<=now）执行到期任务，每分钟一次
  - 优先用 APScheduler 后台调度器驱动；任一环节失败即退回原生守护线程（双路径，不因依赖缺失而失效）
  - 标准库实现 cron 解析（分/时/日/月/周；支持 * / 数字 / 逗号列表 / 范围 a-b / 步进 */n）
  - 时区固定 Asia/Shanghai（UTC+8，中国无夏令时），不依赖 pytz / zoneinfo
  - 到期任务渲染 content_template 后按 target_json 的 channel/peer_id/peer_type 发送

日志模板与原版对齐：公共轮询线程已启动 / ✅·❌ 每任务结果 / job <id> tick 异常。
导入本模块本身不产生任何副作用：不建数据库连接、不起线程、不发网络请求。
连接/线程动作全部推迟到函数体内。
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone

from app.storage.db import get_conn, new_id, now_ts

__all__ = [
    "ensure_scheduler",
    "register_job",
    "refresh_all_jobs",
    "send_reply",
]

# Asia/Shanghai = 固定 UTC+8（中国自 1991 年起无夏令时）
_TZ_SHANGHAI = timezone(timedelta(hours=8))

# 轮询间隔（秒）：定时消息粒度到分钟，与原版一致——每分钟扫一次 cron
_POLL_INTERVAL_SEC = 60.0

# 计算 next_run_at 时最多向前扫描的分钟数（约 400 天，覆盖 2/29 这类罕见 cron）
_MAX_SCAN_MINUTES = 400 * 24 * 60

# 退出/启动守卫
_START_LOCK = threading.Lock()
_STARTED = False

# 内存调度表（refresh_all_jobs 重建）
_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()


# ============================================================
# cron 解析（仅标准库）
# ============================================================

def _parse_field(field: str, lo: int, hi: int) -> set[int]:
    """解析单个 cron 字段为匹配值集合。

    支持：* / 单个数字 / 逗号列表 a,b,c / 范围 a-b / 步进 */n / a-b/n / a/n。
    """
    values: set[int] = set()
    for part in str(field).split(","):
        part = part.strip()
        if not part:
            continue
        step = 1
        base = part
        if "/" in part:
            base, _, step_s = part.partition("/")
            try:
                step = int(step_s)
            except ValueError:
                step = 1
            if step <= 0:
                step = 1
        base = base.strip()
        if base == "*" or base == "":
            start, end = lo, hi
        elif "-" in base:
            a, _, b = base.partition("-")
            start, end = int(a), int(b)
        else:
            start = end = int(base)
        for v in range(start, end + 1, step):
            if lo <= v <= hi:
                values.add(v)
    return values


def _cron_fields(expr: str) -> list[str] | None:
    fields = str(expr or "").split()
    if len(fields) != 5:
        return None
    return fields


def _valid_cron(expr: str) -> bool:
    """校验 5 字段 cron 表达式是否合法。"""
    fields = _cron_fields(expr)
    if not fields:
        return False
    bounds = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]
    for field, (lo, hi) in zip(fields, bounds):
        try:
            if not _parse_field(field, lo, hi):
                return False
        except (ValueError, TypeError):
            return False
    return True


def _match_cron(expr: str, dt: datetime) -> bool:
    """判断 dt（Asia/Shanghai）是否命中 5 字段 cron。"""
    fields = _cron_fields(expr)
    if not fields:
        return False
    minute_f, hour_f, dom_f, month_f, dow_f = fields
    if dt.minute not in _parse_field(minute_f, 0, 59):
        return False
    if dt.hour not in _parse_field(hour_f, 0, 23):
        return False
    if dt.month not in _parse_field(month_f, 1, 12):
        return False

    dom_restricted = dom_f.strip() != "*"
    dow_restricted = dow_f.strip() != "*"
    dom_match = dt.day in _parse_field(dom_f, 1, 31)
    # cron 的周：0=周日..6=周六，7 也代表周日；python weekday() 周一=0..周日=6
    dow_set = {0 if v == 7 else v for v in _parse_field(dow_f, 0, 7)}
    cron_dow = (dt.weekday() + 1) % 7
    dow_match = cron_dow in dow_set

    # 标准 cron 语义：日/周同时受限时取「或」，否则受限的那个生效
    if dom_restricted and dow_restricted:
        if not (dom_match or dow_match):
            return False
    elif dom_restricted:
        if not dom_match:
            return False
    elif dow_restricted:
        if not dow_match:
            return False
    return True


def _compute_next_run(expr: str, after_epoch: float | None = None) -> int | None:
    """计算 expr 的下一次触发时刻（epoch 秒）；扫描上限内无解返回 None。"""
    base = time.time() if after_epoch is None else after_epoch
    dt = datetime.fromtimestamp(base, tz=_TZ_SHANGHAI)
    # 从下一整分钟开始扫
    dt = dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(_MAX_SCAN_MINUTES):
        if _match_cron(expr, dt):
            return int(dt.timestamp())
        dt += timedelta(minutes=1)
    return None


# ============================================================
# 内存调度表
# ============================================================

def _parse_target(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        val = json.loads(raw)
        return val if isinstance(val, dict) else {}
    except Exception:
        return {}


def refresh_all_jobs(agent_id: str = "", app_id: str = "") -> list[dict]:
    """从 DB 重载全部启用任务，重建内存调度表。返回任务列表。"""
    conn = get_conn()
    sql = "SELECT * FROM scheduled_job WHERE enabled=1"
    params: list = []
    if app_id:
        sql += " AND app_id=?"
        params.append(app_id)
    if agent_id:
        sql += " AND agent_id=?"
        params.append(agent_id)
    rows = conn.execute(sql, params).fetchall()
    jobs: list[dict] = []
    for r in rows:
        d = dict(r)
        d["target"] = _parse_target(d.get("target_json"))
        jobs.append(d)
    with _JOBS_LOCK:
        _JOBS.clear()
        _JOBS.update({j["job_id"]: j for j in jobs})
    return jobs


# ============================================================
# 任务注册
# ============================================================

def register_job(job_id: str, cron_expr: str, name: str, agent_id: str,
                 app_id: str = "", content_template: str = "",
                 target: dict | str | None = None,
                 timezone: str = "Asia/Shanghai") -> dict:
    """写入/更新一条 scheduled_job，并计算 next_run_at。

    非法 cron 抛 ValueError（调用方自行捕获转成友好返回）。
    返回 {"ok": True, "job_id": ..., "next_run_at": ...}。
    """
    expr = str(cron_expr or "").strip()
    if not _valid_cron(expr):
        raise ValueError(f"非法 cron 表达式: {cron_expr!r}")
    if not job_id:
        job_id = new_id("job")

    nxt = _compute_next_run(expr)
    if isinstance(target, str):
        target_json = target or "{}"
    else:
        target_json = json.dumps(target or {}, ensure_ascii=False)

    conn = get_conn()
    ts = now_ts()
    conn.execute(
        """INSERT INTO scheduled_job
           (job_id, app_id, agent_id, name, cron_expr, content_template, target_json,
            timezone, enabled, last_run_at, next_run_at, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(job_id) DO UPDATE SET
             app_id=excluded.app_id, agent_id=excluded.agent_id, name=excluded.name,
             cron_expr=excluded.cron_expr, content_template=excluded.content_template,
             target_json=excluded.target_json, timezone=excluded.timezone,
             enabled=excluded.enabled, next_run_at=excluded.next_run_at,
             updated_at=excluded.updated_at""",
        (job_id, app_id, agent_id, name or "", expr, content_template or "",
         target_json, timezone or "Asia/Shanghai", 1, None, nxt, ts, ts),
    )
    conn.commit()
    return {"ok": True, "job_id": job_id, "next_run_at": nxt}


# ============================================================
# 模板占位符
# ============================================================

def _safe_daily_earnings() -> str:
    """尝试取当日 CPS 佣金汇总（好单库）；拿不到就返回空串（绝不抛异常）。"""
    try:
        from app.storage import app_credential_dao
        cred = app_credential_dao.get("haodanku_api_key") or {}
        api_key = (cred.get("value") or "").strip()
        if not api_key:
            return ""
        from app.apps.cps_selector.tool import call_tool as _cps_call
        res = _cps_call({
            "__tool_name": "cps_earnings",
            "__is_manager": True,
            "__credentials": {"haodanku_api_key": api_key},
            "mode": "summary",
            "days": 1,
        })
        if isinstance(res, dict) and res.get("ok"):
            note = res.get("note")
            if note:
                return str(note)
            summary = res.get("summary")
            if isinstance(summary, dict):
                return (f"预估佣金 ¥{summary.get('predict_money', 0)}，"
                        f"已结算 ¥{summary.get('settled_money', 0)}")
    except Exception:
        pass
    return ""


def _fill_template(text: str, **ctx) -> str:
    """替换占位符 {now} / {today} / {get_daily_earnings}。

    可用 ctx 覆盖：now / today / get_daily_earnings。
    取不到的值用空串填充，绝不抛异常。
    """
    if not text:
        return ""
    out = str(text)
    now_val = ctx.get("now") or datetime.now(_TZ_SHANGHAI).strftime("%Y-%m-%d %H:%M:%S")
    today_val = ctx.get("today") or datetime.now(_TZ_SHANGHAI).strftime("%Y-%m-%d")
    out = out.replace("{now}", str(now_val))
    out = out.replace("{today}", str(today_val))
    if "{get_daily_earnings}" in out:
        earnings = ctx.get("get_daily_earnings")
        if earnings is None:
            earnings = _safe_daily_earnings()
        out = out.replace("{get_daily_earnings}", str(earnings if earnings is not None else ""))
    return out


# ============================================================
# 发送与执行
# ============================================================

def send_reply(channel: str, peer_id: str, content: str,
               peer_type: str = "friend") -> tuple[bool, str | None]:
    """统一发送消息（供调度器与 tool 复用）。

    微信走风控串行锁；其他组织内渠道直发。返回 (ok, err)。
    实际实现由 schedule_message.tool.send_reply 提供，这里懒加载避免循环依赖。
    """
    try:
        from app.apps.schedule_message.tool import send_reply as _impl
    except Exception as e:
        return False, f"send_reply 不可用: {e}"
    try:
        ok, err = _impl(channel, peer_id, content, peer_type)
        return bool(ok), (err or None)
    except Exception as e:
        return False, str(e)


def _run_job(job: dict, now: int) -> None:
    """执行一条到期任务并推进 next_run_at。"""
    job_id = job.get("job_id", "")
    expr = job.get("cron_expr", "")
    content = _fill_template(job.get("content_template") or "")
    target = job.get("target") or {}
    channel = target.get("channel", "")
    peer_id = target.get("peer_id", "")
    peer_type = target.get("peer_type", "friend") or "friend"

    ok, err = send_reply(channel, peer_id, content, peer_type)
    # 日志模板与原版对齐：成功打结果 dict，失败打「执行失败: <err>」
    result = {"ok": bool(ok), "channel": channel, "peer_id": peer_id, "error": err or None}
    app_id = job.get("app_id", "")
    if ok:
        print(f"[SchedulerCommon] ✅ app={app_id} job={job_id}: {result}", flush=True)
    else:
        print(f"[SchedulerCommon] ❌ app={app_id} job={job_id} 执行失败: {err}", flush=True)

    nxt = _compute_next_run(expr)
    conn = get_conn()
    try:
        if nxt is None:
            # 非法/不可解析的 cron → 停用，避免每个 tick 反复触发
            conn.execute(
                "UPDATE scheduled_job SET last_run_at=?, enabled=0, updated_at=? WHERE job_id=?",
                (now, now, job_id),
            )
        else:
            conn.execute(
                "UPDATE scheduled_job SET last_run_at=?, next_run_at=?, updated_at=? WHERE job_id=?",
                (now, nxt, now, job_id),
            )
        conn.commit()
    except Exception as e:
        print(f"[SchedulerCommon] job {job_id} 状态更新失败: {e}", flush=True)


def _reschedule_only(job: dict, now: int) -> None:
    """任务缺 next_run_at（外部直插）时补算一次。"""
    nxt = _compute_next_run(job.get("cron_expr", ""))
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE scheduled_job SET next_run_at=?, updated_at=? WHERE job_id=?",
            (nxt, now, job.get("job_id", "")),
        )
        conn.commit()
    except Exception as e:
        print(f"[SchedulerCommon] job {job.get('job_id', '')} 补算 next_run_at 失败: {e}", flush=True)


def _tick() -> None:
    """一轮扫描：重建调度表 + 执行到期任务。单任务异常只告警，不影响其他任务。"""
    jobs = refresh_all_jobs()
    now = now_ts()
    for job in jobs:
        job_id = job.get("job_id", "")
        nxt = job.get("next_run_at")
        if nxt is None:
            _reschedule_only(job, now)
            continue
        try:
            due = int(nxt) <= now
        except (TypeError, ValueError):
            due = False
        if not due:
            continue
        try:
            _run_job(job, now)
        except Exception as e:
            print(f"[SchedulerCommon] job {job_id} tick 异常: {e}", flush=True)


def _loop() -> None:
    while True:
        try:
            _tick()
        except Exception as e:
            print(f"[SchedulerCommon] 轮询 tick 异常: {e}", flush=True)
        time.sleep(_POLL_INTERVAL_SEC)


# APScheduler 后台调度器实例（活着就行，模块级持有防止被 GC）
_APS_SCHED = None


def _start_backend() -> str:
    """启动轮询后端：优先 APScheduler，任一环节失败退回原生守护线程。返回后端名。"""
    global _APS_SCHED
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        sched = BackgroundScheduler(timezone=_TZ_SHANGHAI)
        sched.add_job(_tick, "interval", seconds=_POLL_INTERVAL_SEC, id="scheduler_common")
        sched.start()
        _APS_SCHED = sched
        return "apscheduler"
    except Exception:
        threading.Thread(target=_loop, name="SchedulerCommon", daemon=True).start()
        return "thread"


def ensure_scheduler() -> bool:
    """惰性启动公共轮询线程（全进程幂等）。返回是否已启动/在运行。"""
    global _STARTED
    with _START_LOCK:
        if _STARTED:
            return True
        _STARTED = True
    _start_backend()
    print("[SchedulerCommon] 公共轮询线程已启动", flush=True)
    return True
