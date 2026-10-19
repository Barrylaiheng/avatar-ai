# PDD 规格 · 模块 13：Settings Data Sync（设置回显数据流）

> **PDD 阶段**：grill → prototype ✅ → to-spec（本文档）→ to-tickets → implement+tdd → code-review
> **前置模块**：M-12 UI Data Sync（人设回显），TD-7 Engine→UI 回调钩子三件套范式
> **Grill 总数**：14 条 → 原型 63 断言 / 63 PASS

---

## 1. Grill 清单（14 条用户验收问题，全部机器可断言）

| Grill | 验收问题（大白话） |
|---|---|
| **S1** | AppEngine 有一个"给 UI 读设置的标准接口"，返回 8 个字段（provider/api_key/base_url/model/supports_image/supports_audio/aigc_explicit/aigc_prefix），3 处 UI 都只调它 |
| **S2** | 如果 Engine 还没初始化，这个接口也能给你合理默认值（provider=deepseek, model=deepseek-v4-flash, api_key=""），不会返回 None 或空 dict |
| **S3** | SettingsPage 所有控件都是 self. 属性（provider_combo / baseurl_edit / _apikey_edit / model_combo / thinking_toggle / _aigc_check / _aigc_prefix_edit），不是局部变量 |
| **S4** | SettingsPage 打开时，所有控件已经从 Engine 回显当前值（不是空白，不是 placeholder） |
| **S5** | API Key 输入框默认 password 模式（显示 ●●●●），有眼睛按钮可切换明文 |
| **S6** | 保存按钮收集 ALL 字段（provider 从 combo 读，不写死 "deepseek"），包括 base_url / model / aigc_explicit / aigc_prefix |
| **S7** | save_settings 增量 diff：完全相同的值重复保存，不触发磁盘 IO 也不触发回调通知 |
| **S8** | register_settings_changed_callback / unregister 机制：任何 UI 可订阅设置变化；注销后不再被调用 |
| **S9** | 保存设置成功后，SettingsPage 控件立即热更新（不用重启，不用切页面），通过回调驱动 |
| **S10** | 失败原子性：Engine 未初始化时 save 返回 False，已有配置不被污染 |
| **S11** | 跨重启持久化：关掉 App 再重新打开，上次 save 的 provider / api_key / model 读回来完全一致 |
| **S12** | Workbench 新增"当前 LLM"卡片（provider + model + 连通状态红/绿点），保存设置后立刻刷新 |
| **S13** | 连续多次 save，最终 UI 显示最后一次的值，不会出现第一次把第二次覆盖的时序错误 |
| **S14** | refresh_settings 双路径：有参数时直接用（回调场景），无参数时主动拉 Engine（init 场景），共用同一套格式化规则 |

---

## 2. 根因探查（为什么会出这个 bug）

### 2.1 SettingsPage 控件局部变量化（R1）
- R1.1：`_build_llm_section` 中 `provider_combo` / `baseurl_edit` / `model_combo` / `thinking_toggle` 都是局部变量，**外部无法 setText / setCurrentText 来回显**。只有 `_apikey_edit` 是 self. 属性。
- R1.2：`_on_save_llm` 中 `provider` 写死为 `"deepseek"`，未读 `provider_combo.currentText()`（局部变量也读不到）。
- R1.3：`base_url` / `model` / `thinking` 字段未采集，未传入 save cfg。

### 2.2 SettingsPage 回显完全缺失（R2）
- R2.1：`__init__` 只调 `_setup_ui()`，**未调用任何 _load_settings / _refresh 方法**。
- R2.2：main_window 创建 SettingsPage 后也**未调用 get_settings 进行回显**。
- R2.3：AppEngine.get_settings() 已实现且字段齐全，但** UI 层从未调用过**。

### 2.3 AppEngine 缺回调机制 + 缺 diff（R3）
- R3.1：**没有 register_settings_changed_callback**（对比 M-12 已有 register_persona_changed_callback）。
- R3.2：save_settings **没有增量 diff**（对比 save_persona 有 changed_any 标记 + 新旧值比较）。
- R3.3：save_settings **保存后不通知 UI**（对比 save_persona 在 changed_any 时遍历回调）。

### 2.4 WorkspacePage 缺 LLM 卡片（R4）
- R4.1：**没有"当前 LLM Provider"卡片**（对比 M-12 已有"当前人设"卡片）。
- R4.2：**没有连通状态红/绿点展示**。
- R4.3：没有订阅 settings 变化的逻辑。

### 2.5 main_window 双写字段不匹配（R5）
- R5.1：SettingsPage._on_save_llm 通过 bridge 异步调 save_settings（路径 A），同时通过 `llm_saved` 信号被 main_window 接收，同步调 `save_settings({"llm": cfg})`（路径 B），**同一份 cfg 被保存两次**。
- R5.2：main_window 把 cfg 包装成 `{"llm": cfg}` 传入 save_settings，但 save_settings 期望扁平结构（`{"api_key": ..., "base_url": ...}`），**字段不匹配，实际不保存任何 LLM 字段**。

---

## 3. 修复方案（4 层，对应 Grill）

### 3.1 Engine 层：get_current_settings_dict + 回调三件套 + diff（对应 S1/S2/S7/S8/S9/S10）
1. **`get_current_settings_dict()`**（S1/S2）：UI 读设置唯一入口，返回 8 字段字典，_config 为 None 时返回默认值兜底。
2. **`register_settings_changed_callback(callback) → bool`**（S8）：UI 注册设置变更钩子。
3. **`unregister_settings_changed_callback(callback) → int`**（S8）：注销钩子。
4. **`save_settings()` 增加新旧值 diff**（S7/S10）：相同则跳过 save_config + 回调。

### 3.2 SettingsPage：控件 self. 化 + 回显 + refresh + 注册回调（对应 S3/S4/S5/S6/S9/S14）
- 局部变量 → self. 属性（provider_combo / baseurl_edit / model_combo / thinking_toggle / _aigc_check / _aigc_prefix_edit）
- 新增 `_load_settings_from_engine()`：init 末尾从 Engine 读配置回填
- 新增 `refresh_settings(settings_dict=None)`：双路径（有参数直接用 / 无参数主动拉）
- `_on_save_llm` 修复：provider 从 combo 读，收集 ALL 字段
- init 末尾注册 register_settings_changed_callback
- 切换 provider 时自动更新 base_url 和 model 列表

### 3.3 WorkspacePage：新增"当前 LLM"卡片（对应 S12）
- 在 `_build_stats_row` 新增 LLM 卡片（provider + model + 红/绿点）
- 新增 `refresh_llm_card(settings_dict=None)`
- init 末尾调 refresh + register 回调

### 3.4 main_window：修复双写（对应 R5）
- 移除 `_on_settings_llm_saved` → `_save_llm_config` 的同步调用路径，统一走 bridge 异步
- 或修复字段映射（但推荐移除，避免双写）

---

## 4. 关键技术决策（复用 TD-7 + 新增 D10~D13）

| ID | 决策 | 为什么 |
|---|---|---|
| D1~D9 | （复用 M-12 TD-7 范式） | 回调钩子三件套 + refresh 双路径 + diff 跳过 + 嵌套 try/except |
| **D10** | provider_combo 切换时自动更新 base_url + model 列表 | 用户切 DeepSeek↔豆包时，base_url 和 model 联动变化，避免手动输入错误 URL |
| **D11** | API Key 回显原值（不脱敏），password 模式保护视觉 | SettingsPage 是用户自己操作的管理界面，脱敏后无法确认 key 尾号；password 模式 + 眼睛切换已足够 |
| **D12** | WorkspacePage LLM 卡片红/绿点：有 api_key → green，无 → red | 不做真实连通性测试（避免 LLM 调用开销），仅展示"是否已配置 Key"的状态；真实连通性由 SettingsPage 的 test 按钮触发 |
| **D13** | main_window 双写路径：移除 llm_saved → _save_llm_config 同步路径 | bridge 异步路径已完整（SaveSettingsWorker.sync_run + start），同步路径是冗余且字段不匹配的，直接移除避免混乱 |

---

## 5. pytest 映射（Grill → 测试用例）

| Grill | pytest 用例数 | 文件 |
|---|---|---|
| S1 | 5 | TestS1S2CurrentSettingsDict |
| S2 | 5 | TestS1S2CurrentSettingsDict（未初始化场景） |
| S3 | 7 | TestS3SettingsPageControlsAreSelf |
| S4 | 5 | TestS4SettingsEchoOnOpen |
| S5 | 1 | TestS5ApiKeyPasswordMode |
| S6 | 6 | TestS6CollectAllFields |
| S7 | 6 | TestS7SaveDiff |
| S8 | 9 | TestS8RegisterUnregister |
| S9 | 4 | TestS9HotRefresh |
| S10 | 2 | TestS10SaveFailureAtomicity |
| S11 | 3 | TestS11CrossRestartPersistence |
| S12 | 6 | TestS12WorkspaceLLMCard |
| S13 | 1 | TestS13SequentialSave |
| S14 | 3 | TestS14RefreshDualPath |
| **合计** | **~63** | |

---

## 6. 已交付物清单

| 类别 | 路径 | 说明 |
|---|---|---|
| 规格文档 | `docs/PDD_INNER_settings_data_sync.md` | 本文档 |
| 原型脚本 | `_prototypes/settings_data_sync_prototype.py` | 63 断言 / 63 PASS |
| pytest 固化 | `tests/test_inner_settings_data_sync_pdd.py` | ~63 用例 |
| Engine 修复 | `src/aibridge/app_engine.py` | 4 接口 |
| SettingsPage 修复 | `src/aibridge/ui/settings_page_v2.py` | 控件 self. 化 + 回显 + refresh |
| WorkspacePage 修复 | `src/aibridge/ui/workspace_page.py` | LLM 卡片 + refresh |
| main_window 修复 | `src/aibridge/ui/main_window.py` | 移除双写路径 |
