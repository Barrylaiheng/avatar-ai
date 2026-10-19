# 里层 PDD · 第 3 模块规格文档 · FINAL
## `engine/context_assembler_v2.py` — 神经 L4 · Persona 注入 + RAG 检索 + Prompt 组装

> **模块 ID**：INNER-CA03
> **定位**：里层 PDD 第 3 模块 = 神经系统（message_processor S10 的真实实现）
> **五层架构**：L4 神经
> **覆盖来源**：V1.1 YOU-01 七段式人设拍板 + message_processor S10 骨架

---

## 0. 6 阶段完成度

| 阶段 | 状态 | 说明 |
|-----:|------|------|
| ① grill | ✅ | CA-01~CA-08 自问自答 |
| ② prototype | ✅ 8/8 | [_prototypes/context_assembler_prototype.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/_prototypes/context_assembler_prototype.py) |
| ③ to-spec | ✅ 8 Seams | 下文 §3 |
| ⑤ implement+tdd | ✅ 8/8 | [tests/test_inner_context_assembler_pdd.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/tests/test_inner_context_assembler_pdd.py) |
| ⑥ 回归+评审 | ✅ | 40 passed（22 MP + 10 SS + 8 CA） |

---

## 1. Grill 拍板

| 编号 | 问题 | 决策 |
|-----:|------|------|
| CA-01 | 职责 | ContextAssemblerV2 只管：① Persona → system message ② RAG 检索 → knowledge 注入 ③ 历史截断 ④ 组装 messages 数组。不管 LLM 调用（S11） |
| CA-02 | 七段式 | 身份/语气/知识边界/回复规则/安全底线/示例/语言风格 → 对齐 V1.1 YOU-01 |
| CA-03 | RAG 接口 | `search(query, top_k)` → `List[RagHit]`；MockRagEngine 占位，正式版替换为向量检索/LLM Wiki |
| CA-04 | 历史窗口 | 默认 10 轮（20 条），超出截断尾部保留最新 |
| CA-05 | messages 格式 | `[{role: "system", content}, {role: "user", content}, {role: "assistant", content}, ...]` — OpenAI 标准格式 |

---

## 2. 核心接口

| 方法 | 入参 | 返回 | 说明 |
|------|------|------|------|
| `assemble_prompt(current_content, history, rag_query, persona)` | current_content, history, rag_query, persona | `AssembledPrompt(messages, persona_used, rag_hits, history_count, truncated)` | S10 调用 |
| `set_persona(persona)` | PersonaTemplate | void | 动态切换人设 |
| `set_rag_engine(rag_engine)` | Any | void | 动态切换 RAG 引擎 |

---

## 3. 8 条 Test Seams

| ID | 标题 | 断言 |
|----|------|------|
| CA-01 | 基础 assemble | 2 条 messages（system+user） |
| CA-02 | persona 注入 | system 含身份/语气关键词 |
| CA-03 | RAG 命中 | system 含"检索到的知识" + 具体内容 |
| CA-04 | RAG 无命中 | system 不含"检索到的知识" |
| CA-05 | 历史截断 | truncated=True, history_count=20 |
| CA-06 | messages 结构 | roles = [system, user, assistant, user] |
| CA-07 | 七段式完整 | 7 个段名都在 system prompt 里 |
| CA-08 | 空 history | 2 条 messages, history_count=0 |

---

## 4. 双轴评审

### 轴 1 · Fowler
- ✅ 单一职责：只管 prompt 组装，不调 LLM
- ✅ 无魔法数字：HISTORY_WINDOW=10 是类常量
- ✅ 可注入：rag_engine / persona 都可运行时替换

### 轴 2 · 规格忠实度
- ✅ 七段式与 V1.1 YOU-01 拍板一致
- ✅ messages 格式与 OpenAI 标准兼容
- ✅ message_processor S10 从 passthrough → 真实调用

---

## 5. 交付物

| 产物 | 位置 |
|------|------|
| Prototype | [_prototypes/context_assembler_prototype.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/_prototypes/context_assembler_prototype.py) |
| 正式实现 | [src/aibridge/engine/context_assembler_v2.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/engine/context_assembler_v2.py) |
| 测试 | [tests/test_inner_context_assembler_pdd.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/tests/test_inner_context_assembler_pdd.py) |
| S10 接入 | [message_processor.py S10](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/engine/message_processor.py#L965-L995) |
