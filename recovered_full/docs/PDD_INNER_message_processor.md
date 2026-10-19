# 里层 PDD · 第 1 模块规格文档 · FINAL
## `engine/message_processor.py` — 供血系统 15 步总调度流水线

> **模块 ID**：INNER-MP01
> **定位**：里层 PDD 第 1 模块 = 供血系统（所有消息 100% 经过这里，决定 12+3 步的顺序和短路条件）
> **对应五层架构**：L1 供血 + 协调 Layers 0~6 执行顺序 + 落库三写点（Chat/Audit/BadCase）
> **覆盖来源**：
> - V1.1 DM/BIZ 16 条决策 + YOU-01/02/03 结论
> - Grill G-01 ~ G-10 10 道拍板
> - Prototype 22 剧本 22/22 全绿
> - 真版 824 行 wcf_bot.py 处理链 + WCF 审计 4 条真实链路 + 关键词库 24+11+SPAM=3
> - ai_core.py 1188 行 ContextAssembler/PromptTemplate 参考

---

## 0. 6 阶段完成度

| 阶段 | 状态 | 本文件章节 |
|-----:|------|-----------|
| ① grill-with-docs | ✅ 通过 | §1 G-01~G-10 |
| ② prototype（throwaway） | ✅ 22/22 全绿 | §2 15 步定义 + Prototype 位置 |
| ③ to-spec（Test Seams = 机器断言）| ✅ **22 条** | §3 22 × Seams 明细 |
| ④ to-tickets | ✅ 7 条 | §4 Tickets T1~T7 |
| ⑤ implement+tdd | ⏳ 待执行（Red→Green）| — |
| ⑥ code-review + 全量回归 | ⏳ 待执行 | §5 双轴评审要点 |

> **再跑 prototype 验证**：`python _prototypes\message_processor_prototype.py` → 输出 `✅ 全部 22 个剧本通过`

---

## 1. Grill G-01 ~ G-10 拍板凝固

| 编号 | Grill 问题 | 决策 |
|-----:|-----------|------|
| G-01 | 处理类型 | ✅ 文字 + 语音（OCR 转文字后处理）❌ 图片/视频/文件/系统通知/撤回（直接跳过，不通知，不 Toast）|
| G-02 | 群聊 vs 私聊 | 私聊全接；群聊必须 @我 或 含触发词（@AI/@搭搭/@分身/AI在吗/搭搭）才触发；管理群例外（全放行给 S06 识别命令）|
| G-03 | 空消息 | 纯空格/空串 → 跳过、不回复、不记历史 |
| G-04 | 去重策略 | ① 1000 msg_id 滑窗 ② 10s 同用户同内容 → 直接丢弃 |
| G-05 | 安全处置 | 砍价 → 发 WARN_KANJIA；广告 → 发 WARN_AD；发完即 return，不调人设/大模型/正常历史 |
| G-06 | 三击拉黑升级 | 24h 命中 ≥3 次 → **拉黑 7 天**（静默丢弃，连发话术都省）；第 1、2 次记 bad_case 待审阅 |
| G-07 | 管理群白名单 | 不走安全、不走频控、不走大模型；识别为命令（3 个默认：查看兜底规则/查看推送配置/查看审核日志）→ 返回执行结果；非命令忽略 |
| G-08 | LLM 兜底 3 档 | ① API Key 无效 → 「AI 配置未完成，请在设置页填写 API Key」② 超时 → 「搭搭正在思考，请稍等...」③ 其他 → 「抱歉，我暂时无法回答，请稍后再试」；兜底回复也盖章 |
| G-09 | 主人自己在微信发消息 | ❌ 分身不回复；✅ 必须同步进好友档案历史（防 AI 风格漂移）；❌ 不走其他流水线 |
| G-10 | 写库规则（含迭代扩展）| chat_history：正常回复 + 主人手动；audit_log：安全命中；**bad_case：3 条触发点（① LLM 兜底 ② 安全 1、2 击待审阅 ③ 用户显式说不对）** = 迭代系统入口 |

---

## 2. 15 步流水线定义

> **对应原型**：`_prototypes/message_processor_prototype.py`（throwaway，Phase 5 正式实现参考）

| 步骤 | 名称 | 做什么 | 对应 Grill |
|-----:|------|--------|-----------|
| S01 | 消息类型检查 | 类型=text/voice 继续；其他类型直接跳过 | G-01 |
| S02 | 群/私场景过滤 | 私聊放行；群聊检查 @/触发词；管理群放行给 S06 | G-02 |
| S03 | 空内容过滤 | content.strip() 为空 → 跳过 | G-03 |
| S04 | 去重 | ① msg_id in 1000 滑窗 ② 10s 同用户同内容 → 跳过 | G-04 |
| S05 | 黑名单前置检查 | 若用户在 7 天黑名单期 → 静默丢弃 | G-06 |
| S06 | 管理群快捷通道 | 管理群识别命令/跳过安全/调大模型 → 返回管理命令结果或忽略 | G-07 |
| S07 | 安全壳 | 砍价→广告→三击拉黑升级；命中则发话术/第 3 击直接丢 | G-05/G-06 |
| S08 | 主人消息仅同步历史 | sender_is_master=True → 只写 chat_history（不回）| G-09 |
| S09 | 意图/阶段分类 | Layer 1+2 正式实现待后续模块 PDD；此处按占位 passthrough | — |
| S10 | 工作包拼装（RAG+人设+历史）| Layer 3+4+5 正式实现待 PDD；此处按占位 passthrough | — |
| S11 | LLM 调用 + 兜底 + AIGC 盖章 | 调 LLM（MVP 里换成正式 llm_generator）；3 档兜底；开启 AIGC 时末尾盖章 | G-08 |
| S12 | 写 ChatHistory（记忆）| 正常回复+主人手动 → 写 chat_history | G-10 |
| S13 | 写 AuditLog（合规留痕）| 安全命中 → 写 audit_log | G-10 |
| S14 | 写 BadCase（迭代错题本入口）| 3 条规则：① LLM 兜底 ② 安全 1、2 击 ③ 用户显式说不对 | G-10 扩展 |
| S15 | 回发渠道 | reply 非空时发回消息渠道 | — |

### 四个短路交叉点（任何一步 stopped_here=true，后续步骤跳过，但 S12~S14 仍按各自规则执行）
- 非文字（S01）、群闲聊未触发（S02）、空内容（S03）、重复消息（S04）、黑名单（S05）、管理群（S06）、安全命中（S07）、主人手动（S08）
- 注意：S07 安全 hit=1/2 击 → stopped_here=true（不写 chat_history，但写 audit_log + S14 bad_case）
- 注意：S08 主人手动 → stopped_here=true（不回，但 S12 写 chat_history）

---

## 3. 22 条 Test Seams 明细

> **机器断言 = 每一条都在 prototype 里跑过 22/22 全绿。Phase 5 TDD：正式 pytest 写这些断言。**

### 3.1 基础 Seams（4 条 = 正常路径）

| ID | 标题 | 输入 | 断言 |
|----|------|------|------|
| SE-01 | 私聊文本 → 正常回复 | 私聊，content="最近有什么奶茶优惠" | reply 非空；action=reply；write_chat_history=True；S01..S11 无 stopped；S15 exists；AIGC 盖章尾存在（默认开）|
| SE-02 | 私聊语音 OCR → 正常回复 | 私聊，msg_type=voice + OCR 文本 | reply 非空；S01.details.type_final=ocr_text |
| SE-03 | 群聊 @我 → 触发 AI | 群聊，is_at_me=True | reply 非空；S02 没 stopped；S12 写 chat_history |
| SE-04 | 群聊触发词（搭搭）→ 触发 | 群聊，content 含"搭搭" | reply 非空；S02.has_trigger_word=True |

### 3.2 边界 Seams（8 条 = 各种短路）

| ID | 标题 | 输入 | 断言 |
|----|------|------|------|
| SE-05 | 群聊无触发 → 静默丢 | 群聊普通闲聊（无@、无触发词）| action=silent_drop；reply 空；all write_*=False |
| SE-06 | 图片跳过 | msg_type=image | action=silent_drop；all write_*=False |
| SE-07 | 空消息跳过 | content="   \n " | action=silent_drop；S03 stopped |
| SE-08 | msg_id 滑窗去重 | 两条同 msg_id，第二条 | 第二条 action=silent_drop；S04.details.决策含滑窗 |
| SE-09 | 10s 同用户同内容去重 | 同一用户同内容连发，第二条 10s 内 | 第二条 action=silent_drop；S04.details.决策含 10s |
| SE-10 | 管理群命令 → 执行返回 | group_wxid=admin-group-master + content="查看兜底规则" | reply 含 `[管理命令] 执行 查看兜底规则`；S06 stopped（not S02）|
| SE-11 | 管理群非命令 → 忽略 | group_wxid=admin-group-master + content="你好" | action=silent_drop；all write_*=False；S06 stopped；early_reply 空 |
| SE-12 | 主人手动同步 → 只写历史不回 | sender_is_master=True + 普通内容 | action=silent_drop；reply 空；write_chat_history=True；S08 stopped；LLM 步骤 skipped |

### 3.3 安全 Seams（5 条 = G-05/G-06）

| ID | 标题 | 输入 | 断言 |
|----|------|------|------|
| SE-13 | 砍价拦截 | 内容含"帮我砍一刀" | reply = WARN_KANJIA；S07.hit 含「砍价=」；write_chat_history=False；write_audit_log=True；S14 bad_case=True, reasons 含「安全命中待审阅：砍价=」 |
| SE-14 | 广告拦截 | 内容含"加我" | reply = WARN_AD；S07.hit 含「广告=」；write_audit_log=True；S14 bad_case=True（待审阅）|
| SE-15 | 安全第 3 击 → 拉黑 7 天静默丢 | 同一用户连续 3 条触发广告 | 第 3 条 action=silent_drop；reply 空；S07.details.升级 含「24h 内命中 3 次 → 拉黑 7 天」|
| SE-16 | 拉黑期内第 4 条 → 黑名单前置拦截 | SE-15 后再发一条（非广告也行）| action=silent_drop；S05.details.决策 含「黑名单」或「剩 168h」 |
| SE-17 | 关键词库完整覆盖 | 24 广告词 + 11 砍价词逐条测试 | 每条都命中对应分类；不出现"砍价被归类成广告"之类的交叉错 |

### 3.4 兜底 + 迭代 Seams（5 条 = G-08 + G-10 扩展）

| ID | 标题 | 输入 | 断言 |
|----|------|------|------|
| SE-18 | 兜底：无 API Key | content 触发 no_api_key | reply 含「AI 配置未完成，请在设置页填写 API Key」；LLM S11.details.fallback=no_api_key；AIGC 盖章存在；S14 bad_case=True（LLM兜底=no_api_key）|
| SE-19 | 兜底：超时 | content 触发 timeout | reply = 「搭搭正在思考，请稍等...」；fallback=timeout；bad_case=True |
| SE-20 | 兜底：其他错误 | content 触发 error | reply = 「抱歉，我暂时无法回答，请稍后再试」；fallback=other_error；bad_case=True |
| SE-21 | 用户显式说不对 → bad_case | content 含 `__你刚才说的不对__`（实际工程里匹配"你刚才说的不对/错了/刚才的回答不对"模式）| bad_case=True，reasons 含「用户反馈：刚才说的不对」|
| SE-22 | 非失败流程不写 bad_case | 正常私聊文本 | bad_case=False；bad_case_reason 空 |

---

## 4. Phase 4 · Tickets（7 条开发任务）

### 开发约束
- 严格按 22 条 Seams 的 TDD 顺序：每个 ticket 先写 Red 测试（失败）→ 写代码 → Green → commit 带 SE-ID
- 禁止先写实现再补测试；100% Red→Green
- 22 条测试写完后，不能挂掉其他已存在的表面 PDD 测试（全量 294 passed）

| ID | 任务标题 | 关联 Seams | 依赖 |
|----|---------|-----------|-----|
| T1 | 搭建 PDD 测试骨架 + 全局 State（去重/黑名单/计数） | SE-08/09/15/16 | — |
| T2 | 实现 S01~S04（类型/群私/空内容/去重）+ 交叉短路写库边界 | SE-05/06/07/08/09 | T1 |
| T3 | 实现 S05~S08（黑名单前置/管理群/安全壳/主人同步）+ 1/2 击 bad_case 写入 | SE-10/11/12/13/14/15/16/17 | T2 |
| T4 | 实现 S09~S10 占位 passthrough（骨架接口），为后续模块留扩展点 | — （不涉及 Seams，只留接口）| T3 |
| T5 | 实现 S11（LLM 调用 + 3 档兜底 + AIGC 盖章）+ dm-05 用户开关控制 | SE-18/19/20 | T4 |
| T6 | 实现 S12~S14（三写落库规则 + BadCase 3 条写入点）| SE-13/14/18/19/20/21/22 | T5 |
| T7 | 全量回归（表面 294 passed）+ 双轴评审（Fowler 异味 + 规格忠实度） | 全部 22 | T1~T6 |

---

## 5. Phase 6 · 双轴评审要点

### 轴 1 · Fowler 代码异味（静态质量）
- ❌ 不准出现 God Class（当前正式 message_processor.py 已经很大了，要拆 function 颗粒度，每个 step 一个内部方法，不要 process() 方法写 200 行）
- ❌ 魔法数字：1000 滑窗、10s、3 次、7 天 → 必须抽成 module-level 常量（和 prototype 里的 ADMIN_GROUP_IDS/KANJIA_KW 一样的做法）
- ❌ 长参数：process() 入参不许超过 5 个；用 Msg dataclass 传
- ❌ 死代码：正式接入时不许出现「导入但未使用」的类（UserFrequencyTracker 是 dead code 的历史教训）
- ❌ 全局可变状态：_State 对应的正式实现要放到 MessageProcessor 实例属性里，不能用模块级 global

### 轴 2 · 规格忠实度（对 22 Seams 1:1）
- 每一条 Seam 的断言都能单独跑
- 3 档兜底文案一字不差
- WARN_KANJIA/WARN_AD 话术逐字一致（来自搭搭 DaDa 真版，改了等于合规边界变化）
- 安全第 3 击 = 绝对不能发话术出去（只 silent_drop + audit）
- 主人手动消息 = 绝对不进入 LLM 流程
- BadCase 写入点 3 条 = 一条不能多一条不能少（严格和 G-10 拍板对应）

---

## 附录：交叉参考凝固索引

| 参考项 | 位置 |
|--------|------|
| V1.1 业务对齐文档 | [SCAI_MVP_BUSINESS_ALIGNMENT_V1.1_FINAL.md](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/docs/SCAI_MVP_BUSINESS_ALIGNMENT_V1.1_FINAL.md) |
| Prototype 源码（throwaway）| [_prototypes/message_processor_prototype.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/_prototypes/message_processor_prototype.py) |
| WCF 真版 824 行报告 | [WCF真实运行数据提取报告_SCAI_PDD输入.md](file:///c:/Users/Administrator/Desktop/WeChatAI_Project/WCF真实运行数据提取报告_SCAI_PDD输入.md) |
| 正式代码（改造对象）| [src/aibridge/engine/message_processor.py](file:///c:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/engine/message_processor.py) |
| 表面 PDD 294 passed 总验收 | [PDD_TOTAL_ACCEPTANCE.md](file:///c:/Users/Administrator/Desktop/WeChatAI_Project/docs/PDD_TOTAL_ACCEPTANCE.md) |
| 架构依赖图（模块依赖顺序）| [ARCHITECTURE_DEPENDENCY_GRAPH.md](file:///c:/Users/Administrator/Desktop/WeChatAI_Project/docs/ARCHITECTURE_DEPENDENCY_GRAPH.md) |
