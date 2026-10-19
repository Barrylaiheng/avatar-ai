# PDD 规格 · 模块 14：Conversation Streaming（LLM SSE + UI 打字机效果）

> **PDD 阶段**：grill ✅ → prototype ✅（10/10 断言通过）→ to-spec ✅（本文档）→ to-tickets ✅ → implement+tdd ⏳ → code-review ⏳
> **前置模块**：M-10 App Bootstrap Wiring、M-11 Persona Injection Chain、M-13 Settings Data Sync
> **Grill 总数**：10 条 → 原型 10/10 断言通过（2026-08-12）
> **TD 决策**：7 条已确认（用户 2026-08-12 拍板，全部采纳建议方向）

---

## 0. 业务背景 + 当前同步路径画像

### 0.1 业务痛点（大白话）

当前用户在 ChatPage 发送一条消息后：
1. 输入框清空，AI 气泡区域出现"…"打字指示器（typing widget）
2. **整个 LLM 生成期间（DeepSeek ~3-8s，豆包 ~2-5s），UI 完全静止，用户看不到任何进展**
3. LLM 返回完整 content 后，AI 气泡"突然"出现一整段文字
4. 用户感知为"卡死 3-8 秒"，体验差

模块 M-14 的目标：**把 LLM 生成从"一次性返回"改为"SSE 流式逐 token 追加"**，UI 在 LLM 开始吐字后立即显示（首字 < 500ms），逐字追加显示，结束后切换 AIGC 徽标 + 元数据落库。

### 0.2 当前同步路径画像（C-1 代码审计）

```
ChatPage._on_send_click(text)
  └─ bridge.start_send_message(text, on_success, on_error)
       └─ SendMessageWorker.start()
            ├─ emit typing_start           ← UI 显示 "…" 打字指示器
            └─ QThread.run()
                 └─ SendMessageWorker.sync_run(engine, user_input, channel)
                      └─ engine.process_message(user_input, channel)   ← with self._lock 同步阻塞
                           ├─ 合规壳 → 业务壳 → 意图识别 → 上下文装配 → RAG 检索
                           ├─ role_config 装配（人设注入，M-11 已修复）
                           ├─ self._llm_generator.generate(role_config, context, rag_result)
                           │    ├─ PromptAssembler.assemble → messages
                           │    ├─ self._llm_client.chat_completion(messages)
                           │    │    └─ self._client.chat.completions.create(**kwargs)   ← 一次性返回
                           │    ├─ explicit_labeler.label(content)   ← AIGC 显式标识
                           │    └─ implicit_marker.mark_message(record)   ← AIGC 隐式标识
                           ├─ IterationEngine.record_interaction
                           └─ return 8 字段 dict
            ├─ emit typing_stop
            └─ emit success(dict)  /  error(str)
       └─ ChatPage._on_engine_reply(result)
            └─ 构造完整 _ChatMessage → append → _render_messages()   ← 整体重绘
```

**4 个阻塞断点**：
- B1：`LLMClient.chat_completion` 一次性等 LLM 完整响应（3-8s）
- B2：`AppEngine.process_message` 在 `self._lock` 内同步阻塞（持有锁期间 UI Worker 无法被中断）
- B3：`SendMessageWorker` 只有 success/error 两个终态信号，**没有 chunk 推送信号**
- B4：`ChatPage._render_messages` 整体重绘，**没有"流式气泡逐字追加"的局部刷新机制**

---

## 1. Grill 清单（10 条用户验收问题，全部机器可断言）

| Grill | 验收问题（大白话） |
|---|---|
| **G1** | LLMClient 有一个新的流式调用接口 `chat_completion_stream(messages, ...)`，返回 generator，**首次 yield delta 的时间 < 500ms**（用 mock LLM 验证，模拟 SSE 首字延迟） |
| **G2** | LLMGenerator 有一个新的流式接口 `generate_stream(role_config, context, rag_result)`，返回 generator；迭代所有 chunk 拼接的字符串，**等于 final 事件里的 content**（不丢字、不重复） |
| **G3** | AppEngine 有一个新的流式接口 `process_message_stream(user_input, session_id)`，返回 generator；**第一个 yield 是 start 事件**（含 persona_name / session_id / intent），让 UI 知道"开始流式了" |
| **G4** | 安全壳拦截时，`process_message_stream` 不进入 LLM 流式调用，**直接 yield 一个 error 事件**（含 safety_check=blocked / safety_reason），UI 显示拦截气泡，不显示流式气泡 |
| **G5** | `process_message_stream` 流式期间 yield 的所有 chunk 拼接，**等于 final 事件里的 content**（端到端不丢字） |
| **G6** | `process_message_stream` 的 final 事件包含**完整 8 字段**（content / is_aigc / rag_count / persona_name / safety_check / tool_calls / session_id / success），与现有 `process_message` 同步返回的 dict 字段完全对齐 |
| **G7** | SendMessageWorker 新增 `chunk_received(str)` 信号，在 `success(dict)` 之前**至少触发 1 次**；新增 `stream_started(dict)` 信号在 chunk 之前触发；`typing_stop` 在 `success` 之后触发 |
| **G8** | SendMessageWorker 有一个 `sync_run_stream(engine, user_input, channel) → generator` 纯函数接口（给 pytest 用），迭代可拿到 start / chunk / final / error 四类事件，**不依赖 QEventLoop** |
| **G9** | ChatPage 流式渲染：start 事件创建占位气泡（content="" + "⏳ AI 生成中"徽标）；chunk 事件追加 delta 到占位气泡 content，**局部刷新该气泡（不整体 _render_messages）**；final 事件把占位气泡的 is_aigc / rag_count / persona_name 元数据补齐，徽标从"⏳ AI 生成中"切换为"✨ AI 生成" |
| **G10** | 流式中途异常（断网 / LLM 中断）：已生成的部分内容**保留显示**，气泡追加"⚠️ 生成中断：{错误}"提示，final 事件标记 `success=False` + `partial=True`，元数据正常落库 |

---

## 2. 根因探查（4 个阻塞断点）

### 2.1 LLMClient 层（B1）
- R1.1：`chat_completion` 调用 `self._client.chat.completions.create(**kwargs)` 时**未传 `stream=True`**，OpenAI 客户端默认等完整响应。
- R1.2：**没有 `chat_completion_stream` 方法**，OpenAI Python SDK 已支持 `stream=True` + 迭代 `response` 拿 `delta.content`，但本层未封装。
- R1.3：流式期间 `usage`（tokens_in / tokens_out）**不在 chunk 里**，需要在最后一个 chunk 或 stream end 时单独拿（OpenAI 在 `stream_options={"include_usage": True}` 时才会推送 usage chunk）。

### 2.2 AppEngine 层（B2）
- R2.1：`process_message` 在 `with self._lock` 内同步执行整个流程，**流式期间锁不能释放**（否则人设/设置可能被并发改），但锁持有期间 generator 不能 yield 给 UI（Qt 跨线程信号可以，但要确保 yield 后锁状态可控）。
- R2.2：**没有 `process_message_stream` 方法**，需要拆分：前半段同步（安全壳→意图→上下文→RAG→role_config）→ yield start → 迭代 LLM stream → yield chunk → 后处理 → yield final。
- R2.3：AIGC 显式标识 `explicit_labeler.label(content)` 是对**完整 content** 操作（加前缀 `[AI]`），流式期间不能逐 chunk 加（会变成 `[AI]chunk1[AI]chunk2...`），需要在 final 阶段统一过一次。

### 2.3 SendMessageWorker 层（B3）
- R3.1：现有信号只有 `success(dict)` / `error(str)` / `typing_start()` / `typing_stop()`，**没有 chunk 推送信号**。
- R3.2：`sync_run` 是阻塞函数返回 `(ok, result, signals)`，**不是 generator**，无法表达流式过程。
- R3.3：`start()` 内的 QThread.run 调 `sync_run` 后 emit 一次信号就结束，**没有迭代 generator + 多次 emit chunk 的循环结构**。

### 2.4 ChatPage 层（B4）
- R4.1：`_on_engine_reply(result)` 一次性构造完整 `_ChatMessage` 并 append，**没有"占位气泡 + 逐字追加"机制**。
- R4.2：`_render_messages` 每次清空所有气泡重新构造，**流式期间如果走这个路径会闪烁严重 + 性能差**；需要新增"局部刷新单个气泡"的方法。
- R4.3：`_MessageBubble` 构造时读 `msg.is_aigc` 决定是否显示 AIGC 徽标，**流式期间 is_aigc 还没确定**（要等 final），需要支持"先生成中徽标 → 结束后切换"。

---

## 3. 修复方案（4 层，对应 Grill）

### 3.1 LLMClient 层：新增 `chat_completion_stream`（对应 G1）
```python
def chat_completion_stream(self, messages, tools=None, tool_choice=None,
                           temperature=None, max_tokens=None) -> Generator[Dict, None, None]:
    """流式调用 LLM，yield 事件 dict
    yield 事件类型：
        {"type": "chunk", "delta": "token_text"}
        {"type": "final", "content": full_content, "usage": {...}, "latency_ms": int, "model": str}
        {"type": "error", "error": str}
    """
    kwargs = {"model": model, "messages": messages, "temperature": t, "max_tokens": mt,
              "stream": True, "stream_options": {"include_usage": True}}
    if tools: kwargs["tools"] = tools
    if tool_choice: kwargs["tool_choice"] = tool_choice
    
    start_time = time.time()
    full_content_parts = []
    usage_info = None
    try:
        response = self._client.chat.completions.create(**kwargs)
        for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                delta = chunk.choices[0].delta.content
                full_content_parts.append(delta)
                yield {"type": "chunk", "delta": delta}
            if chunk.usage:  # 最后一个 chunk 带 usage
                usage_info = chunk.usage
        yield {
            "type": "final",
            "content": "".join(full_content_parts),
            "usage": {"tokens_in": usage_info.prompt_tokens if usage_info else 0,
                      "tokens_out": usage_info.completion_tokens if usage_info else 0},
            "latency_ms": int((time.time() - start_time) * 1000),
            "model": model,
        }
    except Exception as e:
        yield {"type": "error", "error": str(e)}
```

### 3.2 LLMGenerator 层：新增 `generate_stream`（对应 G2）
- 迭代 `llm_client.chat_completion_stream(messages)`：
  - chunk 事件：原样 yield（不加 AIGC 标识，避免逐 chunk 重复）
  - final 事件：对完整 content 过 `explicit_labeler.label(content)` + `implicit_marker.mark_message(record)`，yield final dict（含 content/message_record/llm_response）
  - error 事件：原样 yield

### 3.3 AppEngine 层：新增 `process_message_stream`（对应 G3/G4/G5/G6/G10）
- **前半段同步**（在 `with self._lock` 内）：合规壳 → 业务壳 → 意图 → 上下文 → RAG → role_config
- 安全壳失败：yield `{"type": "error", "safety_check": "blocked", "safety_reason": ..., "success": False}` 后 return
- 安全壳通过：yield `{"type": "start", "persona_name": ..., "session_id": ..., "intent": ...}` 后**释放锁**（关键决策 TD-2）
- **流式阶段**（不在锁内）：迭代 `llm_generator.generate_stream`：
  - chunk → yield `{"type": "chunk", "delta": ...}`
  - final → 后处理（AIGC 标识已由 generator 处理）+ IterationEngine.record_interaction → yield `{"type": "final", ...8字段dict}`
  - error → yield `{"type": "error", "error_message": ..., "partial_content": 已生成部分, "success": False, "partial": True}`

### 3.4 SendMessageWorker 层：新增流式信号 + sync_run_stream（对应 G7/G8）
- 新增 3 个信号：`stream_started(dict)` / `chunk_received(str)` / `stream_final(dict)`
- 新增静态方法 `sync_run_stream(engine, user_input, channel) → Generator[Dict, None, None]`：纯函数式，迭代 `engine.process_message_stream`，原样 yield 事件 dict（pytest 直接迭代验证）
- 新增 `start_stream(engine, user_input, channel)`：QThread.run 内迭代 sync_run_stream generator，按事件类型 emit 不同信号：
  - start 事件 → emit `stream_started(dict)` + `typing_start()`
  - chunk 事件 → emit `chunk_received(str)`
  - final 事件 → emit `stream_final(dict)` + `typing_stop()` + `success(dict)`
  - error 事件 → emit `error(str)` + `typing_stop()`

### 3.5 UIEngineBridge 层：新增 `start_send_message_stream`（外观 Facade）
- 新增方法：`start_send_message_stream(user_input, channel, on_stream_started, on_chunk, on_stream_final, on_error) → StreamSendMessageWorker`
- 内部创建 worker，绑定信号到回调

### 3.6 ChatPage 层：流式渲染（对应 G9/G10）
- 新增 `self._streaming_bubble: Optional[_MessageBubble] = None` 跟踪当前流式气泡
- `_on_engine_stream_start(meta)`：创建占位 `_ChatMessage`（content=""），append 到 session，构造 `_MessageBubble` 但**徽标显示"⏳ AI 生成中"**，存到 `self._streaming_bubble`
- `_on_engine_chunk(delta)`：把 delta 追加到占位 message 的 content，**调用 `_streaming_bubble.update_content(new_content)` 局部刷新**（不调 `_render_messages`）
- `_on_engine_stream_final(result)`：把 is_aigc / rag_count / persona_name 元数据补到占位 message，调用 `_streaming_bubble.finalize(result)` 切换徽标为"✨ AI 生成" + 追加 RAG 命中标签，清空 `self._streaming_bubble`
- `_on_engine_stream_error(err_msg)`：在占位气泡后追加"⚠️ 生成中断：{err_msg}"，徽标切换为"⚠️ 生成失败"，清空 streaming_bubble
- `_MessageBubble` 新增 `update_content(text)` 和 `finalize(result_dict)` 方法

---

## 4. 关键技术决策（7 条 TD，已确认）

### TD-1：流式只解决"首字感知"，不缩短总时长 ✅
**决策**：M-14 的目标是**首字 < 500ms + 逐字追加显示**，让用户感知"AI 在干活"；总生成时长不变（仍 3-8s）。  
**为什么**：LLM 总 token 数不变，流式只是把"等待 → 一次性显示"变成"等待 → 逐字显示"，不改变 LLM 实际耗时。  
**确认状态**：用户 2026-08-12 拍板接受。

### TD-2：流式期间锁释放策略 ✅
**决策**：`process_message_stream` 前半段（安全壳/意图/RAG/role_config）在 `with self._lock` 内同步执行，yield start 事件后**释放锁**，流式阶段不在锁内。  
**为什么**：流式期间 LLM 调用 3-8s，如果持有锁，期间用户保存人设/设置会阻塞 UI（M-12/M-13 的回调机制无法触发）。释放锁后，人设/设置可并发改（但本轮 LLM 已用旧 role_config，下一轮才生效，符合产品预期）。  
**权衡**：极小概率并发问题——用户在 LLM 流式期间保存新人设，本轮回复用旧人设，下一轮用新人设。可接受。  
**确认状态**：用户 2026-08-12 拍板接受。

### TD-3：安全壳策略（输入壳前处理，输出壳后处理）✅
**决策**：
- **输入壳**（合规 + 业务）：在流式开始**前**同步执行，拦截则不进入 LLM 流式，直接 yield error 事件
- **输出壳**（AIGC 显式标识 + 隐式标识）：在流式**结束**时对完整 content 统一过一次，不在 chunk 期间逐字加
**为什么**：① 流式期间逐 chunk 加 `[AI]` 前缀会变成 `[AI]chunk1[AI]chunk2`；② 输出违规词检测如果流式期间做，部分违规内容已显示给用户，拦截意义不大。  
**权衡**：流式期间显示的"原始 LLM 输出"可能含违规词（极小概率，因为输入壳已过滤），final 时才加 AIGC 标识。可接受（MVP 阶段）。  
**确认状态**：用户 2026-08-12 拍板接受。

### TD-4：process_message 同步路径保留 ✅
**决策**：保留现有 `process_message` 同步方法，**不删除不重构**，新增 `process_message_stream` 并行存在。  
**为什么**：① 公众号云端服务（M-7'）的 5s 占位回复需要同步路径（流式不适合 5s 限制场景）；② 现有 251 条 pytest 全部基于同步路径，删除会破坏 M-1~M-13 全部基线；③ 渐进式改造，降低风险。  
**确认状态**：用户 2026-08-12 拍板同意。

### TD-5：mock 路径流式兼容 ✅
**决策**：ChatPage 没有 bridge 时（向后兼容场景）走 mock，mock 路径**也改为流式**（QTimer 定时推送 chunk），保持 UI 行为一致。  
**为什么**：如果 mock 走同步、真实走流式，UI 需要两套渲染逻辑，维护成本高。  
**权衡**：mock 路径增加少量复杂度，但 UI 统一为流式渲染。  
**确认状态**：用户 2026-08-12 拍板同意。

### TD-6：错误恢复策略 ✅
**决策**：流式中途异常（断网 / LLM 中断）：① 已生成的部分内容**保留显示**；② 气泡追加"⚠️ 生成中断：{错误}"提示；③ final 事件标记 `success=False` + `partial=True`；④ 元数据正常落库（content 为已生成部分）。  
**为什么**：用户已看到的部分内容是有意义的，不应清空；partial 标记便于后续 BadCase 收集（M-11 IterationEngine）。  
**确认状态**：用户 2026-08-12 拍板接受。

### TD-7：AIGC 徽标动态状态 ✅
**决策**：流式期间气泡底部徽标显示"⏳ AI 生成中"（灰色），final 事件后切换为"✨ AI 生成"（绿色，is_aigc=True 时）或隐藏（is_aigc=False 时）。  
**为什么**：① 流式期间 is_aigc 还没确定（要等 final）；② "生成中"徽标给用户明确的进度感知；③ 合规要求 AIGC 标识必须在内容展示时伴随（流式期间用"生成中"占位，结束后切换为正式标识，符合合规精神）。  
**确认状态**：用户 2026-08-12 拍板同意。

---

## 5. Grill → pytest 映射预估

| Grill | 预估 pytest 数 | 验证方式 |
|---|---|---|
| G1 | 2 | mock LLMClient，断言 generator 首次 yield < 500ms + chunk 结构正确 |
| G2 | 2 | mock LLMClient 推 3 个 chunk，断言拼接 == final.content |
| G3 | 2 | 真实 AppEngine + mock LLM，断言首个 yield 是 start 事件 + 字段齐全 |
| G4 | 2 | 输入违规词，断言 yield error 事件 + safety_check=blocked + 不进入 LLM |
| G5 | 2 | mock LLM 推 N 个 chunk，断言拼接 == final.content（端到端） |
| G6 | 2 | 断言 final 事件 8 字段齐全 + 与同步路径 process_message 返回字段对齐 |
| G7 | 2 | SendMessageWorker 信号顺序：stream_started → chunk_received ≥1 → stream_final / success |
| G8 | 2 | sync_run_stream 返回 generator，pytest 迭代断言 4 类事件 |
| G9 | 3 | ChatPage 流式渲染：占位气泡创建 / chunk 追加局部刷新 / final 徽标切换 |
| G10 | 2 | mock LLM 中途抛异常，断言已生成部分保留 + partial=True + 错误提示 |
| **合计** | **~21** | 与 M-12（22）/ M-13（63）量级相当 |

---

## 6. 推进计划（PDD 6 阶段）

| 阶段 | 产出物 | 状态 |
|---|---|---|
| 1 grill | 本文档 §1 Grill 清单 + §4 TD 决策点 | ✅ |
| 2 prototype | `_prototypes/conversation_streaming_prototype.py` 10/10 断言通过 | ✅ |
| 3 to-spec | 本文档定稿（TD 决策固化） | ✅ |
| 4 to-tickets | §3 修复方案拆分为开发任务 | ✅ |
| 5 implement+tdd | src/ 修改 + `tests/test_inner_conversation_streaming_pdd.py` | ⏳ |
| 6 code-review | inner_* 全量回归 + 知识库导入 | ⏳ |

### 开发任务清单（to-tickets）

- [ ] **T1**：`src/aibridge/engine/llm_generator.py` LLMClient 新增 `chat_completion_stream` 方法（G1）
- [ ] **T2**：`src/aibridge/engine/llm_generator.py` LLMGenerator 新增 `generate_stream` 方法（G2）
- [ ] **T3**：`src/aibridge/app_engine.py` 新增 `process_message_stream` 方法（G3/G4/G5/G6/G10，含锁释放 TD-2）
- [ ] **T4**：`src/aibridge/ui/ui_engine_bridge.py` SendMessageWorker 新增 `stream_started`/`chunk_received`/`stream_final` 信号 + `sync_run_stream` + `start_stream`（G7/G8）
- [ ] **T5**：`src/aibridge/ui/ui_engine_bridge.py` UIEngineBridge 新增 `start_send_message_stream` Facade
- [ ] **T6**：`src/aibridge/ui/chat_page.py` 新增流式渲染：占位气泡 + 局部刷新 + 徽标切换（G9/G10）
- [ ] **T7**：`src/aibridge/ui/chat_page.py` _MessageBubble 新增 `update_content`/`finalize`/`mark_error` 方法
- [ ] **T8**：`tests/test_inner_conversation_streaming_pdd.py` 编写 10 条 Grill 对应 pytest（~21 用例）
- [ ] **T9**：inner_* 全量回归（应 ≥ 251 + 新增 ≈ 272 passed）
- [ ] **T10**：知识库导入 + PDD 总验收 v1.3 更新

---

## 7. 与其它 PDD 模块的关联

- **前置依赖**：
  - M-10 App Bootstrap Wiring：AppEngine 装配 13 组件，是流式接口能拿到真实 LLMClient/RAGEngine/SafetyShield 的基础
  - M-11 Persona Injection Chain：role_config 字段对齐 PromptAssembler 契约，流式期间 role_config 装配复用 M-11 已有逻辑
  - M-13 Settings Data Sync：流式期间锁释放后，settings 可并发改（TD-2），下一轮 LLM 调用生效新配置
- **后续影响**：
  - M-7' 公众号云端服务：5s 占位回复仍走同步 `process_message`（TD-4），流式路径不用于云端
  - 后续 Agent 工具调用（tool_calls）：流式期间 tool_calls 在 final 事件统一返回（不在 chunk 期间推送），与 OpenAI tool_call 流式语义对齐
