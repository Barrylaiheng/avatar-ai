# SCAI MVP 架构分析（一）：模块依赖有向图 + 信号流映射

> **里层建设 / 阶段 1 产物**（承接 [PDD_TOTAL_ACCEPTANCE.md](./PDD_TOTAL_ACCEPTANCE.md) 的表层关闭）
>
> **分析方法**：纯静态扫描 `src/aibridge/`（2026-08-09），不做运行期推断。
>
> **扫描脚本**：[scripts/analyze_architecture.py](../scripts/analyze_architecture.py)
> **一次性中间产物**：[docs/_arch_tmp/](./_arch_tmp/)（00_summary + 01~07 明细）

---

## 0. 执行摘要

| 维度 | 结果 | 说明 |
|------|------|------|
| `.py` 文件总数 | 66 | 全部位于 `src/aibridge/` |
| **顶级子包数** | **9** | `root / ui / bridges / engine / agent / rag / database / config / security / utils`（agent/logging 当前没有内部 import 边，但作为包存在） |
| 内部 `import` 语句数 | 125 | 全部是 `from aibridge.X / import aibridge.X` 形式 |
| **子包间依赖边数** | **17** | （仅跨子包计数，同子包不计） |
| **子包级循环依赖** | **✅ 0** | DAG，无环 |
| **跨层依赖异味** | **✅ 0** | 方向一致：root→ui→下；engine/rag→database/config/utils；utils/security 为纯叶子 |
| `pyqtSignal` 定义数 | 102 | **全部定义在 `ui` 包**（102/102 = 100%） |
| `.emit()` 调用数 | 80 | **全部在 `ui` 包**（80/80 = 100%） |
| `.connect()` 调用数 | 150 | 100% 在 `ui` 包；其中 **`main_window.py` 24 条** = 唯一的 UI→AppEngine wiring 盒 |
| **关键 UI→Engine 接线盒** | `ui/main_window.py` | 24 条 connect，0 条 emit，0 条定义（✅ 纯「接线盒」，职责单一） |

---

## 1. 子包级依赖 DAG（ASCII 图）

方向从上到下 = 依赖方向（上层允许 import 下层；无反向）：

```
                 ┌───────────────────────┐
                 │  root (main.py +      │ 组合根：
                 │   app_engine.py)      │ main.py=入口+启动；
                 └──┬────────┬────────┬──┘ app_engine=装配所有子系统
                    │        │        │
      imports ui    │        │        │  imports bridges/engine/rag/database/config
                    ▼        ▼        ▼
   ┌──────────────┐    ┌──────────┐    ┌──────────────┐
   │     ui       │    │ bridges  │    │    engine    │  ← bridges 内部零 import 下游（✅ 正确）
   └──────┬───────┘    └──────────┘    └──┬───┬───────┘
  仅跨包  │                            3│   │4  5（向下）
 persona_ │ database                     │   │
  editor  │                              │   │
          ▼                              ▼   ▼           ┌──────────────┐
   ┌──────────────┐                ┌─────────────────┐   │    rag       │
   │   database   │◄──── 2 ────────┤  config / utils │◄──┤  (1→engine,  │
   └──────┬───────┘                └──────┬──────────┘   │ 2→database,  │
     1→utils│                        1→utils │1→security │ 3→config,    │
          ▼                               ▼   ▼          │ 4→utils)     │
   ┌──────────────┐                ┌─────────────────┐   └──────────────┘
   │    utils     │  (纯叶子)      │    security     │    (纯叶子)
   └──────────────┘                └─────────────────┘
```

### 边表（17 条，按源包分组）

| # | 源 | 目标 | 引用文件数 | 说明 |
|---|----|------|-----------:|------|
| 1 | root | ui | 2 | `main.py → main_window / theme`（✅ 入口装配） |
| 2 | root | bridges | 5 | `app_engine → message_router / internal_message / base_adapter / wcf_adapter ×2` |
| 3 | root | engine | 8 | `app_engine → safety_shield / intent_router / context_assembler / llm_generator / message_store / iteration_engine / aigc_marker / schedule_manager`（**核心装配点**，8 条 = 最重的下游） |
| 4 | root | rag | 2 | `app_engine → rag_engine / knowledge_base_manager` |
| 5 | root | database | 2 | `app_engine → database_manager / database_migrator` |
| 6 | root | config | 1 | `app_engine → config_manager` |
| 7 | ui | database | 1 | **唯一一处 UI 直引下包**：`persona_editor.py → DatabaseManager`（⚠ 可讨论：是否改由 AppEngine 暴露接口？） |
| 8 | engine | database | 4 | `context_assembler / iteration_engine / message_processor / safety_shield`（✅ 业务层访问持久化） |
| 9 | engine | config | 3 | `llm_generator / message_processor / schedule_manager`（✅） |
| 10 | engine | utils | 5 | 最多的叶子依赖（context / iteration / llm / safety / schedule 都用 `generate_id/now_iso/json_*`）（✅） |
| 11 | rag | engine | 1 | `rag_engine → IntentType`（⚠ 可讨论：enum 下沉到 config/common 以消除反向层的"engine 语义层"依赖？） |
| 12 | rag | database | 2 | `knowledge_base_manager / rag_engine`（✅） |
| 13 | rag | config | 3 | `chromadb / knowledge_base / rag_engine`（✅） |
| 14 | rag | utils | 4 | chromadb / document_parser / knowledge_base / wiki_manager（✅） |
| 15 | database | utils | 1 | `database_manager → get_data_dir`（✅） |
| 16 | config | security | 1 | `config_manager → ApiKeyVault`（✅ 安全层被配置依赖，正确方向） |
| 17 | config | utils | 1 | `config_manager → get_data_dir`（✅） |

### 明确的叶子包（✅ 正确）

- `utils`：被 5 个包依赖，自己不依赖任何内部包 → **true leaf**
- `security`：仅被 config 依赖，自己不依赖任何内部包 → **true leaf**
- `bridges`：仅被 root 依赖，内部零 import 下游包（✅ 正确：bridges 是通道抽象，不应自己调 engine）

---

## 2. 子包级依赖矩阵（精确计数）

行=源包（谁 import），列=目标包（被 import）；数字=源包内**至少一次**引用目标的文件数。

| 源 \ 目标 | root | ui | bridges | engine | rag | database | config | security | utils |
|---|---|---|---|---|---|---|---|---|---|
| root | · | 1 | 1 | 1 | 1 | 1 | 1 |  |  |
| ui |  | · |  |  |  | 1 |  |  |  |
| bridges |  |  | · |  |  |  |  |  |  |
| engine |  |  |  | · |  | 4 | 3 |  | 5 |
| rag |  |  |  | 1 | · | 2 | 3 |  | 4 |
| database |  |  |  |  |  | · |  |  | 1 |
| config |  |  |  |  |  |  | · | 1 | 1 |
| security |  |  |  |  |  |  |  | · |  |
| utils |  |  |  |  |  |  |  |  | · |

### 架构健康度

- **循环依赖**：✅ 0（子包级严格 DAG）
- **跨层异味**：✅ 0（没有 engine/rag/database 反向 import ui/root）
- **agent / logging 子包**：当前 0 条内部 import 边（存在但未被其它包 `from aibridge.agent.x / logging.x` 引用，可能是 `__init__` 间接暴露或使用较少，属于后续数据流分析范围）

---

## 3. pyqtSignal 信号流分析

### 3.1 总体特征

| 指标 | 值 | 关键结论 |
|------|----|---------|
| 定义（= signal 声明） | 102 | **100% 在 ui 包**；engine/rag/bridges 中**无一个 QObject 信号**（✅ 业务层不耦合 Qt，极高可移植性） |
| 发送（.emit()） | 80 | 100% 在 ui 包（定义和发送同层符合 Qt 惯例） |
| 接收（.connect()） | 150 | **分布分析**：36 在 linear_wizard（UI 内部自连接），24 在 **main_window（唯一 UI→Engine 接线盒）**，其余是 ChatPage/KnowledgePage/Workspace/PersonaEditor 等页面内部 wiring |

### 3.2 UI↔Engine 关键接线盒

**`ui/main_window.py`**：定义 0 / emit 0 / connect 24 — 纯接线盒（✅ 符合 Facade 角色）。

24 条 connect 的目标方法（推测都连到 main_window.py 内部 `_on_*`，再由它调用 `self.app_engine.*`；下一步数据流分析会验证此调用链）：

| connect 所在上下文（按信号源页面）| 数量（概） | 用途 |
|--------------------------------|----------:|------|
| sidebar.page_changed / theme_toggled | 2 | 全局路由 + 主题切换 |
| chat_page (message_sent / kb_toggled / llm_saved) | 3 | 会话消息 + LLM 配置下发 |
| settings_page_v2 (settingsSaved / llm_saved / wcf_test_requested / oa_test_requested) | 4 | 配置保存 + WCF/企业微信连通测试 |
| knowledge_page (discuss_requested ×2 / entry_saved / export_requested) | 4 | 知识页→ 讨论 / 保存 / 导出 |
| workspace_page (channel_changed / search_changed / status_filter_changed / schedule_toggled / new_schedule_requested) | 5 | 工作区 → 引擎筛选与调度 |
| iteration_page (optimize_requested / discuss_requested) | 2 | 迭代页 → 坏样本优化 |
| worker_threads.finished / failed（ChatReplyWorker ×2 / WcfTestWorker / KbExportWorker / IterationOptWorker）| 5+ | **异步回调主通道**：后台线程完成后回到主线程处理 |

**注**：24 条的精确明细见 [docs/_arch_tmp/06_signal_connects.md](./_arch_tmp/06_signal_connects.md) 中 main_window.py 条目。

### 3.3 信号 wiring 热点 Top 10

按 connect 数降序（代表一个文件内的"内部耦合面"）：

| 排名 | 文件 | 定义数 | emit 数 | connect 数 | 观察 |
|-----:|------|-------:|--------:|-----------:|------|
| 1 | ui/linear_wizard.py | 12 | 13 | 36 | 单文件 connect 最大（内部子控件多，页面级自洽，✅ 属于初始化向导的"重 UI 文件"正常） |
| 2 | ui/main_window.py | 0 | 0 | 24 | ✅ **0 定义 0 emit**：完美接线盒，唯一出 UI 层去 AppEngine 的门 |
| 3 | ui/persona_editor.py | 4 | 3 | 13 | 人设编辑（内部表单控件联动） |
| 4 | ui/chat_page.py | 15 | 9 | 10 | 会话主页面（定义最多的文件） |
| 5 | ui/knowledge_page.py | 13 | 6 | 8 | 知识页 |
| 6 | ui/workspace_page.py | 8 | 7 | 8 | 工作区 |
| 7 | ui/settings_page_v2.py | 8 | 5 | 8 | 设置 V2 |
| 8 | ui/activation_dialog.py | 7 | 7 | 5 | 激活对话框 |
| 9 | ui/iteration_page.py | 5 | 3 | 5 | 迭代优化页 |
| 10 | ui/settings_page.py（老版本）| 4 | 4 | 5 | 设置老版本（PDD 已淘汰为 settings_page_v2） |

---

## 4. 两处可讨论的方向（⚠ 非坏味道，只是可优化点）

本节不是"异味"（它们的方向合法，功能正确），只是"在进入里层建设之前值得讨论的 2 条设计选择"。

### ⚠ D-1：`ui/persona_editor.py` 直接 `from aibridge.database.database_manager import DatabaseManager`（ui → database）

- **现状**：PersonaEditor 直接 new / 调用 `DatabaseManager`（ui 包内唯一跨到下包的 import，1 处）
- **为什么合法**：数据库对象不反向引用 UI，循环风险为零，功能也能跑
- **为什么值得讨论**：人设编辑**逻辑上是业务操作**（"创建/删除/应用人设"应在 AppEngine 或 persona service）。当前直连 DB 的代价：
  - 单测 PersonaEditor 需要连真实 DB（或自己 mock DatabaseManager）
  - 将来要切换人设存储后端（如云端 / 远程配置）时 PersonaEditor 代码也要改
- **建议（进入"数据流/里层 2 阶段"时再决定是否动手）**：将 `_on_save / _on_delete / _on_apply / _on_persona_selected` 的 4 条 DB 调用改为通过 AppEngine 暴露的 4 个纯方法接口，UI 只调 `self.app_engine.*` — 这样 `ui → database` 这条边被消除，UI 层只剩"root 的引用"。

### ⚠ D-2：`rag/rag_engine.py → aibridge.engine.intent_router.IntentType`（rag → engine）

- **现状**：`IntentType` enum 定义在 `aibridge.engine.intent_router`，rag 包引用它做路由分发判断（1 处）
- **为什么合法**：方向上 rag 可以依赖 engine（两者都是中层，rag 稍薄），DAG 不变。
- **为什么值得讨论**：IntentType 是一个"语义 enum"（比如 `CHAT / KNOWLEDGE / WORKSPACE` 等），本质上更像**全局共享常量**，放在 engine 下让 rag 依赖 engine 把"两个本来可独立演化的层绑死了"。
- **建议（数据流 2 阶段决定）**：把 enum 下放到 `aibridge/config/`（或 `aibridge/utils/`）作为独立的 `domain_types.py`，engine 和 rag 都从 config/utils 取。消除 rag→engine 这条 1 处边 → **engine/rag 变成两个可独立测试的并列中层**（对未来把 RAG 独立成服务更友好）。

---

## 5. 对应「里层建设」的后续 4 步优先级（承接 PDD 总验收 §7）

基于本图得到的**真实数据**，推荐执行顺序调整（原 1→2→3→4，微调为 1→2a→2b→3→4）：

| 顺序 | 工作项 | 为什么现在知道它该排这？（基于本图数据）| 预计产物 |
|-----:|--------|---------------------------------------|---------|
| 1 | ✅ 模块依赖有向图（本文档）| 刚完成 | =本文档= |
| 2a | **UI→AppEngine 数据流审计** | 因为信号流分析唯一指出 `main_window.py:24 connect` 是唯一的 UI 出门；把这 24 条每条对应到 `_on_*` 再到调用的 `app_engine.*` 方法 = 一张 UI→Engine 调用契约表 | `docs/ARCHITECTURE_DATAFLOW_UI_ENGINE.md`（24 条 × 信号→目标方法→参数→返回） |
| 2b | **WCF→bridges→message_router→engine 入站流** | 因为 bridges 子包**零下游 import**（好），但也意味着它的入口是被外部/线程回调驱动的。我们要精确绘出：从 bridges 收到外部消息（on_message）到 engine.message_processor.process_message 的完整链。 | `docs/ARCHITECTURE_DATAFLOW_BRIDGES_INBOUND.md` |
| 3 | **Engine 内部信号流（非 Qt）** | engine 子包有 9 个子模块（message_store/llm_generator/message_processor/...）但**零 Qt 信号**；这 9 个模块之间的函数/方法调用就是"信号流"（可称为"Engine Call Graph"），我们要绘出 message_processor → safety_shield → context_assembler → llm_generator → ... 的内部顺序与异常路径 | `docs/ARCHITECTURE_ENGINE_CALLGRAPH.md`（含 stage_classifier / signal_detector / hard_rules_executor 的处理流水线） |
| 4 | **安全/权限边界审计** | config→security 现在是 1 处单向边（很好），要查：ApiKeyVault 被谁调用（读/写），llm_generator 怎么拿 key，日志有没有泄露 key，wcf_adapter 有没有把 key 序列化到外部 | `docs/ARCHITECTURE_SECURITY_AUDIT.md`（结合 PDD Bug #2 防止 api_key 明文的安全规范） |

**以上 4 项 = 里层系统性建设的基线（血管/神经/免疫系统）完成标志**。全部做完后，项目就真正达到：表层（PDD 验收）+ 里层（依赖/数据/信号/安全）双稳定，可以进入模块拆分、TDD 重构或新增功能阶段。

---

## 附 A. 子包说明（9 + 2 观测值）

> 来自代码扫描的实际构成（非设计图）

| 子包 | .py 文件数 | 核心职责（观测值）|
|------|-----------:|-------------------|
| `root` (= main.py + app_engine.py + `__init__.py`) | 3 | 入口装配：AppEngine 是"上帝容器"，创建所有管理器；main.py 创建 QApplication → MainWindow → AppEngine |
| `ui/` | 27 (含 components/) | 全部 Qt UI（PDD 283 Seams 已验收），所有 pyqtSignal 的宿主 |
| `bridges/` | 5 | 外部通道：`base_adapter` / `internal_message` / `message_router` / `wcf_adapter` / `__init__`（✅ 零下游 import） |
| `engine/` | 14 | 业务引擎：message_processor / llm_generator / intent_router / context_assembler / safety_shield / iteration_engine / aigc_marker / message_store / schedule_manager / signal_detector / stage_classifier / hard_rules_executor / `__init__` |
| `rag/` | 7 | RAG + 知识：rag_engine / knowledge_base_manager / chromadb_manager / document_parser / hybrid_retriever / wiki_manager / `__init__` |
| `agent/` | 5 | Agent（当前没有被其他包的 `from aibridge.agent.*` 直接 import，可能通过 AppEngine 间接调用）|
| `database/` | 2 | database_manager / database_migrator（sqlite3）|
| `config/` | 1 | config_manager（配所有运行态设置）|
| `security/` | 1 | api_key_vault（✅ 叶子节点）|
| `logging/` | 1 | log_manager（观测：当前无被其他包 `from aibridge.logging.*` 的 import，可能走 logging.getLogger 标准库直用） |
| `utils/` | 1 | common（✅ 纯叶子：generate_id / now_iso / json_* / get_data_dir）|

---

## 附 B. 扫描可重复性

```powershell
# 重新生成所有 _arch_tmp 明细 + 本文档依据的统计
cd c:\Users\Administrator\Desktop\WeChatAI_Project
python scripts\analyze_architecture.py

# 输出位置
ls docs\_arch_tmp\0*.md   # 00_summary ~ 07_signal_hotspots
```
