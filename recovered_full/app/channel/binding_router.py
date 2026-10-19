"""绑定路由：根据 (channel, peer_id) 找到应该用哪个智能体回复。

MVP 规则：一个 peer 在一个 channel 只能绑一个智能体（如果有人把同一个好友绑到多个智能体，
取最后更新时间最大的那条）。未绑定的 peer 直接丢弃，不回复。
"""

from __future__ import annotations

from typing import Optional

from storage.dao import ChannelsDAO


class BindingRouter:
    def __init__(self, channels_dao: ChannelsDAO):
        self._dao = channels_dao

    def find_agent_for_peer(self, channel: str, peer_id: str) -> Optional[dict]:
        """查某用户/群在某渠道上应使用的智能体。

        返回 {"agent_id":str, "peer_name":str, "peer_type":str, "aigc_enabled":bool} 或 None。
        """
        if not peer_id:
            return None
        channel = (channel or "wcf").strip().lower() or "wcf"
        # 最直接的查法：先把该渠道所有 enabled=1 的绑定拉出来，再按 peer_id 过滤。
        # 正常一个渠道绑定不会上万条，性能可以接受。
        import sqlite3
        from storage.db import get_conn
        conn = get_conn()
        rows = conn.execute(
            """SELECT b.agent_id, b.peer_id, b.peer_name, b.peer_type, b.enabled,
                      b.updated_at, a.aigc_enabled
               FROM channel_binding b
               LEFT JOIN ai_agent a ON a.id = b.agent_id
               WHERE b.channel = ? AND b.peer_id = ? AND b.enabled = 1
                 AND (a.channel = '' OR a.channel = ?)
                 AND (a.active = 1 OR a.active IS NULL)
               ORDER BY b.updated_at DESC""",
            (channel, peer_id, channel),
        ).fetchall()
        if not rows:
            return None
        r = rows[0]
        agent_id = r["agent_id"]
        if not agent_id:
            return None
        return {
            "agent_id": agent_id,
            "peer_name": r["peer_name"] or peer_id,
            "peer_type": r["peer_type"] or "friend",
            "aigc_enabled": bool(r["aigc_enabled"] if r["aigc_enabled"] is not None else 1),
        }

    def find_all_agents_for_manager(self, channel: str, peer_id: str) -> list[dict]:
        """查该管理者在某渠道上绑定的**所有**智能体（聚合路由用）。

        和 find_agent_for_peer 的关键区别：
        1. 不加 LIMIT 1 → 返回全部绑定的 agent
        2. 不检查 agent.channel 锁 → 管理者可以跨 agent.channel 聚合
        3. 只查 is_manager=1 的 binding
        4. 额外返回 kb_enabled / kb_ids / llm_config_id（聚合 RAG 需要）

        返回 list[{"agent_id", "peer_name", "peer_type", "kb_enabled", "kb_ids",
                   "llm_config_id", "aigc_enabled"}, ...]；无结果返回 []。
        """
        if not peer_id:
            return []
        channel = (channel or "wcf").strip().lower() or "wcf"
        import sqlite3
        from storage.db import get_conn
        conn = get_conn()
        rows = conn.execute(
            """SELECT b.agent_id, b.peer_name, b.peer_type,
                      a.kb_enabled, a.kb_ids, a.llm_config_id, a.aigc_enabled
               FROM channel_binding b
               LEFT JOIN ai_agent a ON a.id = b.agent_id
               WHERE b.channel = ? AND b.peer_id = ? AND b.enabled = 1 AND b.is_manager = 1
                 AND (a.active = 1 OR a.active IS NULL)
               ORDER BY b.updated_at DESC""",
            (channel, peer_id),
        ).fetchall()
        if not rows:
            return []
        result = []
        for r in rows:
            aid = r["agent_id"]
            if not aid:
                continue
            result.append({
                "agent_id": aid,
                "peer_name": r["peer_name"] or peer_id,
                "peer_type": r["peer_type"] or "friend",
                "kb_enabled": int(r["kb_enabled"] or 0),
                "kb_ids": r["kb_ids"] or "",
                "llm_config_id": r["llm_config_id"] or "",
                "aigc_enabled": bool(r["aigc_enabled"] if r["aigc_enabled"] is not None else 1),
            })
        return result
