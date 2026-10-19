# -*- coding: utf-8 -*-
"""好单库 CPS 助手 —— 批量选品 runner。

bridge._handle_run_app_once 会调用 run(context)，并读取返回 dict 的
items / total_searched / note。items 每项至少含 title, platform, price,
commission_rate, score。

context 支持：
  keywords / keyword —— 关键词（list 或 str）
  mode               —— search/coupon/hot/compare，默认 search
  platforms          —— 可选，限定平台
  top / page_size    —— 返回条数，默认 10
"""
from __future__ import annotations

from app.apps.cps_selector.tool import (
    DEFAULT_SEARCH_PLATFORMS,
    read_stored_api_key,
    search_products,
)


def run(context: dict | None = None, **kwargs) -> dict:
    context = context if isinstance(context, dict) else {}
    if kwargs:
        merged = dict(context)
        for k, v in kwargs.items():
            if v is not None and k not in merged:
                merged[k] = v
        context = merged

    keywords = context.get("keywords")
    if not keywords and context.get("keyword"):
        keywords = [context["keyword"]]
    if isinstance(keywords, str):
        keywords = [keywords]
    keywords = [k for k in (keywords or []) if isinstance(k, str) and k.strip()]

    if not keywords:
        return {"ok": True, "items": [], "total_searched": 0, "note": "未提供关键词，无法选品"}

    mode = str(context.get("mode") or "search").lower()
    if mode not in ("search", "coupon", "hot", "compare"):
        mode = "search"

    platforms = context.get("platforms")
    if not isinstance(platforms, list):
        platforms = None

    try:
        top = int(context.get("top") or context.get("page_size") or 10)
    except (TypeError, ValueError):
        top = 10
    top = max(1, min(top, 20))

    apikey = read_stored_api_key()
    if not apikey:
        return {"ok": True, "items": [], "total_searched": 0, "note": "未配置好单库 API Key"}

    try:
        items, total_searched = search_products(
            apikey,
            keywords,
            platforms=platforms or DEFAULT_SEARCH_PLATFORMS,
            page_size=top,
            mode=mode,
        )
    except Exception as e:
        return {"ok": True, "items": [], "total_searched": 0,
                "note": f"好单库选品失败：{e}"}

    note = f"「{'/'.join(keywords)}」模式 {mode}，命中 {total_searched} 条，取前 {len(items)} 条"
    return {"ok": True, "items": items, "total_searched": total_searched, "note": note}
