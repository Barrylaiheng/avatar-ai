"""MCP（Model Context Protocol）配置管理。

职责：
- SQLite KV 表存 enabled / token
- token 鉴权 + 生成
- FastMCP server 线程启停

所有调用方（bridge handler / mcp_server / main）都通过 get_mcp_manager() 拿到单例。
"""
from __future__ import annotations

import os
import sqlite3
import threading
import uuid
from pathlib import Path


def _get_db_path() -> Path:
    """和 storage.db.get_db_path 保持一致的路径。"""
    override = os.environ.get("SCAI_APP_DIR")
    if override:
        base = Path(override)
    else:
        appdata = os.environ.get("APPDATA")
        if not appdata:
            raise RuntimeError("APPDATA 环境变量未设置")
        base = Path(appdata) / "SCAI"
    base.mkdir(parents=True, exist_ok=True)
    return base / "scai_v1.db"


_LOCK = threading.Lock()
_CONN: sqlite3.Connection | None = None


def _ensure_conn() -> sqlite3.Connection:
    global _CONN
    with _LOCK:
        if _CONN is None:
            # 与主库共用同一个文件，同样启用 BUSY 重试连接（多进程写竞争兜底）
            from storage.db import BusyRetryConnection
            _CONN = sqlite3.connect(
                str(_get_db_path()), check_same_thread=False, timeout=5,
                factory=BusyRetryConnection,
            )
            _CONN.row_factory = sqlite3.Row
            _CONN.execute("PRAGMA journal_mode = WAL")
            _CONN.execute("PRAGMA busy_timeout = 5000")
            _CONN.execute("""CREATE TABLE IF NOT EXISTS mcp_config (
                      key   TEXT PRIMARY KEY,
                      value TEXT NOT NULL DEFAULT ''
                   )""")
            _CONN.commit()
        return _CONN


def _short_path(path: str) -> str:
    """取 Windows 8.3 短路径（不含空格）。取不到返回空字符串。"""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(1024)
        n = ctypes.windll.kernel32.GetShortPathNameW(path, buf, 1024)
        if n and buf.value and buf.value != path:
            return buf.value
    except Exception:
        pass
    return ""


def _spawnable_exe(path: str) -> str:
    """把 exe 路径转成 MCP 客户端能直接启动的写法。

    难点：不同客户端启动方式不同，对空格的要求正好相反 ——
      · Trae 把 command 拼成命令行交给 cmd.exe 执行：
        路径含空格不加引号会在空格处断开（报「不是内部或外部命令」）。
      · WorkBuddy 按 argv 直接启动进程（其官方连接器里带空格的
        "C:\\Program Files\\NVIDIA Corporation\\...\\NvAppMcpServer.exe"
        就是不加引号的），加了引号会变成文件名的一部分而找不到文件。

    最稳的中间解：优先用 8.3 短路径 —— 不含空格，两种启动方式都能跑。
    取不到短路径时，才退化成「含空格就加引号」（先保住 Trae）。
    """
    short = _short_path(path)
    if short and " " not in short:
        return short
    if " " in path and not (path.startswith('"') and path.endswith('"')):
        return '"' + path + '"'
    return path


class MCPManager:
    """MCP 配置管理 + server 进程/线程控制。"""

    def get(self, key: str) -> str | None:
        row = _ensure_conn().execute("SELECT value FROM mcp_config WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set(self, key: str, value: str) -> None:
        conn = _ensure_conn()
        conn.execute("""INSERT INTO mcp_config (key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value""", (key, value))
        conn.commit()

    def generate_token(self) -> str:
        return uuid.uuid4().hex

    def get_or_generate_token(self) -> str:
        t = self.get("token")
        if t:
            return t
        t = self.generate_token()
        self.set("token", t)
        return t

    def verify_token(self, token: str) -> bool:
        stored = self.get("token")
        return bool(stored and token and stored == token)

    def is_enabled(self) -> bool:
        return self.get("enabled") == "1"

    def set_enabled(self, enabled: bool) -> None:
        self.set("enabled", "1" if enabled else "0")

    def get_contact(self) -> str:
        """获取开发者联系方式。默认为空字符串，用户可在前端/DB 配置。"""
        return self.get("contact_info") or ""

    def set_contact(self, contact: str) -> None:
        self.set("contact_info", contact or "")

    def get_config(self) -> dict:
        import sys
        import json as _json
        enabled = self.is_enabled()
        token = self.get_or_generate_token() if enabled else (self.get("token") or "")
        # 路径带空格的处理交给 _spawnable_exe：优先 8.3 短路径（Trae 和 WorkBuddy
        # 两种启动方式都认），取不到才退化成加引号（见该函数说明）。
        py = _spawnable_exe(sys.executable or "python")
        env = {"MCP_TOKEN": token}
        # PYTHONPATH 只在开发版（源码运行）有意义：让 `python -m app.mcp_server` 找得到项目根。
        # 打包版（frozen）自带 bootloader 做模块加载，这时 __file__ 在 _MEIPASS 临时目录里，
        # 写进配置就会给用户看到一个「关掉应用就失效」的临时路径 —— 纯垃圾字段，干脆不写。
        if not getattr(sys, "frozen", False):
            env["PYTHONPATH"] = str(Path(__file__).parent.parent)
        install_cfg = {
            "mcpServers": {
                "Avatar AI": {
                    "command": py,
                    "args": ["-m", "app.mcp_server"],
                    "env": env,
                }
            }
        }
        return {
            "enabled": enabled,
            "token": token,
            "install_string": _json.dumps(install_cfg, ensure_ascii=False, indent=2) if token else "",
        }


_mgr: MCPManager | None = None
_mgr_lock = threading.Lock()


def get_mcp_manager() -> MCPManager:
    global _mgr
    with _mgr_lock:
        if _mgr is None:
            _mgr = MCPManager()
        return _mgr
