# MVP 异步响应架构 · 综合方案

> **版本：** V0.1 · 2026-09-18
> **触发：** 真机测试中发现大文件（PDF/Excel）处理期间 AI 沉默等待，用户焦虑。
> **范围：** 调研所有渠道（WCF/企微/飞书/钉钉/OA）、所有耗时场景、对标成熟 IM Bot 框架（企微 AI Bot / 飞书 / Telegram / Discord / Slack / OpenClaw / Hermes / Coze / Dify）。
> **核心原则：** 不头疼医头，一药治百病——一套通用架构覆盖 5 个渠道、所有耗时场景。

---

## 一、问题全景：哪些场景会触发等待焦虑？

### 1.1 根因分析

**对用户来说，所有耗时场景的体验是一样的——"我发了东西，AI 没反应"。** 但根因分三层：

| 层级 | 控制方 | 具体场景 | MVP 能做什么 |
|------|--------|---------|-------------|
| **MVP 可控** | 我们自己 | 大文件下载 / 文件解析 / 大图片 Vision / RAG 检索慢 / 风控 delay / 线程池满 | 两阶段架构 + 进度反馈 |
| **LLM 厂商** | API 提供方 | 429 限流 / TTFT 变慢 / 超时 / Token 超长拒答 | 退避重试 + 超时降级 |
| **用户硬件** | 用户电脑 | CPU 慢 / 内存不够 / 机械硬盘 / 网络差 | 无能为力，但架构能缓解体感 |

### 1.2 所有触发场景清单

| 场景 | 耗时原因 | 预估耗时 | 触发概率 |
|------|---------|---------|---------|
| 文件 > 3MB | 下载 + 解析 | 5-30s | 高 |
| 图片 > 3MB + Vision | LLM 处理 | 3-15s | 中 |
| LLM API 429 | 厂商限流 | 不定 | 中 |
| 线程池满（max_workers=3） | 排队 | 不定 | 低 |
| 风控 delay | 模拟真人打字 | 最长 99s | 可控 |
| RAG 检索 | ChromaDB 向量搜索 | 2-5s | 低 |
| 语音 ASR（未来） | AASR API | 5-15s | 待接入 |
| 联网搜索（未来） | 搜索 API | 5-20s | 待接入 |

---

## 二、跨渠道文件/图片机制对比

| 渠道 | 文件大小上限 | 归一化能拿到 | 文件获取方式 | send_reply 能主动发 |
|------|-------------|-------------|-------------|-------------------|
| **WCF（微信）** | ~100MB | ✅ type + extra(路径) + XML totallen | WCF 自动下载到本地 | ✅ 是 |
| **企微** | 10GB（PC端） | ✅ msgtype + media_id | Media API 下载 | ✅ 回调 + 主动 |
| **飞书** | 50MB | ✅ msg_type + file_key | 文件 API 下载 | ✅ 回调 + 主动 |
| **钉钉** | 20MB | ✅ msgtype + downloadCode | 下载 API | ✅ 回调 + 主动 |
| **OA** | 小 | ✅ media_id | 下载 API | ✅ 回调 + 主动 |

**关键发现：**
1. **所有渠道都支持主动发消息**（send_reply 都是公开方法）
2. **所有渠道归一化后都有 media_id / file_path**（ChannelMessage dataclass 已统一）
3. **所有渠道都有文件大小信息**——要么 API 给（totallen/media_info），要么本地 os.path.getsize()
4. **所有渠道的耗时场景本质相同**——大文件下载 + 解析 + LLM 处理

---

## 三、行业对标：成熟产品怎么做的？

调研覆盖 **企微 AI Bot / 飞书 / 钉钉 / Telegram / Discord / Slack / WhatsApp / OpenClaw / Hermes / Coze / Dify**，提炼出六大通用模式：

### 模式 1：先 ACK 再异步处理（所有平台 Webhook 强制要求）

这不是"最佳实践"——是**不这么做就会被平台干掉**。

| 平台 | 强制 ACK 时间 | 不 ACK 的后果 |
|------|-------------|--------------|
| **Slack** | 3 秒 | 重试 3 次 → 标记失败 → 连续失败 5% 以上自动禁用 App |
| **Discord** | 3 秒 | Interaction Token 直接失效 → "Interaction failed" |
| **企微** | 5 秒 | 回调超时 → 重试 |
| **钉钉** | 3 秒 | 回调超时 → 重试 |
| **飞书** | 5 秒 | 回调超时 → 重试 |

**成熟做法：** Webhook handler 里**零 I/O 零计算**——收到消息 → 塞队列 → 立即返回 200 OK。后台 Worker 从队列取出来慢慢处理。

```
[Slack] ──3s 内──► [Webhook Handler] ──<50ms──► 返回 200 OK
                        │
                        ▼
                    塞 Redis 队列
                        │
                        ▼
                  [Worker] 慢慢调 LLM
```

### 模式 2：流式打字效果（平台原生支持）

**用户体验最好的方式**——ChatGPT 那套打字机效果，很多 IM 平台原生就支持：

| 平台 | 实现方式 | 效果 |
|------|---------|------|
| **企微 AI Bot** | WebSocket 长连接 + `stream()` API | 先显示"思考中" → 逐字更新 → `finish=true` 结束（10 分钟内必须 finish） |
| **飞书 AI 机器人** | 流式卡片 + CardKit API | 卡片内容打字机效果，10 次/秒更新 |
| **Telegram** | `sendChatAction(typing)` | 用户看到机器人正在输入（每 4s 需刷新） |
| **WhatsApp** | `mark_as_typing` 状态 | 同上 |

> ⚠️ **关键限制：** 这些都是**平台 AI 机器人**的 API——不是普通用户账号。我们走的 WCF 是普通微信账号，平台不给流式 API。这是我们和 Coze/Dify 等 SaaS 的根本区别。

### 模式 3：主动推送进度（所有异步架构的标配）

**OpenClaw（腾讯 AI Agent 框架）**的做法最清晰，三层进度反馈：

```javascript
// 来自腾讯云开发者社区的 OpenClaw 实战代码
async function longRunningSkill(context, params) {
  const { sendProgress } = context;
  
  await sendProgress('🔍 正在搜索相关资料...');      // 第 1 步：确认收到
  const searchResults = await searchWithTimeout(...);
  
  await sendProgress(`📄 找到 ${searchResults.length} 条，正在分析...`); // 第 2 步：阶段性进度
  const analysis = await analyzeWithTimeout(...);
  
  await sendProgress('✍️ 正在生成报告...');          // 第 3 步：最终阶段
  return { report: finalReport };
}
```

**核心原则：**
- 进度消息要有**信息量**（"已处理 3/5 个文件" 而非 "正在处理"）
- 频率控制在 **5-10 秒一条**（太频繁是噪音）
- 每个平台都有主动发消息的 API（我们的 `send_reply` 就是这个）

### 模式 4：双层超时（必做的容错）

| 层次 | 作用范围 | 典型值 | 触发后 |
|------|---------|--------|--------|
| **操作级超时** | 单个外部 API 调用（文件下载、LLM 请求） | 5-30 秒 | throw → 上层决定是否重试 |
| **任务级超时** | 整个 Skill 的总执行时限 | 2-10 分钟 | 取消所有子操作 → 保存进度 → 告知用户"可稍后查看" |

**OpenClaw 的实现：**
```javascript
// 任务级超时用 Promise.race
async function skillWithTimeout(skillFn, taskTimeoutMs = 120_000) {
  const timeoutPromise = new Promise((_, reject) => 
    setTimeout(() => reject(new Error('Task timeout')), taskTimeoutMs)
  );
  return Promise.race([skillFn(), timeoutPromise]);
}
```

### 模式 5：限流处理（429 退避 + 本地令牌桶）

| 层次 | 做法 |
|------|------|
| **平台 API 限流**（Slack 429 / Discord 429） | 读取 `Retry-After` header → 指数退避 → 重试 |
| **LLM API 限流**（429 rate limit） | 指数退避（1s → 2s → 4s → 8s）→ 最多重试 3 次 → 超时降级 |
| **本地令牌桶** | MVP 跑在用户本地电脑，不是服务器，**不用令牌桶**——队列满了就是硬件瓶颈 |

### 模式 6：消息队列 + 线程池（并发基础）

**这才是"队列堵塞考验用户硬件"的答案：**

| 成熟框架怎么做 | 我们现在怎么做 | 差距 |
|---|---|---|
| Redis / RabbitMQ 持久化队列 | ThreadPoolExecutor 内存队列 | 进程死了队列就没了 |
| 消费者组 + 自动重试 | 无重试 | 一条消息失败就跳过 |
| 优先级队列（高优先级先处理） | FIFO | 紧急消息被大文件堵住 |
| 死信队列（失败消息转移） | 无 | 消息丢失不可追溯 |

---

## 四、综合对比：成熟 SaaS vs 我们的 MVP

| 维度 | Coze/Dify（飞书/企微 AI 机器人） | 我们的 MVP（WCF 普通账号 + 多渠道） | 本质区别 |
|------|---------------------------------|----------------------------------|---------|
| **流式效果** | ✅ 平台原生支持打字机 | ❌ 普通账号，平台不给 | 权限问题 |
| **回调超时** | ✅ 3-5s 强制 ACK | ⚠️ WCF 是长轮询，不强制 | 接入方式不同 |
| **主动推送** | ✅ 平台 response_url 1 小时有效 | ✅ 我们的 send_reply 是普通 API | 能力相同 |
| **文件下载** | ✅ 平台 API 下载 | ✅ WCF 自动落盘，其他渠道 API 下载 | 能力相同 |
| **限流** | ⚠️ 走平台限额 + LLM 限额 | ⚠️ 走 WCF 风控 + LLM 限额 | 场景不同 |
| **队列** | ✅ Redis 持久化 + Worker | ⚠️ ThreadPoolExecutor 内存队列 | 架构差距 |

---

## 五、我们该学什么？该忽略什么？

### ✅ 必学的（和平台无关，完全能做）

| 模式 | 我们的实现方式 |
|------|---------------|
| **先 ACK 再异步** | Pipeline 收到消息 → 丢 ThreadPoolExecutor → 主线程立即返回（WCF 不强制但保持一致） |
| **两阶段回复** | quick_llm_call 发占位 → 后台线程处理 → send_reply 发结果 |
| **双层超时** | LLM API 调用 30s 超时 + 后台任务 2min 超时 |
| **限流退避** | Bridge 捕获 429 → 指数退避重试 → 3 次失败降级 |
| **进度反馈** | 翻译层运营规则 + send_reply 主动发"正在解析..." |

### ❌ 不该学的（平台不支持 or MVP 不需要）

| 模式 | 为什么不学 |
|------|-----------|
| **流式打字效果** | 普通微信账号没有这个 API，WCF 不支持 |
| **Redis 持久化队列** | MVP 跑在用户本地电脑，加 Redis 太重 |
| **优先级队列** | MVP 并发量低（max_workers=3），FIFO 够用 |
| **死信队列** | MVP 可以接受重启后消息丢失（毕竟是用户自己的 AI） |
| **Slack/Discord 的 Interaction Token 3s 强制 ACK** | 我们走的是 IM 消息通道，不是 AI 机器人回调，没有这个限制 |

---

## 六、综合方案：MVP 异步响应架构

### 6.1 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 1：归一化层（渠道特定，5 个文件各改一点）                │
│                                                             │
│  WcfClient._normalize_raw()                                 │
│  WeComClient._normalize()                                   │
│  DingTalkClient._normalize()   →  ChannelMessage            │
│  FeishuClient._normalize()        + file_size               │
│  OaClient._normalize()            + is_ready                │
├─────────────────────────────────────────────────────────────┤
│  Layer 2：Pipeline 两阶段（完全通用，不关心渠道）              │
│                                                             │
│  _process_one() 收到消息                                    │
│    │                                                        │
│    ├─ [快路径] 小文件/文本 → 同步处理（现有逻辑不动）          │
│    │                                                        │
│    └─ [慢路径] 触发两阶段 →                                  │
│         1. quick_llm_call → send_reply(占位文案)             │
│         2. ThreadPoolExecutor 后台线程：                     │
│            a. 轮询等待文件就绪                               │
│            b. parse_document（如果是文件）                    │
│            c. Bridge full_llm_call（翻译层 + RAG）           │
│            d. send_reply(真正内容)                          │
│         3. finally: 超时兜底（30s 发降级提示）                │
├─────────────────────────────────────────────────────────────┤
│  Layer 3：Bridge 容错（完全通用）                             │
│                                                             │
│  - 429 捕获 → 指数退避 1s→2s→4s → 最多 3 次                  │
│  - LLM API 超时 30s → 抛异常 → Pipeline 触发降级             │
│  - Token 超长 → 提前检查 → 降级提示                          │
│  - quick_llm_call（轻量，跳过完整 RAG，只调 LLM）            │
├─────────────────────────────────────────────────────────────┤
│  Layer 4：翻译层运营规则（LLM 自己决定怎么说）                │
│                                                             │
│  _build_runtime_context() 注入：                             │
│  ▎运营规则：等待体感管理                                    │
│    · < 3MB 或文本 → 正常同步                                │
│    · 3-10MB → 先占位 "收到啦～稍等我一下"                    │
│    · > 10MB → 先占位 "文件有点大，可能需要点时间哦"          │
│    · 429 限流 → 占位 "LLM 现在有点忙，稍等哦"                │
│    · 超时 30s → 降级 "网络好像有点慢，要不稍后再试？"        │
│    · 占位文案由你（LLM）根据实际情况自然决定                  │
└─────────────────────────────────────────────────────────────┘
```

### 6.2 ChannelMessage 扩展

```python
@dataclass
class ChannelMessage:
    # ... 现有字段保持不动 ...
    msg_type: str           # text / file / image / voice / video
    file_path: str           # 本地路径
    file_name: str           # 文件名
    media_id: str            # 渠道 media_id / downloadCode / file_key
    file_size: int           # 🆕 字节数，0=未知
    is_ready: bool           # 🆕 文件是否已下载就绪
```

各渠道归一化层负责填这两个新字段：

| 渠道 | file_size 来源 | is_ready 判断 |
|------|---------------|--------------|
| WCF | XML 中 totallen | `os.path.isfile(file_path)` 轮询 |
| 企微 | media API 返回 | 下载完成即 ready |
| 飞书 | file_key API | 下载完成即 ready |
| 钉钉 | downloadCode API | 下载完成即 ready |
| OA | file_url 响应头 | 下载完成即 ready |

### 6.3 触发条件（慢路径入口）

```python
def _should_trigger_two_stage(
    msg: ChannelMessage,
    llm_history_ms: int,      # 过去 5 次 LLM API 平均响应时间
    queue_depth: int,         # ThreadPoolExecutor 排队长度
) -> bool:
    """
    满足任一条件触发两阶段
    """
    # 条件 1：文件/图片超过阈值
    if msg.msg_type in ('file', 'image') and msg.file_size > 3 * 1024 * 1024:
        return True
    
    # 条件 2：LLM API 历史响应慢（过去 5 次平均 > 5s）
    if llm_history_ms > 5000:
        return True
    
    # 条件 3：队列堵塞（ThreadPoolExecutor 排队 > 3 条）
    if queue_depth > 3:
        return True
    
    # 条件 4：未来扩展（ASR / 联网搜索）
    # if msg.needs_asr or msg.needs_web_search:
    #     return True
    
    return False
```

### 6.4 防坑设计（调研后识别的高风险点）

| 坑 | 防护 | 代码位置 | 风险等级 |
|---|------|---------|---------|
| 后台线程崩溃，永远只显示占位 | try-catch 全兜 + finally 超时兜底 | Pipeline 后台线程 | 🔴 P0 |
| 两阶段重复触发（翻译层不知道已回复占位） | Bridge 加状态标记 `_replied_placeholder` | Bridge 内部 | 🔴 P0 |
| 并发两个两阶段互相干扰 | 每个会话独立后台线程 + 风控锁保护 send_reply | Pipeline ThreadPoolExecutor | 🔴 P0 |
| 小文件误触发两阶段（占位白发了） | 阈值 3MB + 预估总耗时 < 3s 不触发 | `_should_trigger_two_stage()` | 🟡 P1 |
| 主动推两条被微信风控 | 两阶段消息间隔加随机抖动（1-3s）+ 复用风控 delay 机制 | Pipeline send_reply | 🟡 P1 |
| 429 限流后用户一直等 | 捕获 429 立即发占位"LLM 忙" | Bridge 429 handler | 🟡 P1 |
| 两次回复被风控 delay 隔开太远 | 占位和真正回复都走同一套风控规则，但间隔加下限（>5s 才允许发第二条） | Pipeline send_reply | 🟡 P1 |
| token 成本翻倍 | quick_llm_call 只发极短 prompt（~200 tokens），占位回复很短 | Bridge | 🟢 P2 |
| 多渠道 send_reply 行为不一致 | 逐个渠道测试，不行就降级成同步 | 各渠道 client | 🟢 P2 |

---

## 七、实施计划

### Phase 0：已完成的 checkpoint（2026-09-18）

| 改动 | 文件 | 说明 |
|------|------|------|
| 归一化层统一文件路径 | `app/channel/*_client.py` | 5 个渠道归一化统一输出路径 |
| 落盘等待逻辑 | `app/channel/wcf_client.py` L880-907 | WCF type=49 轮询等文件就绪 |
| Pipeline 文件就绪轮询 | `app/channel/message_pipeline.py` L139-151 | 二次防护 |
| 翻译层 runtime context | `app/bridge.py` L5788-5973 | 系统简报注入 |
| parse_document 支持 PDF/Excel | `app/bridge.py` | pypdf + openpyxl |
| 角色差异化 fallback | `app/channel/message_pipeline.py` L453-477 | 管理者 vs 普通用户 |

**状态：** 三次 PDF 真机测试全通过，**建议先 commit**。

### Phase 1：两阶段架构（下一个 session）

| 改动 | 文件 | 复杂度 |
|------|------|--------|
| ChannelMessage 加 file_size / is_ready | `app/channel/message_pipeline.py` | 🟢 |
| 5 个渠道归一化填新字段 | `app/channel/*_client.py` | 🟡 |
| `_should_trigger_two_stage()` | `app/channel/message_pipeline.py` | 🟢 |
| Pipeline 两阶段分支 | `app/channel/message_pipeline.py` | 🟡 |
| quick_llm_call（轻量 LLM 调用） | `app/bridge.py` | 🟢 |
| Bridge 429 退避 + 超时降级 | `app/bridge.py` | 🟡 |
| 翻译层加运营规则 | `app/bridge.py` | 🟢 |
| 后台线程 try-catch + 超时兜底 | `app/channel/message_pipeline.py` | 🟢 |

### Phase 2：后续迭代

| 内容 | 时机 |
|------|------|
| 语音 ASR 接入两阶段 | AASR API 接入时 |
| 联网搜索接入两阶段 | MVP 2.0 规划时 |
| LLM API 历史延迟统计 | Phase 1 稳定后 |
| 多渠道真机验证 | Phase 1 完成后逐个测 |
| 三层进度反馈（不只是占位+结果） | 用户反馈需要时 |

---

## 八、真正"想不到的坑"预判

> **你说的对，一定有我们想不到的坑。** 预演几个真实场景：

### 场景 A：用户连发两个大文件
```
10:00:00 用户发 15MB PDF A
10:00:01 MVP 发占位 "收到啦～稍等"
10:00:02 用户发 8MB Excel B
10:00:03 MVP 发占位 "收到啦～稍等"
10:00:05 PDF A 解析完 → 后台线程 A 调 LLM 分析 A
10:00:20 Excel B 解析完 → 后台线程 B 调 LLM 分析 B
10:00:25 风控触发 delay 30s → 两条分析内容被延迟
```
**风险：** ThreadPoolExecutor max_workers=3，两个后台线程 + 主线程 刚好占满。但风控 delay 是在 send_reply 里 sleep，不是在线程池里 sleep——**不会阻塞队列。**

### 场景 B：占位发出去了，但 LLM 很快处理完了
```
10:00:00 用户发 5MB PDF
10:00:01 MVP 判断 > 3MB → 发占位 "收到啦～稍等我一下"
10:00:03 文件落盘 + parse_document 完成
10:00:04 Bridge 调 LLM → 1s 就返回了
10:00:05 MVP 发真正内容
```
**风险：** 用户看到 "收到啦～稍等我一下" → 紧接着就出了真正内容。**占位变成了噪音！** 需要加"预估总耗时 < 3s 不触发两阶段"的判断。

### 场景 C：后台线程崩溃了
```
10:00:00 用户发 10MB PDF
10:00:01 MVP 发占位 "收到啦～稍等"
10:00:05 文件落盘 → parse_document 抛异常（PDF 损坏）
10:00:05 后台线程 try-catch 没写全 → 静默退出
... 用户永远只看到占位！
```
**防护：** try-catch 全兜住 + finally 超时兜底（30s 发降级提示）。

### 场景 D：LLM 限流 429
```
10:00:00 用户发 4MB PDF
10:00:01 MVP 发占位 "收到啦～稍等"
10:00:10 文件落盘 + parse 完成
10:00:11 Bridge 调 LLM → 返回 429
10:00:11 Bridge 指数退避 → 等 5s → 重试 → 又 429 → 等 10s → 重试 → 又 429 → 超时
```
**防护：** 捕获 429 立即发占位"LLM 现在有点忙，稍等哦"。

### 场景 E：主动推两条被微信风控
```
10:00:00 用户发大文件（好友/正常对话）
10:00:01 MVP 发占位 "收到啦～稍等"
10:00:30 MVP 发真正内容
```
**风险：** 企微 AI 机器人主动推是合法的，但 WCF 普通账号**连续发两条消息**在微信"正常对话窗口"内是安全的——因为用户刚给你发了消息，你回复两条是正常对话行为。但如果间隔太长（> 5 分钟）可能被判定为主动骚扰。**当前风控 delay 机制会管理间隔。**

---

## 九、结论

1. **今天的文件处理修复是 MVP 1.0 的稳定 checkpoint，应该先 commit**
2. **两阶段架构是通用解法，不是头疼医头——它覆盖所有渠道、所有耗时场景**
3. **我们和成熟 SaaS 的核心差距是"账号权限"（普通账号 vs AI 机器人 API），而非"架构能力"**
4. **最需要警惕的坑是 WCF 风控——但在正常对话窗口内回复两条是安全的**
5. **架构本身安全（快路径不动，慢路径可选触发，随时可回退），风险在实现细节里，真机测出来**
6. **加新渠道时只需在归一化层填 file_size + is_ready，Pipeline 两阶段自动生效**

---

## 附录：调研来源

| 来源 | 链接 | 关键信息 |
|------|------|---------|
| OpenClaw 长耗时处理 | https://developer.cloud.tencent.com/article/2639040 | 三层进度反馈、双层超时 |
| 企业微信 AI Bot 排坑 | https://cloud.tencent.com/developer/article/2679907 | ret=-2 真假限流、context_token 失效 |
| 企微 AI 机器人长连接 | https://developer.work.weixin.qq.com/document/path/101463 | 流式消息 10 分钟必须 finish |
| 企微主动回复消息 | https://developer.work.weixin.qq.com/document/path/101138 | response_url 1 小时有效 |
| 飞书智能体对话 API | https://open.larkoffice.com/document/uAjLw4CM/ukTMukTMukTM/aily-v1/agent-agent_chat/create | 异步发起 + 流式输出 5 分钟超时 |
| 飞书流式更新卡片 | https://open.feishu.cn/document/cardkit-v1/streaming-updates-openapi-overview | 打字机效果、10 次/秒更新 |
| Slack/Discord 3s 超时 | https://dev.to/instawebhook/managing-slack-and-discord-bot-webhooks-without-getting-rate-limited-2m8e | 3s ACK、重试风暴、429 处理 |
| WhatsApp AI 加速 | https://www.bitbytes.io/blog/speed-up-whatsapp-ai-assistant | 快回复目标 2-3s、"Checking now — one moment" |
| Telegram Bot 并发 | https://nerdleveltech.com/building-powerful-telegram-bots-with-ai-a-complete-guide | webhook 立即返回 200、后台线程处理 |
| 多平台 Chatbot 架构 | https://amiable.dev/blog/luminescent-cluster/05-multi-platform-chatbots/ | thin adapters + central gateway、消息归一化 |
