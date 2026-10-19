"""DPAPI 机器绑定加密模块（Windows 专用）。

用 Windows DPAPI 保护 LLM API Key / 激活码等敏感字段：
- 仅当前用户可解密
- 密文绑定到本机 TPM + 用户凭证（按项目约束为机器绑定加密）
- 加密格式：`v1:<base64_ciphertext>`，便于未来版本升级
"""

import os
import base64
import ctypes
import ctypes.wintypes


# ====== DPAPI 原生声明 ======
_CryptProtectData = ctypes.windll.crypt32.CryptProtectData
_CryptUnprotectData = ctypes.windll.crypt32.CryptUnprotectData
_LocalFree = ctypes.windll.kernel32.LocalFree


class _CRYPTOAPI_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


def _dpapi_encrypt(plaintext: bytes, description: str = "") -> bytes:
    """调用 CryptProtectData 加密二进制数据（机器/用户绑定）。"""
    blob_in = _CRYPTOAPI_BLOB()
    blob_out = _CRYPTOAPI_BLOB()

    blob_in.cbData = len(plaintext)
    blob_in.pbData = ctypes.cast((ctypes.c_byte * len(plaintext))(*plaintext), ctypes.POINTER(ctypes.c_byte))

    desc = ctypes.c_wchar_p(description or "SCAI Secret")

    ok = _CryptProtectData(
        ctypes.byref(blob_in),
        desc,
        None,          # OptionalEntropy：无
        None,          # Reserved
        None,          # PromptStruct：无提示
        0x01,          # CRYPTPROTECT_UI_FORBIDDEN（禁止UI）
        ctypes.byref(blob_out),
    )
    if not ok:
        err = ctypes.GetLastError()
        raise RuntimeError(f"DPAPI CryptProtectData 失败，WinError={err}")

    # 有符号 c_byte → 无符号字节串
    pb = ctypes.cast(blob_out.pbData, ctypes.POINTER(ctypes.c_ubyte))
    cipher = bytes(pb[: blob_out.cbData])
    _LocalFree(blob_out.pbData)
    return cipher


def _dpapi_decrypt(ciphertext: bytes) -> bytes:
    """调用 CryptUnprotectData 解密二进制数据。"""
    blob_in = _CRYPTOAPI_BLOB()
    blob_out = _CRYPTOAPI_BLOB()

    blob_in.cbData = len(ciphertext)
    blob_in.pbData = ctypes.cast((ctypes.c_byte * len(ciphertext))(*ciphertext), ctypes.POINTER(ctypes.c_byte))

    desc = ctypes.c_wchar_p()

    ok = _CryptUnprotectData(
        ctypes.byref(blob_in),
        ctypes.byref(desc),
        None,          # OptionalEntropy：无
        None,          # Reserved
        None,          # PromptStruct：无提示
        0x01,          # CRYPTPROTECT_UI_FORBIDDEN
        ctypes.byref(blob_out),
    )
    if not ok:
        err = ctypes.GetLastError()
        raise RuntimeError(f"DPAPI CryptUnprotectData 失败，WinError={err}。密文可能绑定到了其他机器/用户。")

    pb = ctypes.cast(blob_out.pbData, ctypes.POINTER(ctypes.c_ubyte))
    plain = bytes(pb[: blob_out.cbData])
    _LocalFree(blob_out.pbData)
    return plain


# ====== 对外接口 ======
_VERSION_PREFIX = "v1:"


def encrypt_secret(plaintext: str) -> str:
    """加密字符串，返回可存储的 ASCII 字符串（v1:<base64>）。"""
    if plaintext is None:
        return ""
    plain_bytes = plaintext.encode("utf-8")
    cipher_bytes = _dpapi_encrypt(plain_bytes, description="SCAI Secret v1")
    return _VERSION_PREFIX + base64.b64encode(cipher_bytes).decode("ascii")


def decrypt_secret(ciphertext: str) -> str:
    """解密 encrypt_secret 的输出。若不是本格式则原样返回（兼容旧数据）。"""
    if not ciphertext or not isinstance(ciphertext, str):
        return ciphertext
    if not ciphertext.startswith(_VERSION_PREFIX):
        # 非 v1 格式，按明文直接返回（向后兼容）
        return ciphertext
    try:
        raw = base64.b64decode(ciphertext[len(_VERSION_PREFIX):])
        plain_bytes = _dpapi_decrypt(raw)
        return plain_bytes.decode("utf-8")
    except Exception as e:
        raise RuntimeError(f"解密失败：{e}")


def _self_test() -> bool:
    """模块自测（开发期用）。"""
    sample = "sk-test-1234567890"
    enc = encrypt_secret(sample)
    assert enc.startswith(_VERSION_PREFIX), "格式不对"
    dec = decrypt_secret(enc)
    assert dec == sample, f"解密前后不一致：{dec} vs {sample}"
    # 兼容明文
    assert decrypt_secret(sample) == sample
    return True


if __name__ == "__main__":
    _self_test()
    print("DPAPI 自测通过")
