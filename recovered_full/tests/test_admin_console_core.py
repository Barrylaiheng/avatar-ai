r"""admin_console.py 核心层 E2E 测试（不跑 PyQt6 GUI，只测 create/revoke/重复拦截/CSV/备份/列表搜索）。

运行：venv\Scripts\python.exe tests\test_admin_console_core.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
sys.path.insert(0, str(APP))

# 隔离到临时目录：不要污染管理员真正的 HOME/AvatarAIAdmin
tmp = Path(tempfile.mkdtemp(prefix="avatar_admin_test_"))
os.environ["AVATAR_ADMIN_HOME"] = str(tmp)

import admin_console as AC  # noqa: E402  必须在 AVATAR_ADMIN_HOME 设好之后才能 import

from storage.machine import get_machine_code  # noqa: E402


def main():
    print(f"[tmp admin_home] {AC.get_admin_home()}")
    # 建表
    conn = AC.get_admin_conn()
    print(f"[ok] 建表/迁移完成，表 admin_licenses 存在")

    MC1 = get_machine_code()
    MC2 = "AA11-BB22-CC33-DD44"
    MC3 = "11AA-22BB-33CC-44DD"

    # ====== 1. create_license 正常生成 3 条 ======
    r1, p1 = AC.create_license(machine_code=MC1, user_tag="张三 (wx_zhangsan)",
                               source="private_transfer",
                               payment_ref="4200002301202601011234567890",
                               amount_cents=29900, notes="老朋友，免 50 元在微信退现金")
    assert p1.exists() and p1.suffix.lower() == ".lic", f".lic 未生成: {p1}"
    import json as _j
    lic1 = _j.loads(p1.read_text(encoding="utf-8"))
    assert lic1["schema"] == "v1" and lic1["machine_code"] == MC1.strip().upper()
    assert lic1["license_key"].startswith("AVTR-") and len(lic1["license_key"]) >= 18
    print(f"[ok] 1. create 成功: ID#{r1['id']} .lic={p1.name} key={r1['license_key'][:10]}***")

    r2, p2 = AC.create_license(machine_code=MC2, user_tag="李四", source="huqijiao_manual",
                               payment_ref="XH-20260831-0002", amount_cents=29900, notes="扫码到账没自动激活")
    r3, p3 = AC.create_license(machine_code=MC3, user_tag="合作媒体赠码", source="complimentary",
                               amount_cents=0, notes="KOL 合作，永久免费")

    # ====== 2. 同一机器码重复拦截 ======
    dup_err = None
    try:
        AC.create_license(machine_code=MC1, user_tag="假装另一个人同一台机器",
                          source="private_transfer", amount_cents=29900)
    except ValueError as e:
        dup_err = str(e)
    assert dup_err and "已在" in dup_err and "别重复收钱" in dup_err, f"重复拦截未命中: {dup_err!r}"
    print(f"[ok] 2. 重复机器码拦截命中: err_head={dup_err[:50]!r}")

    # ====== 3. 空机码/非法来源拦截 ======
    # 每条 = ((machine_code, source), 期望错误提示子串)
    cases = [
        (("", "private_transfer"), "机器码不能为空"),
        (("short", "private_transfer"), "机器码太短"),
        ((MC2, "not_a_source"), "来源非法"),
    ]
    for (mc, src), msg_expected in cases:
        try:
            AC.create_license(machine_code=mc, source=src,
                              amount_cents=29900, user_tag="异常测试")
        except ValueError as e:
            err = str(e)
        else:
            err = ""
        assert msg_expected in err, f"未拦截 mc={mc!r} src={src!r}: {err!r}（期望含 {msg_expected!r}）"
    print(f"[ok] 3. 边界校验：空机码/短码/非法来源 3 个拦截全部命中")

    # ====== 4. list_licenses 搜索 & 状态筛选 ======
    all_rows = AC.list_licenses()
    assert len(all_rows) == 3, f"list 行数不对: {len(all_rows)}"
    by_mc = {r["machine_code"]: r for r in all_rows}
    assert by_mc[MC1.strip().upper()]["user_tag"].startswith("张三")
    # 搜机器码后6位，应该只命中1条
    s = AC.list_licenses(keyword=MC2[-6:])
    assert len(s) == 1 and s[0]["machine_code"] == MC2, f"搜索机器码不准: {[r['machine_code'] for r in s]}"
    # 搜"合作"，应该命中 r3
    s = AC.list_licenses(keyword="合作")
    assert len(s) == 1 and s[0]["source"] == "complimentary"
    print(f"[ok] 4. 列表查询：全量 3 条 / 按机码精确搜 1 条 / 按备注模糊搜 1 条 全部正确")

    # ====== 5. stats 正确 ======
    st = AC.stats()
    # this_month 只看时间，我们刚写的肯定当月；total_active=3；total_rev_cents = 29900+29900+0
    assert st["total_active"] == 3
    assert st["total_rev_cents"] == 29900 + 29900, f"累计收入不对: {st['total_rev_cents']}"
    assert st["total_revoked"] == 0
    assert st["manual_count"] == 3  # huqijiao_manual + private_transfer + complimentary 都算人工
    print(f"[ok] 5. stats: 本月{st['this_month_count']}笔/收入¥{st['this_month_rev_cents']/100:.2f}  "
          f"累计有效{st['total_active']}  人工兜底占比{st['manual_count']}/{st['total_active']}")

    # ====== 6. revoke_license ======
    r = AC.revoke_license(r3["id"], reason="KOL 合作到期 2026-12-31")
    assert r["status"] == "revoked" and r["revoked_at"] > 0
    assert "KOL 合作到期" in (r["notes"] or "")
    # 再作废旧ID：拦截
    try:
        AC.revoke_license(r3["id"]); assert False, "不应走到这里"
    except ValueError as e:
        assert "已经是作废" in str(e)
    # 作废旧ID：DB id 不存在
    try:
        AC.revoke_license(999_999); assert False
    except ValueError as e:
        assert "不存在" in str(e)
    st2 = AC.stats()
    assert st2["total_active"] == 2 and st2["total_revoked"] == 1
    # 作废后再为同一 MC3 生成新的（场景：换电脑 或 原作废重发）—— 应允许（因为旧的已是 revoked）
    r3b, p3b = AC.create_license(machine_code=MC3, user_tag="合作媒体（二次补发）", source="replacement",
                                 amount_cents=0, notes="原赠码作废，新机器码重发（演示）")
    st3 = AC.stats()
    assert st3["total_active"] == 3 and st3["total_revoked"] == 1
    print(f"[ok] 6. revoke：状态流转正确 + 重作废旧记录拦截 + 不存在ID拦截 + 作废后能重新为同一MC生成（补码场景）。现有效 3，作废 1。")

    # ====== 7. export_csv ======
    out_csv = AC.export_csv()
    assert out_csv.exists() and out_csv.suffix.lower() == ".csv"
    text = out_csv.read_text(encoding="utf-8-sig", errors="replace")
    # utf-8-sig 首字节 BOM EF BB BF
    assert text.startswith("ID") or text.startswith("\ufeffID"), f"CSV 中文头不对: {text[:40]!r}"
    # 行数（含表头）= 4 条有效记录 + 1 表头；但第 6 步作废后又为同一 MC 生成了一条（replacement），实际记录数 = 5 条
    expected_records = 5
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert len(lines) == expected_records + 1, f"导出行数不对: {len(lines)}，期望 {expected_records + 1}（{expected_records} 条记录 + 表头）"
    # 张三这行要包含
    assert any("张三" in ln for ln in lines), "导出CSV 缺少张三行"
    print(f"[ok] 7. export_csv：{out_csv.name}（{len(text)}字节，{len(lines)}行，UTF-8-BOM），含张三记录")

    # ====== 8. 自动备份存在 ======
    backup_dir = AC.get_admin_home() / "backups"
    day = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
    today = backup_dir / f"{AC._DB_NAME}.{day}.bak"
    assert today.exists() and today.stat().st_size > 0, f"当日自动备份缺失: {today}"
    # 读得通（SQLite 可读 header）
    import sqlite3 as _s
    with _s.connect(str(today)) as c:
        n = c.execute("SELECT COUNT(*) FROM admin_licenses").fetchone()[0]
    assert n == 4, f"备份DB 记录数不一致: {n}"
    print(f"[ok] 8. 自动备份：{today.name}（{today.stat().st_size} 字节）可读，记录数={n}，与主库一致")

    # ====== 9. verify_license_file 在 MVP 端能直接验通过（端到端闭环） ======
    from storage.license import verify_license_file as _verify_lic
    # 注意 verify_license_file 会读 %APPDATA%\SCAI\license.dat（用户端那个真正的位置）
    # 测试不要污染生产，直接用 raw 读取生成的 .lic 模拟用户端导入后落盘的结果：
    from storage.license import verify_license_key as _verify_key
    for r, lic_path in [(r1, p1), (r2, p2), (r3b, p3b)]:
        data = _j.loads(Path(lic_path).read_text(encoding="utf-8"))
        assert _verify_key(data["license_key"], data["machine_code"]), f"lic 文件离线HMAC验失败: {r}"
    print(f"[ok] 9. 生成的 3 个 .lic 文件都通过 HMAC 离线验签，与 MVP 端 verify_license_key 实现完全一致 → 用户端导入即可激活的闭环已验证")

    print("\n========== admin_console 核心层 E2E：9/9 全部通过 ==========")
    print("  ① create_license: 正常3条 + .lic 输出")
    print("  ② 同机器码 active 重复拦截")
    print("  ③ 边界拦截：空机码/短码/非法来源 ×3")
    print("  ④ list_licenses：全量/按机码精确/按用户备注模糊 3 种搜索")
    print("  ⑤ stats：本月/累计收入、生效数、作废数、人工兜底占比")
    print("  ⑥ revoke：状态流转 + 双重废拦截 + 不存在ID + 作废后可重新为同一MC生成（补码）")
    print("  ⑦ export_csv：UTF-8 BOM + 行数正确 + Excel 直接开中文不乱码")
    print("  ⑧ 写操作后当日自动备份：文件存在 + 可读 SQLite + 记录数=主库一致")
    print("  ⑨ .lic 文件与 MVP 端 verify_license_key 算法对齐 → 用户导入闭环")
    print(f"\n测试数据存于（已隔离，对真实账本无影响）：\n  {tmp}")


if __name__ == "__main__":
    main()
