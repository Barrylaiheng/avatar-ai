# SCAI MVP · 里层 PDD 规格文档 · 模块 7
# 模块：INNER-UI07 · UI ↔ Engine 数据流打通

> **版本**：v1.0
> **生成日期**：2026-08-10
> **前置**：[PDD_INNER_TOTAL_ACCEPTANCE.md](./PDD_INNER_TOTAL_ACCEPTANCE.md)（v3.0，模块 1-6 全绿）
> **原型**：[_prototypes/ui_engine_flow_prototype.py](../_prototypes/ui_engine_flow_prototype.py)（15 Seams 全绿）

---

## §1 模块定位

**一句话**：把表层 UI 组件（ChatPage / PersonaEditor / Workbench / SettingsPage）和里层 Engine（AppEngine + MessageProcessorV2 + ContextAssemblerV2 + KarpathyWikiReader）用标准接口串联起来，确保 UI 层的每个用户动作都有对应的 Engine 响应，且响应可测试。

### 为什么是模块 7？

里层模块 1~6 已经把 engine 内部 15 步流水线、安全壳、人设装配、迭代系统、桥接层、RAG→LLM Wiki 全部做通。但 engine 代码还是"独立运行"状态，UI 层（ChatPage 发消息按钮、PersonaEditor 保存按钮、WCF 连接按钮等）点击后，怎么调用 engine、engine 返回什么结构、返回后 UI 怎么渲染——这些**跨层的数据流契约**还没有用 PDD 固化。

模块 7 就是：**把 UI→Engine 的 15 条契约（Test Seams）写入机器可验证测试**，作为表层 UI 对接时的验收标准。后续表层 UI 开发时，只需对照本模块的返回结构渲染，不用关心 engine 内部。

---

## §2 Grill 清单（已拍板）

| # | 决策 | 拍板 |
|---|------|------|
| UI-G1 | 对话场景分流 | ChatPage（搭建对话）走 `AppEngine.process_message`（无 WCF/安全壳 S07）；Workbench（微信真实消息）走 `process_v2`（15 步流水线） |
| UI-G2 | KarpathyWikiReader 初始化时机 | AppEngine.initialize(kb_root=...) 时构造 Reader 并注入 ContextAssemblerV2._rag_reader |
| UI-G3 | Persona 注入链路 | PersonaEditor 保存 → AppEngine.save_persona(dict) → 同时写入 ContextAssemblerV2 + MessageProcessorV2 内的 PersonaTemplate |
| UI-G4 | KB 开关联动 | ChatPage 顶部 KB Switch → set_kb_enabled(bool) → process_message 内 rag 步骤是否执行 |
| UI-G5 | 返回结构稳定 | process_message 返回必须包含：content / is_aigc / tool_calls / rag_count / model / tokens_in / tokens_out / safety_check 这 8 个字段（即使 tool_calls 为空数组也必须有） |
| UI-G6 | Workbench 消息列表 | Tab 切「微信」→ engine.get_channel_messages("wechat", limit=50) → 渲染消息卡片 |
| UI-G7 | Workbench 手动回复 | 选联系人 → 输入 → send_channel_message("wechat", target_wxid, text) → 通过 WCF 发送 |
| UI-G8 | WCF 连接流程 | connect_wcf() → 构造 WcfAdapter(message_callback=_on_wcf_message) → adapter.start()；disconnect 则 stop + 置空 |
| UI-G9 | 主人 wxid 注入 | SettingsPage 填写主人 wxid → set_master_wxid("wxid_xxx") → process_v2 S08 判断 sender_is_master |
| UI-G10 | AIGC 标识开关 | 设置页 AIGC 开关 → save_settings({"aigc_explicit": bool}) → AigcExplicitLabeler.enable/disable |
| UI-G11 | LLM API Key | 保存 provider + api_key → save_settings() → LLMGenerator.set_config + test_llm_connection |

---

## §3 Test Seams 定义（15 条，机器可验证）

### §3.1 断言规则说明

- 每条 Seam 对应一个 pytest 测试函数：`test_uiXX_name()`
- 断言用 `assert` 表达；失败时附带 **可读原因**（使用 pytest 的 `-v` 输出）
- **不使用真实外部依赖**（不启动 Qt、不连真实 WCF、不调真实 LLM）。使用 Mock 组件或本地纯函数。

---

### §3.2 Seam 列表

| ID | 标题 | 输入 | 断言要点 |
|----|------|------|---------|
| UI-01 | PersonaEditor 保存 → engine.persona 更新 | save_persona(7 字段 dict) + get_persona() | identity/tone/reply_rules/safety_bottomline/examples/language_style 全部与输入一致；identity 首字段必相等 |
| UI-02 | AppEngine 初始化注入 RAG | initialize(kb_root="/mock") + process_message("PDD 是什么？") | 未 init 时 rag_count=0；init 后 rag_count>=1；system_has_knowledge=True |
| UI-03 | ChatPage 正常发消息 | 配好 Key → process_message("你好") | content 非空；is_aigc=True；返回包含全部 8 个核心字段 |
| UI-04 | KB 开关切换 | init(kb_root) → set_kb_enabled(False) → process_message("PDD") | True 时 rag_count>=1；False 时 rag_count=0；is_kb_enabled() 状态对应 |
| UI-05 | tool_calls 字段稳定 | 任意输入 process_message | "tool_calls" 字段存在；类型为 list（可能为空，但不能缺失/None） |
| UI-06 | Workbench 微信消息列表 | connect_wcf → 模拟收 2 条 → get_channel_messages("wechat") | 返回 len>=2；channel='mp' 返回 [] |
| UI-07 | Workbench 手动发送 | connect → send_channel_message("wechat", target, text) | WCF 连接时返回 True，断开/错渠道时返回 False；sent 队列记录+1 |
| UI-08 | WCF 连接状态切换 | connect_wcf() / disconnect_wcf() | init=False → connect=True → disconnect=False |
| UI-09 | WCF 收消息→处理→回发→写 Store | connect + 配 Key + _on_wcf_message(user_msg) | MessageStore._records len>0（写入 history）；WcfAdapter._sent len>0（回发） |
| UI-10 | 主人消息→只同步历史不回复 | set_master_wxid(wxid) + 发一条主人消息 | WcfAdapter._sent len 不变（不回发）；Store 写入 direction=out |
| UI-11 | AIGC 显式标识开关 | aigc_explicit=False→True 分别 process_message | 关时回复不以"[AI]"结尾；开时必以"[AI]"结尾 |
| UI-12 | LLM API Key 保存与测试 | 未配 Key→test_llm_connection 失败；配有效 Key→成功 | 未配 success=False；配后 success=True 且返回 model 非空 |
| UI-13 | 七段式 Persona 拼装 | 默认完整人设 process_message → persona_segments；缺 1 段人设 → persona_segments | 完整 =7；缺 knowledge_boundary 段 =6 |
| UI-14 | RAG 命中 rag_count 正确 | init + PDD 查询/无关查询 | 命中 >=1；无关 =0 |
| UI-15 | BadCase 写入可查 | 不配 Key → process_message → get_bad_cases() | bad_case 数量 >=1；reasons 中包含"API Key 未配置"关键字 |

---

## §4 开发任务清单（to-tickets）

基于 PDD 规格，拆分为以下实现任务：

### §4.1 AppEngine 层新增/完善接口（已存在 app_engine.py，补完方法）

| TID | 任务 | 说明 | 对应 Seam |
|-----|------|------|----------|
| T-UI-01 | save_persona(persona_dict) -> bool + get_persona() -> dict | 对齐七段式字段，同步更新 ctx._persona + mp 内 persona 引用 | UI-01 / UI-13 |
| T-UI-02 | initialize(kb_root: str) -> bool | 构造 KarpathyWikiReader（失败降级）并注入 ctx._rag_reader | UI-02 |
| T-UI-03 | process_message(user_input, session_id) -> dict | 返回 8 字段标准结构，含 persona_segments、rag_count、system_has_knowledge 调试字段 | UI-03/04/05/11/12/13/14 |
| T-UI-04 | set_kb_enabled(bool) + is_kb_enabled() | 保存 _kb_enabled，process_message 内判断是否 rag 检索 | UI-04 |
| T-UI-05 | get_channel_messages(channel, limit, offset) -> list + send_channel_message(channel, target, content) -> bool | channel='wechat' 时从 MessageStore 查 / WCF 发 | UI-06/07 |
| T-UI-06 | connect_wcf() -> bool + disconnect_wcf() + is_wcf_connected() + _on_wcf_message(msg) | 构造/销毁 WcfAdapter；message_callback 调 process_v2 并回写 Store + S15 回发 | UI-08/09 |
| T-UI-07 | set_master_wxid(wxid) | 调 mp.set_master_wxid | UI-10 |
| T-UI-08 | save_settings(dict) -> bool + test_llm_connection() -> dict | aigc_explicit / aigc_prefix / provider / api_key 配置 | UI-11/12 |
| T-UI-09 | get_bad_cases(limit) -> list | 透传 iteration_engine.get_badcases | UI-15 |

### §4.2 测试任务

| TID | 任务 | 说明 |
|-----|------|------|
| T-UI-10 | 新建 tests/test_inner_ui_engine_pdd.py | 对应 §3.2 15 条 Seam，全部用 pytest 实现，AppEngine 可 mock 外部依赖 |

---

## §5 PDD 接口契约（process_message 返回结构）

所有 UI 层 ChatPage 对话渲染必须基于以下返回结构（类型契约）：

```python
{
    # 核心三字段（ChatPage 气泡渲染必需）
    "content": str,                     # 回复正文（已 AIGC 盖章 / 兜底文案）
    "is_aigc": bool,                    # True 时渲染 AIGC 标识
    "tool_calls": list,                 # 工具调用卡片；空数组时不渲染（字段必存在）

    # 调试 & 指标字段（气泡小尾巴 / 侧边栏统计）
    "rag_count": int,                   # RAG 命中数；ChatPage KB 状态灯
    "system_has_knowledge": bool,       # system prompt 是否注入了"【检索到的知识】"
    "persona_segments": int,            # 人设拼装了几段（完整=7）
    "intent": "chat" | "tool" | ...,    # 意图标签（V2 扩展）
    "model": str,                       # 实际使用的模型名
    "tokens_in": int,                   # prompt 消耗 tokens
    "tokens_out": int,                  # 回复消耗 tokens

    # 状态字段（UI Toast / 跳转）
    "safety_check": "passed" | "blocked",  # 安全壳结果
    "fallback": "",                     # "no_api_key"/"timeout"/"other"/""
    "bad_case_written": bool,           # True 时跳转迭代页提示
    "aigc_metadata": {                  # AIGC 标识详情（合规 7.15）
        "implicit": True,               # 隐式标识=始终为 True（7.15 盖章法）
        "explicit": bool,               # True=显式标识开启，回复结尾追加 [AI]
    } if is_aigc else {},
}
```

### 缺失字段的处理规范（UI 侧）
- 任何缺失字段 = 使用默认值，**不能崩溃**。ChatPage 用 `result.get("key", default)` 取值。
- `content` 缺失 → 提示"回复为空，稍后重试"。
- `is_aigc` 缺失 → 默认 False（不显示 AIGC 标识）。

---

## §6 Acceptance 运行命令

```bash
cd C:\Users\Administrator\Desktop\WeChatAI_Project
python -m pytest tests/test_inner_ui_engine_pdd.py -v
```

预期：**15 passed**。
