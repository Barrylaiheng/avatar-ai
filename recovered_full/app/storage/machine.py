"""机器码生成 — 基于 Windows 硬件指纹。

设计原则：
- 优先用 PowerShell Get-CimInstance 拉取主板 UUID / CPU ID / BIOS 序列号
- 上述任一拉取失败时降级到 uuid.getnode() + platform.processor() + socket.gethostname()
- 用 sha256 摘要硬件指纹，取前 16 字节 hex，按 4-4-4-4 分组，全大写
- 同一台机器多次调用结果稳定（输入指纹一致即稳定）
- 不依赖第三方包，纯标准库 + Windows 系统命令
"""
from __future__ import annotations

import hashlib
import platform
import socket
import subprocess
import uuid

# 模块级缓存：机器码在同一台机器上永远不变，第一次算完直接复用
_CACHED_CODE: str | None = None


def _run_powershell(cmd: str, timeout: float = 3.0) -> str:
    """执行 PowerShell 命令，返回 stdout（去空白）。失败返回空串。"""
    try:
        # 创建子进程，无窗口，避免弹出黑框
        startupinfo = None
        try:
            import subprocess as _sp
            startupinfo = _sp.STARTUPINFO()
            startupinfo.dwFlags |= _sp.STARTF_USESHOWWINDOW
        except Exception:
            pass
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            capture_output=True, text=True, timeout=timeout,
            startupinfo=startupinfo,
        )
        out = (result.stdout or "").strip()
        return out
    except Exception:
        return ""


def _fetch_hardware_fingerprint() -> str:
    """收集硬件指纹原始字符串（拼接多个来源）。

    每个来源单独 try，任意一个失败不影响其他。
    """
    parts: list[str] = []

    # 来源 1：主板产品 UUID（Get-CimInstance 替代已废弃的 wmic）
    uuid_val = _run_powershell(
        "(Get-CimInstance Win32_ComputerSystemProduct).UUID"
    )
    if uuid_val and uuid_val.upper() != "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF":
        parts.append("uuid:" + uuid_val)

    # 来源 2：CPU ProcessorId
    cpu_id = _run_powershell("(Get-CimInstance Win32_Processor).ProcessorId")
    if cpu_id:
        parts.append("cpu:" + cpu_id)

    # 来源 3：BIOS 序列号
    bios_sn = _run_powershell("(Get-CimInstance Win32_BIOS).SerialNumber")
    if bios_sn:
        parts.append("bios:" + bios_sn)

    # 降级来源：MAC 地址 + CPU 型号字符串 + 主机名
    if not parts:
        parts.append("mac:" + str(uuid.getnode()))
        parts.append("cpu_name:" + platform.processor())
        parts.append("host:" + socket.gethostname())

    # 拼接并排序，保证顺序稳定
    parts.sort()
    return "|".join(parts)


def get_machine_code() -> str:
    """生成当前机器的机器码（格式：A1B2-C3D4-E5F6-G7H8）。

    - 同一台机器稳定输出
    - 不同机器输出不同（依赖硬件指纹差异）
    - 输出格式：4 段 4 字符 hex，全大写
    - 首次调用约 1.7s（调 3 次 PowerShell 读硬件），后续调用 <1ms（直接返回缓存）
    """
    global _CACHED_CODE
    if _CACHED_CODE is not None:
        return _CACHED_CODE
    fingerprint = _fetch_hardware_fingerprint()
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()
    # 取前 16 个 hex 字符（64 bit），分 4 段
    raw = digest[:16].upper()
    _CACHED_CODE = f"{raw[0:4]}-{raw[4:8]}-{raw[8:12]}-{raw[12:16]}"
    return _CACHED_CODE


if __name__ == "__main__":
    # 命令行自测：打印当前机器码
    print("机器码:", get_machine_code())
