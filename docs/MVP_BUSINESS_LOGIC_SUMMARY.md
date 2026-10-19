# 影分身AI · MVP 业务逻辑汇总（UI/UX 对齐版）

> **用途**：交付 UI/UX 设计师，对比 HTML 原型阶段的业务场景与操作逻辑要求，找出「外观做了但逻辑没打通」的差距点。
> 
> **阅读方式**：先看「用户第一天 8 步剧本」了解全局流程，再看 L1-L5 五条主线的详细拆解。每条主线都标注了：解决什么场景、前台怎么操作、后台怎么跑、数据存哪、易错断点。

---

## 一、用户第一天完整使用剧本（8 步串联）

| 步骤 | 用户操作 | 对应主线 | 预期结果 | 易错断点 |
|---|---|---|---|---|
| 1 | 双击 SCAI.exe 启动 | 启动入口 | 不崩溃弹窗，出现首启向导 | sys.stderr/stdout=None 三层兜底 |
| 2 | Step 1 填 LLM API Key + Model → 点「测试连接」 | L1 | Toast「连接成功 ✓」或具体错误 | F-1.1 假按钮：必须真实发 HTTP |
| 3 | 点「下一步」→ Step 2 确认人设 → 点「开始使用」 | L1+L4 | 进入主窗口，标题栏显示人设名 | F-1.2 空校验；L4 热更新内存 |
| 4 | 人设 Tab → 改人设 → 保存 | L4 | Toast 提示 + 标题栏立刻变 + 下句对话语气变 | 内存先写再写盘 |
| 5 | 对话 Tab → 输入「你好」→ 回车 | L2 | 打字机效果 + AIGC 徽标 + 元数据 | F-1.4 无 Key 友好提示；安全壳三重拦截 |
| 6 | 知识 Tab → 导入文档 | L3-A | Toast「导入成功」+ 列表异步刷新 | 失败显示具体错误；补 type frontmatter |
| 7 | 对话 Tab → 问「我们产品主打什么？」 | L3-B+L2 | AI 引用文档内容 + 元数据显示 RAG 命中数 | L1+L2 混合检索；双命中加分 |
| 8 | 关闭软件 → 再打开 | L5 | 直接进主窗口，所有数据还在 | 6 类数据写盘；bootstrap 顺序加载 |

---

## 二、L1 · 首次启动 & 配置向导

### 解决什么业务场景
用户第一次打开软件时，LLM API Key 是空的、人设是空的——软件就是个空壳。必须通过 3 步向导把「AI 引擎 + 身份设定」配进去，软件才能真正开始工作。

### 前台交互（用户看到的）

**Step 1 · AI 引擎配置页**
- 下拉选 Provider（DeepSeek / 千问 / 自定义）
- 填 Base URL（接口地址）
- 填 API Key（密钥输入框）
- 填 Model 名称（如 deepseek-chat）
- 点「测试连接」→ 看结果 Toast
- 点「下一步」→ 进入 Step 2

**Step 2 · 人设确认页**
- 显示默认人设卡片（如「产品经理小张」）
- 可编辑：名称、头像、职业标签
- 可编辑：系统提示词（人设规则）
- 点「下一步」→ 进入 Step 3

**Step 3 · 完成页**
- 显示「配置完成」欢迎语
- 展示快速上手指南
- 点「开始使用」→ 进入主窗口

### 后台逻辑（代码怎么跑）

| 步骤 | 后台处理 | 数据写入 |
|---|---|---|
| Step 1 测试连接 | `_on_test_connection()` → 校验非空 → 先存内存 → 开线程调 `AppEngine.test_llm_connection()` 真实发 HTTP → Toast 反馈 | — |
| Step 1 下一步 | `_save_llm_settings()` → `AppEngine.save_settings()` → `ConfigManager` 写 config.json | config.json |
| Step 2 保存人设 | `AppEngine.save_persona()` → 更新内存 `PersonaInjector` + 写 persona 文件 | data/persona/*.md + config.json |
| Step 3 完成 | 写 `first_run_done=true` + 自动创建示例人设和欢迎文档 | config.json + data/wiki/welcome.md |

### 易错断点

| 编号 | 问题 | 修复方式 |
|---|---|---|
| F-1.1 | 测试连接是假按钮，只检查非空不真发请求 | 新开线程调 `test_llm_connection()` 真实发 LLM 请求，Toast 显示结果 |
| F-1.2 | 下一步不校验，空 Key 也能进下一步 | API Key / Model 非空强校验 + Toast 失败提示 |

---

## 三、L2 · 对话聊天主流程（8 步流水线）

### 解决什么业务场景
用户在输入框打了一句话 → 回车发送 → 要看到 AI 回复一段话（打字机效果 + AIGC 标识 + 元数据）。中间 8 步对应「供血系统 + 神经系统 + 免疫系统 + 知识检索」的组合调度。

### 前台交互（用户看到的）
- 用户在输入框打字 → 回车 / 点发送按钮
- 用户气泡出现在右侧
- AI 回复气泡出现在左侧，逐字显示（打字机效果，首字 < 500ms）
- 回复完成后，气泡右下角显示绿色 🤖 AIGC 徽标
- 气泡下方元数据：「人设：xxx · 📚 引用 N 条知识 · 🔧 Tool: RAG」

### 后台 8 步流水线

| 步骤 | 处理模块 | 关键逻辑 |
|---|---|---|
| 1. LLM 就绪检查 | app_engine.py 最前面 | 检查 api_key 非空 + client.is_available()；不通过 → 提前返回友好提示 |
| 2. 安全壳（三重拦截） | safety/ 模块 | PII 检测（温和提醒）/ Prompt 注入（静默丢弃）/ 广告检测（3 次拉黑 7 天） |
| 3. 意图识别 | intents/ 模块 | 关键词匹配快捷指令（帮助/清空/换人设/管理群命令），命中直接返回 |
| 4. 上下文装配 | ContextAssembler | 注入人设系统提示词 + 最近 10 轮历史 + 预留 RAG 插入位 |
| 5. RAG 知识检索 | UnifiedRetriever | L1 关键词 + L2 向量并行检索 → 融合排序 → Top 3 片段（详见 L3） |
| 6. LLM 流式调用 | LLMGenerator | 组装 prompt → 发送 LLM API → SSE 逐 token yield |
| 7. 生成结束后处理 | app_engine.py | 追加 AIGC 徽标 + 元数据 + 异常 Toast |
| 8. 保存对话历史 | messages.db (SQLite) | 异步写入，不阻塞 UI |

### 数据来源
- 人设：data/persona/*.md（通过 PersonaInjector 注入）
- 历史对话：messages.db（最近 10 轮滑动窗口）
- 知识片段：data/wiki/ + data/chromadb/（RAG 检索结果）

### 易错断点

| 编号 | 问题 | 修复方式 |
|---|---|---|
| F-1.4 | 无 Key 崩溃或无提示 | Step 1 前置检查，不进流水线直接返回「去设置页配 Key」 |
| P4-1 | 安全壳误拦或漏拦 | warn_pii 温和提醒 + silent_drop 静默丢弃 |
| RAG-1 | RAG 命中 0 无降级 | ChromaDB 不可用 → 纯关键词；rag_count=0 不影响回答 |
| SSE-1 | SSE 断流/超时，气泡停一半 | yield 错误事件，前端补「回答中断，请重试」+ 记日志 |
| AIGC-1 | AIGC 法规标识缺失 | 每轮 AI 气泡右下角固定显示绿色 🤖 AIGC 徽标 |

---

## 四、L3 · 知识库导入 & RAG 生效流程

### 解决什么业务场景
用户有一堆文档（简历、产品资料、工作笔记、客户信息…），想让 AI 回答时引用这些内容。分两条支线：A 导入支线（写路径）和 B 检索支线（读路径）。

### 支线 A：知识库导入（写路径）

**前台交互：**
- 📚 知识 Tab 页
- 左侧：知识分类树（concepts / entities / architecture）
- 右侧：文档列表（标题 / 日期 / 状态）
- 点「导入文档」→ 选文件（.md / .txt / .pdf / .docx）
- 导入完成 Toast 提示 + 列表异步刷新

**后台处理：**

| 步骤 | 处理模块 | 关键逻辑 |
|---|---|---|
| A1 解析转换 | DocToWikiImporter | 按后缀路由：md/txt 直读 / pdf 用 PyPDF2 / docx 用 python-docx；补 YAML frontmatter（type/title/tags/date） |
| A2 切片+向量化 | WikiIngestPipeline | 三种模式（全量/增量/重建）；512 字符语义切片；bge-small-zh-v1.5 嵌入 768 维；写入 ChromaDB |

**数据存储：**
- 知识本体：`data/wiki/{type}/{slug}.md`（LLM Wiki 格式，Obsidian/Git 可直接打开，人类可读）
- 向量索引：`data/chromadb/`（检索加速层，可从 Markdown 重建）

**知识库目录结构：**
```
data/wiki/
├── concepts/       # 概念说明（如「RAG是什么」）
├── entities/       # 实体档案（如「公司介绍」「我的简历」）
└── architecture/   # 架构文档（如「MVP模块图」）
```

**每个知识页格式：**
```markdown
---
type: entity          # 必填：entity | concept | architecture
title: 我的简历
tags: [简历, 个人]
date: 2026-01-15
---
# 正文内容（Markdown）
```

### 支线 B：RAG 检索生效（读路径）

**触发入口：** L2 对话流水线 Step 5

**后台处理：**

| 步骤 | 处理模块 | 关键逻辑 |
|---|---|---|
| B1 双路径并行 | UnifiedRetriever.retrieve(query, limit=3) | L1 关键词 + L2 向量同时跑 |
| B2 融合排序 | Fusion 逻辑 | ① 来源去重（同内容双命中合并）② 双命中加分：max+0.1×min ③ 加权和：vec×0.6 + kw×0.4 ④ 权重可配置 |

**L1 关键词检索（KarpathyWikiReader）：**
- 扫 wiki/**/*.md 的 frontmatter + 正文
- BM25 关键词命中（精确、可解释）
- 降级兜底：ChromaDB 挂了 → 纯 L1，w_keyword=1.0

**L2 向量检索（ChromaDB）：**
- 用户 query → bge-small-zh-v1.5 嵌入
- 余弦相似度 Top K（语义相关，模糊命中）
- 降级兜底：KB 目录找不到 → 纯 L2，不崩溃

**前台可见效果：**
- 对话气泡下方元数据显示「📚 引用 N 条知识」
- 用户一眼知道这条回答有没有用自己的资料

### 易错断点

| 编号 | 问题 | 修复方式 |
|---|---|---|
| M-20 | 导入失败无反馈 | Toast 显示具体错误（格式/网络/权限） |
| KB-1 | 缺 type frontmatter 导致检索命中 0 | 导入时自动补 type=entity |
| KB-2 | 大文件导入 UI 阻塞 | 后台 Worker 线程处理，前台只更新进度条 |

---

## 五、L4 · 人设生效流程（热更新 · 无需重启）

### 解决什么业务场景
用户在「🎭 人设 Tab」改了 AI 的身份（比如从「产品经理小张」切到「健身教练」），希望立刻生效——下一句对话语气就变，不重启软件，不丢当前对话上下文。

### 前台交互
- 🎭 人设 Tab 页
- 左侧：人设列表（选中高亮当前）
- 右侧：人设编辑器（姓名 / 头像 / 职业标签 / 系统提示词）
- 修改 → 点「保存」
- 保存后：Toast 提示 + 顶部标题栏立刻变 + 工作台 Tab 人设卡片更新

### 后台逻辑

| 步骤 | 处理 | 效果 |
|---|---|---|
| 1. 写内存 | `PersonaInjector.current_persona = new_persona` | 下一轮对话立刻用新人设 |
| 2. 写盘 | `data/persona/{id}.md`（LLM Wiki 格式） | 重启后恢复 |
| 3. 更新配置 | config.json → current_persona_id | 记录当前选中 |
| 4. UI 联动 | 标题栏 + 工作台 Tab + 人设列表高亮 | 3 处实时刷新 |

**对接 L2：** ContextAssembler 每次装配 prompt 时从 `PersonaInjector.current_persona` 读，保证用的是最新人设。

### 易错断点

| 编号 | 问题 | 修复方式 |
|---|---|---|
| P-1 | 保存无反馈 | Toast「人设已保存 ✓」+ 失败时红色错误 |
| P-2 | 内存未热更新，重启才生效 | save_persona 先写 PersonaInjector 再写盘 |
| P-3 | 回切人设 Tab 内容丢失 | 编辑器 bind Persona 对象引用，刷新时重新拉回填 |

---

## 六、L5 · 配置持久化 & 重启恢复

### 解决什么业务场景
用户关了软件再打开，之前配的 Key、改的人设、聊的记录、导入的知识……全要还在。所有数据存在 `%APPDATA%\SCAI\`（Win）或外部 data 目录，和程序本体解耦。

### 6 类持久化数据清单

| 序号 | 数据类型 | 存储位置 | 格式 | 关键字段 |
|---|---|---|---|---|
| 1 | LLM 配置 | config.json | JSON | provider / base_url / api_key(DPAPI加密) / model / rag权重 |
| 2 | 人设数据 | data/persona/*.md | LLM Wiki | frontmatter(name/tag) + 正文(系统提示词) |
| 3 | 首启标志 | config.json | JSON | first_run_done: bool |
| 4 | 知识库本体 | data/wiki/ | LLM Wiki | concepts/ + entities/ + architecture/ |
| 5 | 对话历史 | messages.db | SQLite | sessions表 + messages表 |
| 6 | 工作台统计 | data.db | SQLite | 对话数/知识页数/BadCase/广告黑名单 |

### 启动时 bootstrap() 加载顺序

| 步骤 | 动作 | 说明 |
|---|---|---|
| 1 | 读 config.json | 补默认值兼容旧版配置 |
| 2 | 加载 persona | 注入 PersonaInjector |
| 3 | 开 RAG Reader | 连接 ChromaDB |
| 4 | 建 LLM Client | 无 Key 记降级状态 |
| 5 | 加载历史消息 | 连接 SQLite |
| 6 | 启动 UI | 检查首启标志决定是否弹向导 |

### 降级横幅
首次启动时顶部黄色横幅显示：
- 🔑 llm_key_missing（请先配 API Key）
- ☁️ oa_cloud_disconnected（公众号云端未连接）

---

## 七、5 条主线 · 一句话记忆口诀

| 主线 | 一句话定位 | 代码入口 |
|---|---|---|
| L1 首启 | 让软件从「空壳」变成「能连 AI」 | first_run_wizard.py |
| L2 对话 | 让用户说的话得到一句像样的回复 | app_engine.process_message_stream() |
| L3 知识 | 让 AI 回答引用用户自己的资料，不瞎扯 | UnifiedRetriever.retrieve() |
| L4 人设 | 让 AI 语气/身份变啥就是啥，立刻生效 | PersonaInjector.current_persona |
| L5 持久化 | 关了再开，所有东西原封不动还在 | AppEngine.bootstrap() |

---

## 八、给 UI/UX 设计师的对齐请求

### 请对比 HTML 原型，检查以下问题：

1. **L1 首启向导**：HTML 原型中 Step 1/2/3 的表单字段和交互流程，是否与上述「前台交互」描述一致？测试连接按钮的 Loading 态和 Toast 反馈是否已设计？

2. **L2 对话气泡**：HTML 原型中 AI 气泡的打字机效果、AIGC 徽标位置、元数据展示格式，是否与上述描述一致？安全壳拦截后的气泡样式（PII 提醒 / 静默丢弃）是否有设计？

3. **L3 知识页**：HTML 原型中知识分类树的结构（concepts/entities/architecture）是否与上述目录结构一致？导入进度条和失败 Toast 样式是否有设计？RAG 命中数在对话气泡元数据中的展示样式是否已设计？

4. **L4 人设页**：HTML 原型中人设编辑器的字段（姓名/头像/标签/系统提示词）是否完整？保存后 3 处 UI 联动刷新（标题栏/工作台/人设列表）是否已设计？

5. **L5 降级横幅**：HTML 原型中顶部黄色降级横幅的样式、内容（llm_key_missing / oa_cloud_disconnected）是否有设计？

### 如有差异，请标注：
- 差异编号（如 L1-D1：首启 Step 1 缺少测试连接按钮的 Loading 态设计）
- 当前 HTML 原型的实际状态
- 建议的修改方向

---

*文档生成时间：2026-08-18*
*项目：影分身AI (Shadow Clone AI) MVP*
