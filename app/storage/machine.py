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


def _run_powershell(cmd: str, timeout: float = 20.0) -> str:
    """执行 PowerShell 命令，返回 stdout（去空白）。失败返回空串。

    用 CREATE_NO_WINDOW 阻止任何黑框弹出（PyInstaller打包后更关键）。

    超时默认 20s（原为 5s）：onefile exe 冷启动时首次拉起 PowerShell +
    CIM 服务暖机常需 1.5s 以上，极端情况超过 5s；超时会导致硬件指纹拉取失败、
    降级成 MAC+主机名的弱指纹 → 机器码与用户激活时不一致 → 授权被降级。
    """
    try:
        # 创建子进程，无窗口，避免弹出黑框
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        creationflags = 134217728  # CREATE_NO_WINDOW
        result = subprocess.run(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", cmd],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
            startupinfo=startupinfo, creationflags=creationflags,
        )
        return (result.stdout or "").strip()
    except Exception:
        return ""


def _fetch_hardware_fingerprint() -> str:
    """收集硬件指纹原始字符串（拼接多个来源）。

    一次 PowerShell 调用拉 3 个硬件字段，用 | 分隔返回。
    """
    parts: list[str] = []

    # 来源：主板 UUID / CPU ProcessorId / BIOS 序列号（一次拉取）
    output = _run_powershell(
        '$u = (Get-CimInstance Win32_ComputerSystemProduct).UUID; $c = (Get-CimInstance Win32_Processor).ProcessorId; $b = (Get-CimInstance Win32_BIOS).SerialNumber; Write-Output "$u|$c|$b"'
    )

    # 解析：| 分隔
    fields = output.split("|") if output else []
    if len(fields) >= 1:
        uuid_val = fields[0].strip()
        if uuid_val and uuid_val.upper() != "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF":
            parts.append("uuid:" + uuid_val)
    if len(fields) >= 2 and fields[1].strip():
        parts.append("cpu:" + fields[1].strip())
    if len(fields) >= 3 and fields[2].strip():
        parts.append("bios:" + fields[2].strip())

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
