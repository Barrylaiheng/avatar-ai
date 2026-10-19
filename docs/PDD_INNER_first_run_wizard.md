# PDD 规格 · 模块 P1-1：First-Run Wizard（首次启动引导向导）

> **PDD 阶段**：grill → prototype ✅（33/33 PASS）→ to-spec（本文档）→ to-tickets → implement+tdd → code-review
> **前置模块**：P1-3 首次启动引导（后台示例数据注入）、P1-2 降级状态可见化、M-11 人设注入链
> **Grill 总数**：10 条 → 原型 33 断言 / 33 PASS

---

## 1. Grill 清单（10 条用户验收问题，全部机器可断言）

| Grill | 验收问题（大白话） |
|---|---|
| **G1** | ConfigManager.is_first_run() 首次返回 True，mark_first_run_done() 后返回 False，持久化跨重启（P1-3 已实现，P1-1 复用） |
| **G2** | ui/first_run_wizard.py 含 FirstRunWizardDialog 类 |
| **G3** | Wizard 3 步流程：Step 1=LLM 配置 / Step 2=人设确认 / Step 3=完成 |
| **G4** | Step 1 LLM 配置：provider 下拉 + api_key 输入 + 测试连接按钮，从 Engine 读当前值回显 |
| **G5** | Step 2 人设确认：显示 P1-3 注入的示例人设（鲜果小助手），可编辑 name/tone |
| **G6** | Step 3 完成页：显示"已为你准备示例知识 5 条" + 开始使用按钮 |
| **G7** | 点击"开始使用"调 engine.mark_first_run_done()，Wizard 关闭 |
| **G8** | 提供"跳过引导"按钮，也调 mark_first_run_done() |
| **G9** | MainWindow.__init__ 末尾检测 is_first_run，True 则弹 Wizard；二次启动不弹 |
| **G10** | Wizard 不阻塞引擎初始化：引擎初始化（含 P1-3 注入）在 Wizard 之前完成 |

---

## 2. 根因探查

### 2.1 P1-3 静默注入无 UI 反馈（R1）
- R1.1：P1-3 的 `bootstrap_first_run` 在 `AppEngine.initialize()` 内静默注入示例人设 + 5 条知识，**用户完全不知情**。
- R1.2：用户首次打开看到的是空 ChatPage，**不知道已注入示例数据**。
- R1.3：LLM API Key 未配置时，用户直接进入主界面看到降级横幅，**没有引导用户去配置**。

### 2.2 缺首次启动引导 UI（R2）
- R2.1：`linear_wizard.py` 已弃用（6 步向导过重），**无轻量级首启向导**。
- R2.2：MainWindow.__init__ **没有 is_first_run 检测逻辑**。
- R2.3：用户首次使用需要自己找 SettingsPage 配 LLM Key、找 PersonaEditor 改人设，**学习成本高**。

---

## 3. 修复方案（2 层，对应 Grill）

### 3.1 UI 层：新建 FirstRunWizardDialog（对应 G2-G8）
- 文件：`src/aibridge/ui/first_run_wizard.py`
- 基于 QDialog 模态弹出，3 步流程：
  - **Step 1 LLM 配置**：provider 下拉 + api_key 输入 + 测试连接按钮，从 Engine 读当前值回显
  - **Step 2 人设确认**：显示 P1-3 注入的示例人设（name/type/tone），可编辑
  - **Step 3 完成页**：显示"已为你准备 5 条示例知识" + 开始使用按钮
- 按钮：上一步 / 下一步 / 跳过引导 / 开始使用
- Step 1→2 时调 `engine.save_settings()`，Step 2→3 时调 `engine.save_persona()`
- 完成/跳过都调 `engine.mark_first_run_done()`

### 3.2 MainWindow 集成（对应 G9-G10）
- 文件：`src/aibridge/ui/main_window.py`
- `__init__` 末尾用 QTimer.singleShot 延迟检测 `is_first_run()`
- True 则弹出 FirstRunWizardDialog 模态对话框
- 引擎初始化（含 P1-3 注入）已在 MainWindow 构造前完成，Wizard 不阻塞

---

## 4. 开发任务（to-tickets）

### Ticket 1：新建 FirstRunWizardDialog（G2-G8）
- 文件：`src/aibridge/ui/first_run_wizard.py`
- 3 步 QStackedWidget + 导航按钮 + 跳过/完成逻辑

### Ticket 2：MainWindow 启动检测首启（G9-G10）
- 文件：`src/aibridge/ui/main_window.py`
- `__init__` 末尾 QTimer.singleShot(800, self._check_first_run)
- 新增 `_check_first_run()` 方法

### Ticket 3：测试用例（G1-G10）
- 文件：`tests/test_inner_first_run_wizard_pdd.py`
- 10 条 pytest 对应 10 条 Grill

---

## 5. 关键技术决策

| 决策 ID | 内容 | 理由 |
|---|---|---|
| **D1** | Wizard 用 QDialog 模态弹出 | 不阻塞引擎初始化，只阻塞用户交互 |
| **D2** | Step 1 LLM 配置复用 engine.save_settings | 避免重复实现保存逻辑 |
| **D3** | Step 2 人设确认复用 engine.save_persona | 同上 |
| **D4** | Wizard 关闭后不重启 App | 回调驱动 UI 更新（M-12/M-13 已实现） |

---

## 6. 边界（不做）

- 6 步完整向导（linear_wizard.py 已弃用）
- 知识库导入在 Wizard 内完成（只提示"已准备 5 条"）
- 微信/公众号渠道配置（在 SettingsPage 配置）
- Wizard 进度保存（关闭即结束）

---

## 7. 验收标准

| 验收项 | 标准 |
|---|---|
| 原型 | 33/33 PASS（已通过） |
| pytest | 10/10 PASS |
| 全量回归 | 与 P1-4+P1-3+P1-2+M-14+M-16+M-22+M-23 联合回归不退化 |
| 持久化 | 完成/跳过后二次启动不弹 Wizard |
