"""阿维达AI · 主程序入口

PyQt6 + QWebEngineView 混合架构：
- HTML 负责界面展示（视觉基准）
- Python 负责业务逻辑（桌面能力）
- QWebChannel 实现 JS ↔ Python 双向通信
"""

import sys
import os
import json
from pathlib import Path

from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QApplication, QMainWindow
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEnginePage
from PyQt6.QtWebChannel import QWebChannel

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

    def createWindow(self, _type):
        """阻止新窗口打开，直接复用当前 page。"""
        return self

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

    WIDTH = 1280
    HEIGHT = 820

    def __init__(self):
        super().__init__()
        self.setWindowTitle("阿维达AI")
        self.resize(self.WIDTH, self.HEIGHT)
        self.setMinimumSize(960, 640)

        # WebEngine 视图
        self.browser = QWebEngineView()
        self.setCentralWidget(self.browser)

        # 自定义 Page（带 QWebChannel 桥接）
        self.page = BridgePage(self.browser)
        self.browser.setPage(self.page)
        # 设置主窗口为 QFileDialog / 弹窗的 parent
        self.page.bridge.set_parent_window(self)

        # 加载 HTML
        html_path = Path(__file__).parent / "web" / "index.html"
        self.browser.setUrl(QUrl.fromLocalFile(str(html_path)))

        # 加载完成后通知 JS 桥接就绪
        self.browser.loadFinished.connect(self._on_load_finished)

    def _on_load_finished(self, ok: bool):
        """HTML 加载完成后通知 JS 桥接已就绪。"""
        if ok:
            print("[App] HTML 加载完成，桥接就绪", flush=True)
            # 启动后台 WCF 线程（只探活，绝不主动打开微信）
            self.page.bridge.start_channel_modules()
            # 通过 bridge.push 信号主动通知 JS，携带首启状态/激活信息等
            self.page.bridge.send_to_js("ready", self.page.bridge.bootstrap_payload())
        else:
            print("[App] HTML 加载失败", flush=True)


def main():
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

    app = QApplication(sys.argv)
    app.setApplicationName("阿维达AI")
    app.setApplicationDisplayName("阿维达AI")

    window = AvatarApp()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
