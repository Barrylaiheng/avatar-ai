r"""支付 + 激活 全链路 E2E smoke 测试（Mock 模式，不真实扣款）。

覆盖：
  1. get_machine_code          → 返回本机机器码
  2. pay_create                → 创建订单并入库 activation_orders（status=created）
                                 · 拉起本地回调 HTTP 服务，/ping 可达
  3. pay_poll（立即）          → paid=False
  4. admin_gen_license         → 管理员密钥正确时生成合法激活码（错误时抛 PermissionError）
  5. activate_with_license     → 手工激活码 OK → activation 表标记已激活
  6. 重置激活后，pay_poll（30s 后 mock 到点）→ paid=True + activated=True
  7. 模拟 HTTP 回调 POST /pay/xunhupay/notify → 触发 mark_paid + 激活（幂等无副作用）
  8. 回调验签不通过 / 无 sign_ok → 不激活、正确返回 "fail"

执行：
  venv\Scripts\python.exe tests\test_payment_bridge_e2e.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
sys.path.insert(0, str(APP))

# 在任何 storage 导入之前，强制 reset DB 到测试文件，避免污染生产
TEST_DB = ROOT / "tests" / "_test_payment_e2e.sqlite3"
os.environ["AVATAR_DB_PATH"] = str(TEST_DB)
if TEST_DB.exists():
    TEST_DB.unlink()

from storage.db import reset_db_for_tests  # noqa: E402
reset_db_for_tests()

import py_compile  # noqa: E402
py_compile.compile(str(APP / "bridge.py"), doraise=True)
py_compile.compile(str(APP / "storage" / "payment.py"), doraise=True)

# 注意：BridgeServer 继承 QObject，需要 QCoreApplication 才能实例化信号机制
# 为了在无 GUI 环境测试，我们用"伪桥接"模式：直接 new 实例，不调用 Qt 事件循环
# （信号 emit 不调用也 OK；我们只测 handler 返回值与 DB 副作用）
from PyQt6.QtCore import QCoreApplication  # noqa: E402
_app = QCoreApplication.instance() or QCoreApplication(sys.argv)

from bridge import BridgeServer  # noqa: E402
from storage import activation_dao, activation_orders_dao  # noqa: E402
from storage.machine import get_machine_code  # noqa: E402
from storage import payment as pay_mod  # noqa: E402


def _call(bridge: BridgeServer, action: str, payload: dict) -> dict:
    """模拟 JS 侧 call：走同一个桥接入口，用 getattr 拿 _handle_*，
    与真实 JS→Python 的调用链完全一致（除了不 emit JSON 信号）。"""
    h = getattr(bridge, f"_handle_{action}", None)
    assert h is not None, f"missing handler: _handle_{action}"
    try:
        data = h(payload)
        return {"ok": True, "data": data}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def assert_ok(r: dict, msg: str = "") -> dict:
    if not r.get("ok"):
        raise AssertionError(f"{msg} failed: {r.get('error')}")
    return r["data"]


def http_post(url: str, data: dict | str, content_type: str = "application/x-www-form-urlencoded") -> tuple[int, str]:
    if isinstance(data, dict):
        body = urllib.parse.urlencode(data).encode("utf-8")
    else:
        body = data.encode("utf-8") if isinstance(data, str) else data
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": content_type,
                 "Content-Length": str(len(body))},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")


def http_get(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")


def main():
    # 必须 mock 模式：测试环境绝对不能真扣钱
    pay_mod.USE_MOCK = True
    assert pay_mod.USE_MOCK, "必须在 MOCK 模式运行此测试，防止真实扣款"
    LOCAL_URL = f"http://{pay_mod.LOCAL_NOTIFY_HOST}:{pay_mod.LOCAL_NOTIFY_PORT}"

    bridge = BridgeServer()

    MC = get_machine_code()
    print(f"[1/8] 机器码 = {MC}")

    # ====== 1. get_machine_code ======
    r = assert_ok(_call(bridge, "get_machine_code", {}))
    assert r["machine_code"] == MC, f"机器码不匹配: {r}"
    print("  [OK] get_machine_code")

    # ====== 2. pay_create ======
    r = assert_ok(_call(bridge, "pay_create", {}))
    assert r.get("trade_order_id"), "缺少 trade_order_id"
    assert r.get("qr_url"), "缺少二维码"
    assert r["amount_yuan"] == 299.0, f"金额错误: {r['amount_yuan']}"
    order_id = r["trade_order_id"]
    mode = r.get("mode")
    assert mode == "mock", mode
    order_snap = activation_orders_dao.get(order_id)
    assert order_snap is not None, "订单未入库"
    assert order_snap["status"] == "created", f"订单状态错误: {order_snap['status']}"
    assert order_snap["machine_code"] == MC
    assert order_snap["amount_cents"] == 29900
    print(f"  [OK] pay_create → 订单 {order_id}, 已入库 status=created")

    # HTTP 回调监听健康检查
    time.sleep(0.3)
    code, body = http_get(f"{LOCAL_URL}/ping")
    assert code == 200 and body == "pong", f"/ping 不通: {code} {body}"
    print("  [OK] 本地 HTTP 回调服务 /ping = pong")

    # ====== 3. pay_poll（立即，应当未支付） ======
    r = assert_ok(_call(bridge, "pay_poll", {"trade_order_id": order_id}))
    assert r["paid"] is False, f"未到 30 秒不应 paid：{r}"
    assert r["activated"] is False
    print("  [OK] pay_poll(立即) → paid=False，符合预期")

    # ====== 4. admin_gen_license（错误密钥 → 抛错，正确 → 返回合法码） ======
    r_bad = _call(bridge, "admin_gen_license", {"admin_seed": "wrong", "machine_code": MC})
    assert r_bad["ok"] is False and "管理员密钥错误" in r_bad["error"], r_bad
    print("  [OK] admin_gen_license(wrong seed) → 拒绝")

    r = assert_ok(_call(bridge, "admin_gen_license",
                        {"admin_seed": "avatar-admin-2025", "machine_code": MC}))
    admin_lic = r["license_key"]
    assert admin_lic.startswith("AVTR-") and len(admin_lic) >= 18, admin_lic
    print(f"  [OK] admin_gen_license → 合法激活码 {admin_lic[:14]}****")

    # ====== 5. activate_with_license（Tab2 人工路径） ======
    # 先用个错的激活码 → dao.activate 抛 ValueError，桥包装成 ok=False + error
    r_bad = _call(bridge, "activate_with_license", {"license_key": "AVTR-0000-0000-0000"})
    assert r_bad["ok"] is False and "激活码无效" in r_bad.get("error", ""), r_bad
    print(f"  [OK] activate_with_license(坏码) → 正确拒绝: {r_bad['error']}")

    # 正确的管理员生成激活码 → 应当成功
    r = assert_ok(_call(bridge, "activate_with_license", {"license_key": admin_lic}))
    assert r.get("activated"), f"激活失败: {r}"
    status = activation_dao.get_status()
    assert bool(status.get("activated")) is True, f"activation_dao 状态未同步：{status}"
    assert status.get("edition") == "正式版", status
    print(f"  [OK] activate_with_license → 激活成功，edition={status['edition']}")

    # 重置激活态，方便测支付自动激活（别影响生产，测试库无所谓）
    from storage.db import get_conn, transaction
    with transaction():
        get_conn().execute("DELETE FROM activation WHERE 1=1")
    assert activation_dao.get_status()["activated"] is False, "重置激活失败"
    print("  [info] 已重置激活状态，继续测试 支付→自动激活 链路")

    # ====== 6. pay_poll（30s 后 mock 到点） → paid=True + activated=True ======
    ts_part = int(order_id[3:13])  # AVT{10_ts}...
    sleep_s = max(0, (ts_part + 31) - int(time.time())) + 1
    print(f"  [info] 等待 mock 到点（+{sleep_s}s 模拟支付成功）...")
    time.sleep(sleep_s)

    r = assert_ok(_call(bridge, "pay_poll", {"trade_order_id": order_id}))
    assert r["paid"] is True, f"poll 未到 paid: {r}"
    assert r["activated"] is True, f"poll 未自动激活: {r}"
    assert r["trade_no"], "缺少 trade_no"
    order_snap = activation_orders_dao.get(order_id)
    assert order_snap["status"] == "paid", f"订单未流转 paid：{order_snap['status']}"
    assert bool(order_snap.get("license_key")), "订单表未写入激活码"
    status = activation_dao.get_status()
    assert status["activated"] and status["edition"] == "正式版"
    print("  [OK] pay_poll(到点) → paid + 自动激活成功, activation_orders.status=paid")

    # 再次 poll：验证幂等（不重复激活副作用）
    r2 = assert_ok(_call(bridge, "pay_poll", {"trade_order_id": order_id}))
    assert r2["paid"] and r2.get("activated")  # 依然 True，但不应报错
    print("  [OK] pay_poll 二次调用：幂等无异常")

    # ====== 7. 模拟 HTTP 回调（另一张新订单） → 走 _process_notify_payload 链路 ======
    r = assert_ok(_call(bridge, "pay_create", {}))
    oid2 = r["trade_order_id"]
    mc2 = r["machine_code"]
    print(f"  [info] 第二张订单 {oid2}，测试 HTTP 回调路径")

    # 模拟虎皮椒 POST：mock_sign_ok=1 + paid=1
    cb_body = urllib.parse.urlencode({
        "mock_sign_ok": "1",
        "paid": "1",
        "out_trade_no": oid2,
        "transaction_id": "XUNHU-CB-20250101-00002",
        "attach": mc2,
    })
    code, body = http_post(
        f"{LOCAL_URL}{pay_mod.LOCAL_NOTIFY_PATH}",
        cb_body,
        "application/x-www-form-urlencoded; charset=utf-8",
    )
    assert code == 200, f"回调 HTTP 码错误: {code} {body}"
    assert body.strip() == "success", f"回调响应非 success: {body!r}"
    time.sleep(0.2)

    # 订单应当已 paid，本机若 mc 匹配（同一个 MC）→ 应当还是 activated（之前已激活，幂等）
    order2 = activation_orders_dao.get(oid2)
    assert order2 is not None, "回调没更新订单"
    assert order2["status"] == "paid", f"回调未把订单置 paid：{order2['status']}"
    assert int(order2.get("notify_attempts") or 0) >= 1
    assert int(order2.get("notify_verified") or 0) == 1
    print("  [OK] HTTP 回调 → order2.status=paid，notify_attempts/verified 留痕正确")

    # ====== 8. 回调验签不通过 → 不激活、正确返回 "fail" ======
    # 第三张订单，模拟坏回调（无 mock_sign_ok）
    r = assert_ok(_call(bridge, "pay_create", {}))
    oid3 = r["trade_order_id"]
    bad_body = urllib.parse.urlencode({
        "paid": "1",
        "out_trade_no": oid3,
        "attach": mc2,
    })
    code, body = http_post(f"{LOCAL_URL}{pay_mod.LOCAL_NOTIFY_PATH}", bad_body)
    assert code == 200
    assert body.strip() == "fail", f"坏回调响应应为 fail：{body!r}"
    order3 = activation_orders_dao.get(oid3)
    # 回调留痕有，但订单仍为 created（没置 paid）
    assert int(order3.get("notify_attempts") or 0) >= 1
    assert int(order3.get("notify_verified") or 0) == 0
    assert order3["status"] == "created", f"坏回调不应置 paid：{order3['status']}"
    print("  [OK] 坏回调（签名不过） → status=created，返回 'fail'，符合预期")

    # ====== 清理 ======
    try:
        if TEST_DB.exists():
            TEST_DB.unlink()
    except Exception:
        pass

    print("\n====== 所有 8 个 E2E 断言全部通过 ======")
    print("  · get_machine_code")
    print("  · pay_create (入库 + HTTP 服务拉起)")
    print("  · pay_poll (立即=未支付 / 30s后=自动激活)")
    print("  · admin_gen_license (密钥控制 + 合法码格式)")
    print("  · activate_with_license (Tab2 人工兜底)")
    print("  · HTTP /pay/xunhupay/notify (真回调 → paid → 幂等激活)")
    print("  · HTTP 坏回调 (验签失败 → 不激活 / 返回 fail)")
    print("  · 测试 DB 已清理，不影响生产数据")


if __name__ == "__main__":
    main()
