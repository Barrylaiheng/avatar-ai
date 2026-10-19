r"""阿维达授权管家（管理员本地控制台）。

【作用】
  管理员（运营者）在自己电脑上用的一个小工具，管理人工兜底激活：
    1) 收到用户发来的机器码 → 输入用户信息 → 一键生成 .lic 授权文件
    2) SQLite 自动记账（防重复/防漏记/可导出 Excel 对账）
    3) 作废选中行（换电脑补授权 / 倒卖封禁）
    4) 搜索 / 导出 Excel / 自动备份

【运行】
  venv\Scripts\python.exe app\admin_console.py
"""
from __future__ import annotations

import csv
import json
import os
import shutil
import sqlite3
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Iterable

# 必须放在任何 storage 导入之前
APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

# admin 控制台独立数据目录（与用户 MVP 的 APPDATA/SCAI 完全分离），
# 放管理员自己电脑的 HOME 目录下，不要放工程目录（避免误 commit）
ADMIN_HOME_ENVVAR = "AVATAR_ADMIN_HOME"
DEFAULT_ADMIN_HOME_V1 = Path.home() / "AvatarAIAdmin"
_DB_NAME = "admin_licenses.db"
_BACKUP_DIRNAME = "backups"
_EXPORT_DIRNAME = "exports"
_OUTPUT_DIRNAME = "output_licenses"  # 生成的 .lic 文件默认放这里（方便一键 QQ 拖拽发送）


def get_admin_home() -> Path:
    override = os.environ.get(ADMIN_HOME_ENVVAR)
    base = Path(override) if override else DEFAULT_ADMIN_HOME_V1
    for sub in (_BACKUP_DIRNAME, _EXPORT_DIRNAME, _OUTPUT_DIRNAME):
        (base / sub).mkdir(parents=True, exist_ok=True)
    return base


def get_admin_db_path() -> Path:
    return get_admin_home() / _DB_NAME


# ============== SQLite 连接 & 建表（存量缺列自动 ALTER） ==============
_LOCK = __import__("threading").RLock()  # RLock：重入场景（backup 里新开连接）不会死锁
_ADMIN_CONN: sqlite3.Connection | None = None


def _create_admin_conn() -> sqlite3.Connection:
    path = get_admin_db_path()
    conn = sqlite3.connect(str(path), check_same_thread=False, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


SCHEMA = {
    "admin_licenses": {
        "id":             "INTEGER PRIMARY KEY AUTOINCREMENT",
        "license_key":    "TEXT NOT NULL",           # AVTR-XXXX-XXXX-XXXX
        # 说明：故意不加 UNIQUE。因为同一台机器码在"旧码作废→补新码（replacement）"场景下，
        # 机器码不变 → HMAC 衍生的激活码字节相同。旧记录已 revoked，新 active，允许两条行并存，
        # 只要【同一 machine_code + status=active】最多 1 条。由 find_active_by_machine + 程序层检查保证。
        "machine_code":   "TEXT NOT NULL",           # 绑定机器码
        "user_tag":       "TEXT DEFAULT ''",         # 昵称 / 微信ID / QQ / 联系方式
        "source":         "TEXT NOT NULL DEFAULT 'private_transfer'",
        "payment_ref":    "TEXT DEFAULT ''",
        "amount_cents":   "INTEGER DEFAULT 0",       # 实际收多少（分）；默认 29900
        "status":         "TEXT NOT NULL DEFAULT 'active'",  # active / revoked / pending_issued
        "notes":          "TEXT DEFAULT ''",
        "issued_at":      "INTEGER DEFAULT 0",
        "activated_at":   "INTEGER DEFAULT 0",
        "revoked_at":     "INTEGER DEFAULT 0",
        "created_at":     "INTEGER NOT NULL",
        "updated_at":     "INTEGER NOT NULL",
    },
    "_indexes": {
        "idx_al_machine":   "CREATE INDEX IF NOT EXISTS idx_al_machine   ON admin_licenses(machine_code)",
        "idx_al_user":      "CREATE INDEX IF NOT EXISTS idx_al_user      ON admin_licenses(user_tag)",
        "idx_al_status":    "CREATE INDEX IF NOT EXISTS idx_al_status    ON admin_licenses(status)",
        "idx_al_created":   "CREATE INDEX IF NOT EXISTS idx_al_created   ON admin_licenses(created_at)",
        "idx_al_source":    "CREATE INDEX IF NOT EXISTS idx_al_source    ON admin_licenses(source)",
        "idx_al_mc_status": "CREATE INDEX IF NOT EXISTS idx_al_mc_status ON admin_licenses(machine_code, status)",
    },
}


def _init_schema() -> None:
    """启动时建表 + 存量迁移（缺列就 ALTER TABLE ADD COLUMN，不做破坏性操作）。"""
    conn = get_admin_conn()
    table = "admin_licenses"
    cols = SCHEMA[table]
    with conn:
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {table} (
                {', '.join(f'{k} {v}' for k, v in cols.items())}
            )
        """)
        existing = {
            r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        for col, decl in cols.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
        for idx_sql in SCHEMA["_indexes"].values():
            conn.execute(idx_sql)


def get_admin_conn() -> sqlite3.Connection:
    global _ADMIN_CONN
    # 必须先拿锁 → 再判断 None → 再创建。但 _init_schema 内部会调用 get_admin_conn()，
    # 所以单靠一个 threading.Lock 会在重入时死锁。这里用可重入锁（RLock）在 __init__ 时改一下。
    with _LOCK:
        if _ADMIN_CONN is None:
            _ADMIN_CONN = _create_admin_conn()
            try:
                _init_schema_v2(_ADMIN_CONN)
            except Exception:
                _ADMIN_CONN.close()
                _ADMIN_CONN = None
                raise
    return _ADMIN_CONN


def _init_schema_v2(conn: sqlite3.Connection) -> None:
    """独立函数，拿外部传进来的 conn 做建表/迁移。避免在 init 时重入 get_admin_conn 造成锁死。"""
    table = "admin_licenses"
    cols = {k: v for k, v in SCHEMA[table].items() if k != "_indexes"}  # 双保险
    with conn:
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {table} (
                {', '.join(f'{k} {v}' for k, v in cols.items())}
            )
        """)
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for col, decl in cols.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
        for idx_sql in SCHEMA["_indexes"].values():
            conn.execute(idx_sql)


# ============== 核心写操作（所有路由只能走这一层，保证一致性） ==============
SOURCE_OPTIONS = (
    ("huqijiao",          "虎皮椒自动（已扫码到账）"),
    ("huqijiao_manual",   "虎皮椒补单（已到账但没自动激活）"),
    ("private_transfer",  "私人转账（微信/支付宝/银行卡）"),
    ("complimentary",     "赠码（内测/朋友/合作）"),
    ("replacement",       "补换机器（原机器作废，新机器重发）"),
    ("other",             "其他（请备注）"),
)


def now_ts() -> int:
    return int(time.time())


def _backup_db():
    """每次写操作（新增/作废）后立即做一份日期命名的 DB 副本到 backups 目录。
    为了省空间，同一天只保留最新一份（覆盖），不同日期叠加。"""
    try:
        src = get_admin_db_path()
        day = datetime.now().strftime("%Y-%m-%d")
        dst = get_admin_home() / _BACKUP_DIRNAME / f"{_DB_NAME}.{day}.bak"
        # sqlite 官方推荐用 .backup() API 做在线备份（WAL 下也安全）
        with sqlite3.connect(str(dst)) as dst_conn:
            with sqlite3.connect(str(src)) as src_conn:
                src_conn.backup(dst_conn, pages=50, progress=None)
        # 再额外拷一份到 OneDrive/Dropbox 同步目录（如果管理员自己建了 sync_dir 软链接）
        sync = get_admin_home() / "sync_dir"
        if sync.exists() and sync.is_dir():
            try:
                shutil.copy2(src, sync / _DB_NAME)
            except Exception:
                pass
    except Exception as e:  # noqa: BLE001
        # 备份失败不影响业务，打印一下让管理员去查
        print(f"[WARN] 备份失败: {e!r}", file=sys.stderr, flush=True)


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row else None


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict]:
    return [dict(r) for r in rows]


def find_active_by_machine(machine_code: str) -> dict | None:
    if not machine_code:
        return None
    row = get_admin_conn().execute(
        "SELECT * FROM admin_licenses WHERE machine_code=? AND status='active' LIMIT 1",
        (machine_code.strip().upper(),),
    ).fetchone()
    return row_to_dict(row)


def list_licenses(keyword: str = "", status: str = "") -> list[dict]:
    sql = "SELECT * FROM admin_licenses WHERE 1=1"
    args: list = []
    if keyword:
        k = f"%{keyword.strip()}%"
        sql += " AND (user_tag LIKE ? OR machine_code LIKE ? OR license_key LIKE ? OR payment_ref LIKE ? OR notes LIKE ?)"
        args += [k, k, k, k, k]
    if status:
        sql += " AND status=?"
        args.append(status)
    sql += " ORDER BY created_at DESC, id DESC LIMIT 500"
    return rows_to_dicts(get_admin_conn().execute(sql, args).fetchall())


def create_license(
    *,
    machine_code: str,
    user_tag: str = "",
    source: str = "private_transfer",
    payment_ref: str = "",
    amount_cents: int = 29900,
    notes: str = "",
) -> tuple[dict, Path]:
    """生成一条授权记录 + 一份 .lic 文件（输出到 admin home/output_licenses）。

    一致性规则：如果此 machine_code 已存在 status=active → 抛 ValueError 拦截，防止重复收钱。
    返回 (记录dict, 生成的lic文件路径)。
    """
    from storage.license import generate_license_key  # 复用 MVP 同一套 HMAC 算法，保证与用户端 verify_license_key 一致

    mc = (machine_code or "").strip().upper()
    if not mc:
        raise ValueError("机器码不能为空")
    # 格式粗校验（不强制严格到 4 段，用户复制时少了横杠也接受，因为 verify 时用 strip 大写归一）
    if len(mc.replace("-", "").replace(" ", "")) < 8:
        raise ValueError("机器码太短，看起来不像是有效的硬件指纹；请让用户从 MVP → 激活 Tab2 完整复制")

    src = (source or "private_transfer").strip()
    valid_sources = {s[0] for s in SOURCE_OPTIONS}
    if src not in valid_sources:
        raise ValueError(f"来源非法：{src}，必须是 {sorted(valid_sources)} 之一")

    tag = (user_tag or "").strip()
    ref = (payment_ref or "").strip()
    notes = (notes or "").strip()

    # ====== 一致性规则 A：同一机器码 active 只能有一条 ======
    existed = find_active_by_machine(mc)
    if existed:
        raise ValueError(
            f"该机器码 {mc[-8:]} 已在 {datetime.fromtimestamp(existed['created_at'])} 激活过（用户：{existed['user_tag'] or '未填'}），"
            f"来源={existed['source']}，别重复收钱！\n\n若确实是【同一台机器重新授权】（如用户重装系统后原激活码丢了），"
            f"请先在列表里选中旧记录→作废，再重新生成新的授权。"
        )

    license_key = generate_license_key(mc)  # AVTR-XXXX-XXXX-XXXX
    ts = now_ts()
    conn = get_admin_conn()

    # ====== 一致性规则 B：同 machine_code 已产生过完全相同 license_key（HMAC 必然，mc 相同 key 相同）——这在"旧码 revoked→重新 generate"时合法，
    #        只要 active 只有一条（规则 A 已拦）。UNIQUE 不拦，只在 key 重复且是"同一状态"时报自定义错方便排错。
    try:
        with conn:
            cur = conn.execute(
                """INSERT INTO admin_licenses
                       (license_key, machine_code, user_tag, source, payment_ref, amount_cents,
                        status, notes, issued_at, activated_at, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?)""",
                (license_key, mc, tag, src, ref, int(amount_cents or 0),
                 notes, ts, ts, ts, ts),
            )
            new_id = cur.lastrowid
    except sqlite3.IntegrityError as e:
        raise ValueError(f"写入账本失败（完整性约束）: {e}") from e

    new_row = row_to_dict(conn.execute("SELECT * FROM admin_licenses WHERE id=?", (new_id,)).fetchone())
    assert new_row is not None

    # ====== 生成 .lic 文件（格式与用户端 license.py read_license_file 完全兼容，直接导入即可） ======
    out_dir = get_admin_home() / _OUTPUT_DIRNAME
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_tag = "".join(c for c in (tag or "user") if c.isalnum() or c in ("_", "-"))[:16] or "user"
    safe_mc = "".join(c for c in mc if c.isalnum())[-6:] or "XXXXXX"
    day = datetime.now().strftime("%Y%m%d")
    file_name = f"license_{day}_{safe_tag}_{safe_mc}_{new_id}.lic"
    out_path = out_dir / file_name
    payload = {
        "schema": "v1",
        "machine_code": mc,
        "license_key": license_key,
        "issued_at": ts,
        "admin_note": f"生成者: admin_console / 来源: {src} / 记录ID: {new_id}",
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    _backup_db()
    return new_row, out_path


def revoke_license(license_id: int, reason: str = "") -> dict:
    """作废选中的授权（换电脑 / 用户倒卖封禁 / 退款）。

    返回更新后的记录 dict。
    """
    if not license_id:
        raise ValueError("license_id 不能为空")
    conn = get_admin_conn()
    row = conn.execute("SELECT * FROM admin_licenses WHERE id=?", (int(license_id),)).fetchone()
    if not row:
        raise ValueError("授权记录不存在")
    if row["status"] == "revoked":
        raise ValueError("该记录已经是作废状态")
    ts = now_ts()
    old_notes = row["notes"] or ""
    new_notes_parts = [old_notes] if old_notes else []
    if reason.strip():
        new_notes_parts.append(f"[作废{datetime.fromtimestamp(ts):%Y-%m-%d}] {reason.strip()}")
    else:
        new_notes_parts.append(f"[作废{datetime.fromtimestamp(ts):%Y-%m-%d}] 管理员操作")
    with conn:
        conn.execute(
            """UPDATE admin_licenses
                  SET status='revoked', revoked_at=?, updated_at=?, notes=?
                WHERE id=?""",
            (ts, ts, "\n".join(new_notes_parts), int(license_id)),
        )
    _backup_db()
    return row_to_dict(conn.execute("SELECT * FROM admin_licenses WHERE id=?", (int(license_id),)).fetchone())


def stats() -> dict:
    """表格底部状态条所需的本月/累计统计。"""
    conn = get_admin_conn()
    now = datetime.now()
    this_month_start = int(datetime(now.year, now.month, 1).timestamp())
    def q(sql, args=()) -> int:
        r = conn.execute(sql, args).fetchone()
        return int(r[0]) if r else 0
    return {
        "this_month_count": q("SELECT COUNT(*) FROM admin_licenses WHERE status='active' AND created_at>=?", (this_month_start,)),
        "this_month_rev_cents": q("SELECT COALESCE(SUM(amount_cents),0) FROM admin_licenses WHERE status='active' AND created_at>=?", (this_month_start,)),
        "total_active": q("SELECT COUNT(*) FROM admin_licenses WHERE status='active'"),
        "total_revoked": q("SELECT COUNT(*) FROM admin_licenses WHERE status='revoked'"),
        "total_rev_cents": q("SELECT COALESCE(SUM(amount_cents),0) FROM admin_licenses WHERE status='active'"),
        "manual_count": q("SELECT COUNT(*) FROM admin_licenses WHERE source IN ('huqijiao_manual','private_transfer','complimentary','replacement','other') AND status='active'"),
        "db_path": str(get_admin_db_path()),
    }


def export_csv(target_path: Path | None = None) -> Path:
    """导出当前全量账本为 CSV（Excel/WPS 直接双击打开）。默认放到 exports 目录，文件名带时间戳。"""
    exports = get_admin_home() / _EXPORT_DIRNAME
    exports.mkdir(parents=True, exist_ok=True)
    if target_path is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        target_path = exports / f"avatar_admin_licenses_{ts}.csv"
    target_path = Path(target_path)
    cols = ["id", "created_at", "user_tag", "machine_code", "license_key", "source",
            "payment_ref", "amount_cents", "status", "issued_at", "activated_at",
            "revoked_at", "notes"]
    headers = {
        "id": "ID",
        "created_at": "创建日期", "user_tag": "用户标识", "machine_code": "机器码",
        "license_key": "激活码", "source": "来源", "payment_ref": "打款单号",
        "amount_cents": "金额(分)", "status": "状态",
        "issued_at": "颁发时间戳", "activated_at": "激活时间戳",
        "revoked_at": "作废时间戳", "notes": "备注",
    }

    def fmt_date(ts: int) -> str:
        if not ts:
            return ""
        return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S")

    rows = list_licenses(keyword="", status="")  # 全量
    with target_path.open("w", encoding="utf-8-sig", newline="") as f:  # utf-8-sig 让 Excel 识别中文不乱码
        w = csv.writer(f)
        w.writerow([headers[c] for c in cols] + ["金额(元)", "创建时间-可读", "作废时间-可读"])
        for r in rows:
            base = [r.get(c, "") for c in cols]
            amt_cents = int(r.get("amount_cents") or 0)
            base.append(f"{amt_cents / 100:.2f}")
            base.append(fmt_date(int(r.get("created_at") or 0)))
            base.append(fmt_date(int(r.get("revoked_at") or 0)))
            w.writerow(base)
    return target_path


# ============== PyQt6 + QWebEngine 网页版控制台（与主程序同一套桥接架构） ==============
#
# 架构与 app/main.py 完全一致：
#   admin_console.html  界面展示（视觉基准）
#   AdminBridge         业务桥接（QWebChannel 暴露给 JS，action 分发到上面的 core 层函数）
#   AdminConsoleWindow  窗口装配（QWebEngineView + QWebChannel + 无缓存 profile）
# 打包：PyInstaller 入口仍是本文件；admin_console.html / avatar_icon.ico 由 spec 的 datas 带入。
import ctypes
import time as _time

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot, QUrl
from PyQt6.QtGui import QDesktopServices, QGuiApplication, QIcon
from PyQt6.QtWidgets import QApplication, QMainWindow, QFileDialog
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PyQt6.QtWebChannel import QWebChannel

_HTML_NAME = "admin_console.html"
_ICON_NAME = "avatar_icon.ico"


def resource_path(relative_path: str) -> Path:
    """PyInstaller onefile/onedir 通用资源路径（与 main.py 同款）。"""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    return base / relative_path


class AdminBridge(QObject):
    """管理员控制台 Python 端桥接对象，通过 QWebChannel 暴露为 JS 的 `bridge`。

    JS → Python：window.pyqtBridge.call(action, payloadJson) → 本类 call() 槽
    Python → JS：pong（call 结果）/ push（主动推送）
    所有业务都走 core 层函数（create_license / revoke_license / list_licenses / stats …），
    与 tests/test_admin_console_core.py 覆盖的是同一层，桥接只做参数透传与错误包装。
    """

    pong = pyqtSignal(str)          # 回传 call 结果（JSON 字符串）
    push = pyqtSignal(str, str)     # 主动推送 (action, payload_json)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._window = None

    def set_parent_window(self, window):
        """设置主窗口引用（QFileDialog 的 parent）。"""
        self._window = window

    # ---------- JS → Python 入口 ----------
    @pyqtSlot(str, str)
    def call(self, action: str, payload_json: str):
        try:
            payload = json.loads(payload_json) if payload_json else {}
        except json.JSONDecodeError:
            payload = {}

        print(f"[AdminBridge] JS→Python: action={action}, payload={payload}", flush=True)

        handler = getattr(self, f"_handle_{action}", None)
        if handler is None:
            self.pong.emit(json.dumps(
                {"ok": False, "action": action, "error": f"未知操作: {action}"}, ensure_ascii=False))
            return

        try:
            data = handler(payload)
            result = {"ok": True, "action": action, "data": data}
            print(f"[AdminBridge] action={action} → ok", flush=True)
        except ValueError as e:  # 业务拦截（重复机器码 / 边界校验）原样回给前端弹提示
            result = {"ok": False, "action": action, "error": str(e)}
            print(f"[AdminBridge] action={action} 拒绝: {e}", flush=True)
        except Exception as e:  # noqa: BLE001
            result = {"ok": False, "action": action, "error": f"{type(e).__name__}: {e}"}
            print(f"[AdminBridge] action={action} 异常: {e}", flush=True)

        self.pong.emit(json.dumps(result, ensure_ascii=False))

    def send_to_js(self, action: str, payload: dict):
        """Python 主动推送消息到 JS。"""
        self.push.emit(action, json.dumps(payload, ensure_ascii=False))

    def bootstrap_payload(self) -> dict:
        """JS 桥接就绪时推送的首包。"""
        return {"status": "Admin bridge connected", **self._handle_ready({})}

    # ---------- 桥接测试 ----------
    def _handle_ping(self, payload):
        return {"message": "pong", "echo": payload, "server_ts": now_ts()}

    def _handle_ready(self, payload):
        """首包：数据目录信息 + 来源字典 + 初始统计。"""
        home = get_admin_home()
        return {
            "db_path": str(get_admin_db_path()),
            "admin_home": str(home),
            "output_dir": str(home / _OUTPUT_DIRNAME),
            "backup_dir": str(home / _BACKUP_DIRNAME),
            "export_dir": str(home / _EXPORT_DIRNAME),
            "sources": [{"value": v, "label": label} for v, label in SOURCE_OPTIONS],
            "status_labels": {"active": "✅ 生效中", "revoked": "🚫 已作废", "pending_issued": "⏳ 待发布"},
            "stats": stats(),
        }

    def _handle_list_licenses(self, payload):
        rows = list_licenses(
            keyword=(payload.get("keyword") or "").strip(),
            status=(payload.get("status") or "").strip(),
        )
        return {"rows": rows, "stats": stats()}

    def _handle_create_license(self, payload):
        rec, out_path = create_license(
            machine_code=payload.get("machine_code", ""),
            user_tag=payload.get("user_tag", ""),
            source=payload.get("source", "private_transfer"),
            payment_ref=payload.get("payment_ref", ""),
            amount_cents=int(payload.get("amount_cents") or 0),
            notes=payload.get("notes", ""),
        )
        # 自动复制 .lic 绝对路径到剪贴板 + 在资源管理器中选中，方便直接拖给用户
        try:
            cb = QApplication.clipboard()
            if cb is not None:
                cb.setText(str(out_path))
        except Exception:
            pass
        try:
            import subprocess
            subprocess.Popen(f'explorer /select,"{out_path}"')
        except Exception:
            pass
        return {"record": rec, "out_path": str(out_path), "license_key": rec["license_key"]}

    def _handle_revoke_license(self, payload):
        rec = revoke_license(int(payload.get("license_id") or 0), reason=payload.get("reason", ""))
        return {"record": rec, "stats": stats()}

    def _handle_export_csv(self, payload):
        out = export_csv()
        saved = ""
        # 可选：让管理员另存一份到桌面发会计（QFileDialog 必须在主线程，桥接槽本就在主线程）
        if payload.get("ask_save") and self._window is not None:
            default = str(Path.home() / "Desktop" / out.name)
            chosen, _ = QFileDialog.getSaveFileName(
                self._window, "另存到…（发给会计 / 自己对账放一份）", default, "CSV 表格 (*.csv)")
            if chosen:
                shutil.copy2(out, chosen)
                saved = chosen
        return {"path": str(out), "saved": saved}

    def _handle_backup_db(self, payload):
        _backup_db()
        return {"backup_dir": str(get_admin_home() / _BACKUP_DIRNAME)}

    def _handle_open_folder(self, payload):
        which = payload.get("which") or "output"
        sub = {"output": _OUTPUT_DIRNAME, "backup": _BACKUP_DIRNAME, "export": _EXPORT_DIRNAME, "home": ""}
        target = get_admin_home() / sub.get(which, "")
        try:
            os.startfile(str(target))  # type: ignore[attr-defined]
        except Exception as e:  # noqa: BLE001
            return {"path": str(target), "error": str(e)}
        return {"path": str(target)}


class AdminPage(QWebEnginePage):
    """自定义 WebEngine Page：挂载 QWebChannel 桥接 + 捕获 JS 控制台日志。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.bridge = AdminBridge()
        self.channel = QWebChannel()
        self.channel.registerObject("bridge", self.bridge)
        self.setWebChannel(self.channel)

    def acceptNavigationRequest(self, url: QUrl, nav_type, is_main_frame: bool):
        """拦截主框架的 http/https 外链，交给系统浏览器打开；本地资源放行。"""
        if not is_main_frame:
            return True
        if url.scheme() in ("http", "https") and url.isValid():
            QDesktopServices.openUrl(url)
            return False
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)

    def javaScriptConsoleMessage(self, level, message, line_number, source_id):
        try:
            level_val = int(level) if isinstance(level, int) else getattr(level, "value", 0)
        except Exception:
            level_val = 0
        prefix = {0: "LOG", 1: "WARN", 2: "ERROR"}.get(level_val, "LOG")
        src = source_id.split("/")[-1] if source_id else "?"
        print(f"[Admin JS {prefix}] L{line_number} @ {src} : {message}", flush=True)


class AdminConsoleWindow(QMainWindow):
    """授权管家主窗口。"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("阿维达 · 授权管家（管理员本地控制台）")

        # 按屏幕分辨率自适应，封顶到设计尺寸
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.resize(min(int(screen.width() * 0.86), 1280), min(int(screen.height() * 0.86), 860))
        self.setMinimumSize(960, 620)

        self.browser = QWebEngineView()
        self.setCentralWidget(self.browser)

        try:
            dpi = QGuiApplication.primaryScreen().logicalDotsPerInch()
            self.browser.setZoomFactor(min(max(dpi / 96.0, 0.8), 1.5))
        except Exception:
            pass

        # 禁用 HTTP 缓存，确保每次加载最新资源
        profile = self.browser.page().profile()
        profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.NoCache)

        self.page = AdminPage(self.browser)
        self.browser.setPage(self.page)
        self.page.bridge.set_parent_window(self)

        html_path = resource_path(_HTML_NAME)
        url = QUrl.fromLocalFile(str(html_path))
        url.setQuery(f"t={int(_time.time())}")  # 附加时间戳，避开缓存
        self.browser.setUrl(url)
        self.browser.loadFinished.connect(self._on_load_finished)

    def _on_load_finished(self, ok: bool):
        if ok:
            print("[Admin] HTML 加载完成，桥接就绪", flush=True)
            self.page.bridge.send_to_js("ready", self.page.bridge.bootstrap_payload())
        else:
            print("[Admin] HTML 加载失败", flush=True)


def _run_gui() -> int:
    from logger import setup_file_logging
    setup_file_logging()

    # OpenGL / Chromium 开关与 main.py 一致（虚拟机 / 无显卡环境可用）；
    # 调试端口用 9223，避免与主程序 9222 冲突。
    os.environ.setdefault("QT_OPENGL", "software")
    os.environ.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")
    os.environ.setdefault(
        "QTWEBENGINE_CHROMIUM_FLAGS",
        "--disable-gpu --disable-gpu-compositing --in-process-gpu"
        " --no-sandbox --enable-features=NetworkServiceInProcess"
        " --remote-debugging-port=9223",
    )

    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AvatarAI.Admin.1.0")

    app = QApplication(sys.argv)
    app.setApplicationName("阿维达授权管家")
    app.setApplicationDisplayName("阿维达授权管家")

    icon_path = resource_path(_ICON_NAME)
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    window = AdminConsoleWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    _ = get_admin_conn()  # 确保表结构就绪（GUI 启动后任一 action 也会触发）
    sys.exit(_run_gui())
