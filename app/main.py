"""阿维达AI · 主程序入口

PyQt6 + QWebEngineView 混合架构：
- HTML 负责界面展示（视觉基准）
- Python 负责业务逻辑（桌面能力）
- QWebChannel 实现 JS ↔ Python 双向通信
"""

import sys
import os
import json
import ctypes
from pathlib import Path


def _patch_subprocess_no_window():
    import subprocess as _sp

    _NOWIN = 0x08000000

    def _ensure(call):
        import functools

        @functools.wraps(call)
        def wrapper(*args, **kwargs):
            cf = kwargs.get("creationflags", 0)
            kwargs["creationflags"] = cf | _NOWIN

            if sys.platform == "win32":
                si = kwargs.get("startupinfo")
                if si is None:
                    try:
                        si = _sp.STARTUPINFO()
                        si.dwFlags |= _sp.STARTF_USESHOWWINDOW
                        kwargs["startupinfo"] = si
                    except Exception:
                        pass
            return call(*args, **kwargs)

        return wrapper

    _sp.run = _ensure(_sp.run)
    _sp.Popen = _ensure(_sp.Popen)


_patch_subprocess_no_window()

from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtGui import QDesktopServices, QGuiApplication, QIcon
from PyQt6.QtWidgets import QApplication, QMainWindow
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PyQt6.QtWebChannel import QWebChannel


def resource_path(relative_path: str) -> Path:
    """PyInstaller onefile/onedir 通用资源路径。
    
    打包后 PyInstaller 把文件解压到 sys._MEIPASS 临时目录；
    开发时用 __file__ 所在目录。
    """
    if hasattr(sys, "_MEIPASS"):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).parent
    return base / relative_path


# 确保能 import bridge
sys.path.insert(0, str(Path(__file__).parent))
from bridge import BridgeServer


class BridgePage(QWebEnginePage):
    """自定义 WebEngine Page，挂载 QWebChannel 桥接 + 捕获 JS 控制台日志。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        # 创建桥接服务与 WebChannel
        self.bridge = BridgeServer()
        self.channel = QWebChannel()
        self.channel.registerObject("bridge", self.bridge)
        self.setWebChannel(self.channel)

    def acceptNavigationRequest(self, url: QUrl, nav_type, is_main_frame: bool):
        """拦截主框架的 http/https 外链，交给系统浏览器打开；iframe/资源加载放行。"""
        if not is_main_frame:
            return True
        scheme = url.scheme()
        if scheme in ("http", "https") and url.isValid():
            QDesktopServices.openUrl(url)
            return False
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)

    def javaScriptConsoleMessage(self, level, message, line_number, source_id):
        """捕获 JS console.log，方便调试。"""
        try:
            level_val = int(level) if isinstance(level, int) else getattr(level, "value", 0)
        except Exception:
            level_val = 0
        # 所有级别都打印，方便定位首启报错位置
        prefix = {0: "LOG", 1: "WARN", 2: "ERROR"}.get(level_val, "LOG")
        src = source_id.split("/")[-1] if source_id else "?"
        print(f"[JS {prefix}] L{line_number} @ {src} : {message}", flush=True)


class AvatarApp(QMainWindow):
    """阿维达AI 主窗口"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("阿维达AI")

        # 按屏幕分辨率自适应窗口大小，并封顶到设计尺寸
        screen = QGuiApplication.primaryScreen().availableGeometry()
        target_w = min(int(screen.width() * 0.88), 1600)
        target_h = min(int(screen.height() * 0.88), 1000)
        self.resize(target_w, target_h)
        self.setMinimumSize(900, 600)

        # WebEngine 视图
        self.browser = QWebEngineView()
        self.setCentralWidget(self.browser)

        # 高 DPI 屏幕按比例放大页面，避免界面过小
        try:
            _dpi = QGuiApplication.primaryScreen().logicalDotsPerInch()
            _zoom = min(max(_dpi / 96.0, 0.8), 1.5)
            self.browser.setZoomFactor(_zoom)
            print(f"[App] 屏幕 DPI={_dpi:.0f}, zoomFactor={_zoom:.2f}", flush=True)
        except Exception as _e:
            print(f"[App] zoomFactor 设置失败: {_e}", flush=True)

        # 禁用 HTTP 缓存，确保每次加载最新资源
        profile = self.browser.page().profile()
        profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.NoCache)

        # 自定义 Page（带 QWebChannel 桥接）
        self.page = BridgePage(self.browser)
        self.browser.setPage(self.page)
        # 设置主窗口为 QFileDialog / 弹窗的 parent
        self.page.bridge.set_parent_window(self)

        # 加载 HTML（附加时间戳 query，避开缓存）
        import time as _time
        html_path = resource_path("web/index.html")
        url = QUrl.fromLocalFile(str(html_path))
        url.setQuery(f"t={int(_time.time())}")
        self.browser.setUrl(url)

        # 加载完成后通知 JS 桥接就绪
        self.browser.loadFinished.connect(self._on_load_finished)

    def _on_load_finished(self, ok: bool):
        """HTML 加载完成后通知 JS 桥接已就绪。"""
        if ok:
            print("[App] HTML 加载完成，桥接就绪", flush=True)
            # 启动后台 WCF 线程（只探活，绝不主动打开微信）
            self.page.bridge.start_channel_modules()
            # 启动 MCP（如启用），异常不阻断主流程
            try:
                from mcp_manager import get_mcp_manager
                _mgr = get_mcp_manager()
                if _mgr.is_enabled():
                    _mgr.get_or_generate_token()
                    self.page.bridge._ensure_mcp_thread_running()
                    print("[App] MCP 已启用，后台启动完成", flush=True)
                else:
                    print("[App] MCP 未启用，跳过", flush=True)
            except Exception as _e:
                print(f"[App] MCP 启动异常（不阻断主流程）: {_e}", flush=True)
            # 通过 bridge.push 信号主动通知 JS，携带首启状态/激活信息等
            self.page.bridge.send_to_js("ready", self.page.bridge.bootstrap_payload())
        else:
            print("[App] HTML 加载失败", flush=True)


def main():
    from logger import setup_file_logging
    setup_file_logging()

    # ===== OpenGL 后端：强制软件渲染（Mesa llvmpipe），根除虚拟机/无显卡环境下 GLES3 fallback =====
    os.environ.setdefault("QT_OPENGL", "software")
    os.environ.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")

    # ===== WebEngine Chromium 启动开关 =====
    #   --disable-gpu                    规避无显卡环境时 Chromium GPU 进程崩溃
    #   --disable-gpu-compositing        强制 CPU 合成，减少 context 重建延迟
    #   --in-process-gpu                 GPU 进程不 fork（首启快 100~300ms）
    #   --no-sandbox                      Windows 桌面 exe 无需沙箱
    #   --enable-features=NetworkServiceInProcess  网络进程内聚，进一步提速
    #   --remote-debugging-port=9222     Chrome DevTools 远程调试（验收UI用：
    #                                      Chrome 打开 http://localhost:9222）
    os.environ.setdefault(
        "QTWEBENGINE_CHROMIUM_FLAGS",
        "--disable-gpu --disable-gpu-compositing --in-process-gpu"
        " --no-sandbox --enable-features=NetworkServiceInProcess"
        " --remote-debugging-port=9222",
    )

    # 设置 Windows 任务栏应用标识，避免任务栏图标合并异常
    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AvatarAI.Prod.1.0")

    app = QApplication(sys.argv)
    app.setApplicationName("阿维达AI")
    app.setApplicationDisplayName("阿维达AI")

    icon_path = resource_path("avatar_icon.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    try:
        from health import health_check
        ok, issues = health_check(app)
        if not ok:
            print(f"[health_check] {len(issues)} 个问题", file=sys.stderr)
    except Exception as hc_err:
        print(f"[health_check] 自检模块异常: {hc_err}", file=sys.stderr)

    window = AvatarApp()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
