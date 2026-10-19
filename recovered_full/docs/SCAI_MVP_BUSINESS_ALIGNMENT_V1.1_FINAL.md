# SCAI MVP · 最终业务对齐凝固文档 V1.1

> **版本**：V1.1 · 最终凝固版
> **更新时间**：2026-08-10
> **状态**：**用户签字确认版 = 之后所有表层/里层 PDD 的唯一业务源头，不再重开对齐讨论**
> **V1.0 → V1.1 变更摘要**：
> - 新增 BIZ-01~04 四项业务决策（首个用户/MVP验收标准/旧系统处置/单多用户）
> - 新增 LLM Wiki 衔接决策（❸ 兼容 Karpathy + Obsidian）
> - 修正 12 步流水线（以真版 824 行 wcf_bot.py 为准，非桌面旧版 509 行）
> - 修正频控真实值（当前全关 0/0/0，非 23:00-8:00）
> - 修正 Prompt 结构（实际精简 4 段，映射到七段式 persona）
> - 新增 CPS 项目架构五层解剖（灵魂/骨架/供血/神经/免疫）
> - 新增两条用户路径（Path A 导入已有知识库 / Path B 从零搭建）

---

## 0. 产品定位（一句话）

> **SCAI MVP = 一个卖给你「把自己的知识蒸馏成 AI 数字分身」的工具。**
> - 第一个用户 = 你自己（做一个关于「怎么做 CPS 业务的 AI 数字分身」的数字分身）
> - 不接管已有搭搭 DaDa，旧系统独立跑，SCAI 做新的分身
> - 单用户、单 PC、单微信（v2.0 再考虑一人管多个分身）
> - MVP 验收标准 = 知识库导入导出 + 迭代系统

### 两条用户路径

| 路径 | 场景 | MVP 要做的 |
|------|------|-----------|
| **Path A** | 用户已有知识库（通过 Obsidian/Trae/Workbody + LLM Wiki 做的）→ 导入 SCAI → 选渠道接入（微信/公众号）→ 上线 | ① .md 文件导入 ② 渠道连接 ③ 分身管理 |
| **Path B** | 用户从零开始 → 通过 AI 面试官对话式搭建分身 → 知识库蒸馏 → 选渠道接入 → 上线 → 迭代优化 | 全流程都做 |

---

## 1. 全部决策清单（11+4+1 = 16 条，凝固不再讨论）

### 1.1 产品与业务决策（DM-01~07 + BIZ-01~04 + LLM-Wiki）

| 编号 | 决策内容 | 来源 |
|------|---------|------|
| **DM-01** | 产品模型 = 第二层「卖工具」，核心卖点 = 数字分身提炼 + 知识库搭建 | V1.0 用户拍板 |
| **DM-02** | 主人不能用微信自发消息控制分身，必须通过 MVP 中后台管理 | V1.0 用户拍板 |
| **DM-03** | 联系人名单 = WCF 同步微信联系人导入 MVP，在 MVP 里管理谁被回复/谁进黑名单 | V1.0 用户拍板 |
| **DM-04** | 公众号逻辑 ≠ 微信：通过 MVP SSH 连服务器拿用户列表（CPS 项目逻辑） | V1.0 用户拍板 |
| **DM-05** | AIGC 盖章 = 设置里用户手动开关（默认开建议开），勾选后末尾加小尾巴。合规必须有，决策权交用户 | V1.0 用户拍板 |
| **DM-06** | 引导 = 一步填 API Key，其余引导放对话逻辑里（AI 面试官模式）。API Key 必须用户自有 | V1.0 用户拍板 |
| **DM-07** | Toast 通知 = 不要，非文字消息直接丢弃不通知主人 | V1.0 用户拍板 |
| **BIZ-01** | **第一个真实用户 = 你自己**。但不用已有 CPS 分身，而是做一个新的「关于怎么做 CPS 业务 AI 数字分身」的数字分身 | V1.1 用户拍板 |
| **BIZ-02** | **MVP 验收标准 = 知识库导入导出 + 迭代系统**。核心命题：先解决「数字分身能力」（知识蒸馏），再解决「渠道能力」（微信/公众号接入）。Path A 用户可跳过蒸馏直接导入 | V1.1 用户拍板 |
| **BIZ-03** | **旧搭搭 DaDa WCF 不切换、不接管，独立跑**。SCAI 做新的分身，两套并行 | V1.1 用户拍板 |
| **BIZ-04** | **单用户工具**：一人一台 PC 管自己的一个分身。v1.0 不支持多用户。未来 v2.0 可能考虑一人管多个分身（不同联系人对应不同分身） | V1.1 用户拍板 |
| **LLM-Wiki** | RAG 层衔接 LLM Wiki 格式（不推翻）。知识库文件 = .md + YAML frontmatter + 双向链接。**选❸兼容模式**：提取 Karpathy 和 Obsidian 公共字段（title/tags/created/source/verified），各自特有字段忽略 | V1.1 用户拍板 |

### 1.2 待用户本人填的纯业务数据（YOU-01~03，不急但要填）

| 编号 | 要填什么 | 状态 | 参考模板 |
|------|---------|------|---------|
| **YOU-01** | 你自己的真实人设 JSON（七段式 7 栏） | 待填 | 参考搭搭 DaDa 的 `OFFICIAL_PERSONA` 3 行精简版 → 扩展为七段式 |
| **YOU-02** | 联系人分组规则表（什么条件→什么分组） | 待填 | 参考规则：备注名含老婆→一级黑名单 |
| **YOU-03** | 安静时段最终值（❶23-08 ❷01-09 ❸全量接） | 待填 | 真实数据：当前全关(0/0/0)，历史用过 23:00-8:00 |

---

## 2. CPS 项目架构五层解剖（从真实代码提取，不是推测）

> 来源：ai_core.py 1188 行完整提取 + wcf_bot.py 824 行真版 + content_moderation.py 128 行 + 服务器 SSH 3 轮审计

### 2.1 人体比喻对照

| 人体系统 | CPS 项目真实代码 | SCAI MVP 里层对应模块 | 里层 PDD 顺序 |
|----------|-----------------|---------------------|:------------:|
| **灵魂（Soul）** | `OFFICIAL_PERSONA` 3 行人设 + `PromptTemplate._build_base_prompt()` | `persona_editor.py` 七段式 + `context_assembler.py` | 4 |
| **骨架（Skeleton）** | LLM(DeepSeek) + Prompt(精简4段) + Context(动态装配) + RAG(意图分类+知识检索) + 迭代(bad_case+templates) | 五层架构全映射 | 1-6 |
| **供血系统（血液）** | 12 步消息处理流水线（process_wcf_message） | `message_processor.py` | 1 |
| **神经系统（神经）** | 消息类型分流 + 群/私聊分流 + @检测 + 异步+占位语 + 意图分类路由 | `message_router.py` + `intent_router.py` | 2 |
| **免疫系统（免疫）** | content_moderation 关键词拦截 + RateLimiter 频控 + 管理群白名单 + AIGC 标识 | `safety_shield.py` + `api_key_vault.py` + `aigc_marker.py` | 3, 5 |

### 2.2 灵魂原文（OFFICIAL_PERSONA）

```python
OFFICIAL_PERSONA = """你是「搭搭DaDa」，一个年轻幽默风趣的AI生活搭子。
不是客服、不是老师——你是会聊天、会省钱的朋友。
你的核心功能是帮用户找到优惠、省钱的CPS优惠链接。"""
```

> SCAI MVP 的 YOU-01 就是让用户填自己的 3 行 → 扩展为七段式。换掉 CPS 内容，枪不变。

### 2.3 Prompt 实际结构（精简 4 段，非 7 段）

搭搭 DaDa 的 `build_reply_prompt()` 实际产出 4 段：

| 段 | 内容 | 对应 SCAI 七段式字段 |
|---:|------|---------------------|
| ① | 人设 + 场景描述（wcf 群聊 / mp 公众号） | `role` + `style` |
| ② | 上下文动态变量（时间/用户/平台）+ 用户原始消息 | 动态注入，不对应固定字段 |
| ③ | RAG 规则注入（16 类知识按关键词+场景动态拼装）+ 话术模板（DB response_templates） | `rules` + `constraints` + `examples` + `output_format` |
| ④ | 引导评价（固定末尾） | `output_format` 的一部分 |

### 2.4 RAG → LLM Wiki 衔接方案

| 层 | 搭搭 DaDa 现状 | SCAI MVP 演进 | 变化 |
|---|---|---|---|
| 意图分类 | `RAGEngineLite.classify_intent()` KEYWORD_MAP 10 类 | **不变** | 业务逻辑层，和知识库格式无关 |
| 知识检索 | `PromptKnowledgeRetriever` 从 DB `knowledge_entries` 表 + 16 个硬编码 DEFAULT_KNOWLEDGE | **改为** 从 LLM Wiki 格式 .md 文件读（frontmatter + 正文 + 双向链接） | DB 表 → .md 文件；SQL → 语义检索 + frontmatter 过滤 |
| 话术模板 | DB `response_templates` 表（JSON） | **保留** | 这是"回复模板"不是"知识" |
| 知识库格式 | DB 表（key/content/keywords/scene/priority） | **.md 文件**，frontmatter 兼容 Karpathy + Obsidian | 选❸兼容模式 |

**LLM Wiki .md 文件 frontmatter 标准（❸ 兼容模式）**：
```yaml
---
title: 知识条目标题
tags: [外卖, 奶茶, CPS]
created: 2026-08-10
source: obsidian  # 或 trae / workbody / manual
verified: true    # Karpathy 特有，Obsidian 用户可省略
aliases: [别名1]  # Obsidian 特有，Karpathy 用户可省略
---
```

---

## 3. message_processor 12 步流水线（以真版 824 行为准）

> ⚠️ V1.0 写的 12 步来自桌面旧版 509 行，V1.1 修正为真版 824 行。差异 14 处。

| 步骤 | 真版代码做的事 | 代码位置（真版） | V1.0 → V1.1 修正 |
|-----:|--------------|-----------------|-----------------|
| 1 | 解析 msg.type/id/sender，判断 is_group/is_private（私聊支持！）| L310-330 | V1.0 漏了私聊支持 |
| 2 | 非文本分流：语音→OCR转文本→转发云端；图片/视频/文件→本地兜底话术；其余跳过 | L331-410 | V1.0 写"全部丢弃"，真版有兜底话术 |
| 3 | 文本空内容过滤 | L411-413 | 不变 |
| 4 | 去重（rate_limiter.is_duplicate，1000 条窗口） | L414-416 | 不变 |
| 5 | 解析 sender_name（遍历 contacts 匹配 wxid） | L417-428 | 不变 |
| 6 | 群聊解析 room_name + @我检测 | L429-447 | 不变 |
| 7 | 内容安全审核（check_text → kanjia 优先 > advertising）→ 违规则发警告 + return | L448-460 | V1.0 写"搭搭DaDa群聊没有"，真版有 |
| 8 | 构造 msg_data → send_to_cloud（POST /api/wcf/receive） | L461-481 | msg_data 多 is_admin_group/is_private 字段 |
| 9 | 云端返回 should_reply=true → _poll_and_send_reply（轮询 /reply） | L482-485 | 不变 |
| 10 | 频控检查（RateLimiter.can_reply：安静时段→每日上限→间隔） | L84-136 | V1.0 写"23:00-8:00"，真版当前全关 0/0/0 |
| 11 | 发送回复（wcf.send_text(reply_text, room_id)）| poll 函数内 | V1.0 桌面版参数顺序反了，真版正确 |
| 12 | 记录历史 + 定时推送（push_scheduler 每 30 秒轮询云端 /push） | L645-689 | V1.0 漏了定时推送 |

### 频控真实值修正

| 配置项 | V1.0 写的 | 真版当前值 | 历史值 |
|--------|----------|-----------|--------|
| quiet_hours_start | 23 | **0（关闭）** | 23（5-6月用过） |
| quiet_hours_end | 8 | **0（关闭）** | 8 |
| daily_push_max | — | **0（不限制）** | 2→50→0 |
| reply_interval_min | 10 分钟 | **0（无间隔）** | 10 |

> 当前是"调试模式"全关。SCAI MVP 建议默认值参考历史：23:00-8:00 + daily_max=50 + interval=10min，但需 YOU-03 拍板。

---

## 4. 已确认的真实数据（直接作为里层 PDD Test Seams 输入）

### 4.1 关键词库（content_moderation.py 真版 128 行）

```
广告词 24 个：加我/加微信/加V/薇信/微我/V我/私聊/私信我/私信/加好友/
             加群/拉群/入群/拉我/佳薇/伽薇/vx/VX/v信/V信/二维码/扫码
砍价词 11 个：砍一刀/帮砍/砍价/助力/投票/拉票/点一下/帮忙点/帮我砍/砍一个/砍完
SPAM_THRESHOLD = 3
USER_FREQUENCY_WINDOW = 10秒
USER_FREQUENCY_MAX = 5条
⚠️ UserFrequencyTracker 是 dead code（导入未使用），SCAI 需新实现接入
```

### 4.2 警告话术

```
kanjia: "⚠️ 检测到疑似砍价/助力链接，这类链接本群不允许发哦～请遵守群规，以免被移出群聊 🙏"
advertising: "⚠️ 检测到疑似引流内容，本群禁止发广告哦～有问题直接在群里说，搭搭帮你找优惠 😊"
```

### 4.3 4 条真实对话链路（Test Seams 假剧本直接用）

| 链路 | 输入 | 预期处理 | 来源日志时间 |
|------|------|---------|-------------|
| ① 用户问优惠 | "能不能直接给优惠我" | 转发云端→云端回复"可以呀，你想找什么优惠？..." | 2026-05-24 18:03 |
| ② 管理指令 | "查看兜底规则" | 转发云端→云端处理管理指令 | 2026-07-14 14:30 |
| ③ 语音消息 | type=34 语音 | MP3→Base64→转发云端→云端回复"收到收到~..." | 2026-05-26 14:59 |
| ④ 安全拦截 | 内容含"加我" | check_text 命中 advertising→发警告话术→return | 2026-06-13 20:01 |

### 4.4 InternalMessage schema（从真版代码提取）

```python
@dataclass
class InternalMessage:
    msg_id: str               # 消息ID
    group_name: str           # 群名 / "私聊"
    group_wxid: str           # 群wxid / 私聊时=sender_wxid
    sender_wxid: str          # 发送者wxid
    sender_name: str          # 发送者昵称
    content: str              # 消息内容
    msg_type: str             # "text"/"voice"/"image"/"video"/"file"
    is_at_me: bool            # 是否@我
    is_admin_group: bool      # 是否管理群
    is_private: bool          # 是否私聊
    is_voice: bool = False    # 语音专属
    voice_data: str = None    # base64 MP3
    image_url: str = None     # 图片专属（预留）
```

### 4.5 contacts 数据结构（wcferry get_contacts() 真实返回）

```python
List[Dict]，每个 contact 含：
wxid / code(微信号) / remark(备注名) / name(昵称) /
country / province / city / gender(已转中文"男"/"女"/"")
```

### 4.6 CPS 五层架构真实代码位置

| 层 | 搭搭 DaDa 代码位置 | 行数 |
|---|---|---|
| ① LLM | .env `DEEPSEEK_API_KEY` + `deepseek_client.py` | — |
| ② Prompt | `ai_core.py` `PromptTemplate.build_reply_prompt()` L711-750 | 40 行 |
| ③ Context | `ai_core.py` `ContextAssembler` L755-997 | 240 行 |
| ④ RAG | `ai_core.py` `RAGEngineLite` L66-221 + `PromptKnowledgeRetriever` L240-549 | 460 行 |
| ⑤ 迭代 | DB `response_templates` 表 + `knowledge_entries` 表 + bad_case 记录 | DB 表 |

### 4.7 真实运行统计

| 指标 | 值 |
|------|---|
| 回复成功 | 362 次 |
| 回复失败 | 7 次 |
| 回复成功率 | 98.1% |
| 安全审核触发 | 1 次（advertising/加我） |
| 频控触发 | 6 次（4 次间隔不足 + 2 次每日上限） |
| ERROR 总数 | 9731 次（99% 是 Push 网络错误，非业务错误） |
| wcferry 版本 | 39.5.2.0 |
| 微信版本 | 3.9.12.51 |

---

## 5. 里层 PDD 模块顺序（V1.1 修正版）

| 顺序 | 模块 | 对应五层 | Test Seams 数据来源 |
|:----:|------|---------|-------------------|
| 1 | `engine/message_processor.py` | 供血系统 | 12 步流水线 + 4 条真实链路 |
| 2 | `bridges/internal_message.py` + `message_router.py` | 神经系统 | InternalMessage schema + contacts 结构 |
| 3 | `engine/safety_shield.py` | 免疫系统 | 关键词库 24+11 + 警告话术 + 频控真实值 |
| 4 | `engine/context_assembler.py` + persona 七段式 | 灵魂+骨架 | ai_core.py ContextAssembler + OFFICIAL_PERSONA + Prompt 4 段结构 |
| 5 | `security/api_key_vault.py` + `engine/aigc_marker.py` | 免疫系统 | DM-05 盖章开关 + Bug #2 明文风险 |
| 6 | `rag/rag_engine.py` + LLM Wiki 衔接 | 骨架(RAG) | RAGEngineLite KEYWORD_MAP + PromptKnowledgeRetriever 16 类 → 改为 .md 文件语义检索 |

---

## 6. 签字区

> 看完后：
> - 口头回复「确认 V1.1」→ 之后所有 PDD 以此为唯一源头
> - 有要改的标章节号 + 你的描述，我出 V1.2

| 角色 | 签字 | 日期 |
|------|------|------|
| 产品/业务（你本人）| _______________ | 2026-08-__ |
| AI 开发方 | Trae（自动） | 2026-08-10 |

---

## 附录：数据来源文件索引

| 来源 | 文件位置 |
|------|---------|
| WCF 真版报告（989 行） | [WCF真实运行数据提取报告_SCAI_PDD输入.md](file:///c:/Users/Administrator/Desktop/WeChatAI_Project/WCF真实运行数据提取报告_SCAI_PDD输入.md) |
| 服务器审计第一轮 | [_server_audit_result.txt](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/docs/_server_audit_result.txt) |
| 服务器审计第二轮 | [_server_audit_result_2.txt](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/docs/_server_audit_result_2.txt) |
| 服务器灵魂提取（ai_core.py 完整） | [_server_audit_result_3_soul.txt](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/docs/_server_audit_result_3_soul.txt) |
| V1.0 原版 | [SCAI_MVP_BUSINESS_ALIGNMENT_V1.0_FINAL.md](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/docs/SCAI_MVP_BUSINESS_ALIGNMENT_V1.0_FINAL.md) |
| 架构依赖图 | [ARCHITECTURE_DEPENDENCY_GRAPH.md](file:///c:/Users/Administrator/Desktop/WeChatAI_Project/docs/ARCHITECTURE_DEPENDENCY_GRAPH.md) |
| PDD 总验收文档 | [PDD_TOTAL_ACCEPTANCE.md](file:///c:/Users/Administrator/Desktop/WeChatAI_Project/docs/PDD_TOTAL_ACCEPTANCE.md) |
