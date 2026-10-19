# WCF 直接注入改造 - 对齐文档

> **目的**：记录 Work 侧已完成的 WCF 改造，以及待 Code 项目推进的 UI 适配项。
> **背景**：WCF 连接模式从 HTTP RPC 改为直接注入（gRPC 直连 Wcferry SDK），Work 侧已完成核心适配，UI 层需 Code 项目继续完善。

---

## 〇、测试环境（2026-07-27 更新）

- **本机状态**：WCF + 低版本微信已在本机安装并测试可用
- **测试环境**：从旧电脑迁回本机（`c:\Users\Administrator\Desktop\WeChatAI_Project`）
- **后期工作范围**：测试、运营梳理、知识库建立都在本机本项目下进行
- **前期准备**：用户已在别的项目中做过部分前期梳理和准备

---

## 一、已完成（Work 侧，Code 侧可直接使用）

### 1.1 `wcf_adapter.py` — 核心适配层

**文件路径**：`src/aibridge/bridges/wcf_adapter.py`

**改动概述**：从 HTTP RPC 模式整体重写为直接注入模式。

| 改动项 | 说明 |
|--------|------|
| `__init__` | 保留 `wcf_ip`/`wcf_port` 参数（接口兼容），实际用于 `Wcf()` 构造函数；`api_key` 保留但不用于鉴权 |
| `_connect_wcf()` | 创建 `Wcf()` 实例直接调用，检测端口冲突，检查微信登录状态 |
| `_msg_receive_loop()` | 使用 `enable_receiving_msg()` + `get_msg(block=True)` 轮询接收消息 |
| 心跳线程 | 新增，定期检查连接状态 |
| 消息处理线程 | 新增，从队列取出消息并调用回调 |
| 端口冲突检测 | `_check_port_occupied()` 检测 10086 端口是否被占用 |
| 连接状态管理 | `_connection_status` 属性，值为 `connected`/`disconnected`/`error` |

**关键代码片段**：

```python
# 直连模式创建 Wcf 实例
def _connect_wcf(self) -> bool:
    try:
        # 检测端口冲突
        if self._check_port_occupied(self._wcf_port):
            logger.warning(f"端口 {self._wcf_port} 已被占用，可能微信未启动或 WCF 已运行")
            return False

        # 直接注入模式
        self._wcf = Wcf(host=self._wcf_ip, port=self._wcf_port, block=False)

        # 检查登录状态
        if not self._wcf.is_login():
            logger.error("微信未登录，请先扫码登录")
            return False

        # 启用消息接收
        self._wcf.enable_receiving_msg()
        self._connected = True
        return True
    except Exception as e:
        logger.error(f"WCF 连接失败: {e}")
        return False

# 消息轮询
def _msg_receive_loop(self):
    while self._running and self._connected:
        try:
            msg = self._wcf.get_msg(block=True, timeout=1)
            if msg:
                internal_msg = self._convert_wcf_message(msg)
                if internal_msg and self.message_callback:
                    self.message_callback(internal_msg)
        except Exception as e:
            logger.error(f"消息接收异常: {e}")
```

---

### 1.2 `app_engine.py` — 应用引擎接口适配

**文件路径**：`src/aibridge/app_engine.py`

**改动概述**：更新 WCF 相关方法，适配直接注入模式。

| 方法 | 改动 |
|------|------|
| `connect_wcf(ip, port, api_key)` | 创建 `WcfAdapter` 实例，调用 `_wcf_adapter.start()` |
| `test_wcf_connection(ip, port, api_key)` | 创建临时 `WcfAdapter` 实例，调用 `check_connection()` |
| `disconnect_wcf()` | 调用 `_wcf_adapter.stop()`，清理实例 |

**关键代码片段**：

```python
def connect_wcf(self, ip: str, port: int, api_key: str) -> bool:
    with self._lock:
        try:
            if self._wcf_adapter is not None:
                self._wcf_adapter.stop()

            self._wcf_adapter = WcfAdapter(
                message_callback=self._on_wcf_message,
                wcf_ip=ip,
                wcf_port=port,
                api_key=api_key,  # 接口保留，直连模式不用于鉴权
            )

            success = self._wcf_adapter.start()
            if success:
                logger.info(f"WCF 连接成功: {ip}:{port}")
            else:
                logger.error(f"WCF 连接失败: {ip}:{port}")
                self._wcf_adapter = None
            return success
        except Exception as e:
            logger.error(f"WCF 连接异常: {e}")
            self._wcf_adapter = None
            return False

def test_wcf_connection(self, ip: str, port: int, api_key: str) -> bool:
    try:
        test_adapter = WcfAdapter(wcf_ip=ip, wcf_port=port, api_key=api_key)
        success = test_adapter.check_connection()
        return success
    except Exception as e:
        logger.error(f"WCF 连接测试异常: {e}")
        return False
```

---

## 二、待 Code 项目推进（UI 层适配）

### 2.1 `settings_page.py` — 设置页 WCF 配置 UI

**文件路径**：`src/aibridge/ui/settings_page.py`

**当前问题**：

1. **测试连接为模拟实现**：`_test_wcf_connection()` 使用 `QTimer.singleShot` + `_simulate_wcf_test_result`，未调用真实 WCF
2. **端口 placeholder 错误**：当前为 `"8080"`，应改为 `"10086"`
3. **缺少连接/断开按钮**：当前只有"测试连接"，需补充"连接"/"断开"按钮
4. **缺少 app_engine 引用**：`SettingsPage` 未接收 `app_engine` 参数，无法调用 `test_wcf_connection`

**目标改动**：

| 改动项 | 当前代码 | 目标代码 |
|--------|----------|----------|
| 构造函数 | `def __init__(self, parent=None)` | `def __init__(self, app_engine=None, parent=None)` |
| 测试连接 | `QTimer.singleShot(1500, self._simulate_wcf_test_result)` | `success = self._app_engine.test_wcf_connection(ip, port, api_key)` |
| 端口 placeholder | `"8080"` | `"10086"` |
| API Key 字段 | 显示且可编辑 | 隐藏或禁用（直连模式不需要，但保留接口兼容） |
| 按钮 | 只有"测试连接" | 增加"连接"/"断开"按钮，调用 `app_engine.connect_wcf` |

**建议实现**：

```python
class SettingsPage(QWidget):
    def __init__(self, app_engine=None, parent=None):
        super().__init__(parent)
        self._app_engine = app_engine
        self._setup_ui()

    def _test_wcf_connection(self):
        if not self._app_engine:
            self._toast_warning("App Engine 未初始化")
            return

        ip = self._wcf_ip_input.text().strip() or "localhost"
        port = int(self._wcf_port_input.text().strip() or "10086")
        api_key = self._wcf_api_key_input.text().strip() or "***"

        self._test_btn.setEnabled(False)
        self._test_btn.setText("测试中...")

        # 异步测试
        from PyQt6.QtCore import QThread, pyqtSignal
        class TestThread(QThread):
            result = pyqtSignal(bool)
            def __init__(self, engine, ip, port, api_key):
                super().__init__()
                self._engine = engine
                self._ip = ip
                self._port = port
                self._api_key = api_key
            def run(self):
                success = self._engine.test_wcf_connection(self._ip, self._port, self._api_key)
                self.result.emit(success)

        self._test_thread = TestThread(self._app_engine, ip, port, api_key)
        self._test_thread.result.connect(self._on_test_result)
        self._test_thread.start()

    def _on_test_result(self, success: bool):
        self._test_btn.setEnabled(True)
        self._test_btn.setText("测试连接")
        if success:
            self._toast_success("WCF 连接成功")
        else:
            self._toast_error("WCF 连接失败，请检查微信和 WCF 服务")
```

---

### 2.2 `main_window.py` — 主窗口传递 app_engine

**文件路径**：`src/aibridge/ui/main_window.py`

**当前问题**：`_setup_settings_page()` 创建 `SettingsPage` 时未传递 `app_engine`。

**目标改动**：

| 方法 | 当前代码 | 目标代码 |
|------|----------|----------|
| `_setup_settings_page()` | `self._settings_page = SettingsPage()` | `self._settings_page = SettingsPage(app_engine=self._app_engine)` |

**建议实现**：

```python
def _setup_settings_page(self):
    """设置页"""
    self._settings_page = SettingsPage(app_engine=self._app_engine)
    return self._settings_page
```

---

### 2.3 本地验证 — 测试 WCF 连接 + 消息收发

**前置条件**：

1. 微信低版本（3.9.12.51）已安装并登录
2. WCF 服务已启动（`wcf.exe` 或相关脚本）
3. 端口 10086 已监听（可用 `netstat -ano | findstr 10086` 确认）

**验证步骤**：

1. 启动 AI Bridge（`dist/AIBridge/AIBridge.exe`）
2. 进入"设置"页或"线性向导"第 4 步
3. 点击"测试连接"，确认提示"WCF 连接成功"
4. 点击"连接"，确认状态变为"已连接"
5. 用另一个微信号向已登录的微信号发送消息
6. 观察 AI Bridge 日志，确认收到消息

**预期结果**：

- 连接成功后，日志显示 `WCF 连接成功: localhost:10086`
- 收到消息时，日志显示 `收到 WCF 消息: <发送者>: <内容>`

---

## 三、接口兼容性说明

| 参数 | HTTP RPC 模式 | 直接注入模式 | 备注 |
|------|--------------|-------------|------|
| `wcf_ip` | WCF HTTP 服务 IP | WCF gRPC 服务 IP（通常 localhost） | 兼容 |
| `wcf_port` | HTTP 端口（如 8080） | gRPC 端口（默认 10086） | 需 UI 提示用户 |
| `api_key` | Bearer Token 鉴权 | 不用于鉴权，保留接口兼容 | 可隐藏 UI |

---

## 四、文件清单

| 文件 | 改动状态 | 负责方 |
|------|---------|--------|
| `src/aibridge/bridges/wcf_adapter.py` | ✅ 已完成 | Work |
| `src/aibridge/app_engine.py` | ✅ 已完成 | Work |
| `src/aibridge/ui/settings_page.py` | ⏳ 待改造 | Code |
| `src/aibridge/ui/main_window.py` | ⏳ 待传递 app_engine | Code |
| 本地验证 | ⏳ 待测试 | Code |

---

## 五、后续推进建议

1. **优先级 P0**：`main_window.py` 传递 `app_engine`（1 行代码）
2. **优先级 P0**：`settings_page.py` 接收 `app_engine` 并调用真实测试连接
3. **优先级 P1**：本地验证 WCF 连接 + 消息收发
4. **优先级 P2**：补充"连接"/"断开"按钮（可选，当前通过向导第 4 步连接也可）

---

**文档编写时间**：2026-07-27
**编写方**：Work 项目（TRAE IDE）
**推进方**：Code 项目（TRAE Code）