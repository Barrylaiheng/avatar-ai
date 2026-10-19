# -*- coding: utf-8 -*-
"""storage.db 的「写操作抗 BUSY」连接层兜底验收。

覆盖：
  1) 主连接确为 BusyRetryConnection，正常读写不受影响
  2) 瞬时写锁竞争（另一连接攥住写锁 0.4s）→ 退避重试后写入成功
  3) 非 BUSY 的 OperationalError（表不存在）→ 立即抛出，不做重试
  4) 写锁被长时间攥住、超过重试预算 → 有界抛出 database is locked（不会无限等待）

做法：2~4 用 busy_timeout=100ms 的短超时连接，让「重试」而不是「busy_timeout 长等待」
成为被测对象，测试因此确定且快速（<3s）。

运行：venv\\Scripts\\python.exe tests\\test_db_busy_retry.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 隔离 DB：必须在 import storage.db 之前设好
tmp = Path(tempfile.mkdtemp(prefix="avatar_busy_test_"))
os.environ["SCAI_APP_DIR"] = str(tmp)

from app.storage import db as DB  # noqa: E402


def _prepare(path: str) -> None:
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY AUTOINCREMENT, v TEXT)")
    c.commit()
    c.execute("PRAGMA journal_mode = WAL")
    c.close()


def _short_conn(path: str) -> sqlite3.Connection:
    """busy_timeout 只有 100ms 的重试连接：把「重试」而非「长等待」作为被测对象。"""
    c = sqlite3.connect(path, factory=DB.BusyRetryConnection, timeout=0.1)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout = 100")
    return c


def _hold_write_lock(path: str, hold_seconds: float) -> threading.Event:
    """在子线程里用独立连接开启写事务并攥住 hold_seconds 秒，返回「已持锁」事件。"""
    ready = threading.Event()

    def worker() -> None:
        c = sqlite3.connect(path, timeout=0.1)
        c.execute("PRAGMA busy_timeout = 100")
        c.execute("BEGIN IMMEDIATE")           # 立刻取得写锁
        c.execute("INSERT INTO t (v) VALUES ('hold')")
        ready.set()
        time.sleep(hold_seconds)
        try:
            c.commit()
        finally:
            c.close()

    threading.Thread(target=worker, name="lock-holder", daemon=True).start()
    assert ready.wait(3), "持锁线程未能及时取得写锁"
    return ready


def main():
    path = str(DB.get_db_path())
    _prepare(path)
    print(f"[tmp SCAI_APP_DIR] {tmp}")

    # ---- 1) 主连接类型 + 正常读写 ----
    conn = DB.get_conn()
    assert isinstance(conn, DB.BusyRetryConnection), f"主连接类型错: {type(conn)}"
    conn.execute("INSERT INTO t (v) VALUES (?)", ("main",))
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1
    print("[ok] 1. 主连接为 BusyRetryConnection，正常写/读不受影响")

    # ---- 2) 瞬时竞争 → 重试后成功 ----
    _hold_write_lock(path, 0.4)
    w = _short_conn(path)
    t0 = time.time()
    w.execute("INSERT INTO t (v) VALUES (?)", ("after-retry",))
    w.commit()
    dt = time.time() - t0
    w.close()
    assert dt >= 0.4, f"未发生退避等待，可能没走重试路径（elapsed={dt:.2f}s）"
    print(f"[ok] 2. 写锁被攥住 0.4s → 退避重试后写入成功（耗时 {dt:.2f}s，确实等待并重试过）")

    # ---- 3) 非 BUSY 错误不重试 ----
    w = _short_conn(path)
    t0 = time.time()
    err = None
    try:
        w.execute("SELECT * FROM no_such_table_xyz")
    except sqlite3.OperationalError as e:
        err = str(e)
    dt = time.time() - t0
    w.close()
    assert err and "no such table" in err, f"应抛出 no such table，实际: {err!r}"
    assert dt < 0.3, f"非 BUSY 错误被错误地重试了（耗时 {dt:.2f}s）"
    print(f"[ok] 3. 非 BUSY 的 OperationalError 立即抛出、不重试（耗时 {dt:.3f}s）：{err!r}")

    # ---- 4) 长时间持锁 → 有界抛出 ----
    _hold_write_lock(path, 6.0)
    w = _short_conn(path)
    t0 = time.time()
    err = None
    try:
        w.execute("INSERT INTO t (v) VALUES (?)", ("should-fail",))
        w.commit()
    except sqlite3.OperationalError as e:
        err = str(e)
    dt = time.time() - t0
    w.close()
    assert err and "locked" in err.lower(), f"应抛出 database is locked，实际: {err!r}"
    assert dt < 3.0, f"重试预算应有界，实际等了 {dt:.2f}s"
    print(f"[ok] 4. 写锁久攥 → 在重试预算内（{dt:.2f}s）有界抛出 database is locked，不会无限等")

    # ---- 5) busy 判定函数本身 ----
    assert DB._is_busy_error(sqlite3.OperationalError("database is locked"))
    assert DB._is_busy_error(sqlite3.OperationalError("database table is locked"))
    assert not DB._is_busy_error(sqlite3.OperationalError("no such table: x"))
    print("[ok] 5. _is_busy_error：只对 BUSY 类错误判真，其它 OperationalError 判假")

    print("\n========== 写操作抗 BUSY（连接层兜底）：5/5 全部通过 ==========")
    print(f"测试数据（已隔离）: {tmp}")


if __name__ == "__main__":
    main()
