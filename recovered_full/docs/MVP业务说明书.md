# MVP 业务说明书（SOP）

> 版本：v1.0  
> 更新日期：2026-09-06  
> 适用范围：WeChatAI_Project MVP 阶段

---

## 目录

1. [产品概述](#1-产品概述)
2. [系统架构](#2-系统架构)
3. [前端功能 SOP](#3-前端功能-sop)
4. [后端模块说明](#4-后端模块说明)
5. [核心业务流程](#5-核心业务流程)
6. [数据模型](#6-数据模型)
7. [付费闸门机制](#7-付费闸门机制)
8. [异常处理与降级策略](#8-异常处理与降级策略)
9. [渠道接入指引](#9-渠道接入指引)

---

## 1. 产品概述

### 1.1 产品定位

**AI 数字分身平台** —— 用户创建智能体（人设），绑定微信联系人，让 AI 以用户的语气和风格自动回复微信消息。智能体通过对话持续积累记忆，知识库提供业务知识支撑，实现"越用越懂你"的 AI 协作体验。

### 1.2 核心价值

| 价值点 | 说明 |
|--------|------|
| 身份模拟 | AI 学习用户的语气、习惯、偏好，模拟用户本人回复 |
| 知识增强 | 绑定知识库，回复时自动检索相关业务知识 |
| 记忆进化 | 从对话中提炼用户画像，24 小时自动整理 |
| 多渠道扩展 | 架构支持接入微信、企业微信、飞书等多渠道 |

### 1.3 MVP 范围

**已实现**：
- 智能体 CRUD（角色、知识库、记忆、其他）
- 知识库管理（创建、上传文档、切片、检索）
- 记忆系统（手动刷新、导入、24h 自动整理）
- 微信渠道连接与消息自动回复
- 对话搬迁（绑定抢占时自动迁移历史）
- 付费激活机制

**规划中**：
- 多渠道接入（企业微信、飞书等）
- 全局记忆导入/导出
- 数据备份与恢复

---

## 2. 系统架构

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────┐
│                    前端 (index.html)                  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐ │
│  │ 智能体管理 │ │ 知识库   │ │ 记忆进化  │ │ 连接管理│ │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └───┬────┘ │
└───────┼────────────┼────────────┼────────────┼──────┘
        │            │            │            │
        ▼            ▼            ▼            ▼
┌─────────────────────────────────────────────────────┐
│                  Bridge (pyqtBridge)                 │
│   IPC 双向通信 · 智能体/记忆/知识库/渠道 处理中心     │
└──────────────────────┬──────────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
┌──────────────┐ ┌──────────┐ ┌──────────────┐
│   Storage    │ │  Channel │ │ LLM Provider │
│  (SQLite)    │ │ (WCF)    │ │  (统一接口)   │
└──────────────┘ └──────────┘ └──────────────┘
```

### 2.2 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | HTML/CSS/JS（单文件，PyQt QWebEngine 渲染） |
| 桥接 | PyQt5 QWebChannel（JS ↔ Python 双向通信） |
| 后端 | Python 3 |
| 数据库 | SQLite（单文件，自动迁移） |
| LLM | 兼容 OpenAI 协议的各家服务商 |
| 渠道 | WCF（微信）|

### 2.3 进程模型

```
主进程 (main.py)
  ├─ PyQt GUI 线程（前端渲染）
  ├─ Bridge 主线程（IPC 处理）
  ├─ ThreadPoolExecutor: WcfPipeline（消息处理，单 worker 串行）
  └─ ThreadPoolExecutor: memory（记忆提炼，可并发）
```

---

## 3. 前端功能 SOP

### 3.1 智能体管理

#### 3.1.1 新建智能体

**操作路径**：首页 → 新建智能体

**必填项**：
- 人设名称（不可为空，重名自动加后缀）
- 语言模型（必须选择）

**默认值**：
| 字段 | 默认值 |
|------|--------|
| 角色定义 | 自定义（prompt 为空） |
| 知识库 | 关闭 |
| 记忆与进化 | 关闭 |
| AIGC 标识 | 开启 |

**校验规则**：
1. 名称为空 → 提示"请输入人设名称"
2. 未选模型 → 提示"请选择语言模型"
3. 重名 → 弹窗确认是否自动加后缀
4. System Prompt 超过 2048 tokens → 拦截并提示精简

#### 3.1.2 编辑智能体

**四个 Tab**：

| Tab | 功能 |
|-----|------|
| 角色 | 人设名称、语言模型、角色定义模板、System Prompt |
| 知识库 | 启用开关、绑定知识库（一个智能体只能绑一个） |
| 记忆与进化 | 生成记忆开关、刷新/编辑/导入记忆 |
| 其他 | AIGC 标识、语速配置等 |

**保存逻辑**：
- 记忆为空结构（enabled=false 且无条目）→ 传空字符串，后端不写入
- 记忆非空 → 传 JSON 字符串

#### 3.1.3 删除智能体

**操作路径**：智能体卡片 → 更多 → 删除

**流程**：
1. 弹窗二次确认（显示智能体名称）
2. 确认后调用 `delete_agent`
3. 成功后刷新智能体列表

### 3.2 知识库

#### 3.2.1 创建知识库

**操作路径**：知识库页 → 新建知识库

**字段**：知识库名称、描述

#### 3.2.2 上传文档

**操作路径**：知识库详情 → 上传文档

**支持格式**：PDF、DOCX、XLS、XLSX、PPTX、MD、TXT、CSV、HTML、EPUB

**流程**：
1. 点击"选择文件"，系统文件选择器
2. 输入文档名称（可选）
3. 提交后系统自动解析、切片、入库
4. 完成后显示文档卡片（含切片数）

#### 3.2.3 检索测试

**操作路径**：知识库详情 → 检索测试

**流程**：
1. 输入问题
2. 点击"检索"
3. 返回相关切片（带来源文档）

#### 3.2.4 导出知识库

**操作路径**：知识库页 → 导出知识库

**输出**：通用知识库格式（兼容 Obsidian / 模型 Wiki）

### 3.3 记忆与进化

#### 3.3.1 记忆结构

```json
{
  "enabled": true,
  "user_profile": [
    {"id": "xxx", "content": "用户画像条目", "category": "身份与偏好"}
  ],
  "episodic": [
    {"id": "xxx", "content": "情景记忆条目", "time": 1234567890}
  ],
  "history": [
    {"time": 1234567890, "before": {...}, "after": {...}}
  ],
  "last_confirm_at": 1234567890,
  "last_refine_at": 1234567890
}
```

#### 3.3.2 刷新记忆

**操作路径**：智能体 → 记忆与进化 → 刷新

**SOP**：
1. 点击"刷新"按钮
2. 后端从该智能体所有非空会话提炼记忆
3. 每个会话取最近 40 条消息
4. LLM 提炼用户画像 + 情景记忆
5. 写入数据库，前端自动更新显示

**降级策略**：LLM 未返回有效记忆时，保留原有记忆，不覆盖。

#### 3.3.3 导入记忆

**操作路径**：智能体 → 记忆与进化 → 导入

**前置条件**：该智能体有从其他智能体搬迁过来的对话（`migrated_from` 非空）

**SOP**：
1. 点击"导入"打开弹窗
2. 勾选要导入的搬迁会话
3. 点击"导入"
4. 后端立即返回，后台异步提炼
5. 弹窗提示"你可以关闭此窗口，完成后会自动录入记忆"
6. 后台完成后推送 `memory_imported` 事件
7. 前端自动更新记忆面板 + toast 提示
8. 搬迁会话的 `migrated_from` 标记被清除

**交互特点**：
- 异步非阻塞，用户可关闭弹窗
- 完成后自动更新，无需手动刷新

#### 3.3.4 24 小时自动整理

**触发时机**：软件启动时

**SOP**：
1. 检查所有智能体
2. 跳过未开启记忆的智能体
3. 跳过 24 小时内已整理过的智能体
4. 后台线程执行全量提炼
5. 更新 `last_memory_refine_at` 时间戳

### 3.4 连接管理

#### 3.4.1 微信连接

**操作路径**：连接页 → 微信开关

**SOP**：
1. 点击开关启动 WCF 服务
2. 等待微信连接成功
3. 显示好友/群数量

#### 3.4.2 绑定联系人

**操作路径**：连接页 → 选择联系人 → 绑定到智能体

**SOP**：
1. 选择微信联系人
2. 选择目标智能体
3. 确认绑定

**抢占替换机制**：
- 如果联系人已被其他智能体绑定
- 自动关闭旧绑定，建立新绑定
- 旧智能体的该联系人对话**搬迁**到新智能体
- 搬迁的对话标记 `migrated_from = 旧智能体ID`
- 新智能体可在"导入记忆"中看到这些搬迁对话

### 3.5 设置

#### 3.5.1 LLM 管理

**操作路径**：设置 → LLM 管理

**支持服务商**：智谱AI、月之暗面、通义千问、腾讯混元、字节豆包、自定义

**配置字段**：服务商名称、Base URL、API Key、模型名称

#### 3.5.2 激活管理

**操作路径**：设置 → 激活

**SOP**：
1. 导出机器码
2. 获得 License 文件
3. 导入 License 文件
4. 激活成功后解锁正式版功能

---

## 4. 后端模块说明

### 4.1 数据层（storage/）

#### 4.1.1 db.py — 数据库管理

| 职责 | 说明 |
|------|------|
| 连接管理 | `get_conn()` 线程局部连接 |
| 事务 | `transaction()` 上下文管理器 |
| 表结构 | 所有表的 CREATE TABLE 定义 |
| 自动迁移 | 缺列时自动 `ALTER TABLE ADD COLUMN` |

#### 4.1.2 dao.py — 数据访问对象

| DAO 类 | 职责 |
|--------|------|
| `AgentDAO` | 智能体 CRUD，重名避让，字段白名单 |
| `KnowledgeBaseDAO` | 知识库 CRUD |
| `KbDocumentDAO` | 文档 CRUD |
| `ConversationDAO` | 会话 CRUD，搬迁，导入标记 |
| `ChatMessageDAO` | 消息 CRUD，按会话列表 |
| `ChannelBindingDAO` | 渠道绑定，抢占替换，对话搬迁 |

#### 4.1.3 retriever.py — RAG 检索

| 功能 | 说明 |
|------|------|
| 索引管理 | 文档切片索引的构建、保存、加载 |
| 检索 | `search(query, top_k, kb_ids)` 返回相关切片 |

#### 4.1.4 llm_provider.py — LLM 调用

| 功能 | 说明 |
|------|------|
| 统一接口 | `from_config(cfg)` → `chat(messages, temperature)` |
| 兼容协议 | OpenAI 兼容协议 |
| 错误处理 | 返回 `{"error": "..."}` 而非抛异常 |

### 4.2 渠道层（channel/）

#### 4.2.1 wcf_client.py — 微信客户端

| 功能 | 说明 |
|------|------|
| 连接管理 | 启动/停止 WCF 服务 |
| 消息接收 | 注册回调，接收微信消息 |
| 消息发送 | `send_reply(peer_id, content)` |
| 联系人获取 | 获取好友/群列表 |

#### 4.2.2 binding_router.py — 绑定路由

| 功能 | 说明 |
|------|------|
| 查找绑定 | `find_agent_for_peer(channel, peer_id)` → 智能体 ID |

#### 4.2.3 message_pipeline.py — 消息流水线

**处理流程**：
```
收到消息 → 空消息/自消息过滤
  → 查绑定智能体（无绑定则丢弃）
  → 找/建会话
  → 调 LLM 获取回复
  → 风控决策（速率/延迟/漏回）
  → 发送回复
```

**线程模型**：`ThreadPoolExecutor(max_workers=1)` 单 worker 串行，避免同会话并发问题。

#### 4.2.4 risk_engine.py — 风控引擎

| 功能 | 说明 |
|------|------|
| 速率控制 | 限制回复频率 |
| 行为模拟 | 随机延迟，模拟真人打字 |
| 漏回 | 概率性跳过发送（消息已入库） |

### 4.3 桥接层（bridge.py）

#### 4.3.1 IPC 通信机制

| 方向 | 机制 |
|------|------|
| JS → Python | `pyqtBridge.call(action, payload)` |
| Python → JS | `send_to_js(action, payload)` |

#### 4.3.2 核心处理函数

| 函数 | 职责 |
|------|------|
| `_handle_create_agent` | 创建智能体（含付费闸门） |
| `_handle_update_agent` | 更新智能体 |
| `_handle_delete_agent` | 删除智能体 |
| `_handle_send_message` | 消息收发核心（RAG + LLM + 入库） |
| `_handle_refresh_memory` | 手动刷新记忆 |
| `_handle_import_memory` | 异步导入记忆 |
| `_handle_list_migrated` | 列出搬迁会话 |
| `_handle_set_channel_binding` | 设置渠道绑定（抢占+搬迁） |

---

## 5. 核心业务流程

### 5.1 消息收发完整链路

```
[微信收到消息]
      │
      ▼
WcfClient._on_wcf_message(msg)
      │
      ▼
MessagePipeline._process_one(msg)
      │
      ├─ 1. 空消息/自消息过滤
      │
      ├─ 2. BindingRouter.find_agent_for_peer(channel, peer_id)
      │     └─ 无绑定 → 丢弃
      │
      ├─ 3. ConversationDAO.get_or_create_by_peer
      │     └─ 同智能体×渠道×peer 共用一个会话
      │
      ├─ 4. Bridge._handle_send_message(payload)
      │     │
      │     ├─ 4.1 获取智能体 + LLM 配置
      │     ├─ 4.2 保存用户消息
      │     ├─ 4.3 构建 system prompt
      │     │     ├─ persona（角色定义）
      │     │     ├─ 记忆注入（用户画像 + 情景记忆）
      │     │     ├─ RAG 检索（知识库相关切片）
      │     │     └─ 通用规则（底线规则）
      │     ├─ 4.4 拼接最近 10 轮历史
      │     ├─ 4.5 调用 LLM
      │     └─ 4.6 保存 assistant 消息
      │
      ├─ 5. RiskEngine.decide（速率/延迟/漏回）
      │     └─ should_send=False → 跳过发送（消息已入库）
      │
      └─ 6. WcfClient.send_reply → 发回微信
```

### 5.2 记忆积累链路

```
[对话消息持续入库]
      │
      ▼
软件启动时 _maybe_daily_memory_refine()
      │
      ├─ 检查所有智能体
      ├─ 跳过未开启记忆的
      ├─ 跳过 24h 内已整理的
      │
      ▼
_daily_refine_one(agent_id)
      │
      ├─ _do_memory_extract_pure(agent_id)
      │     ├─ 取所有非空会话
      │     ├─ 每会话取最近 40 条
      │     ├─ 合并喂给 LLM
      │     └─ LLM 返回 user_profile + episodic
      │
      ├─ _save_memory_result(agent_id, result)
      │     ├─ 写入 ai_agent.memories
      │     └─ 更新 last_memory_refine_at
      │
      └─ 完成
```

### 5.3 对话搬迁链路

```
[绑定已被占用的联系人]
      │
      ▼
ChannelBindingDAO.replace_binding(new_agent_id, channel, peer_id)
      │
      ├─ Step 1: 关闭该 peer 所有其他人的 enabled 绑定
      │
      ├─ Step 2: upsert 自己的 enabled=1 绑定
      │
      └─ Step 3: 搬迁 conversation
            ├─ 新智能体已有同 peer 会话 → 删除旧会话
            └─ 新智能体无同 peer 会话 → 
                UPDATE conversation 
                SET agent_id=new, migrated_from=旧agent_id
                WHERE channel=? AND peer_id=? AND agent_id!=new
      │
      ▼
新智能体的"导入记忆"弹窗显示搬迁会话
      │
      ▼
用户勾选导入 → 异步提炼记忆 → 清除 migrated_from
```

### 5.4 知识库 RAG 链路

```
[用户消息]
      │
      ▼
_handle_send_message 中:
      │
      ├─ use_kb=True 且 kb_enabled=1 且已激活
      │
      ├─ 解析 kb_ids
      │
      ├─ retriever.search(user_input, top_k=3, kb_ids=kb_ids)
      │
      ├─ 拼接为 "参考资料：[来源]: 内容"
      │
      └─ 注入 system prompt
```

---

## 6. 数据模型

### 6.1 ai_agent（智能体）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT | 智能体 ID |
| name | TEXT | 人设名称 |
| avatar | TEXT | 头像 |
| system_prompt | TEXT | 角色定义 |
| agent_type | TEXT | 类型 |
| style | TEXT | 风格 |
| memories | TEXT | 记忆 JSON |
| aigc_enabled | INTEGER | AIGC 标识开关 |
| emoji_enabled | INTEGER | emoji 开关 |
| llm_config_id | TEXT | LLM 配置 ID |
| kb_ids | TEXT | 绑定知识库 ID JSON |
| kb_enabled | INTEGER | 知识库开关 |
| rate_profile | TEXT | 语速配置 JSON |
| last_memory_refine_at | INTEGER | 上次记忆整理时间 |
| created_at | INTEGER | 创建时间 |
| updated_at | INTEGER | 更新时间 |

### 6.2 conversation（会话）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT | 会话 ID |
| agent_id | TEXT | 所属智能体 |
| channel | TEXT | 渠道（wcf/oa） |
| peer_id | TEXT | 联系人 ID |
| peer_name | TEXT | 联系人名称 |
| peer_type | TEXT | 联系人类型（friend/group） |
| title | TEXT | 会话标题 |
| message_count | INTEGER | 消息数 |
| migrated_from | TEXT | 搬迁来源智能体 ID |
| created_at | INTEGER | 创建时间 |
| updated_at | INTEGER | 更新时间 |

### 6.3 chat_message（对话消息）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT | 消息 ID |
| conversation_id | TEXT | 所属会话 |
| role | TEXT | 角色（user/assistant） |
| content | TEXT | 消息内容 |
| channel | TEXT | 渠道 |
| aigc_marked | INTEGER | AIGC 标识 |
| model | TEXT | 使用的模型 |
| created_at | INTEGER | 创建时间 |

### 6.4 channel_binding（渠道绑定）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT | 绑定 ID |
| agent_id | TEXT | 智能体 ID |
| channel | TEXT | 渠道 |
| peer_id | TEXT | 联系人 ID |
| peer_name | TEXT | 联系人名称 |
| peer_type | TEXT | 联系人类型 |
| enabled | INTEGER | 是否启用 |
| created_at | INTEGER | 创建时间 |
| updated_at | INTEGER | 更新时间 |

---

## 7. 付费闸门机制

### 7.1 功能权限

| 功能 | 免费版 | 正式版 |
|------|--------|--------|
| 创建智能体 | ✅ | ✅ |
| 消息自动回复 | ✅ | ✅ |
| 绑定知识库 | ❌ | ✅ |
| 智能记忆（提炼/导入） | ❌ | ✅ |
| 24h 自动整理 | ❌ | ✅ |

### 7.2 闸门实现

**前端闸门**：
- 知识库/记忆开关：免费版灰显，点击弹激活 Modal
- 文案切换：免费版显示"升级正式版启用 →"

**后端闸门**：
- `_assert_kb_bind_allowed`：免费版禁止 `kb_ids` 非空
- `_assert_learning_allowed`：免费版禁止 `memories` 非空
- RAG 检索：未激活时强制 `use_kb=False`

---

## 8. 异常处理与降级策略

### 8.1 LLM 调用失败

| 场景 | 处理 |
|------|------|
| LLM 返回 error | 保存错误消息到会话，返回 error 给前端 |
| LLM 超时 | 由 provider 内部处理，返回 error |

### 8.2 记忆提炼失败

| 场景 | 处理 |
|------|------|
| 无对话 | 返回空结构，不覆盖原有记忆 |
| LLM 返回空 | 保留原有记忆 |
| 异步导入异常 | 推送 `memory_imported` error 事件 |

### 8.3 RAG 检索失败

| 场景 | 处理 |
|------|------|
| 检索异常 | try/except 捕获，不注入知识库内容，继续回复 |
| 知识库无数据 | 返回空，不注入 |

### 8.4 消息处理异常

| 场景 | 处理 |
|------|------|
| 流水线异常 | try/except 捕获，返回 PipelineResult(handled=False) |
| 线程池满溢 | 打印日志，消息丢弃 |

---

## 9. 渠道接入指引

### 9.1 渠道抽象

当前渠道层已抽象，接入新渠道需实现：

1. **渠道客户端**（类似 `wcf_client.py`）
   - 实现消息接收回调
   - 实现消息发送方法
   - 实现联系人获取方法

2. **消息格式适配**
   - 将渠道消息转为 `WcfMessage` 统一格式（或定义通用消息结构）
   - 字段：channel、peer_id、peer_name、peer_type、content、is_self

3. **绑定路由**
   - `BindingRouter` 已支持按 channel + peer_id 查找
   - 无需修改，新渠道自动适配

4. **消息流水线**
   - `MessagePipeline` 已渠道无关
   - 注入新渠道客户端即可

### 9.2 接入步骤

```
1. 创建 channel/<new_channel>_client.py
2. 实现接收/发送/联系人接口
3. 在 main.py 中初始化并注入 MessagePipeline
4. 在 bridge.py 中添加渠道状态查询接口
5. 前端连接页添加渠道开关
```

---

## 附录：IPC 接口清单

### 智能体
- `create_agent` / `update_agent` / `delete_agent` / `rename_agent`
- `get_agents` / `get_agent_recent`

### 记忆
- `refresh_memory` / `import_memory` / `list_migrated`
- `memory_imported`（推送）

### 知识库
- `create_kb` / `update_kb` / `delete_kb` / `get_kb_list`
- `add_kb_document` / `delete_kb_document` / `get_kb_document_chunks`
- `search_kb` / `export_kb`

### 渠道
- `set_channel_binding` / `list_channel_bindings`
- `fetch_wcf_contacts` / `fetch_wcf_avatar`
- `start_wcf` / `stop_wcf` / `get_wcf_status`

### LLM
- `save_llm_provider` / `delete_llm_provider` / `get_llm_providers`
- `set_default_llm_provider` / `test_llm_connection`

### 激活
- `get_activation_status` / `activate` / `import_license_file`
- `get_machine_code` / `export_machine_code`

---

*文档结束。如有理解偏差或遗漏，请反馈对齐。*
