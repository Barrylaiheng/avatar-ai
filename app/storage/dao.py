"""数据访问层 DAO — 针对各表的薄封装。

设计原则：
- 每个 DAO 方法职责单一（增删改查 + 一两个常用组合查询）
- 写操作默认调用处显式事务包裹（get_conn 已打开）
- BridgeServer 层负责敏感字段加解密，DAO 只收已加密的 api_key/license_key
"""

from __future__ import annotations
import json

# 渠道能力表（后端版）：channel（后端渠道号）→ 各格式的 lock 默认值
# 与前端 _FMT_BY_CHAN 一一对应，但用后端渠道号（wcf / oa / wecom / feishu / dingtalk）
_CHANNEL_CF_DEFAULTS = {
    #           voice  file   image  video
    "wcf":     {"voice": False, "file": False, "image": False, "video": False},  # 微信
    "oa":      {"voice": False, "file": False, "image": False, "video": False},  # 服务号（file lock 不勾）
    "wecom":   {"voice": True,  "file": False, "image": False, "video": False},  # 企微
    "feishu":  {"voice": True,  "file": False, "image": False, "video": False},  # 飞书
    "dingtalk":{"voice": True,  "file": False, "image": False, "video": False},  # 钉钉
}
# 后端版：服务号 file lock 不勾
_CHANNEL_CF_LOCKED = {
    "oa": {"file": False},  # 服务号文件不支持，lock 不勾
}


def normalize_content_formats(content_formats: str | dict, channel: str) -> str:
    """按渠道强制修正 content_formats 里 lock 字段的值。

    后端强制保证 lock 字段永远和渠道能力表一致，避免 DB 脏数据。
    前端用户勾选不生效的 lock 字段（voice 反选）会被覆盖回去。
    """
    if isinstance(content_formats, str):
        try:
            cf = json.loads(content_formats)
        except Exception:
            cf = {}
    else:
        cf = dict(content_formats or {})

    cf.setdefault("text", True)  # text 永远 True

    # 1) 按渠道修正 voice
    defaults = _CHANNEL_CF_DEFAULTS.get(channel, _CHANNEL_CF_DEFAULTS["wcf"])
    cf["voice"] = defaults["voice"]
    cf.setdefault("image", defaults["image"])
    cf.setdefault("video", defaults["video"])
    cf.setdefault("file", defaults["file"])

    # 2) 渠道特有 lock 规则（服务号 file 不支持）
    locked = _CHANNEL_CF_LOCKED.get(channel, {})
    for k, v in locked.items():
        cf[k] = v

    return json.dumps(cf, ensure_ascii=False)
from .db import (
    get_conn,
    transaction,
    new_id,
    now_ts,
    row_to_dict,
    rows_to_dict_list,
)
from .crypto import encrypt_secret, decrypt_secret


# ====== LLM 配置 ======
class LLMConfigDAO:
    def list_all(self) -> list[dict]:
        rows = get_conn().execute(
            "SELECT * FROM llm_config ORDER BY is_default DESC, updated_at DESC"
        ).fetchall()
        out = rows_to_dict_list(rows)
        for o in out:
            o["api_key"] = decrypt_secret(o.get("api_key", ""))
        return out

    def get_default(self) -> dict | None:
        row = get_conn().execute(
            "SELECT * FROM llm_config WHERE is_default = 1 LIMIT 1"
        ).fetchone()
        if not row:
            # 没默认的，取最新一条
            row = get_conn().execute(
                "SELECT * FROM llm_config ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
        if not row:
            return None
        o = row_to_dict(row)
        o["api_key"] = decrypt_secret(o.get("api_key", ""))
        return o

    def get(self, cfg_id: str) -> dict | None:
        row = get_conn().execute(
            'SELECT * FROM llm_config WHERE id = ?', (cfg_id,)
        ).fetchone()
        if not row:
            return None
        o = row_to_dict(row)
        o["api_key"] = decrypt_secret(o.get("api_key", ""))
        return o

    def upsert(self, data: dict) -> dict:
        """新增或更新 LLM 配置；若 is_default=True，则清掉其他默认。

        data 字段: id?/name/provider/base_url/api_key(明文)/model/is_default
        """
        conn = get_conn()
        cfg_id = data.get("id") or new_id("llm")
        name = data["name"].strip()
        provider = data.get("provider", "custom")
        base_url = data.get("base_url", "").strip()
        api_key_raw = data.get("api_key", "") or ""
        api_key_enc = encrypt_secret(api_key_raw)
        model = data.get("model", "").strip()
        is_default = 1 if data.get("is_default") else 0
        ts = now_ts()

        with transaction():
            if is_default:
                conn.execute("UPDATE llm_config SET is_default = 0, updated_at = ?", (ts,))
            exists = conn.execute('SELECT 1 FROM llm_config WHERE id = ?', (cfg_id,)).fetchone()
            if exists:
                conn.execute(
                    """UPDATE llm_config
                       SET name=?, provider=?, base_url=?, api_key=?, model=?,
                           is_default=?, updated_at=?
                       WHERE id=?""",
                    (name, provider, base_url, api_key_enc, model, is_default, ts, cfg_id),
                )
            else:
                conn.execute(
                    """INSERT INTO llm_config
                       (id, name, provider, base_url, api_key, model, is_default, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (cfg_id, name, provider, base_url, api_key_enc, model, is_default, ts, ts),
                )
        return self.get(cfg_id) or {"id": cfg_id}

    def delete(self, cfg_id: str) -> bool:
        with transaction():
            cur = get_conn().execute('DELETE FROM llm_config WHERE id = ?', (cfg_id,))
            return cur.rowcount > 0


# ====== 智能体 ======
class AgentsDAO:
    def list_all(self) -> list[dict]:
        rows = get_conn().execute(
            "SELECT * FROM ai_agent ORDER BY created_at ASC"
        ).fetchall()
        return rows_to_dict_list(rows)

    def get(self, agent_id: str) -> dict | None:
        row = get_conn().execute(
            'SELECT * FROM ai_agent WHERE id = ?', (agent_id,)
        ).fetchone()
        return row_to_dict(row)

    def ensure_unique_name(self, name: str, exclude_id: str | None = None) -> str:
        """确保智能体名称唯一，重名自动加 (1)(2) 后缀。

        例：DB 已有 "小雨"、"小雨(1)"，新建传 "小雨" → 返回 "小雨(2)"。
        """
        base = name.strip()
        if not base:
            return base
        conn = get_conn()
        rows = conn.execute(
            'SELECT name FROM ai_agent WHERE id != ?',
            (exclude_id or '',),
        ).fetchall()
        existing = {r[0] for r in rows}
        if base not in existing:
            return base
        # 已有同名 → 从 (1) 开始试，直到找到空位
        i = 1
        while f'{base}({i})' in existing:
            i += 1
        return f'{base}({i})'

    def list_by_name(self, name: str) -> list:
        rows = get_conn().execute(
            'SELECT * FROM ai_agent WHERE name = ?', (name,)
        ).fetchall()
        return [row_to_dict(r) for r in rows]

    def create(self, data: dict) -> dict:
        conn = get_conn()
        aid = data.get("id") or new_id("agent")
        # 重名自动加后缀（创建时 exclude_id 为空串，不会误伤）
        data["name"] = self.ensure_unique_name(data.get("name", ""), exclude_id="")
        name = data["name"].strip()
        avatar = data.get("avatar", "") or "🤖"
        description = data.get("description", "") or ""
        system_prompt = data.get("system_prompt", "") or ""
        agent_type = data.get("agent_type", "") or "default"
        style = data.get("style", "") or ""
        memories = data.get("memories", "") or ""
        aigc_enabled = 1 if data.get("aigc_enabled", 1) else 0
        emoji_enabled = 1 if data.get("emoji_enabled", 1) else 0
        non_text_notice = 1 if data.get("non_text_notice", 1) else 0
        llm_config_id = data.get("llm_config_id") or None
        kb_ids = json.dumps(data.get("kb_ids") or [], ensure_ascii=False)
        kb_enabled = 1 if data.get("kb_enabled", 1) else 0
        rate_profile = json.dumps(data.get("rate_profile") or {"level": "conservative"}, ensure_ascii=False)
        channel = data.get("channel", "") or ""
        content_formats = normalize_content_formats(
            data.get("content_formats") or '{"text":true,"voice":true,"image":false,"video":false,"file":false}',
            channel,
        )
        active = 1 if data.get("active", 1) else 0
        ts = now_ts()
        with transaction():
            conn.execute(
                """INSERT INTO ai_agent
                   (id, name, avatar, description, system_prompt, agent_type, style, memories,
                    aigc_enabled, emoji_enabled, non_text_notice, llm_config_id, kb_ids, kb_enabled, rate_profile, channel, content_formats, active, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (aid, name, avatar, description, system_prompt, agent_type, style, memories,
                 aigc_enabled, emoji_enabled, non_text_notice, llm_config_id, kb_ids, kb_enabled, rate_profile, channel, content_formats, active, ts, ts),
            )
        return self.get(aid)

    def update(self, agent_id: str, data: dict) -> dict | None:
        existing = self.get(agent_id)
        if not existing:
            return None
        # 重名避让：如果 payload 带了 name，先检查唯一性（exclude_id=自己，避免误伤）
        if "name" in data:
            data["name"] = self.ensure_unique_name(data["name"], exclude_id=agent_id)

        # 如果改了 channel 或 content_formats，必须 normalize 确保 lock 字段和渠道能力一致
        if "channel" in data or "content_formats" in data:
            chan = data.get("channel") or existing.get("channel", "") or ""
            raw_cf = data.get("content_formats") or existing.get("content_formats") or ""
            data["content_formats"] = normalize_content_formats(raw_cf, chan)

        sets, args = [], []
        allow_keys = {
            "name", "avatar", "description", "system_prompt", "agent_type", "style",
            "memories", "aigc_enabled", "emoji_enabled", "llm_config_id", "kb_ids",
            "kb_enabled", "rate_profile", "last_memory_refine_at", "oa_auto_enable",
            "non_text_notice", "channel", "content_formats", "active",
        }
        for k, v in data.items():
            if k not in allow_keys:
                continue
            sets.append(f'"{k}" = ?')
            if k in ("kb_ids", "rate_profile") and isinstance(v, (list, dict, tuple)):
                args.append(json.dumps(v, ensure_ascii=False))
            elif k in ("aigc_enabled", "emoji_enabled", "oa_auto_enable", "non_text_notice", "kb_enabled", "active"):
                args.append(1 if v else 0)
            else:
                args.append(v)
        if not sets:
            return self.get(agent_id)
        sets.append('updated_at = ?')
        args.append(now_ts())
        args.append(agent_id)
        with transaction():
            get_conn().execute(
                f'UPDATE ai_agent SET {", ".join(sets)} WHERE id = ?', args
            )
        return self.get(agent_id)

    def rename(self, agent_id: str, new_name: str) -> dict | None:
        return self.update(agent_id, {"name": new_name.strip()})

    def delete(self, agent_id: str) -> bool:
        """删除智能体：级联清理所有关联数据，防止孤儿记录 + 审计日志"""
        import os, time, json, traceback
        from storage.db import get_conn as _gc

        # --- 审计日志（删之前先记下来，防止误删了找不回） ---
        try:
            audit_dir = os.path.join(os.environ.get("APPDATA", ""), "SCAI")
            os.makedirs(audit_dir, exist_ok=True)
            audit_file = os.path.join(audit_dir, "audit.log")
            agent_row = _gc().execute(
                "SELECT id, name, channel, created_at FROM ai_agent WHERE id = ?", (agent_id,)
            ).fetchone()
            snapshot = dict(agent_row) if agent_row else {}
            with open(audit_file, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "ts": int(time.time()), "op": "delete_agent",
                    "agent": snapshot
                }, ensure_ascii=False) + "\n")
        except Exception:
            pass  # 审计写失败不影响主流程

        with transaction(checkpoint=True):  # ★ 关键操作：commit 后强制 WAL checkpoint
            conn = _gc()
            # 1) 先清 chat_message（conversation 还没删，靠 conversation_id 关联）
            conn.execute(
                """DELETE FROM chat_message
                   WHERE conversation_id IN (
                       SELECT id FROM conversation WHERE agent_id = ?
                   )""", (agent_id,)
            )
            # 2) 清 conversation
            conn.execute("DELETE FROM conversation WHERE agent_id = ?", (agent_id,))
            # 3) 清 channel_binding
            conn.execute("DELETE FROM channel_binding WHERE agent_id = ?", (agent_id,))
            # 4) 清 peer_profile 里这个 agent 关联的条目（peer_profile 没有 agent_id 字段，按 channel 关联）
            try:
                conn.execute("DELETE FROM peer_profile WHERE agent_id = ?", (agent_id,))
            except Exception:
                pass  # peer_profile 没 agent_id 字段就跳过
            # 5) 清 agent_app 关联（表或字段不存在时兜底跳过）
            try:
                conn.execute("DELETE FROM agent_app WHERE agent_id = ?", (agent_id,))
            except Exception:
                pass
            # 6) 清 scheduled_job 关联（表或字段不存在时兜底跳过）
            try:
                conn.execute("DELETE FROM scheduled_job WHERE agent_id = ?", (agent_id,))
            except Exception:
                pass
            # 7) 最后删 ai_agent 本体
            cur = conn.execute("DELETE FROM ai_agent WHERE id = ?", (agent_id,))
            return cur.rowcount > 0


# ====== 知识库 ======
class KnowledgeBaseDAO:
    def list_all(self) -> list[dict]:
        rows = get_conn().execute(
            "SELECT * FROM knowledge_base ORDER BY updated_at DESC"
        ).fetchall()
        return rows_to_dict_list(rows)

    def get(self, kb_id: str) -> dict | None:
        row = get_conn().execute(
            'SELECT * FROM knowledge_base WHERE id = ?', (kb_id,)
        ).fetchone()
        return row_to_dict(row)

    def create(self, data: dict) -> dict:
        conn = get_conn()
        kid = data.get("id") or new_id("kb")
        name = data["name"].strip()
        description = data.get("description", "") or ""
        icon = data.get("icon", "") or "📚"
        source_type = data.get("source_type", "wiki")
        kb_type = data.get("kb_type", "document")  # organized / document / mixed
        # 类型和 icon 同步（整理型=📚 / 资料型=📄 / 混合型=📒）
        if not data.get("icon"):
            icon = {"organized": "📚", "document": "📄", "mixed": "📒"}.get(kb_type, "📚")
        ts = now_ts()
        with transaction():
            conn.execute(
                """INSERT INTO knowledge_base
                   (id, name, description, icon, doc_count, chunk_count, source_type,
                    kb_type, created_at, updated_at)
                   VALUES (?,?,?,?,0,0,?,?,?,?)""",
                (kid, name, description, icon, source_type, kb_type, ts, ts),
            )
        return self.get(kid)

    def update(self, kb_id: str, data: dict) -> dict | None:
        if not self.get(kb_id):
            return None
        sets, args = [], []
        allow_keys = {"name", "description", "icon", "doc_count", "chunk_count",
                      "source_type", "kb_type"}
        for k, v in data.items():
            if k not in allow_keys:
                continue
            sets.append(f'"{k}" = ?')
            args.append(v)
        if not sets:
            return self.get(kb_id)
        sets.append('updated_at = ?')
        args.append(now_ts())
        args.append(kb_id)
        with transaction():
            get_conn().execute(
                f'UPDATE knowledge_base SET {", ".join(sets)} WHERE id = ?', args
            )
        return self.get(kb_id)

    def delete(self, kb_id: str) -> bool:
        # 级联清理下属切片 & 文档记录（SQLite 默认未开启外键级联）
        with transaction():
            # 1) 先清切片（必须先于文档删除，否则 FOREIGN KEY 约束会触发；即使没约束也要防残留）
            get_conn().execute(
                'DELETE FROM kb_chunk WHERE kb_id = ?', (kb_id,)
            )
            # 2) 再清下属文档
            get_conn().execute(
                'DELETE FROM kb_document WHERE kb_id = ?', (kb_id,)
            )
            # 3) 最后删知识库本体
            cur = get_conn().execute(
                'DELETE FROM knowledge_base WHERE id = ?', (kb_id,)
            )
            return cur.rowcount > 0


# ====== 文档（归属知识库） ======
class DocumentsDAO:
    def list_by_kb(self, kb_id: str) -> list[dict]:
        rows = get_conn().execute(
            'SELECT * FROM kb_document WHERE kb_id = ? ORDER BY created_at DESC',
            (kb_id,),
        ).fetchall()
        return rows_to_dict_list(rows)

    def get(self, doc_id: str) -> dict | None:
        row = get_conn().execute(
            'SELECT * FROM kb_document WHERE id = ?', (doc_id,)
        ).fetchone()
        return row_to_dict(row)

    def create(self, data: dict) -> dict:
        conn = get_conn()
        did = data.get("id") or new_id("doc")
        kb_id = data["kb_id"]
        name = data["name"].strip()
        file_path = data.get("file_path", "") or ""
        size_bytes = int(data.get("size_bytes") or 0)
        chunk_count = int(data.get("chunk_count") or 0)
        status = data.get("status", "pending")
        ts = now_ts()
        with transaction():
            conn.execute(
                """INSERT INTO kb_document
                   (id, kb_id, name, file_path, size_bytes, chunk_count, status, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (did, kb_id, name, file_path, size_bytes, chunk_count, status, ts, ts),
            )
            # 同步知识库冗余计数（与 update_status / delete 行为一致）
            conn.execute(
                """UPDATE knowledge_base SET
                       doc_count = (SELECT COUNT(*) FROM kb_document WHERE kb_id = knowledge_base.id),
                       chunk_count = (SELECT COALESCE(SUM(chunk_count),0) FROM kb_document WHERE kb_id = knowledge_base.id),
                       updated_at = ?
                   WHERE id = ?""",
                (ts, kb_id),
            )
        return self.get(did)

    def update_status(self, doc_id: str, status: str, chunk_count: int | None = None, error: str = "") -> dict | None:
        doc = self.get(doc_id)
        if not doc:
            return None
        sets = ['status = ?', 'updated_at = ?', 'error = ?']
        args = [status, now_ts(), error]
        if chunk_count is not None:
            sets.insert(1, 'chunk_count = ?')
            args.insert(1, chunk_count)
        args.append(doc_id)
        with transaction():
            get_conn().execute(
                f'UPDATE kb_document SET {", ".join(sets)} WHERE id = ?', args
            )
            # 同步知识库冗余计数
            get_conn().execute(
                """UPDATE knowledge_base SET
                       doc_count = (SELECT COUNT(*) FROM kb_document WHERE kb_id = knowledge_base.id),
                       chunk_count = (SELECT COALESCE(SUM(chunk_count),0) FROM kb_document WHERE kb_id = knowledge_base.id),
                       updated_at = ?
                   WHERE id = ?""",
                (now_ts(), doc["kb_id"]),
            )
        return self.get(doc_id)

    def save_chunks(self, doc_id: str, kb_id: str, chunks: list[dict]) -> int:
        """将解析后的切片列表写入 kb_chunk 表。

        注意：chunk.id 是 doc_parser 内部生成的局部 id（不同文档之间可能重复），
        入库时必须基于 doc_id + sort_order 生成全局唯一主键，避免 UNIQUE 冲突。
        """
        if not chunks:
            return 0
        ts = now_ts()
        rows = []
        for i, c in enumerate(chunks):
            # 强制全局唯一主键：不再信任局部 chunk_id
            cid = f"chunk_{doc_id}_{i}"
            rows.append((
                cid, doc_id, kb_id, i,
                c.get("content", ""),
                int(c.get("char_count", 0)),
                int(c.get("token_count", 0)),
                None, ts,
            ))
        with transaction():
            conn = get_conn()
            # 先清空旧切片（防止重复上传残留）
            conn.execute('DELETE FROM kb_chunk WHERE doc_id = ?', (doc_id,))
            conn.executemany(
                """INSERT INTO kb_chunk
                   (id, doc_id, kb_id, sort_order, content, char_count, token_count, vector, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                rows,
            )
        return len(rows)

    def get_chunks_by_doc(self, doc_id: str) -> list[dict]:
        """获取指定文档的所有切片，按原文顺序排序。"""
        rows = get_conn().execute(
            'SELECT * FROM kb_chunk WHERE doc_id = ? ORDER BY sort_order ASC',
            (doc_id,),
        ).fetchall()
        return rows_to_dict_list(rows)

    def list_chunks_by_kb(self, kb_id: str) -> list[dict]:
        """获取指定知识库下所有切片（按文档 + sort_order 排序），用于图谱抽取等批量分析。"""
        rows = get_conn().execute(
            """SELECT c.*, d.name AS doc_name
               FROM kb_chunk c
               JOIN kb_document d ON d.id = c.doc_id
               WHERE c.kb_id = ?
               ORDER BY d.created_at DESC, c.doc_id, c.sort_order ASC""",
            (kb_id,),
        ).fetchall()
        return rows_to_dict_list(rows)

    def delete(self, doc_id: str) -> bool:
        doc = self.get(doc_id)
        if not doc:
            return False
        with transaction():
            # 1) 先清下属切片（否则切片变成 kb_chunk 表里的孤儿，RAG 还能检索到）
            get_conn().execute('DELETE FROM kb_chunk WHERE doc_id = ?', (doc_id,))
            # 2) 再删文档记录
            cur = get_conn().execute('DELETE FROM kb_document WHERE id = ?', (doc_id,))
            # 3) 重算 KB 的 doc_count/chunk_count 冗余计数
            get_conn().execute(
                """UPDATE knowledge_base SET
                       doc_count = (SELECT COUNT(*) FROM kb_document WHERE kb_id = knowledge_base.id),
                       chunk_count = (SELECT COALESCE(SUM(chunk_count),0) FROM kb_document WHERE kb_id = knowledge_base.id),
                       updated_at = ?
                   WHERE id = ?""",
                (now_ts(), doc["kb_id"]),
            )
            return cur.rowcount > 0


# ====== 渠道连接状态 ======
class ChannelsDAO:
    def get_all_status(self) -> list[dict]:
        rows = get_conn().execute("SELECT * FROM channel_connection").fetchall()
        return rows_to_dict_list(rows)

    def get(self, channel: str) -> dict | None:
        row = get_conn().execute(
            'SELECT * FROM channel_connection WHERE channel = ?', (channel,)
        ).fetchone()
        return row_to_dict(row)

    def upsert(self, channel: str, connected: bool, config: dict | None = None, error: str = "") -> dict:
        conn = get_conn()
        ts = now_ts()
        config_json = json.dumps(config or {}, ensure_ascii=False)
        with transaction():
            exists = conn.execute(
                'SELECT 1 FROM channel_connection WHERE channel = ?', (channel,)
            ).fetchone()
            if exists:
                conn.execute(
                    """UPDATE channel_connection
                       SET connected=?, config_json=?, last_check=?, error=?
                       WHERE channel=?""",
                    (1 if connected else 0, config_json, ts, error, channel),
                )
            else:
                conn.execute(
                    """INSERT INTO channel_connection
                       (channel, connected, config_json, last_check, error)
                       VALUES (?,?,?,?,?)""",
                    (channel, 1 if connected else 0, config_json, ts, error),
                )
        return self.get(channel)

    # ---- channel_binding（智能体 × 渠道 × peer 勾选） ----
    def list_bindings(self, agent_id: str, channel: str) -> list[dict]:
        rows = get_conn().execute(
            """SELECT * FROM channel_binding
               WHERE agent_id = ? AND channel = ?
               ORDER BY enabled DESC, peer_name""",
            (agent_id, channel),
        ).fetchall()
        return rows_to_dict_list(rows)

    def list_all_enabled_peer_occupants(self, channel: str) -> list[dict]:
        """返回某渠道下所有「已启用」绑定的占用清单（跨全部 agent）。

        每条: {peer_id, agent_id, agent_name, peer_name, peer_type, updated_at}
        用来让前端渲染时标记「哪些 peer 被其他智能体占用了」。
        """
        rows = get_conn().execute(
            """SELECT b.peer_id, b.peer_name, b.peer_type, b.agent_id, b.updated_at,
                      a.name AS agent_name
               FROM channel_binding b
               LEFT JOIN ai_agent a ON a.id = b.agent_id
               WHERE b.channel = ? AND b.enabled = 1""",
            (channel,),
        ).fetchall()
        return rows_to_dict_list(rows)

    def find_conflict(self, channel: str, peer_id: str, exclude_agent_id: str) -> dict | None:
        """查某 peer 在某渠道上是否已被「其他 agent」启用绑定。

        返回冲突记录 dict 或 None。给 set_binding 做前置排他校验用。
        """
        row = get_conn().execute(
            """SELECT b.peer_id, b.peer_name, b.agent_id, b.peer_type,
                      a.name AS agent_name
               FROM channel_binding b
               LEFT JOIN ai_agent a ON a.id = b.agent_id
               WHERE b.channel = ? AND b.peer_id = ? AND b.enabled = 1
                 AND b.agent_id != ?""",
            (channel, peer_id, exclude_agent_id),
        ).fetchone()
        return row_to_dict(row) if row else None

    def set_binding(self, agent_id: str, channel: str,
                    peer_id: str, peer_name: str,
                    peer_type: str = "friend", enabled: bool = True) -> dict:
        # ========== DEBUG TRACING: 谁在改 binding.enabled? ==========
        import traceback, time as _t
        _ts = _t.strftime("%H:%M:%S", _t.localtime())
        try:
            conn_for_check = get_conn()
            old = conn_for_check.execute(
                "SELECT enabled FROM channel_binding WHERE agent_id=? AND channel=? AND peer_id=?",
                (agent_id, channel, peer_id),
            ).fetchone()
            old_en = old["enabled"] if old else None
            new_en = 1 if enabled else 0
            print(f"[DAO][{_ts}] set_binding 被调用: peer={peer_id!r}({peer_name}) old_enabled={old_en} new_enabled={new_en}", flush=True)
            if old_en != new_en:
                print(f"[DAO][{_ts}] ⚠️⚠️⚠️ 状态变化！ {old_en} → {new_en}  调用堆栈:", flush=True)
                print("-----------------------------------------------------------", flush=True)
                traceback.print_stack(limit=15)
                print("-----------------------------------------------------------", flush=True)
        except Exception as _dbg_e:
            print(f"[DAO DEBUG 日志自身报错] {_dbg_e}", flush=True)
        # ========== END DEBUG TRACING ==========

        conn = get_conn()
        ts = now_ts()
        bid = new_id("cb")
        with transaction():
            exists = conn.execute(
                """SELECT id FROM channel_binding
                   WHERE agent_id = ? AND channel = ? AND peer_id = ?""",
                (agent_id, channel, peer_id),
            ).fetchone()
            if exists:
                conn.execute(
                    """UPDATE channel_binding
                       SET peer_name=?, peer_type=?, enabled=?, updated_at=?
                       WHERE id=?""",
                    (peer_name, peer_type, 1 if enabled else 0, ts, exists["id"]),
                )
                bid = exists["id"]
            else:
                conn.execute(
                    """INSERT INTO channel_binding
                       (id, agent_id, channel, peer_id, peer_name, peer_type, enabled, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (bid, agent_id, channel, peer_id, peer_name, peer_type,
                     1 if enabled else 0, ts, ts),
                )
        row = conn.execute('SELECT * FROM channel_binding WHERE id = ?', (bid,)).fetchone()
        return row_to_dict(row)

    def replace_binding(self, new_agent_id: str, channel: str, peer_id: str,
                        peer_name: str, peer_type: str = "friend") -> dict:
        """事务化抢占替换：先关对方所有 enabled 绑定，再绑自己。

        整个操作在一个 transaction 里原子执行——要么全成功，要么全回滚。
        返回新绑定记录 dict。
        """
        conn = get_conn()
        ts = now_ts()
        bid = new_id("cb")
        with transaction():
            # Step 1: 关闭该 peer 在本渠道上所有其他人的 enabled 绑定
            # （防御性：可能有多条 enabled=1 脏数据，一次性全关）
            # 一并清掉 is_manager，避免「抢占后旧主人仍是管理者」的幽灵标记
            conn.execute(
                """UPDATE channel_binding
                   SET enabled=0, is_manager=0, updated_at=?
                   WHERE channel=? AND peer_id=? AND enabled=1
                     AND agent_id!=?""",
                (ts, channel, peer_id, new_agent_id),
            )
            # Step 2: 给自己 upsert 一条 enabled=1
            exists = conn.execute(
                """SELECT id FROM channel_binding
                   WHERE agent_id=? AND channel=? AND peer_id=?""",
                (new_agent_id, channel, peer_id),
            ).fetchone()
            if exists:
                conn.execute(
                    """UPDATE channel_binding
                       SET peer_name=?, peer_type=?, enabled=1, updated_at=?
                       WHERE id=?""",
                    (peer_name, peer_type, ts, exists["id"]),
                )
                bid = exists["id"]
            else:
                conn.execute(
                    """INSERT INTO channel_binding
                       (id, agent_id, channel, peer_id, peer_name, peer_type, enabled, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (bid, new_agent_id, channel, peer_id, peer_name, peer_type, 1, ts, ts),
                )
            # Step 3: 搬迁 conversation —— 之前 owner 的会话归新 agent 所有
            # （chat_message 通过 conversation_id 外键自动跟随，不用动）
            # 排除新 agent 自己已有的同 peer conversation，避免覆盖
            # 同时记录 migrated_from = 旧 agent_id（用于导入列表）
            # 如果新 agent 已有同 peer 的 conversation，则把旧的删掉避免重复
            existing_own = conn.execute(
                """SELECT id FROM conversation
                   WHERE agent_id=? AND channel=? AND peer_id=?""",
                (new_agent_id, channel, peer_id),
            ).fetchall()
            if existing_own:
                # 新 agent 已经有这条 peer 的对话了 → 删掉旧 owner 的，不搬
                conn.execute(
                    """DELETE FROM conversation
                       WHERE channel=? AND peer_id=? AND agent_id!=?""",
                    (channel, peer_id, new_agent_id),
                )
            else:
                # 新 agent 没有 → 搬迁，并记录来源
                conn.execute(
                    """UPDATE conversation
                       SET agent_id=?, migrated_from=agent_id, updated_at=?
                       WHERE channel=? AND peer_id=?
                         AND agent_id!=?""",
                    (new_agent_id, ts, channel, peer_id, new_agent_id),
                )
        row = conn.execute('SELECT * FROM channel_binding WHERE id=?', (bid,)).fetchone()
        return row_to_dict(row)

    # ---- 管理者标记（is_manager）----
    def list_managers(self, agent_id: str, channel: str) -> list[dict]:
        """列出某 agent 在某渠道上已标记为管理者的绑定（需 enabled=1）。"""
        rows = get_conn().execute(
            """SELECT * FROM channel_binding
               WHERE agent_id = ? AND channel = ?
                 AND is_manager = 1 AND enabled = 1
               ORDER BY peer_name""",
            (agent_id, channel),
        ).fetchall()
        return rows_to_dict_list(rows)

    def clear_managers(self, agent_id: str, channel: str) -> int:
        """清除某 agent 在某渠道上的全部管理者标记（只清标记，不删绑定）。"""
        with transaction():
            cur = get_conn().execute(
                """UPDATE channel_binding
                   SET is_manager=0, updated_at=?
                   WHERE agent_id=? AND channel=? AND is_manager=1""",
                (now_ts(), agent_id, channel),
            )
            return cur.rowcount

    def set_manager(self, agent_id: str, channel: str, peer_id: str,
                    peer_name: str = "", peer_type: str = "friend",
                    is_manager: bool = True) -> dict:
        """设置/取消管理者标记。

        - 标记为管理者时强制 enabled=1（管理者必须有可路由的绑定落点）。
        - 绑定不存在且要取消标记时，视为无操作，返回 {}。
        """
        conn = get_conn()
        ts = now_ts()
        bid = new_id("cb")
        flag = 1 if is_manager else 0
        with transaction():
            exists = conn.execute(
                """SELECT id FROM channel_binding
                   WHERE agent_id=? AND channel=? AND peer_id=?""",
                (agent_id, channel, peer_id),
            ).fetchone()
            if exists:
                if flag:
                    conn.execute(
                        """UPDATE channel_binding
                           SET peer_name=COALESCE(NULLIF(?,''), peer_name),
                               enabled=1, is_manager=1, updated_at=?
                           WHERE id=?""",
                        (peer_name, ts, exists["id"]),
                    )
                else:
                    conn.execute(
                        """UPDATE channel_binding
                           SET peer_name=COALESCE(NULLIF(?,''), peer_name),
                               is_manager=0, updated_at=?
                           WHERE id=?""",
                        (peer_name, ts, exists["id"]),
                    )
                bid = exists["id"]
            else:
                if not flag:
                    return {}
                conn.execute(
                    """INSERT INTO channel_binding
                       (id, agent_id, channel, peer_id, peer_name, peer_type,
                        enabled, is_manager, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,1,1,?,?)""",
                    (bid, agent_id, channel, peer_id, peer_name, peer_type, ts, ts),
                )
        row = conn.execute('SELECT * FROM channel_binding WHERE id=?', (bid,)).fetchone()
        return row_to_dict(row) or {}

    def is_manager_peer(self, agent_id: str, channel: str, peer_id: str) -> bool:
        """判断某 peer 在某渠道上是否是该 agent 的管理者（需标记且 enabled=1）。"""
        row = get_conn().execute(
            """SELECT 1 FROM channel_binding
               WHERE agent_id=? AND channel=? AND peer_id=?
                 AND is_manager=1 AND enabled=1""",
            (agent_id, channel, peer_id),
        ).fetchone()
        return row is not None

    def delete_binding(self, binding_id: str) -> bool:
        with transaction():
            cur = get_conn().execute(
                'DELETE FROM channel_binding WHERE id = ?', (binding_id,)
            )
            return cur.rowcount > 0


# ====== 激活 / 试用计数 ======
ACTIVATION_SINGLETON = "singleton"


class ActivationDAO:
    def _ensure_row(self) -> None:
        conn = get_conn()
        row = conn.execute(
            'SELECT 1 FROM activation WHERE id = ?', (ACTIVATION_SINGLETON,)
        ).fetchone()
        if not row:
            with transaction():
                conn.execute(
                    """INSERT INTO activation
                       (id, activated, license_key, machine_code, activated_at,
                        trial_used, trial_limit, updated_at)
                       VALUES (?,0,'','',0,0,50,?)""",
                    (ACTIVATION_SINGLETON, now_ts()),
                )

    def get_status(self) -> dict:
        self._ensure_row()
        row = get_conn().execute(
            'SELECT * FROM activation WHERE id = ?', (ACTIVATION_SINGLETON,)
        ).fetchone()
        o = row_to_dict(row) or {}
        try:
            o["license_key"] = decrypt_secret(o.get("license_key", ""))
        except Exception:  # noqa: BLE001
            pass
        activated = bool(o.get("activated"))
        o["edition"] = "正式版" if activated else "免费版"
        o["activated"] = activated  # 统一返回 True/False，避免 int(1/0) 让前端搞混
        return o

    def increment_trial_used(self, n: int = 1) -> dict:
        self._ensure_row()
        with transaction():
            get_conn().execute(
                """UPDATE activation
                   SET trial_used = trial_used + ?, updated_at = ?
                   WHERE id = ?""",
                (n, now_ts(), ACTIVATION_SINGLETON),
            )
        return self.get_status()

    def set_trial_limit(self, limit: int) -> dict:
        self._ensure_row()
        with transaction():
            get_conn().execute(
                "UPDATE activation SET trial_limit = ?, updated_at = ? WHERE id = ?",
                (limit, now_ts(), ACTIVATION_SINGLETON),
            )
        return self.get_status()

    def can_use_trial(self) -> bool:
        s = self.get_status()
        if bool(s.get("activated")):
            return True
        return int(s.get("trial_used", 0)) < int(s.get("trial_limit", 50))

    def activate(self, license_key: str, machine_code: str) -> dict:
        """激活本机。

        校验流程：
        1. 必须传 license_key 和 machine_code
        2. license_key 必须是 machine_code 的合法签名（防伪造）
        3. machine_code 必须等于当前本机机器码（防拷贝到其他机器激活）
        4. 校验通过 → 写 license.dat（离线持久化）+ 写 SQLite
        """
        from .license import verify_license_key, write_license_file
        from .machine import get_machine_code

        license_key = (license_key or "").strip()
        machine_code = (machine_code or "").strip()
        if not license_key:
            raise ValueError("激活码不能为空")
        if not machine_code:
            raise ValueError("机器码缺失")

        # 当前本机机器码必须与传入的 machine_code 一致
        current_mc = get_machine_code()
        if machine_code != current_mc:
            raise ValueError(
                "机器码不匹配：传入的机器码与本机不符。"
                "可能原因：激活码是为其他机器生成的，或本机硬件已变更。"
            )

        # 激活码必须是本机机器码的合法签名
        if not verify_license_key(license_key, machine_code):
            raise ValueError("激活码无效：签名校验失败，请确认激活码正确")

        # 校验通过：写 license.dat（离线持久化）
        write_license_file(machine_code, license_key)

        # 同步写 SQLite（带加密）+ 幂等：activated_at 只在首次从 0→1 时写入，二次激活不覆盖
        self._ensure_row()
        current = self.get_status()
        key_enc = encrypt_secret(license_key)
        ts = now_ts()
        existing_activated_at = current.get("activated_at") or 0
        activated_at_final = existing_activated_at if existing_activated_at > 0 else ts
        already_activated = bool(current.get("activated")) and bool(existing_activated_at > 0)
        with transaction():
            get_conn().execute(
                """UPDATE activation
                   SET activated = 1, license_key = ?, machine_code = ?,
                       activated_at = ?, updated_at = ?
                   WHERE id = ?""",
                (key_enc, machine_code, activated_at_final, ts, ACTIVATION_SINGLETON),
            )
        status = self.get_status()
        status["already_activated"] = already_activated
        return status

    def deactivate(self) -> dict:
        # 撤销激活时同步删 license.dat（否则下次启动离线校验会重新激活）
        from .license import delete_license_file
        delete_license_file()
        self._ensure_row()
        with transaction():
            get_conn().execute(
                """UPDATE activation
                   SET activated = 0, license_key = '', machine_code = '',
                       activated_at = 0, updated_at = ?
                   WHERE id = ?""",
                (now_ts(), ACTIVATION_SINGLETON),
            )
        return self.get_status()

    def admin_generate_license(self, target_machine_code: str) -> str:
        """【管理员手工兜底 SOP 用】直接为某个机器码生成激活码字符串。

        生成后调用者（通常是 bridge._handle_admin_gen_license 或 CLI 脚本）
        会把这串码发给用户，用户去 Tab2「输入激活码」提交即可。
        该函数只负责生成签名，不直接写 activation 表（因为那是"当前机器"的表，
        管理员可能是为客户机器远程生成，不是自己本机）。
        """
        from .payment import generate_license_for_machine
        mc = (target_machine_code or "").strip()
        if not mc:
            raise ValueError("机器码为空，不能生成激活码")
        return generate_license_for_machine(mc)


# ====== 激活订单表（虎皮椒支付） ======
class ActivationOrdersDAO:
    """activation_orders 表薄封装。

    状态枚举：
      created  — 已创建订单、二维码下发给前端、等待用户支付
      pending  — 回调或轮询里首次收到但还没走完处理流程（中间态，短暂存在）
      paid     — 已收到支付成功（已通过验签），且激活码生成并写入 activation 表成功
      expired  — 订单超过 expires_at 时间戳未支付
      failed   — 回调验签失败/金额不对/机器码不一致（判定欺诈或错误，不激活）
      refunded — 已退款（管理员手动操作，MVP 初版暂时不做自动化退款接口）
    """

    VALID_STATUSES = {"created", "pending", "paid", "expired", "failed", "refunded"}

    def create(self, data: dict) -> dict:
        """创建新订单。字段参考 activation_orders schema；id 必传（= out_trade_no）。"""
        conn = get_conn()
        ts = now_ts()
        oid = str(data.get("id") or "").strip()
        if not oid:
            raise ValueError("订单 id（out_trade_no）不能为空")
        status = (data.get("status") or "created") in self.VALID_STATUSES and \
            (data.get("status") or "created") or "created"
        row = {
            "id": oid,
            "xunhu_order_id": data.get("xunhu_order_id") or "",
            "transaction_id": data.get("transaction_id") or "",
            "machine_code": data.get("machine_code") or "",
            "amount_cents": int(data.get("amount_cents") or 0),
            "amount_yuan": float(data.get("amount_yuan") or 0.0),
            "status": status,
            "mode": data.get("mode") or "mock",
            "goods_name": data.get("goods_name") or "",
            "attach_json": json.dumps(data.get("attach_json") or {}, ensure_ascii=False),
            "license_key": encrypt_secret(data.get("license_key") or ""),
            "qr_url": data.get("qr_url") or "",
            "notify_raw": "",
            "notify_attempts": 0,
            "notify_verified": 0,
            "created_at": int(data.get("created_at") or ts),
            "expires_at": int(data.get("expires_at") or (ts + 15 * 60)),
            "paid_at": 0,
            "updated_at": ts,
        }
        with transaction():
            conn.execute(
                """INSERT INTO activation_orders
                   (id,xunhu_order_id,transaction_id,machine_code,amount_cents,amount_yuan,
                    status,mode,goods_name,attach_json,license_key,qr_url,
                    notify_raw,notify_attempts,notify_verified,
                    created_at,expires_at,paid_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (row["id"], row["xunhu_order_id"], row["transaction_id"], row["machine_code"],
                 row["amount_cents"], row["amount_yuan"], row["status"], row["mode"],
                 row["goods_name"], row["attach_json"], row["license_key"], row["qr_url"],
                 row["notify_raw"], row["notify_attempts"], row["notify_verified"],
                 row["created_at"], row["expires_at"], row["paid_at"], row["updated_at"]),
            )
        return self.get(oid) or row

    def get(self, order_id: str) -> dict | None:
        row = get_conn().execute(
            'SELECT * FROM activation_orders WHERE id = ?', (order_id,)
        ).fetchone()
        if not row:
            return None
        o = row_to_dict(row) or {}
        for key_enc in ("license_key",):
            try:
                o[key_enc] = decrypt_secret(o.get(key_enc, ""))
            except Exception:  # noqa: BLE001
                pass
        if o.get("attach_json"):
            try:
                o["attach_json"] = json.loads(o["attach_json"])
            except Exception:  # noqa: BLE001
                o["attach_json"] = {}
        return o

    def _raw_set(self, order_id: str, updates: dict) -> dict | None:
        if not self.get(order_id):
            return None
        sets, args = [], []
        for k, v in (updates or {}).items():
            if k == "attach_json" and not isinstance(v, str):
                v = json.dumps(v or {}, ensure_ascii=False)
            if k == "license_key":
                v = encrypt_secret(v or "")
            sets.append(f'"{k}" = ?')
            args.append(v)
        if not sets:
            return self.get(order_id)
        sets.append('"updated_at" = ?')
        args.append(now_ts())
        args.append(order_id)
        with transaction():
            get_conn().execute(
                f'UPDATE activation_orders SET {", ".join(sets)} WHERE id = ?', args
            )
        return self.get(order_id)

    def mark_pending(self, order_id: str) -> dict | None:
        return self._raw_set(order_id, {"status": "pending"})

    def mark_paid(self, order_id: str, *,
                  transaction_id: str = "",
                  xunhu_order_id: str = "",
                  paid_at: int | None = None,
                  license_key: str = "",
                  attach_json: dict | None = None) -> tuple[dict | None, bool]:
        """状态流转到 paid。幂等：如果已经是 paid，返回 (已有订单, False 未改动)。

        成功支付会写：transaction_id、paid_at、license_key（加密）、status=paid。
        还会返回一个 bool：True=首次刚流转为 paid（此时应触发 activation_dao.activate）
                       False=之前已是 paid，不用重复激活
        """
        cur = self.get(order_id)
        if not cur:
            return None, False
        if cur.get("status") == "paid":
            return cur, False  # 幂等
        paid_at = paid_at or now_ts()
        updates: dict = {
            "status": "paid",
            "paid_at": paid_at,
            "transaction_id": transaction_id or cur.get("transaction_id") or "",
            "xunhu_order_id": xunhu_order_id or cur.get("xunhu_order_id") or "",
            "license_key": license_key or "",
        }
        if attach_json is not None:
            updates["attach_json"] = attach_json
        updated = self._raw_set(order_id, updates)
        return updated, True

    def mark_failed(self, order_id: str, *, reason: str = "") -> dict | None:
        snap = {"reason": reason, "failed_at": now_ts()}
        old = self.get(order_id) or {}
        prev = old.get("attach_json") or {}
        if isinstance(prev, dict):
            snap = {**prev, **snap}
        return self._raw_set(order_id, {"status": "failed", "attach_json": snap})

    def mark_expired_if_needed(self, order_id: str) -> dict | None:
        row = self.get(order_id)
        if not row:
            return None
        if row.get("status") != "created":
            return row  # 其他状态不自动变过期
        exp = int(row.get("expires_at") or 0)
        if exp and now_ts() >= exp:
            return self._raw_set(order_id, {"status": "expired"})
        return row

    def record_notify(self, order_id: str, *,
                      raw_body: str,
                      verified: bool,
                      attempts_increment: int = 1) -> dict | None:
        cur = self.get(order_id) or {}
        attempts = int(cur.get("notify_attempts") or 0) + int(attempts_increment)
        return self._raw_set(order_id, {
            "notify_raw": raw_body or "",
            "notify_attempts": attempts,
            "notify_verified": 1 if verified else 0,
        })


# ====== 对话会话 ======
class ConversationDAO:
    def list_by_agent(self, agent_id: str, channel: str | None = None) -> list[dict]:
        sql = """SELECT * FROM conversation WHERE agent_id = ?"""
        args: list = [agent_id]
        if channel:
            sql += " AND channel = ?"
            args.append(channel)
        sql += " ORDER BY updated_at DESC"
        rows = get_conn().execute(sql, args).fetchall()
        return rows_to_dict_list(rows)

    def list_all(self, *, agent_id: str | None = None,
                 channel: str | None = None,
                 keyword: str | None = None,
                 limit: int = 200) -> list[dict]:
        """全局历史会话查询（对应"历史"Tab）。

        过滤维度：
          agent_id  : 限定智能体（单智能体详情页历史按钮用）
          channel   : wcf / wecom / oa / feishu / dingtalk 渠道筛选
          keyword   : 模糊匹配 title 或 peer_name
        返回按 updated_at DESC 排序的会话记录（含 peer_name/channel/message_count）。
        """
        sql_parts = ["SELECT * FROM conversation WHERE 1=1"]
        args: list = []
        if agent_id:
            sql_parts.append("AND agent_id = ?"); args.append(agent_id)
        if channel:
            sql_parts.append("AND channel = ?"); args.append(channel)
        if keyword:
            like = f"%{keyword}%"
            sql_parts.append("AND (title LIKE ? OR peer_name LIKE ?)")
            args += [like, like]
        sql_parts.append("ORDER BY updated_at DESC LIMIT ?")
        args.append(int(limit))
        sql = "\n".join(sql_parts)
        rows = get_conn().execute(sql, args).fetchall()
        return rows_to_dict_list(rows)

    def get(self, conv_id: str) -> dict | None:
        row = get_conn().execute(
            'SELECT * FROM conversation WHERE id = ?', (conv_id,)
        ).fetchone()
        return row_to_dict(row)

    def create(self, agent_id: str, title: str = "",
               channel: str = "wcf", peer_id: str = "",
               peer_name: str = "", peer_type: str = "friend") -> dict:
        conn = get_conn()
        cid = new_id("conv")
        ts = now_ts()
        with transaction():
            conn.execute(
                """INSERT INTO conversation
                   (id, agent_id, channel, peer_id, peer_name, peer_type,
                    title, message_count, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
                (cid, agent_id, channel, peer_id, peer_name, peer_type,
                 title[:100], ts, ts),
            )
        return self.get(cid)

    def update_title(self, conv_id: str, title: str) -> dict | None:
        with transaction():
            get_conn().execute(
                """UPDATE conversation SET title = ?, updated_at = ? WHERE id = ?""",
                (title[:100], now_ts(), conv_id),
            )
        return self.get(conv_id)

    def touch(self, conv_id: str) -> None:
        get_conn().execute(
            "UPDATE conversation SET updated_at = ? WHERE id = ?",
            (now_ts(), conv_id),
        )

    def delete(self, conv_id: str) -> bool:
        with transaction():
            cur = get_conn().execute(
                'DELETE FROM conversation WHERE id = ?', (conv_id,)
            )
            return cur.rowcount > 0

    def list_migrated_by_agent(self, agent_id: str) -> list[dict]:
        """列出该智能体下「从别处搬迁过来、尚未导入记忆」的会话。"""
        rows = get_conn().execute(
            """SELECT c.*, a.name AS from_agent_name
               FROM conversation c
               LEFT JOIN ai_agent a ON a.id = c.migrated_from
               WHERE c.agent_id = ? AND c.migrated_from IS NOT NULL
               ORDER BY c.updated_at DESC""",
            (agent_id,),
        ).fetchall()
        return rows_to_dict_list(rows)

    def clear_migrated(self, conv_ids: list[str]) -> int:
        """标记会话为「已导入记忆」（清除 migrated_from 标记）。"""
        if not conv_ids:
            return 0
        placeholders = ",".join("?" * len(conv_ids))
        with transaction():
            cur = get_conn().execute(
                f"UPDATE conversation SET migrated_from=NULL WHERE id IN ({placeholders})",
                conv_ids,
            )
            return cur.rowcount


# ====== per-peer 画像 ======
class PeerProfileDAO:
    """per-peer 画像 DAO —— scope = (channel, peer_id)，UNIQUE 物理隔离。"""

    def get(self, channel: str, peer_id: str) -> dict | None:
        """取一条画像记录。"""
        row = get_conn().execute(
            "SELECT * FROM peer_profile WHERE channel=? AND peer_id=?",
            (channel, peer_id),
        ).fetchone()
        return row_to_dict(row) if row else None

    def upsert(self, data: dict) -> dict:
        """新增或更新一条画像。UNIQUE(channel, peer_id) 保证幂等。"""
        channel = data["channel"]
        peer_id = data["peer_id"]
        ts = now_ts()
        conn = get_conn()
        existing = conn.execute(
            "SELECT id FROM peer_profile WHERE channel=? AND peer_id=?",
            (channel, peer_id),
        ).fetchone()
        if existing:
            # 更新
            sets = []
            args = []
            allow = {"peer_name", "role", "memories", "last_refine_at"}
            for k, v in data.items():
                if k not in allow:
                    continue
                sets.append(f'"{k}" = ?')
                args.append(v)
            sets.append('updated_at = ?')
            args.append(ts)
            args.extend([channel, peer_id])
            if sets:
                conn.execute(
                    f'UPDATE peer_profile SET {", ".join(sets)} WHERE channel=? AND peer_id=?',
                    args,
                )
        else:
            # 新增
            pid = data.get("id") or new_id("pp")
            conn.execute(
                """INSERT INTO peer_profile
                   (id, channel, peer_id, peer_name, role, memories, last_refine_at, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (pid, channel, peer_id,
                 data.get("peer_name", "") or "",
                 data.get("role", "user") or "user",
                 data.get("memories", "{}") or "{}",
                 data.get("last_refine_at", 0) or 0,
                 ts, ts),
            )
        return self.get(channel, peer_id) or {}

    def list_by_channel(self, channel: str) -> list[dict]:
        """列出某渠道下所有画像。"""
        rows = get_conn().execute(
            "SELECT * FROM peer_profile WHERE channel=? ORDER BY updated_at DESC",
            (channel,),
        ).fetchall()
        return rows_to_dict_list(rows)

    def delete(self, channel: str, peer_id: str) -> bool:
        cur = get_conn().execute(
            "DELETE FROM peer_profile WHERE channel=? AND peer_id=?",
            (channel, peer_id),
        )
        return cur.rowcount > 0


# ====== 对话消息 ======
class ChatMessageDAO:
    def list_by_conversation(self, conv_id: str) -> list[dict]:
        rows = get_conn().execute(
            """SELECT * FROM chat_message
               WHERE conversation_id = ?
               ORDER BY created_at ASC""",
            (conv_id,),
        ).fetchall()
        return rows_to_dict_list(rows)

    def create(self, conversation_id: str, role: str, content: str,
               tokens: int = 0, aigc_marked: int = 0,
               channel: str = "wcf", model: str = "", source_tag: str = "") -> dict:
        conn = get_conn()
        mid = new_id("msg")
        ts = now_ts()
        with transaction():
            conn.execute(
                """INSERT INTO chat_message
                   (id, conversation_id, role, content, tokens, aigc_marked,
                    channel, model, source_tag, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (mid, conversation_id, role, content, tokens, aigc_marked,
                 channel, model, source_tag, ts),
            )
            # 同步会话 updated_at + message_count 冗余计数
            conn.execute(
                """UPDATE conversation SET
                       updated_at = ?,
                       message_count = (
                           SELECT COUNT(*) FROM chat_message
                           WHERE conversation_id = conversation.id
                       )
                   WHERE id = ?""",
                (ts, conversation_id),
            )
        return self.get(mid)

    def get(self, msg_id: str) -> dict | None:
        row = get_conn().execute(
            'SELECT * FROM chat_message WHERE id = ?', (msg_id,)
        ).fetchone()
        return row_to_dict(row)

    def delete_by_conversation(self, conv_id: str) -> int:
        with transaction():
            cur = get_conn().execute(
                'DELETE FROM chat_message WHERE conversation_id = ?', (conv_id,)
            )
            return cur.rowcount

    def list_recent_by_agent(self, agent_id: str, hours: int = 24,
                             limit: int = 200) -> list[dict]:
        """拉取某 agent 最近 N 小时的所有渠道消息（user + assistant）。"""
        import time
        since = int(time.time() - hours * 3600)
        rows = get_conn().execute(
            """SELECT cm.*, c.channel, c.peer_name
               FROM chat_message cm
               JOIN conversation c ON cm.conversation_id = c.id
               WHERE c.agent_id = ?
                 AND cm.created_at >= ?
                 AND cm.content IS NOT NULL
               ORDER BY cm.created_at DESC
               LIMIT ?""",
            (agent_id, since, limit),
        ).fetchall()
        return rows_to_dict_list(rows)


RISK_CONFIG_SINGLETON = "singleton"

class RiskConfigDAO:
    """风控配置（账号级，单行表）。所有智能体共用一套策略。"""

    def _ensure_row(self) -> None:
        conn = get_conn()
        row = conn.execute(
            'SELECT 1 FROM risk_config WHERE id = ?', (RISK_CONFIG_SINGLETON,)
        ).fetchone()
        if not row:
            with transaction():
                conn.execute(
                    """INSERT INTO risk_config
                       (id, level, auto_adjust, busy_prob, leak_back,
                        health_score, updated_at)
                       VALUES (?, 'conservative', 1, 1, 1, 100, ?)""",
                    (RISK_CONFIG_SINGLETON, now_ts()),
                )

    def get(self) -> dict:
        self._ensure_row()
        row = get_conn().execute(
            'SELECT * FROM risk_config WHERE id = ?', (RISK_CONFIG_SINGLETON,)
        ).fetchone()
        o = row_to_dict(row) or {}
        # 统一转成 bool
        for k in ("auto_adjust", "busy_prob", "leak_back"):
            o[k] = bool(o.get(k))
        return o

    def update(self, **fields) -> dict:
        allow_keys = {"level", "auto_adjust", "busy_prob", "leak_back", "health_score"}
        sets, vals = [], []
        for k, v in fields.items():
            if k not in allow_keys:
                continue
            if isinstance(v, bool):
                v = 1 if v else 0
            sets.append(f'"{k}" = ?')
            vals.append(v)
        if not sets:
            return self.get()
        sets.append('"updated_at" = ?')
        vals.append(now_ts())
        vals.append(RISK_CONFIG_SINGLETON)
        with transaction():
            get_conn().execute(
                f'UPDATE risk_config SET {", ".join(sets)} WHERE id = ?',
                vals,
            )
        return self.get()


# ====== 智能体 × 应用（多对多） ======
class AgentAppDAO:
    """多对多表：哪个智能体启用了哪个应用 + 运行时配置（JSON）"""

    def list_by_agent(self, agent_id: str) -> list[dict]:
        rows = get_conn().execute(
            'SELECT * FROM agent_app WHERE agent_id = ? ORDER BY app_id ASC',
            (agent_id,),
        ).fetchall()
        return rows_to_dict_list(rows)

    def list_by_app(self, app_id: str) -> list[dict]:
        rows = get_conn().execute(
            'SELECT * FROM agent_app WHERE app_id = ? AND enabled = 1',
            (app_id,),
        ).fetchall()
        return rows_to_dict_list(rows)

    def get(self, agent_id: str, app_id: str) -> dict | None:
        row = get_conn().execute(
            'SELECT * FROM agent_app WHERE agent_id = ? AND app_id = ?',
            (agent_id, app_id),
        ).fetchone()
        return row_to_dict(row)

    def upsert(self, agent_id: str, app_id: str, enabled: bool = True,
               config_json: str = "{}") -> dict:
        row = self.get(agent_id, app_id)
        ts = now_ts()
        with transaction():
            if row:
                get_conn().execute(
                    "UPDATE agent_app SET enabled = ?, config_json = ?, updated_at = ? WHERE agent_id = ? AND app_id = ?",
                    (1 if enabled else 0, config_json, ts, agent_id, app_id),
                )
            else:
                get_conn().execute(
                    "INSERT INTO agent_app (agent_id, app_id, enabled, config_json, installed_at, updated_at) VALUES (?,?,?,?,?,?)",
                    (agent_id, app_id, 1 if enabled else 0, config_json, ts, ts),
                )
        return self.get(agent_id, app_id) or {}

    def toggle(self, agent_id: str, app_id: str, enabled: bool) -> bool:
        row = self.get(agent_id, app_id)
        ts = now_ts()
        with transaction():
            if row:
                get_conn().execute(
                    "UPDATE agent_app SET enabled = ?, updated_at = ? WHERE agent_id = ? AND app_id = ?",
                    (1 if enabled else 0, ts, agent_id, app_id),
                )
            else:
                get_conn().execute(
                    "INSERT INTO agent_app (agent_id, app_id, enabled, config_json, installed_at, updated_at) VALUES (?,?,?,?,?,?)",
                    (agent_id, app_id, 1 if enabled else 0, "{}", ts, ts),
                )
        return True

    def delete(self, agent_id: str, app_id: str) -> bool:
        with transaction():
            cur = get_conn().execute(
                "DELETE FROM agent_app WHERE agent_id = ? AND app_id = ?",
                (agent_id, app_id),
            )
            return cur.rowcount > 0


# ====== 跨应用共享凭据 ======
class AppCredentialDAO:
    """跨应用共享的凭据（好单库 API Key 等），value 存 DPAPI 加密后字符串"""

    def get(self, key: str) -> dict | None:
        row = get_conn().execute(
            'SELECT * FROM app_credential WHERE credential_key = ?', (key,)
        ).fetchone()
        return row_to_dict(row)

    def list_all(self) -> list[dict]:
        rows = get_conn().execute(
            'SELECT * FROM app_credential ORDER BY credential_key ASC'
        ).fetchall()
        return rows_to_dict_list(rows)

    def save(self, key: str, value: str) -> dict:
        ts = now_ts()
        with transaction():
            existing = self.get(key)
            if existing:
                get_conn().execute(
                    "UPDATE app_credential SET value = ?, updated_at = ? WHERE credential_key = ?",
                    (value, ts, key),
                )
            else:
                get_conn().execute(
                    "INSERT INTO app_credential (credential_key, value, updated_at) VALUES (?,?,?)",
                    (key, value, ts),
                )
        return self.get(key) or {"credential_key": key, "value": value}

    def delete(self, key: str) -> bool:
        with transaction():
            cur = get_conn().execute(
                "DELETE FROM app_credential WHERE credential_key = ?", (key,)
            )
            return cur.rowcount > 0
