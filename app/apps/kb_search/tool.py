"""知识库检索应用 — tool 入口。

bridge 契约：
    call_tool(args: dict) -> dict
    args 由 bridge 注入：__tool_name / __agent_id / __is_manager / __credentials / __app_config
    - 必须按 args.get("__tool_name") 分发，本应用工具名固定为 "kb_search"
    - 返回值必须可 json 序列化，绝不抛异常给 bridge

数据来源：
    SQLite 的 kb_chunk 表（经 app.storage 的 kb_dao / docs_dao 读取），
    在内存中用 KeywordRetriever 做 BM25 关键词检索。

模块导入零副作用：不发网络请求、不建 DB 文件、不启动线程（DB 连接为首次调用时惰性建立）。
"""
from __future__ import annotations

from app.storage.retriever import KeywordRetriever


TOOL_NAME = "kb_search"
DEFAULT_TOP_K = 5
MAX_TOP_K = 20


def _to_int(value, default: int) -> int:
    """宽松地把参数转 int，失败则用默认值。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _load_chunks(kb_id: str = "") -> list[dict]:
    """从 DB 读出切片，标准化为 KeywordRetriever.add_chunks 需要的结构。

    kb_id 为空时读取全部知识库的切片；指定时只读该库。
    """
    from app.storage import kb_dao, docs_dao

    raw: list[dict] = []
    if kb_id:
        raw = docs_dao.list_chunks_by_kb(kb_id) or []
    else:
        for kb in (kb_dao.list_all() or []):
            kid = kb.get("id")
            if not kid:
                continue
            raw.extend(docs_dao.list_chunks_by_kb(kid) or [])

    chunks: list[dict] = []
    for i, c in enumerate(raw):
        content = (c.get("content") or "").strip()
        if not content:
            continue
        chunks.append({
            "id": c.get("id") or f"db_{i}",
            "content": content,
            "char_count": c.get("char_count") or len(content),
            "position": c.get("sort_order", i),
            "source": c.get("doc_name") or c.get("doc_id") or "",
            "doc_id": c.get("doc_id", ""),
            "kb_id": c.get("kb_id", ""),
        })
    return chunks


def _search(query: str, top_k: int, kb_id: str) -> list[dict]:
    """按关键词检索并整理为精简结果列表。"""
    retriever = KeywordRetriever()
    retriever.add_chunks(_load_chunks(kb_id))
    kb_ids = [kb_id] if kb_id else None
    hits = retriever.search(query, top_k=top_k, kb_ids=kb_ids)
    results: list[dict] = []
    for h in hits:
        results.append({
            "content": h.get("content", ""),
            "score": h.get("score", 0),
            "kb_id": h.get("kb_id", ""),
            "doc_id": h.get("doc_id", ""),
            "source": h.get("source", ""),
            "position": h.get("position", 0),
        })
    return results


def call_tool(args: dict) -> dict:
    """按 __tool_name 分发执行知识库检索。"""
    try:
        args = args or {}
        name = args.get("__tool_name") or TOOL_NAME
        if name != TOOL_NAME:
            return {"ok": False, "error": f"未知工具名: {name}"}

        query = (args.get("query") or "").strip()
        if not query:
            return {"ok": False, "error": "缺少 query 参数"}

        top_k = max(1, min(MAX_TOP_K, _to_int(args.get("top_k"), DEFAULT_TOP_K)))
        kb_id = (args.get("kb_id") or "").strip()

        results = _search(query, top_k, kb_id)
        return {
            "ok": True,
            "query": query,
            "top_k": top_k,
            "kb_id": kb_id,
            "count": len(results),
            "results": results,
        }
    except Exception as e:  # noqa: BLE001 —— 绝不把异常抛回 bridge
        return {"ok": False, "error": f"知识库检索失败: {e}"}
