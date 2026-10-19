r"""虎皮椒 V3 支付对接（微信个人远程支付 / 支付宝个人支付）。

官方 API 文档：
  - 准备工作：https://www.xunhupay.com/doc/prepare.html
  - 下单接口：https://www.xunhupay.com/doc/api/pay.html    POST /payment/do.html
  - 查询接口：https://www.xunhupay.com/doc/api/search.html  POST /payment/query.html（或 query.do）
  - 退款接口：https://www.xunhupay.com/doc/api/refund.html

V3 签名算法（官方文档 HASH 生成步骤）：
  Step 1. 把所有「非空值」参数按参数名 ASCII 从小到大（字典序）排序；
          hash 参数本身不参与签名，其他参数名区分大小写；空字符串 / None 不参与。
  Step 2. 用 URL 键值对格式拼接：k1=v1&k2=v2...
  Step 3. 在最后**直接**拼接 APPSECRET（前不带 & ，也不带 hash= 前缀）
  Step 4. 对结果做 MD5(utf-8) ，得到 32 位小写 hash 值。

返回字段（下单成功）：
  - openid       历史遗留字段名，实际是 orderid（虎皮椒内部订单号）
  - url_qrcode   PC 端二维码内容（有效期 5 分钟），可直接交给前端 qrcode.js 画图
  - url          手机端跳转（PC 场景不用）
  - errcode      0 表示成功
  - errmsg       错误说明
  - hash         返回签名，可再验签

使用方式：
  1. 真实支付：在下面配置区填 XUNHU_APPID / XUNHU_SECRET ，把 USE_MOCK=False
  2. MVP 本地联调：用默认 USE_MOCK=True，30 秒后 poll_status 会自动返回 paid=True
     回调接口直接塞一个验签通过的模拟包也能触发激活
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any


# ==================== 配置区（审核通过后把 APPID/APPSECRET 填进来；默认本地模拟模式） ====================
USE_MOCK: bool = True                          # True=模拟，不真实扣款；False=连真实虎皮椒
XUNHU_APPID: str = ""                          # 默认空，优先从 _secrets.py 覆盖
XUNHU_SECRET: str = ""                         # 默认空，优先从 _secrets.py 覆盖
PAY_API_BASE: str = "https://api.xunhupay.com" # 正式网关
PAY_API_BACKUP: str = "https://api.dpweixin.com"  # 备用网关（主网关挂了可切到这个）
PAY_GOODS_NAME: str = "AVATAR AI · 正式版永久激活码"
PAY_AMOUNT_YUAN: float = 299.0                 # 299.00 元（注意：虎皮椒 total_fee 单位是「元」不是「分」！）
ORDER_EXPIRE_SECONDS: int = 15 * 60            # 15 分钟订单有效期
REQ_TIMEOUT: int = 12

# 优先从 _secrets.py 读敏感凭证（该文件在 .gitignore 里，永远不进仓库）
try:
    from . import _secrets as _s  # noqa: WPS433
    if getattr(_s, "XUNHU_APPID", ""):
        XUNHU_APPID = _s.XUNHU_APPID
    if getattr(_s, "XUNHU_SECRET", ""):
        XUNHU_SECRET = _s.XUNHU_SECRET
except ImportError:
    pass  # _secrets.py 不存在 = 开发阶段，凭证保持空字符串

# ========== 本地回调 HTTP 服务配置 ==========
# 回调监听地址：虎皮椒 POST 到 http://127.0.0.1:<LOCAL_NOTIFY_PORT>/pay/xunhupay/notify
# 真实环境下可用内网穿透把此端口映射到公网；MVP 阶段「轮询」即可完成激活，
# 本地回调服务作为双保险，当回调真的到达时立刻激活（体验更好）。
LOCAL_NOTIFY_HOST: str = "127.0.0.1"
LOCAL_NOTIFY_PORT: int = 8765
LOCAL_NOTIFY_PATH: str = "/pay/xunhupay/notify"


def default_notify_url() -> str:
    """返回默认的回调 URL（下单时若调用方没传 notify_url，就用它）。"""
    return f"http://{LOCAL_NOTIFY_HOST}:{LOCAL_NOTIFY_PORT}{LOCAL_NOTIFY_PATH}"


# ==================== 签名 / 验签工具（V3 标准严格实现） ====================
def _sign(params: dict[str, Any], secret: str) -> str:
    """按官方 HASH 步骤生成签名：k=v 字典序(ASCII) → 末尾直接拼 secret → MD5 小写 32 位。"""
    if not secret:
        return ""
    items: list[tuple[str, str]] = []
    for k, v in params.items():
        if k == "hash":
            continue
        if v is None or v == "":
            continue
        items.append((str(k), str(v)))
    items.sort(key=lambda pair: pair[0])  # ASCII 字典序
    joined = "&".join(f"{k}={v}" for k, v in items)
    raw = f"{joined}{secret}".encode("utf-8")
    return hashlib.md5(raw).hexdigest().lower()


def verify_sign(data: dict[str, Any], secret: str = "") -> bool:
    """对外公开的验签工具（回调 / 返回包都用这个）。"""
    s = secret or XUNHU_SECRET
    if not s:
        return False  # 没配密钥时：一律判不通过，防止没配置就上线误接
    incoming = (data or {}).get("hash")
    if not incoming:
        return False
    expected = _sign(data, s)
    # 时序安全比对（虽然金额不大，但保持好习惯）
    import hmac as _hmac
    return _hmac.compare_digest(str(incoming).lower(), expected.lower())


def _post_json(url: str, data: dict[str, Any], timeout: int = REQ_TIMEOUT) -> dict[str, Any]:
    """POST form-urlencoded 并解析 JSON。虎皮椒接口支持 form POST，返回 JSON。"""
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
            "Accept": "application/json, */*",
            "Origin": "https://pay.avatar-ai.local",  # 与我们申请时填的发起域名一致，降低风控拒单
            "Referer": "https://pay.avatar-ai.local/",
            "User-Agent": "AVATAR-AI-MVP-Payment/1.0 (Desktop; Windows NT)",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            text = r.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as e:
        return {"ok": False, "error": f"网络错误：{e.reason}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"请求失败：{type(e).__name__}: {e!r}"}
    if not text.strip():
        return {"ok": False, "error": "虎皮椒接口返回空字符串"}
    try:
        return {"ok": True, "json": json.loads(text), "raw": text}
    except Exception:  # noqa: BLE001
        # 个别失败场景返回非 JSON（比如 HTML），截前 300 字给排查
        return {"ok": False, "error": "响应非 JSON：" + text[:300].replace("\n", " ")}


def _gen_out_trade_no(machine_code: str) -> str:
    """生成唯一商户订单号：前缀 AVT + 秒时间戳(10) + machine 末 4 + uuid 短码 6。

    虎皮椒要求 trade_order_id 在当前应用内唯一，且只允许 [A-Za-z0-9_\\-*] 字符。
    """
    safe_mc_tail = "".join(ch for ch in machine_code[-4:] if ch.isalnum()).rjust(4, "0")
    return f"AVT{int(time.time())}{safe_mc_tail}{uuid.uuid4().hex[:6]}"


# ==================== 对外 API 1：创建订单 / 生成二维码 ====================
def create_order(
    machine_code: str,
    *,
    out_trade_no: str | None = None,
    amount_yuan: float | None = None,
    goods_name: str | None = None,
    notify_url: str | None = None,
) -> dict[str, Any]:
    """创建虎皮椒扫码支付订单。

    统一返回结构（mock / real 都一致）：
        ok:                  bool
        mode:                "mock" | "real"
        trade_order_id:      我们自己的 out_trade_no，用于后续查单和回调对账
        qr_url:              二维码内容字符串（前端 qrcode.js 画图即可）
        amount:              带 ¥ 号字符串，如 "¥299.00"
        amount_yuan:         数字 299.0
        amount_cents:        数字 29900
        goods_name:          订单标题
        expires_at:          过期秒级时间戳（15 分钟）
        note?:               模拟模式下给前端/开发者的提示文字
        error?:              ok=False 时的错误原因
    """
    amount_yuan = float(amount_yuan) if amount_yuan is not None else PAY_AMOUNT_YUAN
    amount_cents = int(round(amount_yuan * 100))
    goods_name = goods_name or f"{PAY_GOODS_NAME} · 机器 {machine_code[-6:] or 'XXXXXX'}"
    out_trade_no = out_trade_no or _gen_out_trade_no(machine_code)
    expires_at = int(time.time()) + ORDER_EXPIRE_SECONDS
    notify_url = notify_url or default_notify_url()

    # 未配参数 or 强制 mock：走模拟（本地联调 / 没开通真通道时都能跑）
    if USE_MOCK or not XUNHU_APPID or not XUNHU_SECRET:
        mode_note = []
        if not XUNHU_APPID or not XUNHU_SECRET:
            mode_note.append("尚未在 storage/payment.py 填入虎皮椒 APPID/APPSECRET")
        if USE_MOCK:
            mode_note.append("当前开启模拟模式，不真实扣款；30 秒后轮询会自动返回支付成功")
        return {
            "ok": True,
            "mode": "mock",
            "note": " · ".join(mode_note) or "模拟模式",
            "trade_order_id": out_trade_no,
            "qr_url": f"weixin://wxpay/bizpayurl?pr=MOCK_{out_trade_no}",
            "amount": f"¥{amount_yuan:.2f}",
            "amount_yuan": amount_yuan,
            "amount_cents": amount_cents,
            "goods_name": goods_name,
            "expires_at": expires_at,
            "_mock_success_at": int(time.time()) + 30,
            "_machine_code": machine_code,
            "_notify_url": notify_url or "",
        }

    # ===== 真实虎皮椒 V3 下单 =====
    params: dict[str, Any] = {
        "version": "1.1",
        "appid": XUNHU_APPID,
        "trade_order_id": out_trade_no,
        "total_fee": f"{amount_yuan:.2f}",   # ⚠️ 官方文档单位是「元」！不用分
        "title": goods_name[:120],            # title 最多 127 字符/42 汉字
        "time": int(time.time()),
        "notify_url": notify_url or "",
        "nonce_str": hashlib.md5(uuid.uuid4().bytes).hexdigest()[:16],
        "attach": machine_code,               # 回调回传机器码，用于绑定激活
        "plugins": "AVATAR-AI-MVP/1.0",
    }
    params["hash"] = _sign(params, XUNHU_SECRET)

    for base in (PAY_API_BASE, PAY_API_BACKUP):
        resp = _post_json(f"{base}/payment/do.html", params)
        if resp["ok"]:
            break
    if not resp.get("ok"):
        return {"ok": False, "error": resp.get("error") or "下单接口全部失败"}

    j: dict[str, Any] = resp["json"]
    errcode = int(j.get("errcode") or 0)
    if errcode != 0:
        return {"ok": False, "error": f"虎皮椒下单失败：{j.get('errmsg','')}（errcode={errcode}）"}

    # 可选：返回包验签（失败只打日志，不影响二维码展示）
    if not verify_sign(j, XUNHU_SECRET):
        print(f"[PAY] WARN 下单返回包验签不通过（但二维码仍可尝试使用）：{j}", flush=True)

    return {
        "ok": True,
        "mode": "real",
        "trade_order_id": j.get("trade_order_id") or out_trade_no,
        "xunhu_order_id": str(j.get("openid") or ""),  # 官方命名错误遗留字段，实际是虎皮椒 orderid
        "qr_url": str(j.get("url_qrcode") or j.get("code_url") or ""),
        "amount": f"¥{amount_yuan:.2f}",
        "amount_yuan": amount_yuan,
        "amount_cents": amount_cents,
        "goods_name": goods_name,
        "expires_at": expires_at,
    }


# ==================== 对外 API 2：轮询订单状态（用于前端 3 秒一次的 pull 刷新） ====================
def poll_order(
    trade_order_id: str,
    *,
    machine_code: str | None = None,
) -> dict[str, Any]:
    """查单。

    返回：
        ok:         bool
        paid:       bool 是否已经支付成功
        paid_at:    秒级时间戳（或 0）
        attach:     回传的 machine_code
        trade_no:   虎皮椒官方交易流水号
        license_key: 当 paid=True+attach 有值时，为该机器码生成的激活码（可直接去 activation_dao.activate）
        error?:     ok=False 时错误信息
    """
    now = int(time.time())
    # ---- Mock 模式：根据 create_order 写的 _mock_success_at 判定（这里我们用创建时间 +30 秒模拟） ----
    if USE_MOCK or not XUNHU_APPID or not XUNHU_SECRET:
        # 解析订单号里的 10 位时间戳（AVT{10_ts}{4_mc}{6_uuid}）
        ts_extracted = 0
        if trade_order_id.startswith("AVT") and len(trade_order_id) >= 13:
            try:
                ts_extracted = int(trade_order_id[3:13])
            except Exception:  # noqa: BLE001
                ts_extracted = 0
        # 【开发调试】暂时关掉 30 秒自动成功，方便测试手动激活路径
        # if ts_extracted and now >= ts_extracted + 30:
        #     from storage.license import generate_license_key
        #     mc = machine_code or ("MOCK-" + trade_order_id[-6:])
        #     return {
        #         "ok": True, "mode": "mock", "paid": True,
        #         "paid_at": now, "attach": mc, "trade_no": "MOCK" + trade_order_id,
        #         "out_trade_no": trade_order_id,
        #         "license_key": generate_license_key(mc),
        #         "note": "模拟模式：30 秒到点自动视为支付成功（非真实交易）",
        #     }
        return {
            "ok": True, "mode": "mock", "paid": False,
            "paid_at": 0, "attach": machine_code, "trade_no": None,
            "out_trade_no": trade_order_id,
        }

    # ---- 真实虎皮椒查单 V3 ----
    params: dict[str, Any] = {
        "appid": XUNHU_APPID,
        "trade_order_id": trade_order_id,
        "time": int(time.time()),
        "nonce_str": hashlib.md5(uuid.uuid4().bytes).hexdigest()[:16],
    }
    params["hash"] = _sign(params, XUNHU_SECRET)
    resp = _post_json(f"{PAY_API_BASE}/payment/query.html", params)
    if not resp.get("ok"):
        # 再试备用网关
        resp2 = _post_json(f"{PAY_API_BACKUP}/payment/query.html", params)
        if resp2.get("ok"):
            resp = resp2
        else:
            return {"ok": False, "error": resp.get("error") or resp2.get("error") or "查单失败"}
    j = resp["json"]
    errcode = int(j.get("errcode") or 0)
    if errcode != 0:
        return {"ok": False, "error": f"虎皮椒查单失败：{j.get('errmsg','')}（errcode={errcode}）"}
    if not verify_sign(j, XUNHU_SECRET):
        return {"ok": False, "error": "查单返回包验签失败，拒绝自动激活"}

    trade_status = str(j.get("trade_status") or j.get("status") or "").upper()
    paid = trade_status in ("TRADE_SUCCESS", "SUCCESS", "PAID", "OD")  # OD=官方V3已支付
    attach = str(j.get("attach") or "")
    paid_at = int(j.get("paid_at") or j.get("time_end") or j.get("time") or time.time()) if paid else 0
    lic = None
    if paid and attach:
        from storage.license import generate_license_key  # 延迟避免循环
        lic = generate_license_key(attach)

    return {
        "ok": True, "mode": "real", "paid": paid,
        "paid_at": paid_at, "attach": attach,
        "trade_no": str(j.get("transaction_id") or j.get("openid") or ""),
        "out_trade_no": trade_order_id,
        "license_key": lic,
    }


# ==================== 对外 API 3：异步回调验签 + 解析（虎皮椒 POST 到 notify_url 时用） ====================
def parse_notify(raw_body: str, content_type: str = "") -> dict[str, Any]:
    """解析虎皮椒异步回调请求体（支持 form / json 两种）并验签。

    返回结构：
        verified:   bool 是否通过签名校验（未通过直接拒绝，不要激活）
        paid:       bool 是否支付成功
        out_trade_no: 我们传的 trade_order_id
        transaction_id: 虎皮椒/微信官方流水号
        attach:     机器码（用来生成激活码）
        raw:        原始请求体（存 DB 留痕）
        parsed:     解析后的 dict（可能空）
        error?:     解析/验签失败原因
    """
    body = raw_body or ""
    data: dict[str, Any] = {}
    if body.strip().startswith("{") or (content_type or "").lower().find("json") >= 0:
        try:
            data = json.loads(body) if body else {}
        except Exception as e:  # noqa: BLE001
            return {"verified": False, "paid": False, "raw": body, "parsed": {},
                    "error": f"回调 JSON 解析失败：{e!r}"}
    else:
        try:
            data = dict(urllib.parse.parse_qsl(body, keep_blank_values=True))
        except Exception as e:  # noqa: BLE001
            return {"verified": False, "paid": False, "raw": body, "parsed": {},
                    "error": f"回调 form 解析失败：{e!r}"}

    # 真实模式才做真实验签；mock 模式下为了方便回调接口 smoke 测试，接受带 "mock_sign_ok=1" 的包视为通过
    secret = XUNHU_SECRET
    if USE_MOCK or not secret:
        ok = bool(data.get("mock_sign_ok"))
        return {
            "verified": ok,
            "paid": bool(data.get("paid")) if ok else False,
            "out_trade_no": data.get("out_trade_no") or data.get("trade_order_id") or "",
            "transaction_id": str(data.get("transaction_id") or ""),
            "attach": str(data.get("attach") or ""),
            "raw": body, "parsed": data,
            "error": ("模拟回调：缺少 mock_sign_ok=1，故意视为未通过" if not ok else None),
        }

    if not verify_sign(data, secret):
        return {"verified": False, "paid": False, "raw": body, "parsed": data,
                "error": "回调签名校验失败（secret 不匹配或参数被篡改）"}

    trade_status = str(data.get("trade_status") or data.get("status") or "").upper()
    paid = trade_status in ("TRADE_SUCCESS", "SUCCESS", "PAID", "OD")  # OD=官方V3已支付；CD=退款 / RD=退款中 / UD=退款失败 都不视为 paid
    return {
        "verified": True, "paid": paid,
        "out_trade_no": data.get("out_trade_no") or data.get("trade_order_id") or "",
        "transaction_id": str(data.get("transaction_id") or data.get("open_order_id") or data.get("openid") or ""),
        "attach": str(data.get("attach") or ""),
        "raw": body, "parsed": data,
    }


# ==================== 对外 API 4：根据回调/查单得到的 machine_code，生成管理员能复用的激活码字符串 ====================
def generate_license_for_machine(machine_code: str) -> str:
    """管理员工具（人工兜底 SOP / 自动化激活 都会用到）。

    返回格式 AVTR-XXXX-XXXX-XXXX（license.py 里本来就是 4 段式），
    保证与 verify_license_key / activation_dao.activate 链条 100% 匹配。
    """
    from storage.license import generate_license_key  # 延迟避免循环
    raw = (machine_code or "").strip()
    if not raw:
        raise ValueError("机器码不能为空")
    return generate_license_key(raw)


# ==================== CLI（开发自测 / 管理员激活码生成） ====================
if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    if not args:
        print("用法：")
        print("  py -m storage.payment create <machine_code>      # 创建支付订单")
        print("  py -m storage.payment poll   <trade_order_id>   # 查订单状态")
        print("  py -m storage.payment gen    <machine_code>     # 为某机器码生成激活码（人工兜底用）")
        print(f"\n当前：USE_MOCK={USE_MOCK}  APPID={'已填' if XUNHU_APPID else '未填'}  APPSECRET={'已填' if XUNHU_SECRET else '未填'}")
        print("修改本文件顶部 4 个常量切换真实支付。")
        sys.exit(0)
    cmd = args[0].lower()
    if cmd == "create":
        mc = args[1] if len(args) > 1 else "TEST-MC-0000"
        print(json.dumps(create_order(mc), ensure_ascii=False, indent=2))
    elif cmd == "poll":
        oid = args[1] if len(args) > 1 else ""
        print(json.dumps(poll_order(oid), ensure_ascii=False, indent=2))
    elif cmd == "gen":
        mc = args[1] if len(args) > 1 else ""
        try:
            print(generate_license_for_machine(mc))
        except ValueError as e:
            print(f"ERROR: {e}")
            sys.exit(1)
    else:
        print(f"未知命令：{cmd}")
        sys.exit(1)
