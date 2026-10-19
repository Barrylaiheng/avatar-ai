"""激活码生成 / 校验命令行工具。

用法：
    # 不传参数：自动取本机机器码并生成激活码
    py -3 -m storage.gen_license

    # 指定机器码生成激活码（客服/开发补发激活码场景）
    py -3 -m storage.gen_license 0B50-995F-DE3A-0608

    # 校验模式：检查某机器码 + 激活码组合是否合法
    py -3 -m storage.gen_license --verify 0B50-995F-DE3A-0608 280B-15BD-334D-176A

    # JSON 输出（便于其他程序调用）
    py -3 -m storage.gen_license --json
    py -3 -m storage.gen_license 0B50-995F-DE3A-0608 --json

说明：
- 激活码 = HMAC-SHA256(机器码) 的前 16 hex 字符，格式 XXXX-XXXX-XXXX-XXXX
- 激活码与机器码一一对应，只能在本机使用
- 业务流程：用户告知机器码 → 客服用此工具生成激活码 → 用户在激活弹窗手动输入
"""
from __future__ import annotations

import argparse
import json
import sys

from .machine import get_machine_code
from .license import generate_license_key, verify_license_key


def _print_human(machine_code: str, license_key: str, note: str = "") -> int:
    """友好文本输出，返回 exit code。"""
    print("=" * 48)
    print("  阿维达AI 激活码生成工具")
    print("=" * 48)
    print(f"  机器码 : {machine_code}")
    print(f"  激活码 : {license_key}")
    if note:
        print("-" * 48)
        print(f"  {note}")
    print("=" * 48)
    print("  使用方式：在「设置 → 激活」弹窗中点击「手动输入激活码」，")
    print("            填入上面的激活码即可完成激活。")
    print("=" * 48)
    return 0


def _print_json(machine_code: str, license_key: str, ok: bool = True,
                error: str = "") -> int:
    """JSON 输出，便于其他程序调用。"""
    payload = {
        "ok": ok,
        "machine_code": machine_code,
        "license_key": license_key,
    }
    if error:
        payload["error"] = error
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gen_license",
        description="阿维达AI 激活码生成 / 校验工具",
    )
    parser.add_argument(
        "machine_code",
        nargs="?",
        default=None,
        help="机器码（XXXX-XXXX-XXXX-XXXX 格式）。不传则自动取本机机器码。",
    )
    parser.add_argument(
        "--verify",
        nargs=2,
        metavar=("MACHINE_CODE", "LICENSE_KEY"),
        help="校验模式：检查机器码 + 激活码是否匹配。",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="JSON 输出（便于其他程序调用）。",
    )
    args = parser.parse_args(argv)

    # ----- 校验模式 -----
    if args.verify:
        mc, lk = args.verify
        ok = verify_license_key(lk, mc)
        if args.json:
            return _print_json(mc, lk.upper() if ok else "", ok=ok,
                               error="" if ok else "激活码与机器码不匹配")
        print("=" * 48)
        print("  激活码校验")
        print("=" * 48)
        print(f"  机器码 : {mc}")
        print(f"  激活码 : {lk}")
        print("-" * 48)
        if ok:
            print("  ✓ 校验通过：激活码合法，匹配该机器码")
            print("=" * 48)
            return 0
        else:
            print("  ✗ 校验失败：激活码与机器码不匹配")
            print("=" * 48)
            return 1

    # ----- 生成模式 -----
    try:
        machine_code = (args.machine_code or "").strip() or get_machine_code()
    except Exception as e:
        if args.json:
            return _print_json("", "", ok=False, error=f"机器码生成失败：{e}")
        print(f"错误：机器码生成失败 - {e}", file=sys.stderr)
        return 2

    # 简单格式校验
    if not machine_code or len(machine_code.replace("-", "")) != 16:
        if args.json:
            return _print_json(machine_code, "", ok=False,
                               error="机器码格式不正确（应为 XXXX-XXXX-XXXX-XXXX）")
        print(f"错误：机器码格式不正确 - {machine_code}", file=sys.stderr)
        return 2

    license_key = generate_license_key(machine_code)

    if args.json:
        return _print_json(machine_code, license_key)

    return _print_human(
        machine_code, license_key,
        note="本机机器码" if not args.machine_code else "指定机器码"
    )


if __name__ == "__main__":
    sys.exit(main())
