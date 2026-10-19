# PDD 规格 · 模块 P1-4：Workspace Real Data（工作台真实卡片数据）

> **PDD 阶段**：grill → prototype ✅（27/27 PASS）→ to-spec（本文档）→ to-tickets → implement+tdd → code-review
> **前置模块**：M-12 UI Data Sync（人设卡片）、M-13 Settings Data Sync（LLM 卡片）、M-19 WCF Handler（消息列表已打通）
> **Grill 总数**：10 条 → 原型 27 断言 / 27 PASS

---

## 1. Grill 清单（10 条用户验收问题，全部机器可断言）

| Grill | 验收问题（大白话） |
|---|---|
| **G1** | AppEngine.get_workspace_stats("wechat") 返回的是 MessageStore 的真实统计（total=128, satisfaction=93），不是 mock 写死的 0 |
| **G2** | AppEngine.get_workspace_stats("mp") 渠道暂未接入，返回零值不崩（阶段 4 实现） |
| **G3** | AppEngine.get_workspace_schedules() 读 config.schedules 字段，返回 list[dict]，每项含 id/name/icon/schedule_desc/enabled，缺字段有默认值 |
| **G4** | config.schedules 为空或不存在时，get_workspace_schedules() 返回空 list 不崩 |
| **G5** | AppEngine.set_workspace_schedule_enabled(id, enabled) 找到 task 写回 config + 持久化；不存在的 task_id 返回 False；幂等 |
| **G6** | WorkspacePage 注入 Engine 时，stats 卡片走真实数据（不再硬编码 0.8s / 95%） |
| **G7** | WorkspacePage 注入 Engine 时，schedules 列表走真实配置（不再 mock 3 条假任务） |
| **G8** | WorkspacePage schedule toggle 时调用 Engine.set_workspace_schedule_enabled，成功后本地状态同步 |
| **G9** | WorkspacePage 新增 refresh_workspace_cards() 方法，一次性拉 stats + schedules，作为统一刷新入口 |
| **G10** | WorkspacePage 无 Engine 时 fallback 全 mock 不崩（兼容 pytest 无 engine 场景） |

---

## 2. 根因探查（为什么会出这个 bug）

### 2.1 Stats 卡片硬编码（R1）
- R1.1：`_on_channel_loaded` 中 `avg_response_time="0.8"`、`satisfaction=95` **写死**，跟真实 MessageStore 数据无关。
- R1.2：`AppEngine.get_workspace_stats(channel)` 已在 M-12 实现（[app_engine.py:1685](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/app_engine.py#L1685)），但 **WorkspacePage 从未调用过**。
- R1.3：渠道切换时 `_switch_channel` 只调 `_refresh_stats()`（读本地 dict），**没有重新从 Engine 拉**。

### 2.2 Schedules 完全 Mock（R2）
- R2.1：`_mock_schedules()` 写死 3 条假任务（每日早安 / 周五水果 / 晚间特价），**无真实数据源**。
- R2.2：`AppEngine` **没有 get_workspace_schedules / set_workspace_schedule_enabled 方法**。
- R2.3：toggle 仅更新本地 `self._schedules` 内存状态，**关 App 后丢失**。

### 2.3 缺统一刷新入口（R3）
- R3.1：WorkspacePage **没有 refresh_workspace_cards() 方法**，无法一次性拉 stats + schedules。
- R3.2：MainWindow **没有定时刷新机制**（P1-5 任务，P1-4 只暴露 API）。

### 2.4 公众号渠道零数据（R4，边界）
- R4.1：`AppEngine.get_workspace_stats("mp")` 返回零值，**阶段 4 才接入**。
- R4.2：P1-4 不处理 mp 渠道真实数据，只保证不崩。

---

## 3. 修复方案（3 层，对应 Grill）

### 3.1 Engine 层：新增 schedules 读写 + 复用 stats（对应 G1-G5）
1. **`get_workspace_stats(channel)`**（G1/G2）：M-12 已实现，P1-4 复用，不改动。
2. **`get_workspace_schedules() → List[Dict]`**（G3/G4）：新增方法，读 `config.schedules` 字段，返回标准结构 list[dict]。
   - 空配置返回 `[]`
   - 缺字段默认值：`enabled=True`、`icon="📅"`
   - 异常返回 `[]`
3. **`set_workspace_schedule_enabled(task_id, enabled) → bool`**（G5）：新增方法，找到 task 后更新 `config.schedules` 并 `save_config()` 持久化。
   - 不存在的 task_id 返回 `False`
   - 幂等：相同状态重复调用也成功
   - 异常返回 `False`

### 3.2 UI 层：WorkspacePage 改造（对应 G6-G9）
- **`refresh_workspace_cards()`**（G9）：新增统一入口，一次性拉 stats + schedules。
- **`__init__` 改造**（G6/G7）：注入 Engine 时调用 `refresh_workspace_cards()` 替换 mock。
- **`_on_channel_loaded` 改造**（G6）：移除硬编码 `0.8s / 95%`，调用 `engine.get_workspace_stats(channel)`。
- **`_switch_channel` 改造**（G6）：切换渠道时调用 `engine.get_workspace_stats(channel)` 刷新。
- **`_on_schedule_toggled` 改造**（G8）：toggle 后调用 `engine.set_workspace_schedule_enabled(id, on)`，成功后本地同步。
- **`_schedules` 初始化**（G7）：注入 Engine 时从 `engine.get_workspace_schedules()` 加载，无 Engine 时保留 mock。

### 3.3 兼容层：无 Engine fallback（对应 G10）
- `__init__` 检测 `app_engine is None` 时，跳过 `refresh_workspace_cards`，保留原 mock 数据。
- `on_schedule_toggled` 检测 `app_engine is None` 时返回 False，不崩。

---

## 4. 开发任务（to-tickets）

### Ticket 1：AppEngine 新增 get_workspace_schedules（G3/G4）
- 文件：[app_engine.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/app_engine.py)
- 方法：`get_workspace_schedules() -> List[Dict[str, Any]]`
- 逻辑：读 `self._config.get("schedules", [])`，标准化每项结构（id/name/icon/schedule_desc/enabled/cron）
- 异常：try/except 返回 `[]`

### Ticket 2：AppEngine 新增 set_workspace_schedule_enabled（G5）
- 文件：[app_engine.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/app_engine.py)
- 方法：`set_workspace_schedule_enabled(task_id: str, enabled: bool) -> bool`
- 逻辑：遍历 `self._config.get("schedules", [])` 找到 task_id，更新 enabled，调 `self._config.set("schedules", ...)` + `self._config.save_config()`
- 返回：找到并更新返回 True，未找到返回 False

### Ticket 3：WorkspacePage 新增 refresh_workspace_cards（G9）
- 文件：[workspace_page.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/workspace_page.py)
- 方法：`refresh_workspace_cards() -> None`
- 逻辑：调用 `engine.get_workspace_stats(channel)` 更新 `_stats[channel]` + 调用 `engine.get_workspace_schedules()` 更新 `_schedules`
- 触发 `_refresh_stats()` + `_render_schedules()`

### Ticket 4：WorkspacePage stats 卡片走真实数据（G6）
- 文件：[workspace_page.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/workspace_page.py)
- 改造 `_on_channel_loaded`：移除硬编码 `0.8s / 95%`，调用 `engine.get_workspace_stats(channel)`
- 改造 `_switch_channel`：切换时调用 `engine.get_workspace_stats(channel)` 刷新

### Ticket 5：WorkspacePage schedules 走真实配置（G7）
- 文件：[workspace_page.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/workspace_page.py)
- 改造 `__init__`：注入 Engine 时调用 `refresh_workspace_cards()` 加载真实 schedules
- 保留无 Engine 时 mock fallback

### Ticket 6：WorkspacePage toggle 调用 Engine（G8 + G10）
- 文件：[workspace_page.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/workspace_page.py)
- 改造 `_on_schedule_toggled`：调用 `engine.set_workspace_schedule_enabled(id, on)`
- 无 Engine 时返回 False 不崩

### Ticket 7：测试用例（G1-G10）
- 文件：[test_inner_workspace_real_data_pdd.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/tests/test_inner_workspace_real_data_pdd.py)
- 10 条 pytest 对应 10 条 Grill

---

## 5. 关键技术决策

| 决策 ID | 内容 | 理由 |
|---|---|---|
| **D1** | 定时推送配置存 `config.json` 的 `schedules` 字段，结构 `[{id, name, icon, schedule_desc, enabled, cron}]` | 跟人设/设置同源管理，可 Git 管理，不新增存储组件 |
| **D2** | `get_workspace_stats` 复用 M-12 已有方法，P1-4 只补 UI 调用层 | 避免重复造轮子，M-12 已测试通过 |
| **D3** | `refresh_workspace_cards` 由 MainWindow 的 QTimer 每 60s 触发（P1-5 接入，P1-4 只暴露 API） | 解耦刷新入口和定时器，P1-4 不越界 |
| **D4** | 定时推送**新增/编辑**任务不在 P1-4 范围（仅读 + 启停） | MVP 边界，新增/编辑 UI 留到后续迭代 |

---

## 6. 边界（不做）

- 公众号 mp 渠道真实统计（阶段 4）
- 定时推送的新增/编辑/删除 UI
- cron 实际调度执行（仅展示配置）
- MainWindow 60s 定时刷新（P1-5 做）

---

## 7. 验收标准

| 验收项 | 标准 |
|---|---|
| 原型 | 27/27 PASS（已通过） |
| pytest | 10/10 PASS |
| 全量回归 | 与 M-14+M-16+M-22+M-23+P1-3+P1-2 联合回归不退化 |
| 降级策略 | 无 Engine 不崩 / 空配置返回空 list / 不存在 task_id 返回 False |
| 持久化 | toggle 后重启 App，状态保留 |
