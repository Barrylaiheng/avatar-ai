"""激活码签名 + license.dat 离线持久化。

设计原则：
- 激活码 = 对机器码做 HMAC-SHA256 签名 → 格式化为 XXXX-XXXX-XXXX-XXXX
- 校验时重新签名比对，防止伪造激活码
- license.dat 写到 %APPDATA%\\SCAI\\license.dat，机器码 + 激活码 + 时间戳
- 离线校验：每次启动读 license.dat，比对签名 + 当前机器码，匹配则视为已激活
- 签名密钥内置于二进制（PyInstaller 打包后嵌入），不是绝对安全但足以防小白破解
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from pathlib import Path

from .db import get_app_dir
from .machine import get_machine_code

# 签名密钥（嵌入式，PyInstaller 打包后会嵌入 exe）
# 注意：这不是绝对安全的方案，但足以防止小白破解和随意盗版。
# 商业级保护需另加壳/混淆/反调试，超出 MVP 范围。
_LICENSE_SECRET = b"avatar-ai-mvp-license-secret-v1-2026"

LICENSE_FILENAME = "license.dat"


def _license_path() -> Path:
    return get_app_dir() / LICENSE_FILENAME


def _format_code(raw_hex: str) -> str:
    """将 16 字符 hex 格式化为 AVTR-XXXX-XXXX-XXXX（项目记忆约定，带品牌前缀防倒卖混淆）。"""
    raw = raw_hex[:12].upper()  # 12 hex → 3 段 4 位，加上前缀共 4 段
    return f"AVTR-{raw[0:4]}-{raw[4:8]}-{raw[8:12]}"


def generate_license_key(machine_code: str) -> str:
    """为指定机器码生成激活码。

    激活码 = HMAC-SHA256(machine_code) 的前 12 字符 hex，格式化为 AVTR-XXXX-XXXX-XXXX。
    """
    msg = (machine_code or "").encode("utf-8")
    digest = hmac.new(_LICENSE_SECRET, msg, hashlib.sha256).hexdigest()
    return _format_code(digest)


def verify_license_key(license_key: str, machine_code: str) -> bool:
    """校验激活码是否匹配指定机器码。兼容去掉 AVTR- 前缀的裸码，统一大写对比。"""
    if not license_key or not machine_code:
        return False
    expected = generate_license_key(machine_code)
    a = str(license_key).upper().replace(" ", "")
    b = str(expected).upper()
    # 允许用户去掉 AVTR- 前缀再粘贴
    if a.startswith("AVTR-") is False and b.startswith("AVTR-"):
        a = "AVTR-" + a
    # 用 hmac.compare_digest 防止时序攻击
    return hmac.compare_digest(a, b)


def write_license_file(machine_code: str, license_key: str) -> Path:
    """写 license.dat（机器码 + 激活码 + 时间戳）。

    文件格式：JSON（人类可读，便于排错）。
    内容字段：
      - machine_code: 绑定的机器码
      - license_key:  对应的激活码
      - issued_at:    颁发时间戳（秒）
      - schema:       文件版本号
    """
    path = _license_path()
    payload = {
        "schema": "v1",
        "machine_code": machine_code,
        "license_key": license_key,
        "issued_at": int(time.time()),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_license_file() -> dict | None:
    """读 license.dat。文件不存在或损坏返回 None。"""
    path = _license_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def verify_license_file() -> bool:
    """离线校验 license.dat 是否有效（签名匹配 + 机器码匹配当前本机）。

    返回 True 表示本机已激活且 license.dat 未被篡改。
    """
    data = read_license_file()
    if not data:
        return False
    machine_code = data.get("machine_code")
    license_key = data.get("license_key")
    if not machine_code or not license_key:
        return False
    # 当前机器码必须与 license.dat 中的一致（防止文件被拷贝到其他机器）
    current_machine = get_machine_code()
    if current_machine != machine_code:
        return False
    return verify_license_key(license_key, machine_code)


def delete_license_file() -> bool:
    """删除 license.dat（用于撤销激活）。"""
    path = _license_path()
    if path.exists():
        try:
            path.unlink()
            return True
        except Exception:
            return False
    return False


if __name__ == "__main__":
    # 命令行自测：生成 + 校验 + 写文件 + 读文件 + 离线校验
    mc = get_machine_code()
    lk = generate_license_key(mc)
    print(f"机器码: {mc}")
    print(f"激活码: {lk}")
    print(f"校验(正确): {verify_license_key(lk, mc)}")
    print(f"校验(错误机器码): {verify_license_key(lk, '0000-0000-0000-0000')}")
    print(f"校验(假激活码): {verify_license_key('AAAA-BBBB-CCCC-DDDD', mc)}")
    p = write_license_file(mc, lk)
    print(f"license.dat 写入: {p}")
    print(f"license.dat 读取: {read_license_file()}")
    print(f"离线校验: {verify_license_file()}")
