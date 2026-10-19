"""
Avatar AI MVP — 运行时健康自检 (L3)
====================================
在 QApplication 创建后、主窗口显示前执行。
如果发现必需模块缺失，立即弹框告诉用户具体是什么问题，不让用户莫名其妙炸。

触发时机：main.py L200 之后调用 health_check()
"""
import sys
import os
import traceback

REQUIRED_MODULES = [
    ("PyQt6", "主 UI 框架"),
    ("jwt", "云授权 JWT 验签"),
    ("qrcode", "支付二维码生成"),
    ("requests", "HTTP 请求"),
]

OPTIONAL_MODULES = [
    ("wcferry", "微信通道"),
    ("pynng", "wcferry 底层通信"),
]

REQUIRED_FILES = [
    ("web", "前端资源目录"),
]


def _import_safe(name):
    """尝试 import，返回 (ok, error_msg)"""
    try:
        __import__(name)
        return True, None
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def health_check(app=None):
    """
    执行自检。返回 (ok: bool, issues: list[str])。
    如果有问题，用 QMessageBox 弹框让用户看到。
    """
    issues = []

    # ── 必需模块 ──────────────────────────────
    for mod, desc in REQUIRED_MODULES:
        ok, err = _import_safe(mod)
        if ok:
            continue
        issues.append(f"❌ 模块缺失: {mod}\n   用途: {desc}\n   错误: {err}")

    # ── 可选模块（缺失只警告，不阻断）──────────
    for mod, desc in OPTIONAL_MODULES:
        ok, err = _import_safe(mod)
        if ok:
            continue
        print(f"[Health] 可选模块缺失: {mod} ({desc}) — 仅影响对应通道，不阻断启动", file=sys.stderr)

    # ── 必需文件 ──────────────────────────────
    try:
        from main import resource_path
    except ImportError:
        try:
            from bridge import resource_path
        except ImportError:
            resource_path = None

    if resource_path:
        for fpath, desc in REQUIRED_FILES:
            full = resource_path(fpath)
            exists = full.exists() if hasattr(full, "exists") else os.path.exists(str(full))
            if exists:
                continue
            issues.append(f"❌ 文件缺失: {fpath}\n   用途: {desc}")

    # ── 有错就弹框 ────────────────────────────
    if issues and app is not None:
        try:
            from PyQt6.QtWidgets import QMessageBox
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Icon.Critical)
            msg.setWindowTitle("阿维达 AI — 环境自检失败")
            msg.setText("程序启动时检测到以下问题：")
            msg.setDetailedText("\n\n".join(issues))
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg.exec()
        except Exception:
            print("!!! Avatar AI health check FAILED !!!", file=sys.stderr)
            for iss in issues:
                print(iss, file=sys.stderr)

    return len(issues) == 0, issues
