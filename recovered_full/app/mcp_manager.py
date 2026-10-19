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
            _CONN = sqlite3.connect(str(_get_db_path()), check_same_thread=False, timeout=5)
            _CONN.row_factory = sqlite3.Row
            _CONN.execute("PRAGMA journal_mode = WAL")
            _CONN.execute("PRAGMA busy_timeout = 5000")
            _CONN.execute("""CREATE TABLE IF NOT EXISTS mcp_config (
                      key   TEXT PRIMARY KEY,
                      value TEXT NOT NULL DEFAULT ''
                   )""")
            _CONN.commit()
        return _CONN


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
        py = sys.executable or "python"
        project_root = str(Path(__file__).parent.parent)
        install_cfg = {
            "mcpServers": {
                "Avatar AI": {
                    "command": py,
                    "args": ["-m", "app.mcp_server"],
                    "env": {
                        "MCP_TOKEN": token,
                        "PYTHONPATH": project_root,
                    },
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
