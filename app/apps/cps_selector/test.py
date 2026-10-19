# -*- coding: utf-8 -*-
"""好单库 CPS 助手 —— 连通性自测。

bridge._handle_run_app_test 会无参调用 run()，返回简要 dict/str。
读取 app_credential 表中的 haodanku_api_key，做一次轻量搜索验证连通性。
"""
from __future__ import annotations

from app.apps.cps_selector.tool import read_stored_api_key, search_products


def run():
    apikey = read_stored_api_key()
    if not apikey:
        return {"ok": False, "error": "未配置好单库 API Key"}

    try:
        items, total = search_products(apikey, ["零食"], platforms=["pdd"], page_size=3, mode="search")
    except Exception as e:
        return {"ok": False, "error": f"好单库连通性测试失败：{e}"}

    if total == 0:
        return {
            "ok": False,
            "message": "能连上但未返回商品，请检查 API Key 权限或稍后重试",
            "sample_count": 0,
        }

    return {
        "ok": True,
        "message": f"好单库连通正常，样例搜索返回 {total} 条",
        "sample_count": total,
        "sample": items[0]["title"] if items else "",
    }
