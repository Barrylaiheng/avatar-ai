r"""SQLite 数据库管理（连接、建表、增量迁移、通用 DAO）。

存储位置：%APPDATA%\SCAI\scai_v1.db
迁移策略：按 ExperienceRecall 的教训 — 启动时读 PRAGMA table_info，
缺列就 ALTER TABLE ADD COLUMN，不做破坏性迁移。
"""

import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from contextlib import contextmanager

from .crypto import encrypt_secret, decrypt_secret


APP_DIR_ENVVAR = "SCAI_APP_DIR"       # 允许测试覆盖
DB_FILENAME = "scai_v1.db"


def get_app_dir() -> Path:
    r"""返回应用数据目录（%APPDATA%\SCAI），不存在则创建。"""
    override = os.environ.get(APP_DIR_ENVVAR)
    if override:
        base = Path(override)
    else:
        appdata = os.environ.get("APPDATA")
        if not appdata:
            raise RuntimeError("APPDATA 环境变量未设置")
        base = Path(appdata) / "SCAI"
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_db_path() -> Path:
    return get_app_dir() / DB_FILENAME


# ====== 连接管理（单线程创建，多线程锁保护） ======
_LOCK = threading.Lock()
_CONN: sqlite3.Connection | None = None


def _create_connection() -> sqlite3.Connection:
    """创建新的 SQLite 连接（启用外键、行工厂、WAL）。"""
    path = get_db_path()
    conn = sqlite3.connect(str(path), check_same_thread=False, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def get_conn() -> sqlite3.Connection:
    """获取全局单例连接（首次调用时建表迁移）。"""
    global _CONN
    with _LOCK:
        if _CONN is None:
            _CONN = _create_connection()
            _ensure_schema(_CONN)
        return _CONN


def reset_db_for_tests():
    """测试专用：关闭并清除全局连接（仅测试环境使用）。"""
    global _CONN
    with _LOCK:
        if _CONN is not None:
            try:
                _CONN.close()
            except Exception:
                pass
            _CONN = None


@contextmanager
def transaction(checkpoint: bool = False):
    """事务上下文（失败回滚）。

    Args:
        checkpoint: True 时 commit 后强制 WAL checkpoint（把 WAL 刷回主 db），
                    用于 delete agent 等关键写操作，防止 crash 丢数据。
                    默认 False（性能优先）。
    """
    conn = get_conn()
    try:
        yield conn
        conn.commit()
        if checkpoint:
            try:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception:
                pass
    except Exception:
        conn.rollback()
        raise


# ====== 表结构定义（v1.0 初始版本） ======
# 采用 "列名→SQL 声明" 字典，便于增量比较与 ALTER。
_TABLES: dict[str, dict[str, str]] = {
    # LLM 配置（用户可保存多组）
    "llm_config": {
        "id":           "TEXT PRIMARY KEY",
        "name":         "TEXT NOT NULL",                 # 名称（如「工作号-深度求索」）
        "provider":     "TEXT NOT NULL",                 # 服务商（DeepSeek/OpenAI/自定义…）
        "base_url":     "TEXT NOT NULL DEFAULT ''",      # API 接口地址
        "api_key":      "TEXT NOT NULL DEFAULT ''",      # API 密钥（DPAPI 加密后入库）
        "model":        "TEXT NOT NULL DEFAULT ''",      # 模型名称
        "is_default":   "INTEGER NOT NULL DEFAULT 0",    # 是否默认 0/1
        "created_at":   "INTEGER NOT NULL",
        "updated_at":   "INTEGER NOT NULL",
    },

    # 智能体/人设
    "ai_agent": {
        "id":           "TEXT PRIMARY KEY",
        "name":         "TEXT NOT NULL",                 # 智能体名称
        "avatar":       "TEXT NOT NULL DEFAULT ''",      # 头像 emoji
        "description":  "TEXT NOT NULL DEFAULT ''",      # 一句话简介
        "system_prompt":"TEXT NOT NULL DEFAULT ''",      # 系统提示词
        "agent_type":   "TEXT NOT NULL DEFAULT 'default'", # 智能体类型（digital_clone/customer_service等）
        "style":        "TEXT NOT NULL DEFAULT ''",      # 回复风格
        "memories":     "TEXT NOT NULL DEFAULT ''",      # 长期记忆（JSON 字符串）
        "aigc_enabled": "INTEGER NOT NULL DEFAULT 1",    # 渠道消息是否加 AIGC 标识
        "emoji_enabled": "INTEGER NOT NULL DEFAULT 1",   # 是否允许 AI 使用 Emoji
        "llm_config_id":"TEXT DEFAULT NULL",             # 使用的 LLM 配置 id，空=全局默认
        "kb_ids":       "TEXT NOT NULL DEFAULT '[]'",    # 绑定的知识库 id 列表（JSON）
        "kb_enabled":   "INTEGER NOT NULL DEFAULT 1",    # 知识库 RAG 总开关（关了就不做 RAG 检索）
        "rate_profile": "TEXT NOT NULL DEFAULT '{\"level\":\"conservative\"}'", # 风控保护档位（JSON）
        "last_memory_refine_at": "INTEGER DEFAULT 0",  # 上次全量记忆整理时间戳（24小时机制）
        "oa_auto_enable": "INTEGER NOT NULL DEFAULT 0", # 服务号自动托管：新关注用户自动绑定本智能体
        "non_text_notice": "INTEGER NOT NULL DEFAULT 1", # 非文字内容标识：非文本消息自动回复提示语
        "content_formats": "TEXT NOT NULL DEFAULT '{\"text\":true,\"voice\":true,\"image\":false,\"video\":false,\"file\":false}'", # 内容形式开关（JSON）
        "channel":      "TEXT NOT NULL DEFAULT ''",      # 锁定的连接渠道：wcf/oa/wecom/feishu/dingtalk，空=未锁定（老数据）
        "created_at":   "INTEGER NOT NULL",
        "updated_at":   "INTEGER NOT NULL",
    },

    # 知识库
    "knowledge_base": {
        "id":           "TEXT PRIMARY KEY",
        "name":         "TEXT NOT NULL",
        "description":  "TEXT NOT NULL DEFAULT ''",
        "icon":         "TEXT NOT NULL DEFAULT '📚'",
        "doc_count":    "INTEGER NOT NULL DEFAULT 0",    # 文档数（冗余，避免实时 COUNT）
        "chunk_count":  "INTEGER NOT NULL DEFAULT 0",    # 切片数（冗余）
        "source_type":  "TEXT NOT NULL DEFAULT 'wiki'",  # wiki/manual/file 预留（旧字段，兼容已有）
        "kb_type":      "TEXT NOT NULL DEFAULT 'document'", # 类型：organized(整理型Wiki) / document(资料型RAG) / mixed(混合型)
        "created_at":   "INTEGER NOT NULL",
        "updated_at":   "INTEGER NOT NULL",
    },

    # 文档（归属某个知识库）
    "kb_document": {
        "id":           "TEXT PRIMARY KEY",
        "kb_id":        "TEXT NOT NULL REFERENCES knowledge_base(id) ON DELETE CASCADE",
        "name":         "TEXT NOT NULL",
        "file_path":    "TEXT NOT NULL DEFAULT ''",      # 源文件物理路径
        "size_bytes":   "INTEGER NOT NULL DEFAULT 0",
        "chunk_count":  "INTEGER NOT NULL DEFAULT 0",
        "status":       "TEXT NOT NULL DEFAULT 'pending'", # pending/parsing/done/failed
        "error":        "TEXT NOT NULL DEFAULT ''",
        "created_at":   "INTEGER NOT NULL",
        "updated_at":   "INTEGER NOT NULL",
    },

    # 文档切片（归属某个文档，存储切片文本 + 向量 + Token）
    "kb_chunk": {
        "id":           "TEXT PRIMARY KEY",
        "doc_id":       "TEXT NOT NULL REFERENCES kb_document(id) ON DELETE CASCADE",
        "kb_id":        "TEXT NOT NULL REFERENCES knowledge_base(id) ON DELETE CASCADE",
        "sort_order":   "INTEGER NOT NULL DEFAULT 0",    # 原文顺序（用于拼接上下文）
        "content":      "TEXT NOT NULL",                  # 切片文本
        "char_count":   "INTEGER NOT NULL DEFAULT 0",
        "token_count":  "INTEGER NOT NULL DEFAULT 0",
        "vector":       "BLOB DEFAULT NULL",              # 向量（二进制，预留）
        "created_at":   "INTEGER NOT NULL",
    },

    # 渠道连接状态（全局：WCF/公众号…）
    "channel_connection": {
        "channel":      "TEXT PRIMARY KEY",              # wcf / oa_cloud
        "connected":    "INTEGER NOT NULL DEFAULT 0",
        "config_json":  "TEXT NOT NULL DEFAULT '{}'",    # 渠道私有配置（JSON）
        "last_check":   "INTEGER NOT NULL DEFAULT 0",
        "error":        "TEXT NOT NULL DEFAULT ''",
    },

    # 智能体 × 渠道 × 好友/群聊 的绑定（渠道配置弹窗里的勾选表）
    "channel_binding": {
        "id":           "TEXT PRIMARY KEY",
        "agent_id":     "TEXT NOT NULL REFERENCES ai_agent(id) ON DELETE CASCADE",
        "channel":      "TEXT NOT NULL",                 # wcf/oa_cloud
        "peer_id":      "TEXT NOT NULL",                 # 好友 id / 群 id / openid
        "peer_name":    "TEXT NOT NULL DEFAULT ''",
        "peer_type":    "TEXT NOT NULL DEFAULT 'friend'",# friend/group/official
        "enabled":      "INTEGER NOT NULL DEFAULT 1",    # 勾选启用
        "is_manager":   "INTEGER NOT NULL DEFAULT 0",    # 管理者标记 0/1
        "created_at":   "INTEGER NOT NULL",
        "updated_at":   "INTEGER NOT NULL",
    },
    # (agent_id, channel, peer_id) 组合唯一
    "__idx_channel_binding_uniq": "UNIQUE (agent_id, channel, peer_id)",

    # 激活状态（单行表）
    "activation": {
        "id":           "TEXT PRIMARY KEY",              # 固定 'singleton'
        "activated":    "INTEGER NOT NULL DEFAULT 0",
        "license_key":  "TEXT NOT NULL DEFAULT ''",      # 激活码（DPAPI 加密）
        "machine_code": "TEXT NOT NULL DEFAULT ''",
        "activated_at": "INTEGER NOT NULL DEFAULT 0",
        "trial_used":   "INTEGER NOT NULL DEFAULT 0",    # 试用已用对话次数
        "trial_limit":  "INTEGER NOT NULL DEFAULT 50",
        "updated_at":   "INTEGER NOT NULL DEFAULT 0",
    },

    # 虎皮椒支付订单（订单留痕 + 回调/轮询状态流转 + 对账）
    "activation_orders": {
        "id":                "TEXT PRIMARY KEY",                    # 我们的 out_trade_no（AVT开头）
        "xunhu_order_id":    "TEXT NOT NULL DEFAULT ''",            # 虎皮椒官方 orderid（openid 返回值）
        "transaction_id":    "TEXT NOT NULL DEFAULT ''",            # 交易流水号（微信官方/虎皮椒）
        "machine_code":      "TEXT NOT NULL DEFAULT ''",            # 绑定的机器码
        "amount_cents":      "INTEGER NOT NULL DEFAULT 0",          # 支付金额（分，29900）
        "amount_yuan":       "REAL NOT NULL DEFAULT 0.0",           # 冗余：元（299.00）
        "status":            "TEXT NOT NULL DEFAULT 'created'",     # created / pending / paid / expired / failed / refunded
        "mode":              "TEXT NOT NULL DEFAULT 'mock'",        # mock / real
        "goods_name":        "TEXT NOT NULL DEFAULT ''",            # 订单标题
        "attach_json":       "TEXT NOT NULL DEFAULT '{}'",          # 其他冗余（虎皮椒返回值存个 json 快照，方便对账）
        "license_key":       "TEXT NOT NULL DEFAULT ''",            # 若已生成激活码，存加密后的值（便于留痕）
        "qr_url":            "TEXT NOT NULL DEFAULT ''",            # 二维码内容，留痕
        "notify_raw":        "TEXT NOT NULL DEFAULT ''",            # 回调的原始 body（最后一次），备查
        "notify_attempts":   "INTEGER NOT NULL DEFAULT 0",          # 回调到达次数
        "notify_verified":   "INTEGER NOT NULL DEFAULT 0",          # 回调最后一次是否验签通过（0/1）
        "created_at":        "INTEGER NOT NULL DEFAULT 0",
        "expires_at":        "INTEGER NOT NULL DEFAULT 0",
        "paid_at":           "INTEGER NOT NULL DEFAULT 0",
        "updated_at":        "INTEGER NOT NULL DEFAULT 0",
    },
    "__idx_act_orders_machine":  "INDEX idx_orders_machine ON activation_orders(machine_code)",
    "__idx_act_orders_status":   "INDEX idx_orders_status  ON activation_orders(status)",
    "__idx_act_orders_paid":     "INDEX idx_orders_paid    ON activation_orders(paid_at)",

    # 对话会话（每次和某个智能体的对话是一个会话）
    "conversation": {
        "id":           "TEXT PRIMARY KEY",
        "agent_id":     "TEXT NOT NULL REFERENCES ai_agent(id) ON DELETE CASCADE",
        "channel":      "TEXT NOT NULL DEFAULT 'wcf'",    # wcf / oa 等渠道标识
        "peer_id":      "TEXT NOT NULL DEFAULT ''",       # 好友id/群id/openid
        "peer_name":    "TEXT NOT NULL DEFAULT ''",       # 对方显示名
        "peer_type":    "TEXT NOT NULL DEFAULT 'friend'", # friend/group/official
        "title":        "TEXT NOT NULL DEFAULT ''",      # 会话标题（自动取首条消息摘要）
        "message_count":"INTEGER NOT NULL DEFAULT 0",     # 消息数（冗余计数）
        "migrated_from":"TEXT DEFAULT NULL",               # 搬迁来源 agent_id（抢占替换时记录，导入后置空）
        "created_at":   "INTEGER NOT NULL",
        "updated_at":   "INTEGER NOT NULL",
    },

    # 对话消息（归属某个会话）
    "chat_message": {
        "id":           "TEXT PRIMARY KEY",
        "conversation_id": "TEXT NOT NULL REFERENCES conversation(id) ON DELETE CASCADE",
        "role":         "TEXT NOT NULL",                 # user / assistant / system
        "content":      "TEXT NOT NULL",
        "tokens":       "INTEGER NOT NULL DEFAULT 0",
        "aigc_marked":  "INTEGER NOT NULL DEFAULT 0",    # 是否加了 AIGC 标识
        "channel":      "TEXT NOT NULL DEFAULT 'wcf'",   # 消息来源渠道（冗余便于历史检索）
        "model":        "TEXT NOT NULL DEFAULT ''",      # assistant 回复所用模型
        "created_at":   "INTEGER NOT NULL",
    },

    # 风控配置（单行表，账号级，所有智能体共用一套策略）
    "risk_config": {
        "id":           "TEXT PRIMARY KEY",              # 固定 'singleton'
        "level":        "TEXT NOT NULL DEFAULT 'conservative'", # 风险等级：ultra_safe/conservative/balanced/aggressive
        "auto_adjust":  "INTEGER NOT NULL DEFAULT 1",    # 自动降速开关
        "busy_prob":    "INTEGER NOT NULL DEFAULT 1",    # 忙碌概率模拟开关
        "leak_back":    "INTEGER NOT NULL DEFAULT 1",    # 漏回模拟开关
        "health_score": "INTEGER NOT NULL DEFAULT 100",  # 账号健康度（0-100）
        "updated_at":   "INTEGER NOT NULL DEFAULT 0",
    },

    # per-peer 画像（双层 profile 架构的第二层）
    # scope = UNIQUE(channel, peer_id)：一个渠道一个 peer 一份画像，物理保证不分裂
    "peer_profile": {
        "id":           "TEXT PRIMARY KEY",
        "channel":      "TEXT NOT NULL",                  # wcf / oa / wecom / feishu / dingtalk
        "peer_id":      "TEXT NOT NULL",                  # 好友id/群id/openid
        "peer_name":    "TEXT NOT NULL DEFAULT ''",
        "role":         "TEXT NOT NULL DEFAULT 'user'",   # 'user' | 'manager'
        "memories":     "TEXT NOT NULL DEFAULT '{}'",     # JSON: { enabled, user_profile: [], episodic: [] }
        "last_refine_at":"INTEGER NOT NULL DEFAULT 0",
        "created_at":   "INTEGER NOT NULL DEFAULT 0",
        "updated_at":   "INTEGER NOT NULL DEFAULT 0",
        "__idx_peer_profile_uniq": "UNIQUE (channel, peer_id)",
    },

    # ===== APP 应用集成（新增表）=====
    **{
        # 智能体已安装的 APP（app_id 对应开放平台应用）
        "agent_app": {
            "agent_id":     "TEXT NOT NULL REFERENCES ai_agent(id) ON DELETE CASCADE",
            "app_id":       "TEXT NOT NULL",
            "enabled":      "INTEGER NOT NULL DEFAULT 1",
            "config_json":  "TEXT NOT NULL DEFAULT '{}'",
            "installed_at": "INTEGER NOT NULL",
            "updated_at":   "INTEGER NOT NULL",
            "__idx_agent_app_pk": "PRIMARY KEY (agent_id, app_id)",
        },
        # APP 凭据（单行键值对）
        "app_credential": {
            "credential_key": "TEXT PRIMARY KEY",
            "value":          "TEXT NOT NULL DEFAULT ''",
            "updated_at":     "INTEGER NOT NULL",
        },
        # 定时任务（APP 驱动的定时内容投放）
        "scheduled_job": {
            "job_id":           "TEXT PRIMARY KEY",
            "app_id":           "TEXT NOT NULL DEFAULT ''",
            "agent_id":         "TEXT NOT NULL REFERENCES ai_agent(id) ON DELETE CASCADE",
            "name":             "TEXT NOT NULL",
            "cron_expr":        "TEXT NOT NULL",
            "content_template": "TEXT NOT NULL",
            "target_json":      "TEXT NOT NULL",
            "timezone":         "TEXT NOT NULL DEFAULT 'Asia/Shanghai'",
            "enabled":          "INTEGER NOT NULL DEFAULT 1",
            "last_run_at":      "INTEGER",
            "next_run_at":      "INTEGER",
            "created_at":       "INTEGER NOT NULL",
            "updated_at":       "INTEGER NOT NULL",
        },
    },
}


def _create_table(conn: sqlite3.Connection, table: str, columns: dict[str, str]):
    """按列定义建表或执行增量迁移。"""
    # 1) 建表（若不存在）
    col_sql_parts = []
    index_sqls: list[str] = []
    for name, decl in columns.items():
        if name.startswith("__idx_"):
            # 伪列：索引/唯一约束声明（只在建表期附加到 CREATE 里）
            col_sql_parts.append(decl)
        else:
            col_sql_parts.append(f'"{name}" {decl}')
    sql = f'CREATE TABLE IF NOT EXISTS "{table}" (\n  ' + ",\n  ".join(col_sql_parts) + "\n)"
    conn.execute(sql)

    # 2) 读现有列，缺列则 ADD COLUMN（增量迁移核心）
    existing = {row["name"] for row in conn.execute(f'PRAGMA table_info("{table}")')}
    for name, decl in columns.items():
        if name.startswith("__idx_"):
            continue
        if name not in existing:
            try:
                conn.execute(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {decl}')
                print(f"[DB] ALTER TABLE {table} ADD COLUMN {name}", flush=True)
            except sqlite3.OperationalError as e:
                # 极个别情况（UNIQUE 列在老 SQLite 版本不允许 ADD）
                print(f"[DB] WARN ALTER TABLE {table} {name} 失败: {e}", flush=True)


def _ensure_schema(conn: sqlite3.Connection):
    """确保所有表 + 单列迁移完成。"""
    for table, columns in _TABLES.items():
        if table.startswith("__"):
            continue
        _create_table(conn, table, columns)
    conn.commit()


# ====== 通用辅助 ======
def new_id(prefix: str) -> str:
    """生成类似 'agent_8f3a...' 的可辨识 ID。"""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def now_ts() -> int:
    return int(time.time())


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    """把 sqlite3.Row / dict / None / 意外对象 统一成纯 dict 或 None。

    历史修复（2026-08-29）：
      - 之前写法是 `return dict(row) if row else None`，如果调用者误传了一个已经是 dict
        的对象（如 rows_to_dict_list(list_of_dict) 这种「双重调用」场景），`dict(a_dict)`
        没问题。但如果上游是「某条意外字符串」，`dict(a_str)` 会把字符拆成 Unicode 码位
        的 key→value 垃圾字典；对于 bytes/int 这种不可迭代标量会直接抛 ValueError。
      - 现在显式按类型分支：
          * dict → copy 一份返回（避免上游修改污染原对象）
          * sqlite3.Row → dict(row)
          * None → None
          * 其它有 keys() + __getitem__ 的 Mapping-like → 遍历转 dict
          * 其它任何类型 → None（调用方的 if row 判断会正常跳过）
    """
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    if isinstance(row, sqlite3.Row):
        return dict(row)
    # 常见的 Mapping-like 对象：UserDict / OrderedDict / pydantic V1/V2 Model 部分模式
    keys_fn = getattr(row, "keys", None)
    if callable(keys_fn):
        try:
            out = {}
            for k in keys_fn():
                try:
                    out[k] = row[k]
                except Exception:
                    continue
            return out
        except Exception:
            return None
    # 其余标量（str/bytes/int/float/list/tuple/set/...）一律 None，不帮它"硬转"
    return None


def rows_to_dict_list(rows) -> list[dict]:
    """列表版 row_to_dict。

    兼容两种调用风格：
      1) DB fetchall() → [sqlite3.Row, ...]  → 正常转 list[dict]
      2) 双重调用（上层已经转 dict 又误调一次）→ list[dict] 原样拷贝，不崩
      3) rows 里混入 str / int / None 等非映射 → 静默丢弃（不抛错）
    """
    if not rows:
        return []
    out = []
    for r in rows:
        d = row_to_dict(r)
        if d is None:
            continue
        out.append(d)
    return out
