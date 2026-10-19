# -*- coding: utf-8 -*-
"""好单库 CPS 助手 —— 工具定义与调用实现。

面向两个工具（由 bridge 按 function.name 分发）：
  - cps_selector  面向顾客：关键词/需求 → 高佣商品（含优惠券）推荐
  - cps_earnings  管理者专属：按时间/平台汇总预估与结算佣金、退款

契约：
  - bridge 注入 args：__tool_name / __agent_id / __is_manager / __credentials / __app_config
  - 返回值必须可 json 序列化
  - 本模块 import 无副作用（不建网络连接、不建 DB 文件）
"""
from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

# ==================== 工具定义 ====================

TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "cps_selector",
        "description": (
            "好单库CPS选品助手（面向顾客）：根据顾客说的关键词或需求，"
            "跨拼多多/京东/唯品会/闲鱼/美团等平台搜索商品，返回带优惠券的高佣省钱推荐。"
            "mode=coupon 只看有券商品；mode=hot 按销量热度排；mode=compare 多平台比价。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "顾客想找的商品/服务关键词，如‘奶茶’‘蓝牙耳机’‘外卖红包’",
                },
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "可选：多个关键词（与 keyword 二选一或多给）",
                },
                "mode": {
                    "type": "string",
                    "enum": ["search", "coupon", "hot", "compare"],
                    "description": "选品模式，默认 search（综合）。coupon=仅带券，hot=看销量，compare=多平台比价",
                },
                "platforms": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "可选：限定平台，取值 pdd/jd/vip/xianyu/meituan/taobao，默认自动挑选可用平台",
                },
                "top": {
                    "type": "integer",
                    "description": "返回条数，默认 6",
                },
            },
            "required": [],
        },
    },
}

TOOL_DEF_EARNINGS = {
    "type": "function",
    "function": {
        "name": "cps_earnings",
        "description": (
            "好单库佣金中心（管理者专属）：按时间范围与平台汇总推广订单的"
            "预估佣金、已结算佣金和退款情况，一句话看‘今天/这周赚了多少’。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["summary", "platform", "detail"],
                    "description": "汇总方式：summary=总计（默认），platform=按平台拆分，detail=订单明细",
                },
                "platforms": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "可选：限定平台 pdd/jd/meituan/eleme，默认全部",
                },
                "days": {
                    "type": "integer",
                    "description": "查询最近 N 天，默认 7（当未显式给 start_date/end_date 时生效）",
                },
                "start_date": {
                    "type": "string",
                    "description": "开始时间，Unix 时间戳或 YYYY-MM-DD",
                },
                "end_date": {
                    "type": "string",
                    "description": "结束时间，Unix 时间戳或 YYYY-MM-DD",
                },
                "date_type": {
                    "type": "integer",
                    "description": "时间口径：1付款时间(默认)/2结算时间/3失效时间/4更新时间",
                },
                "state": {
                    "type": "integer",
                    "description": "订单状态：0全部(默认)/1已付款/2已结算/3已退款",
                },
                "top": {
                    "type": "integer",
                    "description": "detail 模式返回的明细条数，默认 20",
                },
            },
            "required": [],
        },
    },
}

# ==================== 好单库接口常量 ====================
# 均取自《好单库API能力说明》与实际集成代码（cps_adapters.py），非臆造。

# 支持关键词搜索的平台 -> 接口地址
SEARCH_ENDPOINTS = {
    "pdd": "http://v2.api.haodanku.com/pdd_goods_search",
    "jd": "https://v3.api.haodanku.com/unify_jdgoods_search",
    "vip": "http://v2.api.haodanku.com/vip_goods_search",
    "xianyu": "http://v3.api.haodanku.com/idle_goods_query",
    "meituan": "https://v3.api.haodanku.com/mt_goods_query",
    "taobao": "http://v2.api.haodanku.com/get_keyword_items",
}

# 订单拉取平台 -> 接口地址
ORDER_ENDPOINTS = {
    "pdd": "https://v3.api.haodanku.com/unify_pdd_order_list",
    "jd": "https://v3.api.haodanku.com/unify_jd_order_list",
    "meituan": "https://v3.api.haodanku.com/mt_order_list",
    "eleme": "https://v3.api.haodanku.com/elm_order_list",
}

DEFAULT_SEARCH_PLATFORMS = ["pdd", "jd", "vip", "xianyu", "taobao"]
DEFAULT_ORDER_PLATFORMS = ["pdd", "jd", "meituan", "eleme"]

HTTP_TIMEOUT = 6

# 部分接口要求 keyword 两次 urlencode（好单库文档要求）
_DOUBLE_ENCODE_PLATFORMS = {"pdd", "jd"}

# 部分接口的 back 只接受离散值（实测：3、6 会返回空，必须取允许值中最接近且 >= 目标的值）
_ALLOWED_BACK = [1, 2, 5, 10, 20, 50, 100, 120, 200, 500, 1000]

# ==================== SSL 上下文 ====================
# 好单库 API 在 Windows 下可能存在证书链不完整问题，跳过校验（与项目既有集成一致）。
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


# ==================== 基础 HTTP ====================

def _http_get(url, params, timeout=HTTP_TIMEOUT):
    """好单库 GET 请求，返回解析后的 dict；异常向上抛出由调用方兜底。"""
    query = urllib.parse.urlencode(params)
    full_url = f"{url}?{query}"
    req = urllib.request.Request(full_url, method="GET")
    resp = urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX)
    try:
        raw = resp.read()
    finally:
        resp.close()
    return json.loads(raw.decode("utf-8"))


def _first(data, *keys):
    """按顺序取第一个非空字段值。"""
    for k in keys:
        if k in data and data[k] not in (None, ""):
            return data[k]
    return ""


def _to_float(value, default=0.0):
    try:
        if isinstance(value, str):
            value = value.strip().replace("%", "").replace("¥", "").replace(",", "")
        return float(value)
    except (TypeError, ValueError):
        return default


def _score(price, rate, sales):
    """0~100 综合评分：佣金比例权重 + 低价加成 + 销量加成。"""
    p = _to_float(price)
    r = _to_float(rate)
    s = _to_float(sales)
    score = 50.0
    score += min(r, 30.0)  # 佣金比例，最高 30
    if p > 0:
        score += max(0.0, 30.0 - min(p, 300.0) / 10.0)  # 低价加成，最高 30
    if s >= 10000:
        score += 10.0
    elif s >= 1000:
        score += 5.0
    return round(min(score, 100.0), 2)


def _normalize_item(platform, raw):
    """把各平台商品字段统一为契约格式（含 title/platform/price/commission_rate/score）。"""
    if platform == "pdd":
        title = _first(raw, "goodsname", "itemtitle")
        price = _first(raw, "itemendprice", "price")
        original = _first(raw, "itemprice", "original_price")
        coupon = _first(raw, "couponmoney", "coupon")
        rate = _first(raw, "promotion_rate", "tkrates", "commission_rate")
        commission = _first(raw, "tkmoney", "commission")
        sales = _first(raw, "itemsale", "sales")
        img = _first(raw, "itempic")
        shop = _first(raw, "shopname")
        item_id = _first(raw, "goods_id", "itemid")
        coupon_url = _first(raw, "couponurl")
    elif platform == "jd":
        title = _first(raw, "goodsname", "itemtitle")
        price = _first(raw, "itemendprice", "price")
        original = _first(raw, "itemprice")
        coupon = _first(raw, "couponmoney", "coupon")
        rate = _first(raw, "commission", "commissionshare", "commission_rate")
        commission = _first(raw, (raw.get("commission_info") or {}).get("commission") if isinstance(raw.get("commission_info"), dict) else "")
        sales = _first(raw, "itemsale", "sales")
        img = _first(raw, "itempic")
        shop = _first(raw, "shopname")
        item_id = _first(raw, "itemid", "skuid")
        coupon_url = _first(raw, "couponurl")
    elif platform == "vip":
        title = _first(raw, "itemshorttitle", "itemtitle")
        price = _first(raw, "itemprice", "price")
        original = _first(raw, "marketPrice")
        coupon = _first(raw, "couponmoney", "coupon")
        rate = _first(raw, "tkrates", "commission_rate")
        commission = _first(raw, "tkmoney", "commission")
        sales = _first(raw, "itemsale", "sales")
        img = _first(raw, "itempic")
        shop = _first(raw, "shopname")
        item_id = _first(raw, "goodsid", "itemid")
        coupon_url = _first(raw, "itemurl")
    elif platform == "xianyu":
        title = _first(raw, "item_title", "title")
        price = _first(raw, "reserve_price", "price")
        original = _first(raw, "original_price")
        coupon = ""
        rate = _first(raw, "commission_rate")
        commission = _first(raw, "estimated_commission")
        sales = ""
        img = _extract_xianyu_img(raw.get("image_urls"))
        shop = ""
        item_id = _first(raw, "item_id")
        coupon_url = ""
    elif platform == "meituan":
        title = _first(raw, "name", "title")
        price = _first(raw, "sellPrice", "price")
        original = _first(raw, "originalPrice")
        coupon = ""
        rate = _first(raw, "commissionPercent", "commission_rate")
        commission = _first(raw, "commission")
        sales = _first(raw, "saleVolume", "sales")
        img = _first(raw, "headUrl")
        shop = _first(raw, "poiName", "shopname")
        item_id = _first(raw, "skuViewId", "itemid")
        coupon_url = ""
    else:  # taobao 或未知，按通用好单库字段解析
        title = _first(raw, "itemshorttitle", "itemtitle", "goodsname", "title")
        price = _first(raw, "itemendprice", "price")
        original = _first(raw, "itemprice")
        coupon = _first(raw, "couponmoney", "coupon")
        rate = _first(raw, "tkrates", "commission_rate")
        commission = _first(raw, "tkmoney", "commission")
        sales = _first(raw, "itemsale", "sales")
        img = _first(raw, "itempic")
        shop = _first(raw, "shopname")
        item_id = _first(raw, "itemid", "goods_id")
        coupon_url = _first(raw, "couponurl", "planlink")

    return {
        "platform": platform,
        "title": str(title or ""),
        "price": str(price) if price != "" else "",
        "original_price": str(original) if original != "" else "",
        "coupon_amount": str(coupon) if coupon != "" else "",
        "commission_rate": str(rate) if rate != "" else "",
        "commission": str(commission) if commission != "" else "",
        "sales": str(sales) if sales != "" else "0",
        "img": str(img or ""),
        "shop": str(shop or ""),
        "item_id": str(item_id or ""),
        "coupon_url": str(coupon_url or ""),
        "score": _score(price, rate, sales),
    }


def _extract_xianyu_img(image_urls):
    if not image_urls:
        return ""
    if isinstance(image_urls, dict):
        urls = image_urls.get("string", [])
        return urls[0] if urls else ""
    if isinstance(image_urls, list):
        return image_urls[0] if image_urls else ""
    return ""


# ==================== 单平台搜索 ====================

def _allowed_back(page_size):
    """取允许的 back 值中最接近且 >= 目标的值。"""
    target = max(1, int(page_size))
    for b in _ALLOWED_BACK:
        if b >= target:
            return b
    return _ALLOWED_BACK[-1]


def _search_one(apikey, platform, keyword, page_size):
    """搜索单个平台，返回标准化商品列表；任何异常都返回空列表。"""
    url = SEARCH_ENDPOINTS.get(platform)
    if not url or not keyword:
        return []

    params = {"apikey": apikey}
    if platform in _DOUBLE_ENCODE_PLATFORMS:
        params["keyword"] = urllib.parse.quote(urllib.parse.quote(keyword))
    else:
        params["keyword"] = keyword

    if platform == "pdd":
        back = max(10, (_allowed_back(page_size) // 10) * 10)
        params.update({"min_id": 1, "back": min(back, 100)})
    elif platform == "jd":
        back = 10 if page_size <= 10 else (20 if page_size <= 20 else 30)
        params.update({"min_id": 1, "back": back, "sort": 2})
    elif platform == "meituan":
        params.update({"min_id": 1, "back": min(_allowed_back(page_size), 20)})
    elif platform == "xianyu":
        # 闲鱼接口不需要 back
        params["min_id"] = 1
    else:  # vip / taobao
        params.update({"min_id": 1 if platform == "vip" else 0, "back": _allowed_back(page_size)})
        if platform == "taobao":
            params["sort"] = 0

    try:
        data = _http_get(url, params)
    except Exception:
        return []

    if not isinstance(data, dict):
        return []
    if data.get("code") not in (1, 200):
        return []
    rows = data.get("data") or []
    if not isinstance(rows, list):
        return []

    items = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        item = _normalize_item(platform, raw)
        if item["title"]:
            items.append(item)
    return items[:page_size]


def search_products(apikey, keywords, platforms=None, page_size=6, mode="search"):
    """跨平台关键词搜索并统一排序。

    返回 (items, total_searched)：total_searched 为各平台原始命中条数之和。
    """
    if isinstance(keywords, str):
        keywords = [keywords]
    keywords = [k for k in (keywords or []) if isinstance(k, str) and k.strip()]
    if not keywords:
        return [], 0

    platforms = [p for p in (platforms or DEFAULT_SEARCH_PLATFORMS) if p in SEARCH_ENDPOINTS]
    if not platforms:
        platforms = list(DEFAULT_SEARCH_PLATFORMS)

    # 关键词最多取 2 个，避免请求过多
    use_keywords = keywords[:2]

    collected = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = []
        for kw in use_keywords:
            for p in platforms:
                futures.append(pool.submit(_search_one, apikey, p, kw, page_size))
        for fut in futures:
            try:
                collected.extend(fut.result(timeout=HTTP_TIMEOUT + 2))
            except Exception:
                continue

    total_searched = len(collected)

    # 去重：同平台同 item_id（无 id 时按标题）只留一个
    seen = set()
    deduped = []
    for it in collected:
        key = (it["platform"], it["item_id"] or it["title"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(it)

    # 排序
    def _has_coupon(it):
        return bool(it.get("coupon_url")) or _to_float(it.get("coupon_amount")) > 0

    if mode == "coupon":
        pool_items = [it for it in deduped if _has_coupon(it)]
    else:
        pool_items = deduped

    if mode == "hot":
        pool_items.sort(key=lambda x: (_to_float(x.get("sales")), x["score"]), reverse=True)
    else:
        pool_items.sort(key=lambda x: x["score"], reverse=True)

    return pool_items[:page_size], total_searched


# ==================== 订单 / 佣金 ====================

def _to_ts(value, default=None):
    """把 Unix 时间戳或 YYYY-MM-DD 转成 int 时间戳。"""
    if value in (None, ""):
        return default
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return int(time.mktime(time.strptime(text, fmt)))
        except ValueError:
            continue
    return default


def _order_status_text(raw):
    status = _first(raw, "order_status", "state", "status")
    settled = _first(raw, "settled_status", "settle_status")
    return str(status), str(settled)


def _is_refund(raw):
    status, settled = _order_status_text(raw)
    joined = f"{status} {settled}".lower()
    return any(t in joined for t in ("refund", "退款", "失效", "已退"))


def fetch_orders(apikey, platforms, start_date, end_date, date_type=1, state=0, page_size=100):
    """拉取各平台订单明细，返回 (orders, total_fetched)。"""
    platforms = [p for p in (platforms or DEFAULT_ORDER_PLATFORMS) if p in ORDER_ENDPOINTS]
    if not platforms:
        platforms = list(DEFAULT_ORDER_PLATFORMS)

    def _one(p):
        url = ORDER_ENDPOINTS[p]
        params = {
            "apikey": apikey,
            "min_id": 1,
            "back": min(page_size, 100),
            "start_date": start_date,
            "end_date": end_date,
            "date_type": date_type,
            "state": state,
        }
        try:
            data = _http_get(url, params)
        except Exception:
            return []
        if not isinstance(data, dict) or data.get("code") not in (1, 200):
            return []
        rows = data.get("data") or []
        if not isinstance(rows, list):
            return []
        result = []
        for raw in rows:
            if isinstance(raw, dict):
                raw = dict(raw)
                raw["_platform"] = p
                result.append(raw)
        return result

    orders = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for fut in [pool.submit(_one, p) for p in platforms]:
            try:
                orders.extend(fut.result(timeout=HTTP_TIMEOUT + 2))
            except Exception:
                continue
    return orders


def aggregate_orders(apikey, platforms=None, start_date=None, end_date=None,
                     date_type=1, state=0, mode="summary", top=20):
    """按平台汇总预估/结算佣金与退款，返回结构化结果。"""
    now = int(time.time())
    start = _to_ts(start_date)
    end = _to_ts(end_date, default=now)
    if start is None:
        start = end - 7 * 86400

    platforms = [p for p in (platforms or DEFAULT_ORDER_PLATFORMS) if p in ORDER_ENDPOINTS]
    if not platforms:
        platforms = list(DEFAULT_ORDER_PLATFORMS)

    orders = fetch_orders(apikey, platforms, start, end, date_type=date_type, state=state)

    by_platform = {}
    details = []
    total_predict = 0.0
    total_settled = 0.0
    refund_count = 0
    refund_money = 0.0

    for raw in orders:
        p = raw.get("_platform", "未知")
        predict = _to_float(_first(raw, "predict_money", "predict_commission", "commission", "estimated_commission"))
        settled = _to_float(_first(raw, "actual_money", "settled_money", "settle_money", "commission"))
        refund = _is_refund(raw)

        bucket = by_platform.setdefault(p, {"platform": p, "orders": 0, "predict_money": 0.0,
                                            "settled_money": 0.0, "refund_count": 0, "refund_money": 0.0})
        bucket["orders"] += 1
        bucket["predict_money"] += predict
        if not refund:
            total_predict += predict
            total_settled += settled
            bucket["settled_money"] += settled
        else:
            refund_count += 1
            refund_money += predict
            bucket["refund_count"] += 1
            bucket["refund_money"] += predict

        if mode == "detail":
            details.append({
                "platform": p,
                "title": str(_first(raw, "title", "product_title", "goodsname", "itemtitle") or ""),
                "order_id": str(_first(raw, "trade_id", "order_id", "trade_parent_id", "order_sn") or ""),
                "pay_price": str(_first(raw, "pay_price", "payprice", "settle_price") or ""),
                "predict_money": round(predict, 2),
                "settled_money": round(settled, 2),
                "status": _order_status_text(raw)[0],
                "refund": refund,
                "paid_time": str(_first(raw, "paid_time", "create_time", "created_at") or ""),
            })

    for b in by_platform.values():
        b["predict_money"] = round(b["predict_money"], 2)
        b["settled_money"] = round(b["settled_money"], 2)
        b["refund_money"] = round(b["refund_money"], 2)

    summary = {
        "start_date": start,
        "end_date": end,
        "date_type": date_type,
        "state": state,
        "platforms": platforms,
        "orders_total": len(orders),
        "predict_money": round(total_predict, 2),
        "settled_money": round(total_settled, 2),
        "refund_count": refund_count,
        "refund_money": round(refund_money, 2),
    }
    result = {"ok": True, "summary": summary,
              "by_platform": sorted(by_platform.values(), key=lambda x: x["predict_money"], reverse=True)}
    if mode == "detail":
        result["details"] = details[: max(1, int(top or 20))]
    result["note"] = _earnings_note(summary)
    result["total_searched"] = len(orders)
    return result


def _fmt_ts(ts):
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(int(ts)))
    except (TypeError, ValueError):
        return str(ts)


def _earnings_note(summary):
    return (
        f"统计 {_fmt_ts(summary['start_date'])} ~ {_fmt_ts(summary['end_date'])} 共 {summary['orders_total']} 单，"
        f"预估佣金 ¥{summary['predict_money']}，已结算 ¥{summary['settled_money']}，"
        f"退款 {summary['refund_count']} 单（¥{summary['refund_money']}）。"
    )


# ==================== 凭据处理 ====================

def _maybe_decrypt(value):
    """好单库 Key 在库中可能是 DPAPI 加密串；decrypt_secret 对明文原样返回。"""
    if not value:
        return ""
    try:
        from app.storage.crypto import decrypt_secret
        return decrypt_secret(value)
    except Exception:
        return value


def _apikey_from_credentials(credentials):
    if not isinstance(credentials, dict):
        return ""
    return _maybe_decrypt(credentials.get("haodanku_api_key", "") or "").strip()


def read_stored_api_key():
    """从 app_credential 表读取好单库 API Key（runner/test 使用）。"""
    try:
        from app.storage import app_credential_dao
        row = app_credential_dao.get("haodanku_api_key")
        return _maybe_decrypt((row or {}).get("value", "") or "").strip()
    except Exception:
        return ""


# ==================== 结果摘要文案 ====================

def _selector_summary(items, total_searched, keywords, mode):
    if not items:
        return (f"没找到「{'/'.join(keywords)}」相关的高佣商品"
                + (f"（已检索 {total_searched} 条）" if total_searched else "")
                + "，换个关键词试试？")
    lines = [f"🛒 为你找到 {len(items)} 款「{'/'.join(keywords)}」好价（已筛自 {total_searched} 条）："]
    for i, it in enumerate(items, 1):
        name = it["title"][:24] + ("…" if len(it["title"]) > 24 else "")
        seg = f"{i}. [{it['platform']}] {name} ¥{it['price']}"
        if it.get("coupon_amount"):
            seg += f"（券¥{it['coupon_amount']}）"
        if it.get("commission_rate"):
            seg += f" 佣金{it['commission_rate']}%"
        lines.append(seg)
        if it.get("coupon_url"):
            lines.append(f"   👉 {it['coupon_url']}")
    return "\n".join(lines)


# ==================== 工具入口 ====================

def _handle_selector(args):
    apikey = _apikey_from_credentials(args.get("__credentials"))
    if not apikey:
        return {"ok": False, "error": "未配置好单库 API Key"}

    keywords = []
    if args.get("keyword"):
        keywords.append(str(args["keyword"]))
    if isinstance(args.get("keywords"), list):
        keywords.extend([str(k) for k in args["keywords"] if str(k).strip()])
    keywords = [k.strip() for k in keywords if k and k.strip()]
    if not keywords:
        return {"ok": False, "error": "请告诉我你想找什么（关键词）"}

    mode = str(args.get("mode") or "search").lower()
    if mode not in ("search", "coupon", "hot", "compare"):
        mode = "search"
    platforms = args.get("platforms") if isinstance(args.get("platforms"), list) else None
    top = int(args.get("top") or 6)
    top = max(1, min(top, 20))

    try:
        items, total_searched = search_products(apikey, keywords, platforms=platforms,
                                                page_size=top, mode=mode)
    except Exception as e:
        return {"ok": False, "error": f"好单库搜索失败：{e}"}

    return {
        "ok": True,
        "items": items,
        "total_searched": total_searched,
        "note": _selector_summary(items, total_searched, keywords, mode),
    }


def _handle_earnings(args):
    if not args.get("__is_manager"):
        return {"ok": False, "error": "该工具仅管理者可用"}

    apikey = _apikey_from_credentials(args.get("__credentials"))
    if not apikey:
        return {"ok": False, "error": "未配置好单库 API Key"}

    mode = str(args.get("mode") or "summary").lower()
    if mode not in ("summary", "platform", "detail"):
        mode = "summary"
    platforms = args.get("platforms") if isinstance(args.get("platforms"), list) else None

    start_date = args.get("start_date")
    end_date = args.get("end_date")
    if not start_date and not end_date:
        days = int(args.get("days") or 7)
        end_ts = int(time.time())
        start_date = end_ts - max(1, days) * 86400
        end_date = end_ts

    try:
        return aggregate_orders(
            apikey,
            platforms=platforms,
            start_date=start_date,
            end_date=end_date,
            date_type=int(args.get("date_type") or 1),
            state=int(args.get("state") or 0),
            mode=mode,
            top=int(args.get("top") or 20),
        )
    except Exception as e:
        return {"ok": False, "error": f"好单库佣金查询失败：{e}"}


def call_tool(args: dict) -> dict:
    """bridge 注入 args 后调用的统一入口，按 __tool_name 分发。"""
    if not isinstance(args, dict):
        return {"ok": False, "error": "参数格式错误"}
    tool_name = args.get("__tool_name", "")
    try:
        if tool_name == "cps_selector":
            return _handle_selector(args)
        if tool_name == "cps_earnings":
            return _handle_earnings(args)
        return {"ok": False, "error": f"未知工具：{tool_name}"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
