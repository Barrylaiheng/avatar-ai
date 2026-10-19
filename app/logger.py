"""阿维达AI · 日志落盘

一行 import 接管所有 print：
    把 sys.stdout / sys.stderr hack 成"同时写控制台 + 写文件"
    文件位置：%APPDATA%\\SCAI\\logs\\scai_YYYYMMDD.log
    保留：最近 7 天
"""
import sys
import os
import time
import shutil
import threading
from pathlib import Path
from datetime import datetime, timedelta

_LOG_DIR = Path(os.environ.get("APPDATA", Path.home() / ".config")) / "SCAI" / "logs"
_RETENTION_DAYS = 7


def _ensure_log_dir() -> Path:
    """确保日志目录存在，返回目录路径。"""
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    return _LOG_DIR


def _current_log_path() -> Path:
    """今日日志文件路径。"""
    return _LOG_DIR / f"scai_{datetime.now().strftime('%Y%m%d')}.log"


def _prune_old_logs():
    """清理超过 7 天的旧日志。"""
    try:
        cutoff = datetime.now() - timedelta(days=_RETENTION_DAYS)
        for f in _LOG_DIR.glob("scai_*.log"):
            try:
                file_date = datetime.strptime(f.stem.replace("scai_", ""), "%Y%m%d")
                if file_date < cutoff:
                    f.unlink(missing_ok=True)
            except ValueError:
                continue
    except Exception:
        return


class _Tee:
    """把两个 stream 合成一个：写 A 同时写 B。"""

    def __init__(self, *streams):
        self._streams = streams
        self._lock = threading.Lock()

    def write(self, data):
        with self._lock:
            for s in self._streams:
                try:
                    s.write(data)
                    if hasattr(s, "flush"):
                        s.flush()
                except Exception:
                    continue

    def flush(self):
        with self._lock:
            for s in self._streams:
                try:
                    s.flush()
                except Exception:
                    continue

    def fileno(self):
        for s in self._streams:
            try:
                return s.fileno()
            except (AttributeError, ValueError, OSError):
                continue
        return -1

    def isatty(self):
        for s in self._streams:
            try:
                if s.isatty():
                    return True
            except Exception:
                continue
        return False


_initialized = False


def setup_file_logging():
    """安装 stdout/stderr tee。main.py 开头调一次就行。"""
    global _initialized
    if _initialized:
        return
    _ensure_log_dir()
    _prune_old_logs()
    today_file = _current_log_path()
    try:
        log_file = open(today_file, "a", encoding="utf-8", errors="replace")
    except Exception:
        print(f"[Logger] 无法创建日志文件 {today_file}，降级为仅控制台", flush=True)
        _initialized = True
        return

    startup_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        log_file.write(f"\n{'=' * 60}\n")
        log_file.write(f"[{startup_ts}] SCAI 启动\n")
        log_file.write(f"[Logger] 日志落盘: {today_file}\n\n")
        log_file.flush()
    except Exception:
        pass

    _orig_stdout = sys.stdout
    _orig_stderr = sys.stderr
    sys.stdout = _Tee(_orig_stdout, log_file)
    sys.stderr = _Tee(_orig_stderr, log_file)

    _initialized = True
    print(f"[Logger] 日志已落盘: {today_file}", flush=True)


def get_log_dir() -> str:
    """供 Bridge 后端调用：返回日志目录路径（给 Bug 反馈打包用）。"""
    return str(_ensure_log_dir())
