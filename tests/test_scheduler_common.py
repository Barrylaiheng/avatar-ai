# -*- coding: utf-8 -*-
"""调度器对齐 + 机器码超时修复 的验收测试。

覆盖：
  A. _scheduler_common：cron 解析 / register_job / tick 到期执行 / 失败与异常分支 /
     日志模板与原版一致（[SchedulerCommon]）/ 双后端（APScheduler 与原生线程兜底）
  B. schedule_message.runner：日志模板与原版一致（[Schedule]）
  C. storage.machine：_run_powershell 超时放宽到 20s 后，>5s 的命令不再降级；机器码格式正确

运行：venv\\Scripts\\python.exe tests\\test_scheduler_common.py
"""
from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 隔离 DB：SCAI_APP_DIR 必须在 import app.storage.db 之前设好
tmp = Path(tempfile.mkdtemp(prefix="avatar_sched_test_"))
os.environ["SCAI_APP_DIR"] = str(tmp)

from app.apps import _scheduler_common as SC  # noqa: E402
from app.apps.schedule_message import runner as RUNNER  # noqa: E402
from app.storage import db as DB  # noqa: E402
from app.storage import machine as MC  # noqa: E402


def _capture(fn, *args, **kwargs):
    """跑 fn 并返回 (返回值, stdout 文本)。"""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ret = fn(*args, **kwargs)
    return ret, buf.getvalue()


def _insert_agent(agent_id: str = "ag_test") -> None:
    ts = int(time.time())
    DB.get_conn().execute(
        "INSERT OR REPLACE INTO ai_agent (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (agent_id, "调度测试智能体", ts, ts),
    )
    DB.get_conn().commit()


def _make_due(job_id: str) -> None:
    DB.get_conn().execute(
        "UPDATE scheduled_job SET next_run_at=? WHERE job_id=?", (int(time.time()) - 10, job_id)
    )
    DB.get_conn().commit()


def test_cron_parsing():
    assert SC._valid_cron("* * * * *")
    assert SC._valid_cron("*/5 9-18 * * 1-5")
    assert not SC._valid_cron("bad")
    assert not SC._valid_cron("0 0 * *")  # 只有 4 段
    assert SC._parse_field("*/15", 0, 59) == {0, 15, 30, 45}
    assert SC._parse_field("1,5-7", 0, 59) == {1, 5, 6, 7}
    nxt = SC._compute_next_run("* * * * *")
    assert nxt is not None and 0 < nxt - time.time() <= 120, f"next_run 异常: {nxt}"
    # 非法 cron 不应算出结果
    assert SC._compute_next_run("not a cron") is None
    print("[ok] A1. cron 解析/校验/下次触发计算 全部正确")


def test_register_job():
    _insert_agent()
    ret, _ = _capture(
        SC.register_job, "job_reg", "*/5 * * * *", "每5分钟", "ag_test",
        app_id="schedule_message", content_template="hi {today}",
        target={"channel": "wcf", "peer_id": "wxid_reg", "peer_type": "friend"},
    )
    assert ret["ok"] and ret["next_run_at"] > time.time()
    row = DB.get_conn().execute("SELECT * FROM scheduled_job WHERE job_id='job_reg'").fetchone()
    assert row is not None and row["app_id"] == "schedule_message" and row["enabled"] == 1
    # 非法 cron 必须抛 ValueError
    try:
        SC.register_job("job_bad", "nope", "坏", "ag_test")
        raise AssertionError("非法 cron 未抛错")
    except ValueError as e:
        assert "非法 cron" in str(e)
    print("[ok] A2. register_job：入库 + next_run_at 计算 + 非法 cron 拦截")


def test_tick_success_and_logs():
    _insert_agent()
    sent: list = []

    def fake_send(channel, peer_id, content, peer_type="friend"):
        sent.append((channel, peer_id, content, peer_type))
        return True, None

    orig_send = SC.send_reply
    SC.send_reply = fake_send
    try:
        _capture(SC.register_job, "job_ok", "* * * * *", "每分钟", "ag_test",
                 app_id="schedule_message", content_template="日报 {today}",
                 target={"channel": "wcf", "peer_id": "wxid_ok"})
        _make_due("job_ok")
        _, out = _capture(SC._tick)
    finally:
        SC.send_reply = orig_send

    assert len(sent) == 1, f"应发出 1 条，实际 {len(sent)}"
    ch, pid, content, ptype = sent[0]
    assert ch == "wcf" and pid == "wxid_ok" and ptype == "friend"
    assert "{today}" not in content and "{now}" not in content, "占位符未渲染"
    assert time.strftime("%Y-%m-%d") in content
    assert "[SchedulerCommon] ✅ app=schedule_message job=job_ok:" in out, f"日志模板不符: {out!r}"
    row = DB.get_conn().execute("SELECT * FROM scheduled_job WHERE job_id='job_ok'").fetchone()
    assert row["next_run_at"] > time.time(), "next_run_at 未推进"
    assert row["last_run_at"] is not None
    print("[ok] A3. tick 到期执行：发送 + 模板渲染 + next_run_at 推进 + ✅ 日志模板一致")


def test_tick_failure_and_exception_logs():
    _insert_agent()
    orig_send = SC.send_reply
    try:
        SC.send_reply = lambda *a, **k: (False, "database is locked")
        _capture(SC.register_job, "job_fail", "* * * * *", "失败", "ag_test",
                 app_id="schedule_message", content_template="x",
                 target={"channel": "wcf", "peer_id": "wxid_f"})
        _make_due("job_fail")
        _, out = _capture(SC._tick)
        assert "[SchedulerCommon] ❌ app=schedule_message job=job_fail 执行失败: database is locked" in out, out

        SC.send_reply = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        _capture(SC.register_job, "job_exc", "* * * * *", "异常", "ag_test",
                 app_id="schedule_message", content_template="x",
                 target={"channel": "wcf", "peer_id": "wxid_e"})
        _make_due("job_exc")
        _, out2 = _capture(SC._tick)
        assert "[SchedulerCommon] job job_exc tick 异常: boom" in out2, out2
    finally:
        SC.send_reply = orig_send
    print("[ok] A4. 失败/异常分支：❌ 执行失败 + job .. tick 异常 日志模板一致，且不中断后续任务")


def test_backends():
    # 原生路径：APScheduler 不可用时必须退回守护线程
    saved = sys.modules.get("apscheduler", "MISSING")
    sys.modules["apscheduler"] = None  # 置 None 让 import 抛 ImportError
    try:
        name, _ = _capture(SC._start_backend)
    finally:
        if saved == "MISSING":
            sys.modules.pop("apscheduler", None)
        else:
            sys.modules["apscheduler"] = saved
    assert name == "thread", f"apscheduler 不可用时应退回 thread，实际 {name}"

    # APScheduler 路径（本 venv 已装）
    name2, _ = _capture(SC._start_backend)
    assert name2 in ("apscheduler", "thread")
    print(f"[ok] A5. 双后端：apscheduler 缺失→thread 兜底；可用→{name2}")
    return name2


def test_ensure_and_runner_logs(backend: str):
    _, out_ensure = _capture(SC.ensure_scheduler)
    assert "[SchedulerCommon] 公共轮询线程已启动" in out_ensure, out_ensure

    _, out_runner = _capture(RUNNER.start_scheduler)
    assert "[Schedule] 后台轮询线程已启动，每分钟扫一次 cron" in out_runner, out_runner
    assert "[Schedule] DB 恢复 " in out_runner and "个定时任务" in out_runner, out_runner
    assert "[Schedule] 轮询循环启动" in out_runner, out_runner
    if backend == "thread":
        assert "[Schedule] ⚠️ apscheduler 未安装" in out_runner, out_runner
    print("[ok] A6. ensure_scheduler / runner 日志模板与原版一致（[SchedulerCommon] / [Schedule]）")


def test_machine_timeout_fix():
    # 基础自测
    out, _ = _capture(MC._run_powershell, "Write-Output hello_mc")
    assert out == "hello_mc", f"powershell 基本调用失败: {out!r}"

    # 核心：>5s 的命令（旧默认 5s 会超时→空串→降级）在 20s 下必须成功
    t0 = time.time()
    out2, _ = _capture(MC._run_powershell, "Start-Sleep -Seconds 6; Write-Output slow_mc")
    elapsed = time.time() - t0
    assert out2 == "slow_mc", f"6s 命令仍被超时截断（elapsed={elapsed:.1f}s）: {out2!r}"

    code = MC.get_machine_code()
    parts = code.split("-")
    assert len(parts) == 4 and all(len(p) == 4 for p in parts), f"机器码格式错: {code}"
    assert code == code.upper()
    assert len(code.replace("-", "")) == 16
    print(f"[ok] C. machine：20s 超时下 6s 命令成功（{elapsed:.1f}s）；机器码={code} 格式正确")


def test_patch_order_fix():
    """回归：main._patch_subprocess_no_window 必须先预导入 asyncio。

    否则 subprocess.Popen 变成普通函数后，asyncio/windows_utils 的
    `class Popen(subprocess.Popen)` 会抛 TypeError，导致此后首次 import asyncio
    全部失败（APScheduler 因此不可用）。必须在【全新子进程】里验证。
    """
    import subprocess as sp
    code = (
        "import sys; sys.path.insert(0, 'app')\n"
        "import main\n"
        "import asyncio\n"
        "from apscheduler.schedulers.background import BackgroundScheduler\n"
        "print('PATCH_ORDER_OK')\n"
    )
    r = sp.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(ROOT))
    assert "PATCH_ORDER_OK" in (r.stdout or ""), \
        f"子进程失败: stdout={r.stdout!r} stderr={r.stderr[-500:]!r}"
    print("[ok] D. subprocess 补丁顺序：先 import asyncio，import main 后 asyncio/APScheduler 仍可导入")


def main():
    print(f"[tmp SCAI_APP_DIR] {tmp}")
    test_cron_parsing()
    test_register_job()
    test_tick_success_and_logs()
    test_tick_failure_and_exception_logs()
    backend = test_backends()
    test_ensure_and_runner_logs(backend)
    test_machine_timeout_fix()
    test_patch_order_fix()

    # 收尾：关掉 APScheduler
    if SC._APS_SCHED is not None:
        try:
            SC._APS_SCHED.shutdown(wait=False)
        except Exception:
            pass

    print("\n========== 调度器对齐 + 机器码超时：全部通过 ==========")
    print("  A1 cron 解析  A2 register_job  A3 tick 成功路径  A4 失败/异常分支")
    print("  A5 双后端兜底  A6 日志模板对齐([SchedulerCommon]/[Schedule])  C 机器码 20s 超时")
    print(f"\n测试数据（已隔离）: {tmp}")


if __name__ == "__main__":
    main()
