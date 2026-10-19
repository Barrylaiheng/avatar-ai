---
文档名称: 阿凡达AI 产品需求文档（PRD）
项目代号: 阿凡达AI / Avatar AI
版本: v1.2
日期: 2026-08-21
状态: 对齐 RAG 检索模块实现（UnifiedRetriever 闭环）
作者: 产品团队
依据: 知识库 wiki/architecture/avatar-ai-project-setup.md 等 6 份沉淀页 + HTML 原型 v2 + 已实现代码
开发方法: PRD 驱动 + 小智 UI/UX 对标 + 关键链路验收
变更记录:
  - v1.2（2026-08-21）：3.5 节重写为「知识库与 RAG 检索」，对齐 UnifiedRetriever 实现
    （L1 BM25 + L2 hash 占位/后续 ChromaDB+bge、kb_id 隔离、_rebuild_index_from_db、
    KarpathyWikiReader、doc_parser、Bridge 桥接表）；旧 HybridRetriever 标注 deprecated
  - v1.1（2026-08-21）：基于 HTML 原型 v2 反推，对齐首启向导/智能体/设置/激活/数据模型
  - v1.0：初版起草
---

# 阿凡达AI 产品需求文档（PRD v1.2）

> 本 PRD 基于知识库沉淀起草，依据文件：
> - `wiki/architecture/avatar-ai-project-setup.md` — 项目设定与商业决策
> - `wiki/concepts/avatar-ai-theory-framework.md` — 6 组件理论框架
> - `wiki/architecture/xiaozhi-architecture-deep-dive.md` — 小智架构深度调研
> - `wiki/architecture/xiaozhi-vs-scai-comparison.md` — 小智 vs SCAI 架构对比
> - `wiki/architecture/ragflow-vs-okf-dual-route.md` — 知识库双路线方案（v1.2 已调整为单入口 UnifiedRetriever）
> - `wiki/concepts/ai-self-evolution.md` — AI 自我进化路线图
> - `app/storage/retriever.py` — UnifiedRetriever / VectorRetriever / KarpathyWikiReader 实现（v1.2 新增依据）
> - `app/storage/doc_parser.py` — 文档解析与切片实现（v1.2 新增依据）
> - `app/bridge.py` — JS↔Python 桥接（add_kb_document / search_kb / _rebuild_index_from_db）（v1.2 新增依据）

---

## 1. 概述

### 1.1 项目定义

| 维度 | 决策 |
|------|------|
| 项目代号 | 阿凡达AI / Avatar AI |
| 与原 SCAI 关系 | **全新项目，不碰原代码**（不否定原 SCAI，是有新想法而单独拎出来） |
| 产品定位 | **个人 AI 数字分身工具** |
| 软件形态 | **PyQt6 桌面 exe**（不做 Web） |
| 数据主权 | **数据全本地存储，仅激活时联网** |
| 商业模式 | **一次买断** |
| 付费平台 | 虎皮椒 V3 |
| 激活机制 | 软件内扫码 → 轮询确认 → 自动激活 → 机器码绑定 → 离线永久可用 |
| 开发方法 | **PRD 驱动 + 小智 UI/UX 对标 + 关键链路验收**（不用 PDD） |
| 仓库可见性 | Public 仓库 + 代码闭源 |
| License | All Rights Reserved / 专有商业 |
| 社区互动 | 只接 issue 不接 PR |
| 小智代码复用 | MIT 合规保留版权声明 |

### 1.2 形态决策：PyQt6 桌面 exe，不做 Web

**决策结论**：借鉴小智 AI 的**交互逻辑**（智能体卡片、单页表单、多模型下拉、AI 一键优化），但不借鉴其**形态**（Web）。

**理由**：
1. **本地 Web 分发是死结**——打包 exe 里启动 Flask 多此一举；让用户装 Python 不可行；Chrome 插件用户不懂
2. **小智做 Web 是被硬件载体逼的**（硬件设备没有屏幕配置 AI），阿凡达的载体是微信，没有这个约束
3. **数据主权 + WCF 本地约束**本身就指向桌面形态
4. **现有 PyQt6 资产可复用**

### 1.3 商业模式概述

- **一次买断**：产品本体一次性付费，永久使用
- **先试用后付费**：用户完成配置后可免费试用 50 次对话，达到上限后需扫码激活
- **可持续性**：不亏损，工具本体买断 + AI 成本用户自担
- **AI 成本自担**：用户自带 LLM API Key，AI 调用成本由用户自行承担

### 1.4 名词约定

| 名词 | 含义 |
|------|------|
| 数字分身 | 用户在阿凡达AI 中创建的、镜像用户本人知识/性格/记忆的 AI 角色 |
| 人设 / 智能体 | 同义，对应数据库 `ai_agent` 表的一行记录 |
| 知识库双路线 | LocalOKFAdapter（数字分身核心记忆，OKF Markdown 本体）+ RAGFlowAdapter（大量文档检索） |
| 记忆驱动自进化 | 替代原 SCAI 的 BadCase 闭环，作为第 4 组件，BadCase 降级为异常熔断机制 |
| BYOK | Bring Your Own Key，用户自带 LLM API Key |
| OKF | Objective Knowledge Fact，对齐 Google OKF v0.1 的 Markdown + YAML frontmatter 知识本体格式 |

---

## 2. 目标用户与场景

### 2.1 目标用户画像

**主要用户**：有微信 + 有个人知识管理诉求的中文个人用户 / 内容创作者 / 知识工作者。

**特征**：
- 自己有 LLM API Key（OpenAI / DeepSeek / 通义千问 / 智谱 / Ollama 本地等）
- 重视数据主权，不希望对话/知识库上传云端
- 希望有一个"懂自己"的 AI 数字分身，长期累积个人记忆与知识
- 习惯桌面端工具，不希望安装 Python 等开发环境
- 有付费意愿（一次性买断可接受，但抗拒订阅）

### 2.2 核心使用场景

| 场景 | 用户动作 | 阿凡达AI 行为 |
|------|---------|---------------|
| **首次启动** | 安装 exe → 启动 → 跟随 2 步向导配置 | 欢迎页（产品介绍）→ 配置 LLM（服务商/API 接口地址/API 密钥/模型名称）→ 自动跳转到「设置 → 渠道连接」 |
| **创建数字分身** | 智能体 Tab → 新建 → 填写人设卡 → 选择模型 → 保存 | 卡片化展示，配置弹窗 4 Tab（角色/模型与记忆/扩展能力/高级） |
| **日常对话** | 历史 Tab 选会话 → 输入消息 → 流式回复 | 打字机效果 + 完成后显示绿色 AIGC 徽标 + 元数据（人设名/RAG 命中数/Tool Calls） |
| **沉淀个人记忆** | 写日记 / 写人设 / 上传文档 | LocalOKFAdapter 编译为 OKF Markdown，存入 `data/wiki/`，向量化到 ChromaDB |
| **大量文档问答** | 上传 100 页 PDF → 提问 | 引导走 RAGFlowAdapter（P1 阶段），透明告知路线差异 |
| **隐式反馈** | 对话气泡 👍/👎 | 被赞记忆 +1，被踩 -1；触发 Self-Refine 自评 |
| **激活付费** | 软件内点「激活」→ 扫码付款 | 2 秒轮询订单状态 → 自动激活 → 绑定机器码 → 永久离线可用 |

### 2.3 非目标用户（明确排除）

- 想要免费使用的用户（本产品一次买断，不提供免费版）
- 没有 LLM API Key 且不愿申请的用户
- 需要 SaaS / 多人协作的团队（本产品是单机桌面工具）
- 需要语音硬件设备联动的用户（小智的目标用户，不是阿凡达的）

---

## 3. 6 组件理论框架（产品方法论）

阿凡达AI 的产品方法论基于 6 组件理论框架，源自 SCAI 项目沉淀，经小智架构调研验证后修正为 6 组件（原 5 组件 + 插件系统 + 升级迭代系统为记忆驱动自进化）。

```
LLM（大脑） + Context（短期记忆） + Prompt（人设/宪法）
+ 记忆驱动自进化（替代原"迭代系统"）+ 知识库双路线（本体 OKF + 检索 RAGFlow）
+ 插件系统（MCP/Tool）
```

### 3.1 组件 1：LLM（大脑）

- **Provider Pattern 多模型切换**：借鉴小智的 `core/providers/llm/` 目录式组织
- **工厂模式动态 import**：启动时按用户配置动态加载 Provider 类
- **多模型配置表**：`sys_config` 表存所有模型配置（provider/apiKey/apiUrl），`ai_agent.llmModelId` 引用某个 configId
- **BYOK**：用户自带 API Key，密钥 DPAPI 机器绑定加密存储

### 3.2 组件 2：Context（短期记忆）

- **分层记忆系统**（MemGPT 思想）：
  - **L1 工作记忆**：当前对话上下文（已有）
  - **L2 用户画像记忆**：跨会话用户偏好（新增，存 SQLite `user_memory` 表）
  - **L3 知识库记忆**：RAG 命中过的 chunk + AI 总结（已有 ChromaDB，新增"AI 总结写入"）
- **summaryMemory**：跨会话上下文压缩（不是知识库），借鉴小智
- **隐式反馈采集**：对话气泡加 👍/👎 按钮（参考 Replika）

### 3.3 组件 3：Prompt（人设 / 宪法）

- **systemPrompt 定义角色性格**
- **借鉴小智 5 分区模板**：
  1. `<identity>` 嵌入用户人设
  2. `<core_rules>` 核心规则
  3. `<output_language_directive>` 输出语言指令
  4. `<anti_ai_smell>` 反 AI 腔
  5. `<format_constraints>` 格式约束
- **人设卡 + 安全壳 = 阿凡达的"宪法"**（Constitutional AI 思想）
- **支持 Jinja2 变量插值**

### 3.4 组件 4：记忆驱动自进化（替代原"迭代系统"）

**核心转变**：BadCase 闭环（2022 年前方法论，落后主流约 4 年）→ 记忆驱动自进化。

- **BadCase 不废弃，降级为异常熔断机制**
- **主路径**：记忆驱动 + Self-RAG + 隐式反馈
- **冷启动种子**：首启向导人设卡 → 直接作为种子记忆

**短期方案（MVP，0-3 个月）**：
1. 分层记忆系统（L1/L2/L3）
2. 隐式反馈采集（👍/👎 + 元数据卡片显示"本次用到的记忆条目"）
3. AI 自评环节（Self-Refine 简化版：被赞 +1，被踩 -1）
4. 冷启动种子：首启向导人设卡

**中期方案（3-9 个月）**：
1. Self-RAG 升级（检索后自评是否够用，不够用触发追问/重检索）
2. CRAG 修正机制（检索质量差时自动重写查询或降级）
3. 知识图谱自动构建（轻量版，从对话抽取实体-关系，存为 Markdown 双向链接）
4. "Dreaming" 后台进程（应用空闲时后台总结近期对话，抽取用户洞察写入 L2）

**长期方案（9-18 个月）**：
1. 技能库累积（Voyager 思想）
2. Reflexion 反思机制
3. 轻量 KTO 思想借鉴（用于"记忆写入权重"）
4. 宪法约束自评（每次记忆写入前 LLM 自评"是否符合宪法"）
5. 多 Agent 思想内化（单分身内化"Checker"角色，回答生成后自评一轮）

**SAGE 自进化三定律（安全护栏）**：
1. 安全第一，任何升级不破坏稳定
2. 性能不减，新技能必须 ≥ 旧能力
3. 自主进化，无需人类写死规则

### 3.5 组件 5：知识库与 RAG 检索

#### 3.5.1 路线决策（对齐当前实现）

原 v1.0 设计的"双路线（LocalOKFAdapter + RAGFlowAdapter）"在 MVP P0 阶段**简化为单入口 UnifiedRetriever**：

| 路线 | 状态 | 说明 |
|------|------|------|
| **UnifiedRetriever（统一检索入口）** | ✅ MVP P0 已实现 | L1 关键词（BM25）+ L2 向量（占位）双层融合 |
| RAGFlowAdapter（外部 RAGFlow 大量文档检索） | 🔜 P1+ 占位 | 上传 100 页 PDF 走外部 RAGFlow，MVP 不做 |

**替代关系**：旧 HybridRetriever 设计过重 + 依赖未实现的 LLMWikiManager，**已 deprecated**，被 UnifiedRetriever 替代为本项目唯一检索入口。

#### 3.5.2 UnifiedRetriever 双层架构

```
UnifiedRetriever（统一检索入口）
  ├─ L1 KeywordRetriever（默认启用，零依赖）
  │    └─ BM25 简化版（k1=1.5, b=0.75）
  │    └─ 中文按字符切分，英文按空格+标点切分（不引 jieba）
  ├─ L2 VectorRetriever（占位实现，后续替换）
  │    └─ 当前：hash n-gram + cosine 相似度（零依赖，过滤碰撞噪声）
  │    └─ 后续：ChromaDB + bge-small-zh-v1.5（接口不变，仅换内部实现）
  └─ 融合排序
       └─ max-min 归一化后加权和：score = w_vector * l2 + w_keyword * l1
       └─ 默认 w_vector=0.6, w_keyword=0.4
       └─ source_layer 标注：L1+L2 / L1_only / L2_only
```

**关键能力**：
- 按 `kb_id` 隔离 chunks，支持 `kb_ids` 过滤检索（多知识库互不污染）
- `remove_document(doc_id)` 同步删 L1+L2 双侧索引
- 启动时 `_rebuild_index_from_db` 从 SQLite `kb_document` 表恢复索引（status=ok 的记录按 file_path 重新解析）

#### 3.5.3 知识本体格式（LLM Wiki）

对齐 Karpathy LLM Wiki + Google OKF v0.1 规范：

| 字段 | 必填 | 说明 |
|------|------|------|
| `type` | 是 | 唯一必填字段（concept/note/log 等） |
| `title` | 否 | 缺失时取正文第一个 H1，再缺失用文件名 |
| `tags` | 否 | 支持 `[a, b]` / `a, b` / `a b` 三种写法 |
| `created` / `updated` / `source` / `author` | 否 | 兼容 Obsidian 原生格式 |
| 正文 | — | Markdown，按 512 字符语义切片 |

**KarpathyWikiReader** 解析带 YAML frontmatter 的 MD 文件，提取标题/标签/正文并切片后喂入 UnifiedRetriever。从 Obsidian / Trae / Workbody 导入知识库时复用此格式。

#### 3.5.4 文档解析（doc_parser）

| 格式 | MVP P0 | 依赖 |
|------|--------|------|
| TXT / MD / LOG / JSON | ✅ 纯标准库 | 无 |
| CSV | ✅ 按行拼接 | 无 |
| HTML | ✅ 正则剥标签 | 无 |
| PDF | 🔜 回电脑后接 | pypdf |
| DOCX | 🔜 回电脑后接 | python-docx |
| DOC / PPTX / XLSX / EPUB | ❌ MVP 不做 | — |

**切片策略**：目标 512 字符，在 `[target-100, target+200]` 区间找最近的句末标点（`。\n！？!?;；`）切分，找不到时找逗号（`，,、`），最后硬切。不重叠（MVP 简化）。

#### 3.5.5 Bridge 桥接（JS ↔ Python）

| Bridge action | 入参 | 返回 |
|---------------|------|------|
| `add_kb_document` | `kb_id, file_path, name?, size_bytes?` | `added, doc, chunk_count, chunk_ids` |
| `search_kb` | `query, top_k=5, kb_ids?` | `results[], stats` |
| `get_kb_document_chunks` | `doc_id, preview=120` | `chunks[{position, char_count, preview}]` |
| `delete_kb_document` | `id` | `deleted, chunks_removed` |
| `pick_kb_document_file` | 无 | `picked, file_path, name, size_bytes`（QFileDialog 通道，回电脑接入） |

**文件选择通道**：HTML `<input type=file>` 受浏览器安全限制拿不到本地真实路径，必须走 Python `QFileDialog` 通道。`pick_kb_document_file` 是桩，返回 `not_implemented` 时前端回退到 `<input type=file>` 并提示"无法真实解析"。

#### 3.5.6 L1 + L2 不可混在一起

延续原设计原则：L1（关键词）+ L2（向量）是**检索加速层**，知识本体是 LLM Wiki Markdown。ChromaDB 明确定位为"检索加速层"，不是知识本体；知识从 Markdown 灌入可重建 ChromaDB。

### 3.6 组件 6：插件系统（MCP / Tool）

- **借鉴小智的 `@register_function` + JSON Schema + Action 响应**
- **Action.REQLLM vs Action.ACTION 区分**——工具执行后是否需要 LLM 再生成回复
- **MCP Server / 接入点 / 工具启用禁用 API**
- **让每个能力（RAG / 联网搜索 / 天气 / 自定义工具）都是独立插件**，LLM 通过 function_call 动态调用

---

## 4. 功能模块清单

### 4.1 主窗口导航结构

借鉴小智顶部导航设计，原型采用 3 Tab 结构：

| Tab 序号 | 名称 | 对应小智 Tab | 主要功能 |
|---------|------|------------|---------|
| 1 | **智能体** | 角色 / 智能体 | 人设卡管理、配置弹窗、模型选择、扩展能力绑定、渠道配置 |
| 2 | **知识库** | 知识库 | 双路线知识库管理、三级钻取、召回测试 |
| 3 | **设置** | 设置 | LLM 管理、渠道连接、激活、主题、关于 |

> **历史对话**：从智能体卡片直接进入（非独立 Tab），点击卡片 → 进入该智能体的历史对话页面。
> 不借鉴的部分：声纹识别 Tab（阿凡达文字交互）、固件编译、OTA 升级、设备 MAC 绑定。

### 4.2 智能体模块（Tab 1）

#### 4.2.1 智能体卡片列表

- **卡片化展示**（借鉴小智，替代原 SCAI 的列表式）
- 每张卡片显示：人设名 / 头像 / 角色 / 绑定模型 / 状态
- **更多菜单**（卡片右上角三点）：
  - **重命名**：弹窗输入新名称
  - **删除智能体**：二次确认弹窗（需输入智能体名称才能激活确认按钮）
    - 红色警示区：「该智能体的所有对话历史 + 记忆数据 不可恢复」
    - 强制输入名称验证：防止误操作
- 操作：新建 / 编辑 / 重命名 / 删除
- 顶部 token 计数器（借鉴小智）：人设 prompt token 数预估

#### 4.2.2 配置弹窗 4 Tab（借鉴小智）

| 子 Tab | 字段 |
|--------|------|
| **角色** | 人设名 / 头像 / systemPrompt（5 分区模板）/ 输出语言 / 是否启用 emoji / TTS 语音（可选） |
| **模型与记忆** | LLM 模型下拉（引用 `sys_config`）/ SLM 模型下拉（用于会话标题生成）/ 记忆模式（mem_local_short/powermem/nomem）/ summaryMemory 开关 |
| **扩展能力** | 插件卡片网格（RAG 知识库 / 联网搜索 / 天气 / 自定义 MCP）/ 启用禁用 / 插件参数配置 |
| **高级** | 安全壳配置（PII 检测 / Prompt 注入检测 / 敏感词）/ AIGC 标识样式 / temperature / max_tokens |

#### 4.2.3 多模型下拉切换（借鉴小智）

- 模型选择进入人设配置（不在全局设置里）
- 下拉项来源：`sys_config` 表
- 支持运行中切换模型（不重启应用）
- 切换后人设卡片实时刷新绑定模型标识

#### 4.2.4 智能体渠道配置（好友/群聊管理）

- **入口**：智能体卡片上的「渠道配置」按钮（或从更多菜单进入）
- **功能**：管理该智能体要服务的微信好友和群聊
- **配置弹窗内容**（参考原型设计）：
  - **Tab 切换**：好友列表 / 群聊列表
  - **筛选行**：搜索框（好友备注/微信号/群名）+ 筛选芯片（全部/已启用）
  - **好友/群聊列表**：
    - 好友：头像、昵称、微信号、备注、启用开关
    - 群聊：群头像、群名称、成员数、启用开关
  - **AIGC 标识开关**：控制该智能体回复是否显示 AIGC 标识
  - **底部状态条**：显示已启用对象数量
- **数据交互**：保存后实时更新智能体的渠道绑定关系

#### 4.2.5 AI 一键优化（借鉴小智）

- 人设 systemPrompt 输入框旁边加「AI 优化」按钮
- 调用当前选中 LLM，按 5 分区模板重写人设
- 优化前后对比 diff（借鉴 Cursor 的 accept/reject）
- 用户确认后才写入

### 4.3 知识库模块（Tab 2）

#### 4.3.1 双路线切换

- 顶部 Tab 切换：`本机知识库（OKF）` / `文档检索（RAGFlow）`
- RAGFlow 路线在 P1 阶段实现，P0 阶段该 Tab 显示「即将上线」占位

#### 4.3.2 LocalOKFAdapter 三级钻取（借鉴小智）

1. **知识库列表**（6 列表格：名称 / 描述 / 文档数 / 切片数 / 状态 / 操作）
   - 操作按钮：管理文档、编辑、删除
   - 删除需二次确认（输入知识库名称验证）
2. **文档管理**（弹窗形式：上传区域 + 文档列表 + 解析状态）
   - 文档列表：文档图标、名称、大小、切片数、状态、移除按钮
   - 文档删除需二次确认（输入文档名称验证）
3. **切片管理**（每片一张 article 卡片 + 编辑 / 删除 + 分页）

#### 4.3.3 文档导入

- **支持格式**：`.md` / `.txt` / `.pdf` / `.docx` / `.doc`（P0） / `.xlsx` / `.pptx`（P1）
- **导入流程**：选择文件 → 解析 → 编译为 OKF Markdown → 存入 `data/wiki/` → 向量化到 ChromaDB
- **导入成功**：Toast 提示 + 更新知识列表
- **PDF 处理**：小量用 OKF 编译（75-92% 准确率），大量引导用户走 RAGFlow（P1）

#### 4.3.4 召回测试

- 输入测试 query → 显示 Top-K 命中 chunk + 分数 + 来源
- 区分 L1 关键词命中 / L2 向量命中 / 双命中
- 双命中条目 score 高于单命中（融合策略：`final_score = max(l1_score, l2_score) + 0.1 * min(l1_score, l2_score)`）

#### 4.3.5 知识库可视化（对齐原 SCAI）

- 切片可视化（article 卡片）
- 来源标注（原始文件路径 + 行号）
- 编辑 / 删除单个 chunk（不影响 raw 原文）

### 4.4 智能体历史模块（从智能体卡片进入）

#### 4.4.1 历史对话页面

- **入口**：从智能体卡片点击进入
- **页面结构**：
  - 顶部：返回按钮 + 智能体头像 + 名称
  - 左侧：会话列表（按时间倒序）+ 会话标题（自动生成）+ 搜索框
  - 右侧：消息流（当前选中会话）

#### 4.4.2 消息气泡设计

- **用户消息**：右对齐，无 AIGC 标识
- **AI 消息**：
  - 流式打字机效果（首字符 <500ms）
  - 完成后显示**绿色 AIGC 徽标**（符合 7 月 15 日法规）
  - 元数据卡片：人设名 / RAG 命中数 / Tool Calls 列表 / 模型名 / token 数
  - **👍/👎 按钮**（隐式反馈采集）
  - 点击元数据中的 RAG 命中条目 → 弹出该 chunk 详情
  - 点击 Tool Calls → 弹出工具调用参数与返回值

#### 4.4.3 记忆条目元数据

- AI 回复完成后，元数据卡片显示「本次用到的记忆条目」
- 用户可点击记忆条目查看 / 编辑 / 删除（参考 Claude CLAUDE.md）

### 4.5 设置模块（Tab 3）

#### 4.5.1 左侧导航结构

设置页采用左侧导航 + 右侧内容区的布局：

| 导航项 | 内容 |
|--------|------|
| **LLM 管理** | 服务商列表 + 新增/编辑/删除服务商 |
| **渠道连接** | WCF 连接状态 + 公众号云端状态 |
| **激活** | 试用期进度 + 扫码激活入口 |
| **主题** | 浅色 / 深色切换 |
| **关于** | 版本号 / 项目信息 |

#### 4.5.2 LLM 管理

- **服务商列表**：显示已配置的所有服务商
- **新增服务商**：弹窗填写（服务商名称 / API 接口地址 / API 密钥 / 模型名称）
- **服务商管理**：编辑 / 删除
- **全中文术语**：服务商、API 接口地址、API 密钥、模型名称

#### 4.5.3 渠道连接（全局状态管理）

**微信（WCF）**：
- 连接状态：已连接 / 未连接
- 详情信息：微信版本、WCF 版本、端口、登录账号、好友数、群聊数、最后心跳
- 操作按钮：测试通道、断开重连、查看日志

**公众号云端**：
- 配置状态：已配置 / 未配置
- 详情信息：AppID、云端部署状态、回调 URL
- 操作按钮：配置云端、测试回调、查看状态

#### 4.5.4 激活（先试用后付费）

**试用中状态**：
- 试用进度条（如 30%，15/50 次）
- 对话次数统计
- 提示：完成配置后即可开始对话

**已激活状态**：
- 激活码、机器码、激活时间
- 永久离线可用

**激活操作**：
- 扫码激活按钮（¥199）
- 引导帮助链接

#### 4.5.5 主题与关于

- **主题切换**：浅色 / 深色
- **关于**：版本号、项目主页、License 信息

### 4.6 扩展能力模块（智能体配置弹窗子 Tab）

- **插件卡片网格**（借鉴小智）
- 每个插件卡片：图标 / 名称 / 简介 / 启用开关 / 参数配置按钮
- MVP P0 内置插件：
  - **RAG 知识库插件**（默认启用，调用 LocalOKFAdapter）
  - **联网搜索插件**（默认禁用，需配置搜索 API）
  - **天气查询插件**（默认禁用，演示用）
- MVP P1 预留 MCP Server 接入

### 4.7 首启向导

**2 步流程**（强制首次启动执行）：

1. **欢迎页**：产品介绍（「欢迎使用阿凡达AI。本工具帮你创建一个懂你的数字分身，所有数据存储在本地，仅激活时联网，永久保护你的数据主权。」）→ 点击「下一步」
2. **配置 LLM**：选择服务商（DeepSeek/豆包/通义千问/智谱 GLM/OpenAI）→ 填写 API 接口地址 → 填写 API 密钥 → 填写模型名称 → 点击「完成，进入主界面」→ **自动跳转到「设置 → 渠道连接」**

> **设计理念**：
> - 仅 2 步，减少首次使用的心理负担
> - 去掉了开源声明、商业模式等冗余信息
> - 进入后直接跳到「渠道连接」，引导用户完成微信/公众号连接，这是核心功能的前提
> - 全中文术语，降低理解门槛

### 4.8 激活流程

#### 4.8.1 先试用后付费模式

```
1. 用户完成 LLM 配置 → 进入主界面 → 默认进入试用期
2. 试用期内可免费使用 50 次对话（所有功能可用）
3. 设置页「激活」模块显示试用进度（如 15/50 次）
4. 达到上限后弹出激活引导 → 扫码付款
5. 付款成功 → 自动激活 → 绑定机器码 → 永久离线可用
```

#### 4.8.2 扫码激活详细流程

```
1. 用户点「扫码激活」按钮（设置 Tab → 激活）
2. 软件生成机器码 + 调虎皮椒 API 创建订单 → 显示支付二维码
3. 软件每 2 秒轮询订单状态（QTimer + HTTP 请求）
4. 用户扫码付款（微信/支付宝）
5. 虎皮椒检测到付款 → API 返回「已支付 + 激活码」
6. 软件拿到激活码 → 本地签名验证 + 绑定机器码 → 写 license.dat
7. 弹「激活成功」→ 永久离线可用
```

**试用期 vs 已激活对比**：
| 功能 | 试用期 | 已激活 |
|------|--------|--------|
| LLM 配置 | ✅ 可用 | ✅ 可用 |
| 人设创建 | ✅ 可用 | ✅ 可用 |
| 知识库导入 | ✅ 可用 | ✅ 可用 |
| 对话 | ✅ 50 次（总计） | ✅ 不限 |
| 渠道连接 | ✅ 可用 | ✅ 可用 |
| 历史导出 | ⚠️ 限最近 7 天 | ✅ 全部 |
| 启动提示 | 黄色试用进度条 | 无 |

---

## 5. 技术架构

### 5.1 架构借鉴策略

基于 [[xiaozhi-vs-scai-comparison]] 的逐项判断：

| 类别 | 项目数 | 内容 |
|------|--------|------|
| **全盘借鉴小智** | 5 项 | 插件系统 / 智能体数据模型 / 多模型配置 / 记忆机制 / 会话标题生成 |
| **借鉴思想保留 SCAI 内核** | 1 项 | 知识库 RAG（借鉴适配器架构，保留 SCAI 混合检索内核） |
| **保留 SCAI** | 3 项 | 配置管理（双层热加载）/ 降级策略 / 消息处理链路（去掉 ASR/TTS） |
| **不借鉴** | 2 项 | WebSocket 服务端 / Java 后端（桌面端不需要） |

**核心判断**：SCAI 的**算法层**（混合检索、降级策略）比小智更透明可控，不需要推翻；SCAI 的**架构封装层**（人设字段散落、无插件系统、检索管理耦合）确实"太理想化"了，应按小智的成熟设计来搭。换句话说：**SCAI 的"脑子"（算法）可以留，"骨架"（架构）要按小智的来搭**。

### 5.2 整体架构图

```
┌──────────────────────────────────────────────────────────┐
│                    PyQt6 桌面 exe                          │
│  ┌──────────────────────────────────────────────────┐    │
│  │  UI 层（PyQt6 widgets + QSS 主题）                 │    │
│  │  智能体 Tab / 知识库 Tab / 历史 Tab / 设置 Tab     │    │
│  └──────────────────────────────────────────────────┘    │
│                          ↓                                │
│  ┌──────────────────────────────────────────────────┐    │
│  │  业务层                                            │    │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐       │    │
│  │  │ 智能体    │  │ 消息处理  │  │ 自进化    │       │    │
│  │  │ Service  │  │ Pipeline │  │ Engine    │       │    │
│  │  └──────────┘  └──────────┘  └──────────┘       │    │
│  └──────────────────────────────────────────────────┘    │
│                          ↓                                │
│  ┌──────────────────────────────────────────────────┐    │
│  │  能力层（6 组件）                                  │    │
│  │  LLM Provider │ Context │ Prompt │ 知识库双路线    │    │
│  │  插件系统（@register_function） │ 记忆驱动自进化    │    │
│  └──────────────────────────────────────────────────┘    │
│                          ↓                                │
│  ┌──────────────────────────────────────────────────┐    │
│  │  数据层                                            │    │
│  │  SQLite（ai_agent/sys_config/messages/user_memory）│   │
│  │  ChromaDB（向量检索）  OKF Markdown（知识本体）     │    │
│  │  license.dat（激活）  config.json（用户配置）       │    │
│  └──────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────┘
              ↓ 仅激活时联网              ↓ 用户配置 AI 服务商
        虎皮椒 V3 + 激活后端          用户的 LLM API Key
```

### 5.3 智能体数据模型（借鉴小智）

#### 5.3.1 `ai_agent` 表（人设单表，对应 4 Tab）

| 字段 | 类型 | 说明 | 对应 Tab |
|------|------|------|---------|
| `id` | TEXT PK | UUID | — |
| `name` | TEXT | 人设名 | 智能体 |
| `avatar` | TEXT | 头像路径 | 智能体 |
| `systemPrompt` | TEXT | 5 分区模板 systemPrompt | 智能体 |
| `language` | TEXT | 输出语言 | 智能体 |
| `enableEmoji` | INT | 是否启用 emoji | 智能体 |
| `llmModelId` | TEXT FK | 引用 `sys_config.id` | 智能体 |
| `slmModelId` | TEXT FK | 引用 `sys_config.id`（小模型用于会话标题） | 智能体 |
| `memMode` | TEXT | mem_local_short / powermem / nomem | 智能体 |
| `summaryMemory` | INT | 是否启用跨会话总结 | 智能体 |
| `aigcEnabled` | INT | 是否显示 AIGC 标识（渠道配置） | 智能体-渠道 |
| `temperature` | REAL | LLM 温度 | 智能体-高级 |
| `maxTokens` | INT | 最大 token 数 | 智能体-高级 |
| `safetyShield` | TEXT JSON | PII/注入/敏感词配置 | 智能体-高级 |
| `created_at` | DATETIME | 创建时间 | — |
| `updated_at` | DATETIME | 更新时间 | — |

#### 5.3.2 `sys_config` 表（AI 服务商配置，借鉴小智）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT PK | UUID |
| `name` | TEXT | 配置名（如"我的 DeepSeek"） |
| `provider` | TEXT | deepseek/doubao/qwen/zhipu/custom |
| `apiKey` | TEXT | DPAPI 加密后的密钥 |
| `apiUrl` | TEXT | API 接口地址 |
| `model` | TEXT | 模型名称（如 deepseek-chat） |
| `isDefault` | INT | 是否默认 |
| `created_at` | DATETIME | — |

#### 5.3.3 `messages` 表（历史消息）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT PK | UUID |
| `session_id` | TEXT FK | 会话 ID |
| `agent_id` | TEXT FK | 智能体 ID |
| `role` | TEXT | user/assistant/system |
| `content` | TEXT | 消息内容 |
| `meta` | TEXT JSON | RAG 命中/Tool Calls/模型名/token 数 |
| `feedback` | INT | 1=赞，-1=踩，0=未评价 |
| `created_at` | DATETIME | — |

#### 5.3.4 `user_memory` 表（L2 用户画像记忆，新增）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT PK | UUID |
| `agent_id` | TEXT FK | 智能体 ID |
| `memory_type` | TEXT | preference/fact/event/insight |
| `content` | TEXT | 记忆内容 |
| `weight` | REAL | 权重（被赞 +1，被踩 -1） |
| `source_session_id` | TEXT FK | 来源会话 |
| `created_at` | DATETIME | — |

#### 5.3.5 `sessions` 表（会话）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT PK | UUID |
| `agent_id` | TEXT FK | 智能体 ID |
| `title` | TEXT | 自动生成标题（slmModelId） |
| `summary` | TEXT | summaryMemory 总结 |
| `created_at` | DATETIME | — |
| `updated_at` | DATETIME | — |

#### 5.3.6 `channel_connection` 表（渠道连接状态）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT PK | UUID |
| `channel_type` | TEXT | wcf / oa_cloud |
| `status` | TEXT | connected / disconnected / error |
| `last_heartbeat` | DATETIME | 最后心跳时间 |
| `version` | TEXT | 版本号（如微信版本） |
| `connected_friends` | INT | 已接入好友数 |
| `connected_groups` | INT | 已接入群聊数 |
| `config` | TEXT JSON | 渠道特定配置（端口/密钥等） |
| `created_at` | DATETIME | — |
| `updated_at` | DATETIME | — |

#### 5.3.7 `channel_binding` 表（智能体渠道绑定）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT PK | UUID |
| `agent_id` | TEXT FK | 智能体 ID |
| `contact_id` | TEXT | 好友/群聊唯一标识（wxid 等） |
| `contact_name` | TEXT | 好友备注或群名 |
| `contact_type` | TEXT | friend / group |
| `enabled` | INT | 是否启用该绑定 |
| `remark` | TEXT | 备注信息 |
| `created_at` | DATETIME | — |
| `updated_at` | DATETIME | — |

### 5.4 LLM Provider Pattern（借鉴小智）

- **目录式组织**：`src/avatar_ai/providers/llm/{openai,deepseek,qwen,zhipu,ollama}/`
- **工厂模式动态 import**：启动时按 `sys_config.provider` 动态加载 Provider 类
- **Provider 基类**：定义统一接口（`chat_complete` / `stream_chat_complete` / `embed`)
- **三层配置优先级**：`config.json`（默认）→ `data/.config.json`（本地覆盖）→ `sys_config` 表（最高）
- **共享策略**：LLM Provider 共享单例（节约资源）

### 5.5 知识库架构（双路线 + 适配器）

```
KnowledgeBaseAdapter（抽象接口）
  ├─ ingest(file_path) → 编译为 OKF Markdown
  ├─ query(text, top_k) → 返回 List[RetrievalResult]
  ├─ list_documents() → 文档列表
  ├─ list_chunks(doc_id) → 切片列表
  ├─ test_recall(query) → 召回测试
  └─ delete_chunk(chunk_id) → 删除切片
        │
        ├─ LocalOKFAdapter（默认，P0）
        │    ├─ L1 知识本体：OKF Markdown + raw/ + wiki/ + index.md + log.md
        │    ├─ L2 检索加速：ChromaDB（<100 页可降级为 grep）
        │    └─ 混合检索（保留 SCAI 内核）：
        │         ├─ L1 关键词检索（KarpathyWikiReader）
        │         ├─ L2 向量检索（ChromaDB）
        │         └─ 融合排序：
        │              └─ final_score = w_vector * vector_score + w_keyword * keyword_score
        │                 （默认 w_vector=0.6, w_keyword=0.4，config 可调）
        │
        └─ RAGFlowAdapter（可选，P1）
             └─ 调用外部 RAGFlow API
```

**降级策略**（保留 SCAI）：
- ChromaDB 不可用（`_embed_fn=None`）→ 降级为纯关键词检索，`weight_keyword=1.0`
- KarpathyWikiReader 不可用（KB 目录未找到）→ 降级为纯向量检索
- 双命中条目 score 高于单命中（融合策略：`max(l1, l2) + 0.1 * min(l1, l2)`）

### 5.6 插件系统架构（全盘借鉴小智）

#### 5.6.1 `@register_function` 装饰器

```python
@register_function(
    name="rag_search",
    description="在用户知识库中检索相关信息",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "检索查询"}
        },
        "required": ["query"]
    },
    action=Action.REQLLM  # 工具执行后需要 LLM 再生成回复
)
def rag_search(query: str) -> ActionResponse:
    # 调用 KnowledgeBaseAdapter.query()
    return ActionResponse(result=results)
```

#### 5.6.2 Action 响应设计（借鉴小智）

| Action 类型 | 含义 | 示例 |
|------------|------|------|
| `Action.REQLLM` | 工具执行后需要 LLM 再生成回复 | RAG 检索、联网搜索 |
| `Action.ACTION` | 直接执行动作，无需 LLM 再生成 | 设置提醒、发邮件 |

#### 5.6.3 MVP P0 内置插件

| 插件名 | Action 类型 | 默认状态 | 说明 |
|--------|------------|---------|------|
| `rag_search` | REQLLM | 启用 | 调用 LocalOKFAdapter |
| `web_search` | REQLLM | 禁用 | 联网搜索（需配置 API） |
| `weather` | REQLLM | 禁用 | 天气查询（演示用） |
| `set_reminder` | ACTION | 禁用 | 设置提醒（P1） |

### 5.7 消息处理链路（保留 SCAI，去掉 ASR/TTS）

```
用户输入文本
  ↓
[安全壳] PII 检测 / Prompt 注入检测 / 敏感词过滤
  ↓
[Context 装配] L1 工作记忆 + L2 用户画像记忆 + summaryMemory
  ↓
[Prompt 装配] 5 分区模板 + Jinja2 插值
  ↓
[LLM 调用] 带 functions schema
  ↓
LLM 决定是否调用工具
  ↓
[functionHandler] 解析 → 执行插件 → ActionResponse
  ├─ Action.REQLLM → 结果回传 LLM 再生成回复
  └─ Action.ACTION → 直接执行动作
  ↓
[安全壳-输出侧] AIGC 标识 / 广告拦截
  ↓
[流式输出] SSE 流式逐字追加（首字符 <500ms）
  ↓
[完成] 添加 AIGC 标识 + 元数据 + 👍/👎 按钮
  ↓
[记忆写入] L2 用户画像记忆 + summaryMemory 更新
  ↓
[隐式反馈] 用户 👍/👎 → 更新记忆权重（Self-Refine）
```

### 5.8 降级策略（保留 SCAI）

**三层兜底 + degraded_details 机制**：

| 层级 | 触发条件 | 降级行为 | 用户感知 |
|------|---------|---------|---------|
| L1 | LLM 正常 | 全功能 | 无 |
| L2 | LLM 超时 / 429 / API Key 失效 | 降级为纯本地知识库检索 + 模板回复 | 黄色降级横幅 |
| L3 | LLM + 知识库均不可用 | 仅返回预设兜底文案 | 红色降级横幅 |

**降级详情卡片**（degraded_details）：
- 显示当前降级原因
- 显示降级路径（哪些组件降级了）
- 提供「重试」按钮

### 5.9 数据存储（保留 SCAI 本地化原则）

| 数据 | 存储位置 | 加密 |
|------|---------|------|
| 配置 | `%APPDATA%\AvatarAI\config.json` | API Key 用 DPAPI 机器绑定加密 |
| 数据库 | `%APPDATA%\AvatarAI\data.db` | SQLite，无加密（本地数据） |
| 历史消息 | `%APPDATA%\AvatarAI\messages.db` | SQLite，无加密 |
| 知识本体 | `%APPDATA%\AvatarAI\data\wiki\` | OKF Markdown |
| 向量库 | `%APPDATA%\AvatarAI\data\chromadb\` | ChromaDB |
| 激活信息 | `%APPDATA%\AvatarAI\license.dat` | 签名验证 + 机器码绑定 |
| 日志 | `%APPDATA%\AvatarAI\logs\` | 明文（便于排查） |

**路径约束**：所有文件路径避免中文字符和空格。

### 5.10 嵌入模型

- **MVP P0**：`BAAI/bge-small-zh-v1.5`（轻量，CPU 可跑）
- **语义分割**：512 字符
- **降级**：sentence_transformers 未打包进 EXE → ChromaDB 降级为纯关键词检索（MVP 体积与功能的权衡，符合降级策略）

---

## 6. 商业模式与激活机制

### 6.1 商业模式：一次买断 + 先试用后付费

- **产品本体**：一次买断（虎皮椒收款 ¥199）
- **先试用**：用户完成 LLM 配置后即可免费试用 50 次对话，体验完整功能
- **AI 成本自担**：用户自带 LLM API Key，AI 调用成本由用户自行承担
- **不做积分制**：一次买断模式下积分制需要后端扣费增加复杂度
- **不做订阅制**：对数字分身场景过重
- **一次买断**的好处：用户买了就是自己的，无续费压力，符合"数字分身"的长期陪伴属性

### 6.2 付费平台：虎皮椒 V3

**选型对比**：

| 平台 | 费率 | 个人可用 | 轮询查询 | 适用场景 |
|------|------|---------|---------|---------|
| **虎皮椒 V3** | 1.6-2.6% | ✅ | ✅ | 个人卖家的支付 API 网关 |
| 面包多 | 类似 | ✅ | ❌ | 自动发货但 API 偏"卖商品"逻辑 |

**选虎皮椒的理由**：
- 本质是"个人卖家的支付 API 网关"
- 专门解决"个人想收钱但没有支付商户号"的问题
- 支持轮询查询订单状态（关键能力）

### 6.3 激活机制：先试用后付费 + 扫码激活

#### 6.3.1 试用期机制

- **触发时机**：用户完成首启向导（2 步）→ 自动进入试用期
- **试用期额度**：50 次对话（所有功能完整可用）
- **试用进度展示**：设置页「激活」模块显示进度条（如 15/50 次）
- **达上限后**：弹出激活引导，提示用户扫码付款

#### 6.3.2 扫码激活流程

```
1. 用户点「扫码激活」按钮（设置 Tab → 激活）
2. 软件生成机器码 + 调虎皮椒 API 创建订单 → 显示支付二维码
3. 软件每 2 秒轮询订单状态（QTimer + HTTP 请求）
4. 用户扫码付款（微信/支付宝）
5. 虎皮椒检测到付款 → API 返回「已支付 + 激活码」
6. 软件拿到激活码 → 本地签名验证 + 绑定机器码 → 写 license.dat
7. 弹「激活成功」→ 永久离线可用
```

#### 6.3.3 选轮询不选 webhook 的理由

- **跨平台稳定**：webhook 要开本地端口，Windows 防火墙会拦，用户还要点"允许访问"很烦
- **实现简单**：一个 QTimer + HTTP 请求
- **用户感知无延迟**：2 秒轮询对用户感知几乎无延迟（用户付完钱 2 秒内激活）
- **不需要用户做任何额外操作**

#### 6.3.4 激活后端

用户有云端服务器，可用于激活后端。

**后端技术栈**：Flask + 虎皮椒 Webhook + 激活码生成

**4 个接口**：

| 接口 | 路径 | 说明 |
|------|------|------|
| 创建订单 | `POST /api/order/create` | 调虎皮椒 API 创建订单 |
| 查询订单 | `GET /api/order/query?order_id=xxx` | 返回订单状态（含激活码） |
| 验证激活码 | `POST /api/license/verify` | 验证激活码签名 |
| 记录激活 | `POST /api/license/activate` | 记录激活码 + 机器码绑定 |

**个体户建议**：建议注册个体工商户（1-3 天），降低支付风控风险。

### 6.4 试用期 vs 已激活状态对比

| 功能 | 试用期 | 已激活 |
|------|--------|--------|
| LLM 配置 | ✅ 可用 | ✅ 可用 |
| 人设创建 | ✅ 可用 | ✅ 可用 |
| 知识库导入 | ✅ 可用 | ✅ 可用 |
| 渠道连接 | ✅ 可用 | ✅ 可用 |
| 对话 | ✅ 50 次（总计） | ✅ 不限 |
| 历史导出 | ⚠️ 限最近 7 天 | ✅ 全部 |
| 启动提示 | 黄色试用进度条 | 无 |

---

## 7. MVP 范围定义

### 7.1 MVP 分级原则

- **P0（必做）**：核心闭环，缺失则产品不成立
- **P1（应做）**：差异化能力，缺失则产品无竞争力
- **P2（可做）**：增强体验，缺失可后期补

### 7.2 P0 范围（核心闭环）

| 模块 | P0 内容 |
|------|---------|
| **首启向导** | 2 步流程（欢迎页 → 配置 LLM：服务商/API 接口地址/API 密钥/模型名称）→ 完成后自动跳转「设置 → 渠道连接」 |
| **智能体 Tab** | 卡片列表 + 新建/编辑（4 Tab 配置弹窗）+ 更多菜单（重命名/删除）+ 删除二次确认（需输入名称）+ 渠道配置弹窗（好友/群聊 Tab + AIGC 开关） |
| **知识库 Tab** | 知识库列表 + 新建/编辑/删除（含二次确认）+ 文档管理弹窗（上传/删除）+ 文档导入（.md/.txt/.pdf/.docx）+ 解析进度 + 召回测试 |
| **智能体历史** | 从智能体卡片进入 → 会话列表 + 消息流 + 会话标题自动生成 + 打字机效果 + AIGC 徽标 + 👍/👎 |
| **设置 Tab** | 左侧导航 + LLM 管理（服务商新增/列表）+ 渠道连接（WCF/公众号状态）+ 激活（试用期/扫码激活）+ 主题切换 + 关于 |
| **渠道连接（设置页）** | WCF 连接状态/详情/操作（测试/断开/日志）+ 公众号云端配置状态/操作 |
| **激活流程** | 先试用后付费（50 次对话）+ 试用进度条 + 扫码激活 + 2 秒轮询 + 自动激活 + 机器码绑定 |
| **扩展能力** | 插件卡片网格 + RAG 插件 + 联网搜索插件 + 天气插件 |
| **降级策略** | 三层兜底 + degraded_details + 黄色降级横幅 |
| **安全壳** | PII 检测 / Prompt 注入检测 / 敏感词过滤 / 广告拦截 |
| **数据存储** | SQLite + ChromaDB + OKF Markdown + DPAPI 加密 |

### 7.3 P1 范围（差异化能力）

| 模块 | P1 内容 |
|------|---------|
| **RAGFlowAdapter** | 接入外部 RAGFlow，大量文档检索 |
| **MCP Server 接入** | 知识库 L3 接入协议（ingest/query/lint） |
| **Dreaming 后台进程** | 应用空闲时总结近期对话，抽取用户洞察写入 L2 |
| **Self-RAG** | 检索后自评是否够用，不够用触发追问/重检索 |
| **CRAG 修正** | 检索质量差时自动重写查询或降级 |
| **更多文档格式** | .xlsx / .pptx |
| **更多内置插件** | set_reminder / send_email / calendar |

### 7.4 P2 范围（增强体验）

| 模块 | P2 内容 |
|------|---------|
| **知识图谱自动构建** | 从对话抽取实体-关系，存为 Markdown 双向链接 |
| **技能库累积** | Voyager 思想，AI 学会新工具调用模式后存入知识库 |
| **Reflexion 反思机制** | 失败对话触发反思，生成"教训笔记" |
| **公众号云端版** | 微信公众号云端入口（后续阶段） |
| **多分身协作** | 多 Agent 思想内化，单分身内化 Checker 角色 |

### 7.5 关键链路验收清单

MVP 完成后必须通过以下关键链路验收：

#### 7.5.1 首启链路
- [ ] 安装 exe → 启动 → 首启向导弹出（2 步流程）
- [ ] 完成 2 步向导（欢迎页 → 配置 LLM）→ 自动跳转到「设置 → 渠道连接」
- [ ] LLM 配置保存成功 → 服务商列表显示已配置
- [ ] 降级横幅：LLM Key 未配置时显示黄色提示

#### 7.5.2 对话链路
- [ ] 智能体 Tab → 选人设 → 进入对话
- [ ] 输入消息 → 流式打字机回复（首字符 <500ms）
- [ ] 完成后显示绿色 AIGC 徽标 + 元数据
- [ ] 元数据点击可展开 RAG 命中 / Tool Calls 详情
- [ ] 👍/👎 可点击 → 影响记忆权重

#### 7.5.3 知识库链路
- [ ] 知识库 Tab → 上传 .md 文件 → 编译成功
- [ ] Toast 提示 + 文档列表更新
- [ ] 召回测试 → 输入 query → 显示 Top-K 命中
- [ ] 切片管理 → 查看 article 卡片 → 编辑/删除

#### 7.5.4 激活链路（先试用后付费）
- [ ] 试用期：完成配置后可开始 50 次对话试用
- [ ] 试用进度显示：设置页显示试用进度条（如 15/50 次）
- [ ] 达上限后：弹出激活引导，提示扫码付款
- [ ] 扫码激活：设置 Tab → 激活 → 弹支付二维码
- [ ] 扫码付款 → 2 秒轮询 → 自动激活成功
- [ ] 已激活状态：显示激活码、机器码、激活时间
- [ ] 关闭网络 → 重启应用 → 仍可正常使用（永久离线可用）

#### 7.5.5 降级链路
- [ ] LLM API Key 故意填错 → 启动时显示黄色降级横幅
- [ ] 横幅显示降级原因 + 重试按钮
- [ ] 对话时降级为模板回复

#### 7.5.6 渠道连接链路（设置页）
- [ ] WCF 连接状态：显示已连接/未连接状态
- [ ] WCF 详情：微信版本、WCF版本、端口、登录账号、好友/群聊数量
- [ ] WCF 操作：测试通道、断开重连、查看日志
- [ ] 公众号云端：显示配置状态（AppID、云端部署、回调URL）
- [ ] 公众号操作：配置云端、测试回调、查看状态

#### 7.5.7 智能体渠道配置链路
- [ ] 智能体卡片 → 点击更多 → 渠道配置
- [ ] 渠道配置弹窗：显示好友/群聊列表（Tab 切换）
- [ ] 好友管理：勾选启用/禁用、AIGC 标识开关
- [ ] 群聊管理：勾选启用/禁用
- [ ] 保存配置后智能体卡片显示已接入好友数量

#### 7.5.8 智能体管理链路
- [ ] 新建智能体：填写配置 → 保存 → 卡片显示
- [ ] 编辑智能体：点击卡片 → 配置弹窗 → 4 Tab 表单
- [ ] 重命名：点击更多 → 重命名 → 弹窗输入新名称
- [ ] 删除智能体：点击更多 → 删除 → 二次确认弹窗（需输入名称）
- [ ] 二次确认：红色警示区 + 输入名称验证 + 确认按钮

#### 7.5.9 主题切换链路
- [ ] 设置 → 主题切换 → 所有页面同步刷新
- [ ] 浅色/深色 token 完整（无白洞/不可读问题）

---

## 8. 非功能性需求

### 8.1 数据主权

- **数据全本地存储**：`%APPDATA%\AvatarAI\` 目录
- **仅激活时联网**：激活成功后永久离线可用
- **BYOK 时联网**：调用用户自有 LLM API
- **不上传任何用户数据到阿凡达服务器**

### 8.2 安全壳（默认全开）

| 能力 | 默认状态 | 行为 |
|------|---------|------|
| PII 检测 | 开启 | 检测到个人隐私信息（身份证/手机号）→ warn_pii 提示 |
| Prompt 注入检测 | 开启 | 检测到注入攻击 → silent_drop 静默丢弃 |
| 敏感词过滤 | 开启 | 命中敏感词 → 替换为 `[已屏蔽]` |
| 广告拦截 | 开启 | 命中黑名单 → 加入 7 天屏蔽名单 |

### 8.3 AIGC 标识

- 所有 AI 生成内容必须显示**绿色 AIGC 徽标**
- 符合 7 月 15 日法规的强制性标识
- 元数据卡片显示：人设名 / RAG 命中数 / Tool Calls / 模型名 / token 数

### 8.4 性能

| 指标 | 目标 |
|------|------|
| 首字符响应时间 | <500ms |
| 知识库导入（<10 页文档） | <30s |
| ChromaDB 向量检索 | <200ms |
| 关键词检索 | <50ms |
| 应用冷启动 | <3s |
| 内存占用（空闲） | <300MB |

### 8.5 兼容性

- **操作系统**：Windows 10 / 11（64 位）
- **CPU 架构**：x64
- **依赖**：无需用户安装 Python / 任何运行时
- **打包**：PyInstaller 单 exe + `_internal/` 目录

### 8.6 国际化

- **MVP**：仅中文
- **P1**：英文（对齐小智）
- **不在 MVP 范围**：其他语言

---

## 9. 验收标准

### 9.1 功能验收

详见 7.5 关键链路验收清单。

### 9.2 测试策略

- **测试时机**：MVP 全部完成后进行，**不进行阶段性测试**（保留 SCAI 经验）
- **测试类型**：单元测试 + 集成测试 + UI 测试 + 端到端测试
- **测试覆盖**：核心链路 100% 覆盖，非核心链路 80% 覆盖

### 9.3 发布标准

- [ ] 7.5 关键链路全部通过（含首启/对话/知识库/激活/降级/渠道/智能体配置/主题）
- [ ] 单元测试覆盖率 ≥ 80%
- [ ] 无 P0 级别 Bug
- [ ] P1 级别 Bug ≤ 5 个
- [ ] 性能指标达标（8.4）
- [ ] 兼容性测试通过（Windows 10 / 11）
- [ ] 安全壳全部默认开启
- [ ] AIGC 标识符合法规
- [ ] 激活流程端到端通过（含试用期 → 扫码激活 → 永久可用）
- [ ] 试用期限制生效（50 次对话上限）
- [ ] 渠道连接状态正确显示（WCF/公众号）
- [ ] 智能体渠道配置功能正常（好友/群聊管理）
- [ ] 智能体管理功能正常（新建/编辑/重命名/删除）
- [ ] 删除二次确认弹窗功能正常
- [ ] LLM 配置全中文化

---

## 10. 风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| sentence_transformers 未打包进 EXE | ChromaDB 向量检索降级为纯关键词 | MVP 接受降级；P1 尝试打包 |
| 虎皮椒支付风控 | 激活流程失败 | 建议用户注册个体工商户 |
| PDF 编译准确率低（75-92%） | 知识库导入质量差 | 小量用 OKF，大量引导走 RAGFlow（P1） |
| LLM API 不稳定 | 对话失败 | 三层降级策略 + degraded_details |
| 用户没有 LLM API Key | 无法使用 | 首启向导引导申请（提供文档） |
| 机器码绑定导致换机无法用 | 用户投诉 | 提供「转移激活」流程（人工） |

---

## 11. 附录

### 11.1 知识库沉淀页索引

| 页面 | 路径 | 说明 |
|------|------|------|
| 项目设定 | `wiki/architecture/avatar-ai-project-setup.md` | 商业决策与项目设定 |
| 6 组件理论 | `wiki/concepts/avatar-ai-theory-framework.md` | 产品方法论 |
| 小智架构调研 | `wiki/architecture/xiaozhi-architecture-deep-dive.md` | 借鉴基础 |
| 架构对比 | `wiki/architecture/xiaozhi-vs-scai-comparison.md` | 借鉴策略 |
| 知识库双路线 | `wiki/architecture/ragflow-vs-okf-dual-route.md` | 知识库架构 |
| 自我进化路线 | `wiki/concepts/ai-self-evolution.md` | 自进化方案 |

### 11.2 术语表

| 术语 | 含义 |
|------|------|
| BYOK | Bring Your Own Key，用户自带 LLM API Key |
| OKF | Objective Knowledge Fact，知识本体格式 |
| RAG | Retrieval-Augmented Generation，检索增强生成 |
| MCP | Model Context Protocol，插件系统协议 |
| SAGE | Self-Adaptive Genetic Evolution，自进化综述框架 |
| MemGPT | 分层记忆系统思想 |
| Self-RAG | AI 自己判断是否需要检索 |
| CRAG | Corrective RAG，AI 自己修正检索结果 |
| Constitutional AI | 宪法 AI，AI 自评 + 宪法约束 |
| DPAPI | Windows Data Protection API，机器绑定加密 |
| WCF | WeChat Framework，微信桌面端框架 |
| BadCase | 异常案例，自进化中的熔断机制 |
| summaryMemory | 跨会话上下文压缩（不是知识库） |

### 11.3 修订历史

| 版本 | 日期 | 修订内容 | 作者 |
|------|------|---------|------|
| v1.0 | 2026-08-19 | 初版，基于知识库沉淀起草 | 产品团队 |
| v1.1 | 2026-08-21 | 基于原型反推更新：首启向导改为2步、导航改为3Tab、LLM术语中文化、渠道连接职责拆分、激活改为先试后付、新增验收链路、完善功能描述 | 产品团队 |

---

**文档结束**
