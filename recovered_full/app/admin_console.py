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


# ============== PyQt6 GUI（只有 3 个控件：搜索栏 + 表格 + 按钮条） ==============
def _run_gui() -> int:
    from PyQt6.QtCore import Qt, QTimer
    from PyQt6.QtGui import QAction, QClipboard, QIcon
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
        QMessageBox, QDialog, QFormLayout, QComboBox, QPlainTextEdit,
        QDialogButtonBox, QLabel, QSpinBox, QFileDialog, QStatusBar,
        QAbstractItemView,
    )

    app = QApplication(sys.argv)
    app.setApplicationName("阿维达授权管家")

    win = QMainWindow()
    win.setWindowTitle("阿维达授权管家 · 管理员本地控制台 v1.0")
    win.resize(1080, 680)

    central = QWidget(win); win.setCentralWidget(central)
    root = QVBoxLayout(central); root.setContentsMargins(16, 16, 16, 12); root.setSpacing(10)

    # 顶部：搜索栏 + 按钮条（一行）
    top_row = QHBoxLayout(); top_row.setSpacing(8)
    search_edit = QLineEdit(); search_edit.setPlaceholderText("🔍 搜：昵称 / 机器码 / 激活码 / 打款单号 / 备注")
    btn_search = QPushButton("搜索")
    btn_add = QPushButton("➕ 新增授权")
    btn_revoke = QPushButton("❌ 作废选中")
    btn_export = QPushButton("📤 导出 Excel(CSV)")
    btn_folder = QPushButton("📁 打开授权文件目录")
    for b in (btn_add, btn_revoke, btn_export, btn_folder):
        b.setCursor(Qt.CursorShape.PointingHandCursor)
    btn_add.setStyleSheet("background:#1f6feb;color:#fff;padding:8px 14px;border-radius:6px;font-weight:600;")
    btn_revoke.setStyleSheet("background:#cf222e;color:#fff;padding:8px 14px;border-radius:6px;")
    btn_folder.setStyleSheet("padding:8px 12px;border-radius:6px;")
    top_row.addWidget(search_edit, 3)
    top_row.addWidget(btn_search, 1)
    top_row.addStretch(1)
    top_row.addWidget(btn_add); top_row.addWidget(btn_revoke); top_row.addWidget(btn_export); top_row.addWidget(btn_folder)
    root.addLayout(top_row)

    # 表格
    cols = ["创建日期", "用户标识", "机器码(后8位)", "来源", "金额", "状态", "打款单号(后6)", "备注(前20字)"]
    table = QTableWidget(0, len(cols)); table.setHorizontalHeaderLabels(cols)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.verticalHeader().setVisible(False)
    h = table.horizontalHeader()
    widths = [140, 180, 120, 150, 80, 80, 130]
    for i, w in enumerate(widths):
        h.resizeSection(i, w)
    h.setSectionResizeMode(len(cols)-1, QHeaderView.ResizeMode.Stretch)
    table.setAlternatingRowColors(True)
    table.setStyleSheet("""
        QTableWidget { gridline-color:#e6e8eb; }
        QHeaderView::section { background:#f5f7fa; padding:8px; border:0; border-bottom:1px solid #e6e8eb; font-weight:600; }
        QTableWidget::item { padding:6px 8px; }
    """)
    table.setProperty("row_id_map", {})  # row index → db id
    root.addWidget(table, 1)

    # 状态条
    bar = QStatusBar(); win.setStatusBar(bar)
    summary_label = QLabel(""); bar.addWidget(summary_label, 1)
    path_label = QLabel(""); bar.addPermanentWidget(path_label)

    SOURCE_LABEL_MAP = {k: v for k, v in SOURCE_OPTIONS}
    STATUS_LABEL = {"active": "✅ 生效中", "revoked": "🚫 已作废", "pending_issued": "⏳ 待发布"}

    def _refresh_summary():
        s = stats()
        rev = s["this_month_rev_cents"] / 100
        total_rev = s["total_rev_cents"] / 100
        manual_ratio = (s["manual_count"] / s["total_active"] * 100) if s["total_active"] else 0
        summary_label.setText(
            f"📊 本月：{s['this_month_count']} 笔 · 收入 ¥{rev:,.2f}   "
            f"🏦 累计：{s['total_active']} 生效 / {s['total_revoked']} 作废 · ¥{total_rev:,.2f}   "
            f"🔧 人工兜底占比：{manual_ratio:.0f}%（{s['manual_count']}/{s['total_active']}）"
        )
        path_label.setText(f"🗄 DB: {s['db_path']}")

    def _refresh_table():
        kw = search_edit.text().strip()
        rows = list_licenses(keyword=kw)
        table.setRowCount(len(rows))
        id_map: dict[int, int] = {}
        for i, r in enumerate(rows):
            id_map[i] = int(r["id"])
            def mk(text: str, is_red=False):
                item = QTableWidgetItem(str(text))
                if is_red:
                    item.setForeground(Qt.GlobalColor.darkRed)
                return item
            created_s = datetime.fromtimestamp(int(r["created_at"])).strftime("%Y-%m-%d %H:%M") if r["created_at"] else ""
            mc = (r["machine_code"] or "")
            mc_show = mc[-8:] if len(mc) >= 8 else mc
            source_show = SOURCE_LABEL_MAP.get(r["source"], r["source"])
            amount = f"¥{int(r['amount_cents'] or 0)/100:.2f}"
            status = STATUS_LABEL.get(r["status"], r["status"])
            pr = (r["payment_ref"] or "")
            pr_show = pr[-6:] if len(pr) >= 6 else pr
            note = (r["notes"] or "").replace("\n", " ")
            note_show = (note[:17] + "…") if len(note) > 20 else note
            is_revoked = r["status"] == "revoked"
            vals = [created_s, r["user_tag"] or "", mc_show, source_show, amount, status, pr_show, note_show]
            for j, v in enumerate(vals):
                item = mk(v, is_red=is_revoked)
                if j == 5 and not is_revoked:
                    item.setForeground(Qt.GlobalColor.darkGreen)
                table.setItem(i, j, item)
        table.setProperty("row_id_map", id_map)
        _refresh_summary()

    def _selected_db_id() -> int | None:
        r = table.currentRow()
        if r < 0:
            return None
        return int(table.property("row_id_map").get(r, 0)) or None

    # -------- 新增授权对话框 --------
    def _do_add():
        dlg = QDialog(win); dlg.setWindowTitle("➕ 新增授权 · 生成 .lic 文件")
        dlg.resize(520, 480)
        form = QFormLayout(dlg); form.setContentsMargins(20, 20, 20, 14); form.setSpacing(10)

        mc_edit = QLineEdit(); mc_edit.setPlaceholderText("A1B2-C3D4-E5F6-G7H8（用户发给你的机器码）")
        user_edit = QLineEdit(); user_edit.setPlaceholderText("昵称 / 微信ID / QQ（方便后续查）")
        src_combo = QComboBox()
        for v, label in SOURCE_OPTIONS:
            src_combo.addItem(label, v)
        src_combo.setCurrentIndex(1)  # 默认「虎皮椒补单」（人工兜底最高频的场景）
        ref_edit = QLineEdit(); ref_edit.setPlaceholderText("虎皮椒单号 / 微信/支付宝交易单号（对账用）")
        amount_spin = QSpinBox(); amount_spin.setRange(0, 999_000_00); amount_spin.setValue(29900)
        amount_spin.setSingleStep(100); amount_spin.setSuffix(" 分")  # 100 分 = 1 元
        amount_label = QLabel("＝ ¥0.00")
        def _sync_amt(v): amount_label.setText(f"＝ ¥{v/100:.2f}")
        amount_spin.valueChanged.connect(_sync_amt); _sync_amt(amount_spin.value())
        amt_row = QHBoxLayout(); amt_row.addWidget(amount_spin, 1); amt_row.addWidget(amount_label)
        amt_wrap = QWidget(); l = QVBoxLayout(amt_wrap); l.setContentsMargins(0,0,0,0); l.addLayout(amt_row)

        notes_edit = QPlainTextEdit(); notes_edit.setPlaceholderText("换电脑说明 / 赠码原因 / 投诉 / 倒卖封禁记录等，留空可")
        notes_edit.setFixedHeight(90)

        hint = QLabel("💡 同一台机器码不能重复生成「生效中」记录，会弹拦截。若确实是补码，请先作废旧记录。")
        hint.setStyleSheet("color:#92400e;background:#fffbe8;border:1px solid #fde68a;border-radius:6px;padding:8px 10px;")
        hint.setWordWrap(True)

        form.addRow("🔑 机器码 *", mc_edit)
        form.addRow("👤 用户标识", user_edit)
        form.addRow("🧾 来源 *", src_combo)
        form.addRow("💰 打款单号", ref_edit)
        form.addRow("🏷 实收金额 *", amt_wrap)
        form.addRow("📝 备注", notes_edit)
        form.addRow(hint)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("✅ 确认生成 .lic 文件")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        form.addRow(bb)

        def _ok():
            try:
                rec, out_path = create_license(
                    machine_code=mc_edit.text(),
                    user_tag=user_edit.text(),
                    source=src_combo.currentData(),
                    payment_ref=ref_edit.text(),
                    amount_cents=int(amount_spin.value()),
                    notes=notes_edit.toPlainText(),
                )
            except ValueError as e:
                QMessageBox.warning(dlg, "参数/拦截", str(e))
                return
            except Exception as e:  # noqa: BLE001
                QMessageBox.critical(dlg, "生成失败", f"{type(e).__name__}: {e}")
                return
            QMessageBox.information(
                dlg, "✅ 生成成功",
                f"记录 ID #{rec['id']} 已入库并备份。\n\n"
                f"🔑 激活码：{rec['license_key']}（已自动复制到剪贴板）\n"
                f"📄 授权文件：{out_path}\n\n"
                f"下一步：把这个 .lic 文件 QQ/微信 拖给用户，并告诉他 MVP → 激活弹窗 Tab2 → "
                f"【导入授权文件】选一下就行，1 秒生效。"
            )
            # 自动复制 .lic 文件绝对路径 + 激活码到剪贴板（方便用户二次粘贴给微信）
            cb: QClipboard | None = app.clipboard()
            if cb is not None:
                cb.setText(str(out_path))
            # 顺带打开文件所在文件夹并选中 .lic（Windows 资源管理器）
            try:
                import subprocess
                subprocess.Popen(f'explorer /select,"{out_path}"')
            except Exception:
                pass
            dlg.accept()

        bb.accepted.connect(_ok)
        bb.rejected.connect(dlg.reject)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            _refresh_table()

    # -------- 作废对话框 --------
    def _do_revoke():
        lid = _selected_db_id()
        if not lid:
            QMessageBox.information(win, "提示", "请先在列表里选中一行要作废的授权记录。")
            return
        row = row_to_dict(get_admin_conn().execute("SELECT * FROM admin_licenses WHERE id=?", (lid,)).fetchone())
        if not row:
            return
        dlg = QDialog(win); dlg.setWindowTitle("❌ 作废选中授权")
        dlg.resize(480, 260)
        f = QFormLayout(dlg); f.setContentsMargins(20, 20, 20, 14); f.setSpacing(10)
        info = QLabel(
            f"确认要作废以下授权？\n\n"
            f"  记录ID：#{row['id']}\n"
            f"  用户：{row['user_tag'] or '(未填)'}\n"
            f"  机器码：{row['machine_code']}\n"
            f"  激活码：{row['license_key']}\n"
            f"  来源：{SOURCE_LABEL_MAP.get(row['source'], row['source'])}\n"
            f"  创建时间：{datetime.fromtimestamp(int(row['created_at'])):%Y-%m-%d %H:%M:%S}"
        )
        info.setStyleSheet("background:#fff7ed;border:1px solid #fed7aa;border-radius:6px;padding:10px 12px;")
        info.setWordWrap(True)
        reason = QLineEdit(); reason.setPlaceholderText("作废原因：如 换电脑 / 退款 / 倒卖封禁 等")
        f.addRow(info)
        f.addRow("📝 作废原因", reason)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("确定作废")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        f.addRow(bb)

        def _ok():
            try:
                revoke_license(lid, reason=reason.text())
            except ValueError as e:
                QMessageBox.warning(dlg, "作废失败", str(e)); return
            except Exception as e:  # noqa: BLE001
                QMessageBox.critical(dlg, "作废失败", f"{type(e).__name__}: {e}"); return
            dlg.accept()
        bb.accepted.connect(_ok); bb.rejected.connect(dlg.reject)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            QMessageBox.information(win, "已作废", "选中的授权已作废，并自动做了一份 DB 备份。")
            _refresh_table()

    # -------- 导出 CSV --------
    def _do_export():
        try:
            out = export_csv()
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(win, "导出失败", f"{type(e).__name__}: {e}"); return
        # 让管理员再自选一个位置另存（方便直接放到桌面发给会计）
        default = str(Path.home() / "Desktop" / out.name)
        chosen, _ = QFileDialog.getSaveFileName(
            win, "另存到...（发给会计 / 自己对账放一份）", default, "CSV 表格 (*.csv)"
        )
        if chosen:
            try:
                shutil.copy2(out, chosen)
            except Exception as e:  # noqa: BLE001
                QMessageBox.warning(win, "另存失败", str(e))
                return
        QMessageBox.information(
            win, "✅ 导出完成",
            f"已导出全量账本：\n{out}\n\n可以用 Excel / WPS / 飞书多维表格 打开，utf-8 带 BOM，中文直接显示。\n"
            f"对账提示：本月收款合计（¥）− 虎皮椒后台收入合计 × 0.98 ≈ 0，差额大就是漏记或多记。"
        )

    def _do_open_folder():
        p = get_admin_home() / _OUTPUT_DIRNAME
        try:
            os.startfile(str(p))  # type: ignore[attr-defined]
        except Exception:
            QMessageBox.information(win, "目录", str(p))

    # 连接信号
    search_edit.returnPressed.connect(_refresh_table)
    btn_search.clicked.connect(_refresh_table)
    btn_add.clicked.connect(_do_add)
    btn_revoke.clicked.connect(_do_revoke)
    btn_export.clicked.connect(_do_export)
    btn_folder.clicked.connect(_do_open_folder)

    _refresh_table()
    # 每 60 秒自动刷新（防止另一处改了 DB 主窗口没反应；MVP 阶段管理员单机其实不需要，但顺手做了）
    t = QTimer(win); t.setInterval(60_000); t.timeout.connect(_refresh_table); t.start()

    # 菜单栏：快速导出/备份/关于
    menu = win.menuBar()
    act = menu.addMenu("⚙ 操作")
    a_export = QAction("📤 导出 CSV 对账", win); a_export.triggered.connect(_do_export); act.addAction(a_export)
    a_backup = QAction("💾 立即备份 DB（手动触发一份）", win)
    def _man_backup(): _backup_db(); QMessageBox.information(win, "备份完成", f"已备份到：{get_admin_home() / _BACKUP_DIRNAME}")
    a_backup.triggered.connect(_man_backup); act.addAction(a_backup)
    a_open_home = QAction("📂 打开管理员 Home 目录", win)
    def _open_home(): os.startfile(str(get_admin_home()))  # type: ignore[attr-defined]
    a_open_home.triggered.connect(_open_home); act.addAction(a_open_home)
    help_ = menu.addMenu("ℹ 帮助")
    a_about = QAction("关于", win)
    a_about.triggered.connect(lambda: QMessageBox.information(
        win, "关于",
        "阿维达授权管家 v1.0\n\n"
        "用途：管理员本机运营兜底激活（场景 A 虎皮椒补单 / 场景 B 私人转账）。\n"
        "账本文件：SQLite 单文件，每次写操作自动日期级备份，可放 OneDrive 同步。\n"
        "账本与用户端 MVP activation 共享同一套 HMAC 算法，生成的 .lic 文件可直接被 MVP 导入识别。",
    ))
    help_.addAction(a_about)

    win.show()
    return app.exec()


if __name__ == "__main__":
    # 写之前初始化一次 DB 连接，保证表结构就绪（GUI 启动后任何一个 action 其实也会自动触发）
    _ = get_admin_conn()
    sys.exit(_run_gui())
