# PDD 规格 · 模块 P1-5：MainWindow 60s 定时刷新工作台

> **PDD 阶段**：grill → prototype ✅（21/21 PASS）→ to-spec（本文档）→ to-tickets → implement+tdd → code-review
> **前置模块**：P1-2 降级横幅（_refresh_degraded_banner）、P1-4 工作台真实数据（refresh_workspace_cards）
> **Grill 总数**：8 条 → 原型 21 断言 / 21 PASS

---

## 1. Grill 清单（8 条）

| Grill | 验收问题 |
|---|---|
| **G1** | MainWindow.__init__ 创建后台 QTimer，interval=60000ms（60s） |
| **G2** | MainWindow 有 _start_auto_refresh_timer() 启动方法 |
| **G3** | MainWindow 有 _stop_auto_refresh_timer() 停止方法 |
| **G4** | 定时器 timeout 触发 _on_auto_refresh_tick() 槽函数 |
| **G5** | tick 时当前页为 workspace 则调用 workspace_page.refresh_workspace_cards() |
| **G6** | tick 时无论哪页都调用 _refresh_degraded_banner() |
| **G7** | MainWindow 析构时自动停止定时器（覆盖 closeEvent） |
| **G8** | 无 WorkspacePage 时不崩（fallback） |

---

## 2. 关键技术决策

| ID | 内容 | 理由 |
|---|---|---|
| **D1** | interval 固定 60s，不做配置 | MVP 简化，用户需求不强 |
| **D2** | 仅 workspace 页刷新 cards，降级横幅每 tick 都刷 | 不打断用户对话/设置操作；降级横幅状态变化频率高（LLM Key 配置后消失）|
| **D3** | 启动后延迟 1500ms 再启动定时器（等 P1-1 Wizard 关闭后） | Wizard 模态关闭后再开始刷新，避免资源竞争 |

---

## 3. 边界（不做）

- 可配置刷新间隔
- 用户手动"暂停刷新"按钮
- 刷新动画/进度条

---

## 4. 开发任务（2 Ticket）

### Ticket 1：MainWindow 加定时器 + 槽函数 + closeEvent
- 文件：[main_window.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/main_window.py)
- 新增类属性 `AUTO_REFRESH_INTERVAL_MS = 60000`
- `__init__` 末尾延迟 1500ms 调 `_start_auto_refresh_timer()`
- 新增 `_start_auto_refresh_timer` / `_stop_auto_refresh_timer` / `_on_auto_refresh_tick`
- 重写 `closeEvent` 停定时器

### Ticket 2：测试用例
- 文件：`tests/test_inner_auto_refresh_pdd.py`
- 8 条 pytest 对应 8 条 Grill

---

## 5. 验收标准

| 验收项 | 标准 |
|---|---|
| 原型 | 21/21 PASS（已通过）|
| pytest | 8/8 PASS |
| 全量回归 | 不退化 |
