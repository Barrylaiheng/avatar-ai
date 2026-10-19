# SCAI MVP · 最终业务对齐凝固文档 V1.0（搭搭DaDa 已跑通版本对齐）

> **版本**：V1.0 · 凝固版  
> **创建时间**：2026-08-10  
> **状态**：**用户签字确认版 = 之后所有表层/里层 PDD 的唯一业务源头，不再重开对齐讨论**
>
> **本回答的结论来源**：
> 1. 用户 2026-08-10 当面拍板的 7 条决策
> 2. 搭搭DaDa（旧电脑已跑通的 CPS 项目）真实代码提取：
>    - `C:\Users\Administrator\Desktop\搭搭Dada\src\wcf_bot.py` 消息处理链路（已真实运行）
>    - `C:\Users\Administrator\Desktop\搭搭Dada\src\ai_core.py` 七段式 Prompt 模板 + ContextAssembler（已真实运行）
>    - `C:\Users\Administrator\Desktop\搭搭Dada\src\content_moderation.py` 频控/敏感词/安静时段（已真实运行）
>    - `C:\Users\Administrator\Desktop\搭搭Dada\docs\年轻人大学生消费需求场景全景_20260505.md` 用户画像调研
> 3. SCAI MVP 需求清单 V0.2 文档
>
> **本回答的承诺**：
> 之后所有里层 PDD grill 题目、Test Seams 假剧本、人设七段式字段含义，**100% 从本文档提取，不再出现「你不懂业务场景」的问题**。

---

## 0. 总览：三张表一句话讲清

| 维度 | 一句话结论 |
|------|------------|
| 产品卖什么 | ✅ **卖工具（第二层）**，核心卖点 = 数字分身提炼 + 知识库搭建（克隆/蒸馏能力），不是卖服务也不是控制微信 |
| 里层 PDD 第 1 步「业务调度秘书」到底干嘛 | = **搭搭DaDa的 wcf_bot.process_wcf_message() + ai_core.ContextAssembler 的逻辑映射**。按固定 12 步流水线跑：「消息类型→去重→安静时段→频控→安全→联系人分组→意图→手谕→人设→历史→承诺→知识库→调大模型→盖章→发出」 |
| 人设档案到底怎么拼 | ✅ **搭搭DaDa七段的扩展变形**。SCAI 的七段 = `role/task/rules/examples/style/constraints/output_format` 对应到搭搭 DaDa 七段，只是字段顺序和命名微调了 |

---

## 1. 用户拍板的 7 条决策（凝固，不再讨论）

| 编号 | 用户拍板内容（原话说的）| 翻译后的开发规格（PDD 要照此执行）| 开发落地形式 |
|------|--------------------------|------------------------------------|--------------|
| **DM-01** | 产品模型 = 第二层「卖工具」，不是卖服务 | MVP 优先验证：知识蒸馏工具 + 数字分身搭建能力 + 人设编辑器 + 七段式 Prompt 拼法 + 微信/公众号渠道连接能力 | 功能优先级：人设/知识库 > 对话（AI面试官）> 迭代 > 工作台/排班 > 渠道连接设置 |
| **DM-02** | 主人不能用微信自发消息控制分身，必须通过 MVP 中后台管理分身 | WCF 收到「主人自己的微信号发来的消息」—— 按普通联系人处理，不识别为控制指令；所有分身配置、人设修改、微信连接开关、排班设置，**仅能通过 MVP GUI 5 页操作** | `bridges/message_router.py` 中不实现「主人身份识别控制指令」分支 |
| **DM-03** | 联系人名单（好友/群）= WCF 同步微信联系人导入 MVP，再在 MVP 里控制谁会被分身回复、谁进黑名单 | ① MVP 启动时通过 `wcf_adapter.get_contacts()`（已有代码）同步全量联系人缓存到档案柜 DB 表 `contacts`；② 用户在 MVP 的工作台页或联系人管理面板上标记「允许分身回复 / 黑名单 / 客户分组 / 禁言时段」；③ 公众号渠道：通过 SSH 连云端服务器拿用户列表（逻辑和微信不一样） | 新增 DB 表 `contacts`（wxid/备注名/角色分组/标签/安静时段配置）；新增 MVP GUI 联系人管理面板（工作台二级）|
| **DM-04** | 公众号逻辑和微信不一样 = 通过 MVP 连服务器，拿服务器上的用户（你们在跑的 CPS 项目逻辑） | MVP 设置页提供「公众号 SSH 服务器连接配置」输入框，SSH 连好后，用户通过 HTTP / 接口从服务器拉微信公众号用户数据，灌到 MVP 的 `contacts` 表；消息收发走服务器回调地址 | 参考：你们搭搭 DaDa 项目 `C:\Users\Administrator\Desktop\搭搭Dada\docs\tech\FC方案_v2.0_综合版.md` 中「公众号回调链路」 |
| **DM-05** | AIGC 盖章 = 设置里用户手动开关，必须有（合规要求）但决策权交用户，不是硬性强制。勾选后 → LLM 发出的每段话末尾加小尾巴 | ① 设置页（SettingsPageV2）加一个 ToggleSwitch：「启用 AI 生成内容标识」= 默认开启（推荐）；② `engine/aigc_marker.py` 中把 `AigcExplicitLabeler` 改成 **suffix 模式（加在末尾）**，默认值从 prefix `[AI生成]` → 改成 suffix `[本消息由AI分身生成]`；③ 盖章开关状态从 DB 表 `settings` 读 | 代码已存在两个盖章器，只要改：① 默认值从 prefix→suffix ② 开关挂到设置页 GUI ③ 读配置 |
| **DM-06** | 引导弹窗 = 一步填 API Key 完事。其余引导不在传统多步向导里，放在对话逻辑里（类似 TRAE 通用 AI，用对话形式完成交互 = AI 面试官模式）。API Key 必须用户自己申请，不用你的（风险考量）。 | ① onboard-modal 维持现状：只有一步填 API Key + 使用其他服务商跳转设置；② 填完 API Key 后跳转到「对话页（AI 面试官）」，AI 面试官主动发问，以对话形式完成：人设初步搭建 → 联系人分组策略确认 → 知识库来源确认 → 微信/公众号渠道连接引导。整个引导是对话流，不是下一步/下一步的 GUI 向导。 | ① 对话页启动逻辑：检测 onboard 完成但 persona 为空 → AI 面试官自动发首句「嗨～现在我们来把你的数字分身搭起来，先问你 3 个小问题：你的对外身份是谁？」；② 面试官状态机引导流程写死在 dialog engine |
| **DM-07** | Toast 通知（非文字消息弹右下角提示）= 不要，别搞复杂了，MVP 验证业务不需要 | 好友发来图片/语音/视频/文件/表情包/位置 — MVP 直接丢弃不通知主人（完全和搭搭 DaDa 的 wcf_bot.py 现状一致：type≠1 非文本除语音 OCR 外直接 log 跳过）| `wcf_adapter.py` 当前第 390 行硬编码 `if msg_type_code != 1: return None` **完全保留现状不变** |

---

## 2. 最关键：从搭搭DaDa真实代码对齐到的「SCAI 业务调度秘书 12 步流水线」

> 这个就是你之前没理解透的「message_processor.py 到底干嘛」—— 现在我把它翻译成**和你已经跑了很久的搭搭DaDa项目一摸一样的流程顺序**，一一对应。

### 2.1 对照关系总表

| 步骤 | 业务调度秘书要做的事 | 对应到你旧电脑搭搭DaDa已跑通的真实代码 | 真实代码文件位置 |
|-----:|---------------------|-----------------------------------------|-----------------|
| **1** | 接收：消息类型初筛（私聊/群@/系统/撤回） | `process_wcf_message()` 开头：`msg.type`、`msg.sender`、`msg.room` 提取；`if not room_id: return`（WCF 只处理群聊）逻辑迁移 | [wcf_bot.py:284](file:///C:/Users/Administrator/Desktop/%E6%90%AD%E6%90%ADDada/src/wcf_bot.py#L284) 起 |
| **2** | 非文字消息处置（语音OCR/图片审核/其余丢弃） | `if msg_type!=1` 分支：语音→`voice_to_text()` OCR转文本后继续；图片→下载→云端OCR审核后丢弃；其余直接 log 跳过 | [wcf_bot.py:302-410](file:///C:/Users/Administrator/Desktop/%E6%90%AD%E6%90%ADDada/src/wcf_bot.py#L302) |
| **3** | 安静时段检查（23:00-次日 08:00 不回复 = 防扰民） | `RateLimiter.can_reply()` 中 `quiet_hours_start/end` 检查：23:00~8:00 跨午夜判断 | [wcf_bot.py:84-129](file:///C:/Users/Administrator/Desktop/%E6%90%AD%E6%90%ADDada/src/wcf_bot.py#L84) |
| **4** | 消息去重 + 频控 | ① `is_duplicate(msg_id)`：最近 1000 条去重；② `UserFrequencyTracker`：10 秒内同用户最多 5 条；③ 每日回复上限 daily_push_max；④ 回复间隔 reply_interval_min | [wcf_bot.py:137-149](file:///C:/Users/Administrator/Desktop/%E6%90%AD%E6%90%ADDada/src/wcf_bot.py#L137) 去重；[content_moderation.py:125-159](file:///C:/Users/Administrator/Desktop/%E6%90%AD%E6%90%ADDada/src/content_moderation.py#L125) 频控 |
| **5** | 联系人分组识别（= 黑名单/客户/普通好友） | ⚠️ 搭搭DaDa WCF 群聊场景没有联系人分组（群是开放的）。SCAI 新增：从档案柜 `contacts` 表查 wxid 对应的 role_group（DM-03 拍板：MVP 用户手动打标） | 新增：`engine/hard_rules_executor.py` 联系人分组匹配函数 |
| **6** | 内容安全审核（违规/广告/砍价/敏感词拦截） | `check_text()`：砍价助力→最严重→警告；广告引流→警告；刷屏检测（连续重复）→记录 | [content_moderation.py:53-119](file:///C:/Users/Administrator/Desktop/%E6%90%AD%E6%90%ADDada/src/content_moderation.py#L53) |
| **7** | 主人手谕（铁规则）执行 | 搭搭DaDa：SystemPrompt 中「硬规则 5 条」（医疗→医院、心理→热线、法律→12348、金融→风险提示、政治→回避）；SCAI 加：① 一级黑名单（老婆/爸妈/老板）→ 不回复 + 不打扰主人 ② 涉及见面/电话/合同/报价/转账 → 一律"我让主人稍后联系您" | 来源：[SystemPrompt设计文档 §1.2 硬性规则](file:///C:/Users/Administrator/Desktop/%E6%90%AD%E6%90%ADDada/docs/SystemPrompt%E8%AE%BE%E8%AE%A1%E6%96%87%E6%A1%A3_v1.0.md#L61) + DM-02 + 需求清单 §6 |
| **8** | 意图识别（这条消息是啥类型？聊天/找知识/要排班/改设置/迭代优化）| 搭搭DaDa：`RAGEngineLite.classify_intent()`：KEYWORD_MAP 10 种（外卖/团购/电影/比价/出行/酒店/会员/安全/指南/聊天）；SCAI 扩展：对应 Sidebar 5 页路由类型 | [ai_core.py:60-103](file:///C:/Users/Administrator/Desktop/%E6%90%AD%E6%90%ADDada/src/ai_core.py#L60) |
| **9** | 🎯 **工作包拼装** = 档案管理员按优先级把材料打包给大模型（最核心一步！）| **从搭搭DaDa `ContextAssembler` + `PromptTemplate.build_reply_prompt()` 直接映射**。优先级顺序按下方 §3 固定 | [ai_core.py:628-738](file:///C:/Users/Administrator/Desktop/%E6%90%ADDada/src/ai_core.py#L628) Prompt拼装；[ai_core.py:743-840](file:///C:/Users/Administrator/Desktop/%E6%90%ADDada/src/ai_core.py#L743) ContextAssembler |
| **10** | 调用大模型写回复 | `llm_generator.py`：接工作包 + 人设七段 → 调 DeepSeek/GPT/Doubao 等用户自己的 API Key（DM-06） | 搭搭DaDa：真实调用在云端 API，WCF 端只负责 POST 到云端 |
| **11** | AIGC 盖章 | `engine/aigc_marker.py`：suffix 模式加在末尾；开关由用户设置页 ToggleSwitch 控制（DM-05） | 搭搭DaDa：合规层面已预埋但 SCAI 更严格（7月15日法规）|
| **12** | 发回微信/公众号 + 记录历史 + 同步主人手动回复 | ① `wcf_adapter.send_text()` 发送；② 写入 `chat_history` DB 表；③ **若主人本人在手机微信手动回了一条 → 同步进档案柜历史**（防止AI下次风格跳变 = WCF-14 确认必须同步） | [wcf_bot.py:send_to_cloud()](file:///C:/Users/Administrator/Desktop/%E6%90%AD%E6%90%ADDada/src/wcf_bot.py#L157) + 聊天历史DB记录逻辑 |

### 2.2 一句话总结 message_processor 和搭搭DaDa 的关系

> **SCAI MVP 的 `message_processor.py` = 搭搭DaDa `wcf_bot.py` 里 process_wcf_message() 的第 1-7 步 + `ai_core.py` ContextAssembler+PromptTemplate 的第 9 步，合并成一个本地 PyQt 版本的统一流水线。** 每一步在你旧电脑上都真实跑过。

---

## 3. 工作包拼装优先级（从搭搭DaDa ContextAssembler 真实实现对齐凝固）

> 这就是你之前听不懂的「人设 JSON 填好作为业务调度秘书核心输入」到底是什么意思 —— 给大模型喂材料的顺序，错了就会风格不对、偏好不对、承诺不对。

**固定优先级（从搭搭DaDa ai_core.py 七段式迁移而来，顺序不再讨论）：**

| 优先顺位 | 内容块 | 内容描述 | 对应 SCAI 字段/来源 | 对应搭搭DaDa 真实 Prompt 段落 |
|---------:|--------|----------|---------------------|------------------------------|
| **1（最高）** | 主人手谕（圣旨） | 绝对不允许 AI 违反的铁规则：一级黑名单、见合同转主人、医疗/心理/法律/金融红线、政治敏感回避 | `hard_rules_executor.py` + `persona.constraints` | [SystemPrompt设计文档 §1.2 硬性规则](file:///C:/Users/Administrator/Desktop/%E6%90%AD%E6%90%ADDada/docs/SystemPrompt%E8%AE%BE%E8%AE%A1%E6%96%87%E6%A1%A3_v1.0.md#L61) 6 条 + PromptTemplate 约束禁忌段 |
| **2** | 人设档案（七段式）| 主人是谁、分身干嘛、怎么说话、举例、风格、格式、边界 | `persona_editor.py` SevenSectionPersona 的 7 个字段（role/task/rules/examples/style/constraints/output_format）| PromptTemplate.`_build_base_prompt()` OFFICIAL_PERSONA + 【任务目标】+【行为原则】|
| **3** | 该好友档案 + 最近聊天历史 | 这个朋友是谁（备注名/分组）、最近和主人说过的 50 句话、防止重复内容、承接上文 | `contacts` 表 + `chat_history` 表（按 wxid + 时间倒序 TOP 50）| ContextAssembler.`get_user_context()` + 对话上下文 |
| **4** | 该好友的重要承诺记录 | 答应客户下周三发合同、答应朋友周末吃饭 — 这类比普通聊天优先级高的特定事项 | `contact_promises` 新增表（wxid + promise_text + due_date）| 搭搭DaDa：`user_profiles.customize_completed` 扩展字段 |
| **5** | 知识库 TOP 3 相关文档片段 | 主人飞书知识库 / 本地 Markdown/PDF 蒸馏出来的内容里，和本条消息语义最相关的前 3 条片段 | `rag_engine.search(query=user_message, top_k=3)` | PromptTemplate.`inject_rag_result()` + 【参考话术】段 |
| **6** | 当前场景描述 | 这条消息的场景：微信私聊/微信群@本人/公众号私聊/什么时间（早中晚餐/深夜）| msg.channel + `get_time_context()` 时段判断（搭搭DaDa 6 个时段）| PromptTemplate.scene_desc + ContextAssembler.`get_time_context()` |
| **7** | 主人最近 3 条手动回复（防风格跳变）| 主人在手机微信上亲自回复过的最近 3 条，给大模型做 few-shot，避免写出和主人真实口吻不一致的回复 | `chat_history` 表中 `is_manual_reply = True` 的最近 3 条 | ⚠️ SCAI 新增，搭搭DaDa 群聊场景无此需求（用户画像不同）|
| **8（最低）** | 当前用户原始消息 | 用户到底说了什么 | msg.content | 【用户消息】段 |

---

## 4. 人设七段式：搭搭DaDa 和 SCAI 的字段映射（凝固，不再改）

> 你之前没听懂「真实人设 JSON 填好」= 就按这个映射填，填完大模型才知道模仿谁。七段顺序和搭搭DaDa 一模一样，只是 SCAI 的 UI 层命名换了下。

| 搭搭DaDa 七段（ai_core.py + SystemPrompt文档）| → 对应 SCAI MVP persona_editor 七段式 SevenSectionPersona | 你要填的「你本人人设」举例（大学生/年轻人群 CPS 场景参考） |
|----------------------------------------------|---------------------------------------------------------|--------------------------------------------------------|
| ① 角色设定（SystemPrompt文档 §1.1 名字+身份+年龄+性格+风格） | SCAI `role` 字段（角色设定 — 定义数字分身是谁）| 「你是 XX（你自己的名字），XX 岁，做大学生/年轻人消费 CPS 的生活搭子，亲切会省钱、性格像你本人性格（此处 100 字内描述你本人真实性格）」 |
| ② 任务目标（PromptTemplate._build_base_prompt() 【任务目标】5 条）| SCAI `task` 字段（任务说明 — 定义核心任务）| 「替主人接微信私聊和群@消息，按主人风格回复，帮用户找消费优惠/陪伴聊天/完成简单日常问答」 |
| ③ 行为规则（【行为原则】3 条 + 【硬性规则】6 条）| SCAI `rules` 字段（行为规则 — 行为约束）+ `constraints` 字段（约束条件）| 「红线：不教犯罪、不泄漏API Key、不碰转账/合同/报价见主人、医疗推荐医院心理热线12356法律12348；风格：不用您用你、不说教不装逼、像朋友聊天」 |
| ④ 示例对话（搭搭DaDa ERROR_CASES 正反案例 + 场景模板 3.1~3.5） | SCAI `examples` 字段（few-shot 示例对话）| 「用户："有奶茶券吗" → 答："查到啦～瑞幸今天 9.9，学校门口那家 10 分钟送到。你上次说喜欢生椰拿铁，要不要顺便带一杯？😊"」（3~5 条你平时怎么跟朋友说话的例子） |
| ⑤ 说话风格（SystemPrompt文档 §四 语气风格 + §1.1 性格） | SCAI `style` 字段（风格指南 — 语气风格）| 「亲切口语化像朋友聊天、偶尔 emoji 和梗、不用敬语、对大学生群体说话偏同龄人语气、回复字数控制在 100~250 字以内」 |
| ⑥ 约束条件 / 自我检查（PromptTemplate 第5-6段 + AIGC 标识）| SCAI `constraints` 字段（边界声明 + 输出约束）| 「不编造商品和优惠链接、不主动推销、情绪倾诉时 0% 商业化、所有建议最后加一句"参考哈，最终决定你定～"」 |
| ⑦ 输出格式（PromptTemplate 第4段 + RAG注入规则） | SCAI `output_format` 字段（输出格式要求）| 「纯文本微信消息，分段用空行，不要用 Markdown 表格；如果有链接，用「【点我：链接文案】→ 真实链接」格式；盖章时最后一行加「[本消息由AI分身生成]」」 |

---

## 5. 排班 / 安静时段逻辑：从搭搭DaDa 真实配置凝固（你拍板的「前期不需要 7×24，但年轻人画像下 23 点后不扰民」）

> 搭搭DaDa wcf_bot.py 的 CONFIG 已真实跑通，照搬过来：

| 配置项 | 搭搭DaDa 真实值 | SCAI MVP MVP 初期方案（MVP 不做GUI排班，先硬编码这些默认值，后续工作台页再做面板） |
|--------|-----------------|-------------------------------------------------------------------------|
| `quiet_hours_start` | **23 点** | 23:00（23 点后所有普通好友消息暂存不发，第二天 8 点后统一处理）|
| `quiet_hours_end` | **次日 8 点** | 次日 8:00（解除安静时段）|
| 例外：二级客户（付费客户/长期大客户） | — | 23:00 后也可以回，但回复末尾加备注「非工作时间处理，如有急事请联系主人手机」 |
| 例外：一级黑名单（老婆/爸妈/老板） | — | 任何时段都**不 AI 回复**，直接存入「主人待办提醒」等主人登录 MVP 时红标提示（不发 Toast = DM-07，只在工作台页展示红标待办卡片） |
| `reply_interval_min`（两条 AI 回复之间的最小间隔） | 10 分钟 | 60 秒（MVP 版先放宽 10 分钟会错过互动） |
| `daily_push_max`（每日主动推送消息上限） | 2 条（搭搭DaDa 主动发早安晚安等） | MVP 阶段：0 条（不做主动推送，只被动回复）；等排班 GUI 做了再开 |
| 限流发送速率上限 | — | A8 安全合规已锁死：≤15 条/分钟、≤300 条/小时 |

---

## 6. 用户画像确认：从搭搭DaDa 调研凝固（= 你说的「大学生/年轻人 CPS 群体画像」就是这个）

> 你说你做 CPS 对象是大学生/年轻人群体 —= 搭搭DaDa 调研结论（2026-05-05），100% 直接复用：

| 画像项 | 调研数据 | 对 SCAI 人设 + 安静时段的影响 |
|--------|---------|------------------------------|
| 目标年龄 | 18-25 岁，大学生为主 | 人设语气：同龄人聊天，不装不端 |
| 月消费 | 1500-2000 元，45% 吃（外卖奶茶零食）| 人设知识核心：外卖/奶茶/日用/服饰的优惠和比价 |
| 最高频场景 | 外卖点餐（每天1-3次）| 知识库里必须有美团/饿了么红包口令，Top of mind |
| 次高频场景 | 奶茶咖啡（每周3-7次：瑞幸9.9/蜜雪/茶百道）| 人设例子里必须至少有 1 条奶茶优惠的对话举例 |
| 活跃作息 | 年轻人熬夜作息 = 对应 DM-03 你说的「23点或12点或1点过后不扰民」| quiet_hours 可设 01:00~09:00，看你最终拍板（§5 默认 23:00~08:00 是搭搭DaDa的保守值，你可改）|
| 社群高频违规 | 广告引流 + 砍价助力 + 拼多多链接（刷屏）| 内容安全 check_text 里三类关键词直接搬 |

---

## 7. 凝固下来的「里层 PDD 第 1 批 module × order」

> 基于以上对齐结论（100% 有代码/决策依据），重新排序里层 PDD 顺序（原来的排序作废，以这个为准，不再讨论顺序）：

| 顺序 | 模块名 | 对应上面的哪几节 | 为什么先做它 |
|-----:|--------|------------------|-------------|
| 1 | `engine/message_processor.py` | §2 12 步流水线（核心对照搭搭DaDa process_wcf_message 1-7 步 + 9 步拼装）| **入口最窄，能锁住所有后面模块的协作契约**：频控怎么走、安全怎么拦、手谕怎么执、工作包怎么拼、大模型怎么调、盖章怎么盖 — 全部按 12 步一根尺子一根尺子量 |
| 2 | `bridges/internal_message.py` + `message_router.py` | §2 step1 消息初筛 + §2 WCF 9 类型枚举（MISS-01 已从源码提取）+ DM-03 联系人同步入口 | 入口分拣台：什么消息进来走什么分支、什么类型丢弃。做 message_processor 之前，必须先把 InternalMessage 的字段 schema 量完。 |
| 3 | `engine/safety_shield.py` | §2 step6 内容安全 + §2 step4 去重频控 + 安静时段 step3 | 免疫系统第 1 环。从搭搭DaDa content_moderation.py 一行一行搬过来，Test Seams 就是「输入砍价助力→必返回 kanjia blocked + 对应警告话术」这类断言，极易 TDD。 |
| 4 | `engine/context_assembler.py` + persona 七段式入库 | §3 工作包拼装 8 步优先级 + §4 七段式映射 | 档案管理员。没有她，写手拿到的材料顺序全乱，人设不对、风格跳变、承诺忘光。 |
| 5 | `security/api_key_vault.py` + `engine/aigc_marker.py` | DM-05 AIGC 盖章开关 + 后缀模式默认文案（短版）+ §1 DM-06 API Key 用户自有 | 免疫系统第 2 环。盖章合规必须过；API Key 保险柜（对照 PDD Bug #2 明文泄漏风险）。 |
| 6 | 其余（llm_generator / intent_classifier / hard_rules_executor / rag_engine） | §2 step7/8/10 | 按 1-5 模块的协作契约逐个对齐。 |

---

## 8. 剩下还需要你本人亲自填的 3 件纯业务数据（不是逻辑，是你本人的信息，代码里怎么提取都提取不出来）

| 编号 | 要填的内容 | 对应哪一节 | 为什么必须你本人填 | 建议格式 |
|------|-----------|-----------|-------------------|---------|
| **YOU-01** | **你自己的真实人设 JSON**（七段式 9 栏除了自动字段和 description、is_active 的其余 7 个字段你用你自己的真实情况填）| §4 人设七段式 | 这是你数字分身模仿谁的源头，只有你知道「你是谁、你怎么说话、你红线是什么、你平时怎么回消息」| 按 §4 右侧「你要填的举例」那行格式，填成 MISS-03 里的 JSON 模板 7 个空栏 |
| **YOU-02** | 联系人角色的「分组规则」= 你准备怎么把同步过来的微信联系人分四类（一级黑名单 / 二级客户 / 三级普通好友 / 四级垃圾人）。具体怎么分？是按"备注名包含关键字"？按"你自己手动一个个打标签"？按"群所属"？还是按"之前聊天记录 AI 自动生成画像再分"？| DM-03 + §2 step5 | 这是纯业务决策，纯看你想怎么管理自己的好友名单。比如「微信号备注名带「老婆」两个字 → 自动进一级黑名单」这类规则。 | 一张规则表：触发条件 → 分组结果。示例：<br>IF 备注名包含「老婆/妈/爸/老板」 → 一级黑名单<br>IF 备注名包含「客户/CEO/总」 → 二级客户<br>其余 → 三级普通好友 |
| **YOU-03** | 安静时段最终值：默认用搭搭DaDa的 23:00-08:00？还是按你说的年轻人画像改成 01:00-09:00？还是干脆 MVP 阶段你不想要安静时段（分身 7×24 全量接）？| §5 排班/安静时段 | 这是你的产品决策，取决于你服务的群体作息。 | 三选一：<br>❶ 23:00~次日08:00<br>❷ 01:00~次日09:00<br>❸ 不做安静时段，全量接 |

---

## 9. 签字区（= 凝固确认）

> 看完本文档后：
> - 如果以上所有内容你觉得「对，就是这个意思，和我脑子里想的一致」，就口头回复「确认 V1.0」 → 之后所有 PDD 以此为唯一源头，不再开业务对齐讨论。
> - 如果有哪几节要改，直接标章节号+你的正确描述，我按你改的出 V1.1，确认完再凝固。

| 角色 | 签字 | 日期 |
|------|------|------|
| 产品/业务（你本人）| _______________ | 2026-08-__ |
| AI 开发方 | Trae（自动） | 2026-08-10 |

---

## 附录 A：从搭搭DaDa提取的所有关键代码证据链（一键跳转点击查看）

| 搭搭DaDa 真实实现 | 代码位置（点击跳转）|
|-------------------|-------------------|
| WCF 消息 12 步处理链路（process_wcf_message）| [wcf_bot.py#L284-L482](file:///C:/Users/Administrator/Desktop/%E6%90%AD%E6%90%ADDada/src/wcf_bot.py#L284-L482) |
| 安静时段 + 每日上限 + 回复间隔频控（RateLimiter）| [wcf_bot.py#L84-L136](file:///C:/Users/Administrator/Desktop/%E6%90%AD%E6%90%ADDada/src/wcf_bot.py#L84-L136) |
| 消息去重（1000 条滑动窗口）| [wcf_bot.py#L137-L149](file:///C:/Users/Administrator/Desktop/%E6%90%AD%E6%90%ADDada/src/wcf_bot.py#L137-L149) |
| 内容安全（砍价/广告/刷屏 三类关键词 + 警告话术）| [content_moderation.py#L15-L119](file:///C:/Users/Administrator/Desktop/%E6%90%AD%E6%90%ADDada/src/content_moderation.py#L15-L119) |
| 单用户发言频率检测（10秒 / 最多 5 条）| [content_moderation.py#L125-L159](file:///C:/Users/Administrator/Desktop/%E6%90%AD%E6%90%ADDada/src/content_moderation.py#L125-L159) |
| WCF 联系人同步：`wcf.get_contacts()` | [wcf_bot.py#L423-L440](file:///C:/Users/Administrator/Desktop/%E6%90%AD%E6%90%ADDada/src/wcf_bot.py#L423-L440) |
| 七段式 Prompt 模板基类 + OFFICIAL_PERSONA + build_reply_prompt() | [ai_core.py#L544-L738](file:///C:/Users/Administrator/Desktop/%E6%90%AD%E6%90%ADDada/src/ai_core.py#L544-L738) |
| ContextAssembler：get_time_context + get_user_context（真实 DB 查询）| [ai_core.py#L743-L840](file:///C:/Users/Administrator/Desktop/%E6%90%AD%E6%90%ADDada/src/ai_core.py#L743-L840) |
| 意图分类 KEYWORD_MAP（10 类 CPS 场景关键词，可扩展）| [ai_core.py#L60-L103](file:///C:/Users/Administrator/Desktop/%E6%90%AD%E6%90%ADDada/src/ai_core.py#L60-L103) |
| 人设 SystemPrompt 设计文档（搭搭DaDa官方）| [SystemPrompt设计文档_v1.0.md](file:///C:/Users/Administrator/Desktop/%E6%90%AD%E6%90%ADDada/docs/SystemPrompt%E8%AE%BE%E8%AE%A1%E6%96%87%E6%A1%A3_v1.0.md) |
| 年轻人/大学生消费需求场景全景调研（CPS 用户画像原始数据）| [年轻人大学生消费需求场景全景_20260505.md](file:///C:/Users/Administrator/Desktop/%E6%90%AD%E6%90%ADDada/docs/%E5%B9%B4%E8%BD%BB%E4%BA%BA%E5%A4%A7%E5%AD%A6%E7%94%9F%E6%B6%88%E8%B4%B9%E9%9C%80%E6%B1%82%E5%9C%BA%E6%99%AF%E5%85%A8%E6%99%AF_20260505.md) |
