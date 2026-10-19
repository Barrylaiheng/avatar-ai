# PDD 规格 · 模块 P1-6：App Startup Smoketest（应用启动冒烟测试）

> **PDD 阶段**：grill → prototype ✅（17/17 PASS）→ to-spec（本文档）→ to-tickets → implement+tdd → code-review
> **前置模块**：M-10 App Bootstrap、P1-1 首启向导、P1-2 降级横幅、P1-4 工作台真实数据、P1-5 60s 定时器、M-17 OA Cloud Bootstrap
> **Grill 总数**：8 条 → 原型 17 断言 / 17 PASS（命中 3 Bug）
> **原型 Bug**：① AppEngine.process_message 无 sender_id 参数，签名需对齐；② OACloudService 路径为 aibridge.oa_service.app 非 service；③ DEFAULT_CONFIG 在 config_manager.py 非 config_loader.py

---

## 1. Grill 清单（8 条）

| Grill | 验收问题 |
|---|---|
| **G1** | AppEngine() + initialize() 在干净临时目录（SCAI_DATA_DIR）不抛异常，返回 bool |
| **G2** | AppEngine 初始化后：is_initialized()=bool；get_degraded_details()=list 可 JSON 序列化（无 PyQt 对象） |
| **G3** | AppEngine.process_message(user_input, session_id) 返回 dict，含 content(str) + is_aigc 字段（LLM 无 Key 时降级不崩，返回占位提示） |
| **G4** | 已有 QApplication 前提下，MainWindow(engine) 实例化不崩溃（不 show/exec） |
| **G5** | MainWindow 实例化后：degraded_banner 非 None；len(_pages)==5（==len(PAGE_ORDER)） |
| **G6** | MainWindow._start_auto_refresh_timer() 调用后，_auto_refresh_timer.isActive()=True |
| **G7** | 安全关闭顺序：_stop_auto_refresh_timer() → window.close() → del window 不抛异常 |
| **G8** | OACloudService.auto_bootstrap(cfg_minimal) 在临时目录下不抛异常；service 非 None（degraded 可接受） |

---

## 2. 关键技术决策

| ID | 内容 | 理由 |
|---|---|---|
| **D1** | 使用 SCAI_DATA_DIR 环境变量指向临时目录，不污染真实 %APPDATA%\SCAI | 测试隔离，防止 pytest 之间相互污染 |
| **D2** | MainWindow 实例化但不调用 show()/exec()，避免弹出真实窗口阻塞 CI | Smoketest 只验证"能创建"，不验证"能交互" |
| **D3** | G8 允许 degraded 状态（message_processor 为 None 或 NullOAService） | MVP 云端服务的 degraded 策略是合法的，不阻塞冒烟 |
| **D4** | LLM 无 Key 时 G3 不应崩溃——process_message 必须返回 content 字段的降级提示 | 用户首次启动不配 Key 是常态，不能崩 |

---

## 3. 边界（不做）

- 真实 LLM 网络调用（始终用空 Key 走 degraded 路径）
- 真实 WCF 连接（AppEngine.is_wcf_connected() 为 False 是预期）
- 真实公众号回调签名（G8 只验证 auto_bootstrap 不崩，不验证 HTTP 路由）
- app.exec() 级别的事件循环（会阻塞测试进程）

---

## 4. 开发任务（1 Ticket）

### Ticket 1：pytest 冒烟测试用例

- **文件**：`tests/test_inner_app_startup_smoke_pdd.py`
- **8 条 pytest 对应 8 条 Grill**：
  - `test_G1_G2_app_engine_init_and_state`：用 tmp_path + monkeypatch 设置 SCAI_DATA_DIR，创建 AppEngine 并 initialize，验证 G1/G2 4 断言
  - `test_G3_process_message_returns_dict`：复用引擎实例，调 process_message 验证 content/is_aigc 字段
  - `test_G4_G5_main_window_instantiation`（需要 QApplication）：创建 MainWindow(engine)，验证 degraded_banner 和 _pages 数量
  - `test_G6_G7_main_window_timer_and_close`（需要 QApplication）：启动定时器 → 验证 isActive → 关定时器 → close → del，不崩
  - `test_G8_oa_cloud_auto_bootstrap`：用独立 tmp_path，构造最小 cfg，调用 OACloudService.auto_bootstrap，验证 service 非 None

---

## 5. 验收标准

| 验收项 | 标准 |
|---|---|
| 原型 | 17/17 PASS（已通过，命中 3 Bug 已修正） |
| pytest | 8/8 PASS |
| 全量回归 | 不退化（675+ passed） |
