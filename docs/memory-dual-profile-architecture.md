# 记忆与进化 · 双层 Profile 架构梳理

> 梳理日期：2026-09-16
> 触发起点：管理者排他检查修复后，用 151 同时绑定「钉钉测试」和「主人模式测试」，发现 `peer_type` 不同步 bug，进而深挖 per-agent profile 混多人的架构缺陷

---

## 一、起点：从 bug 到架构问题

### 1.1 触发场景

管理者排他检查修复后，用户用 151 同时绑定「钉钉测试」和「主人模式测试」两个智能体，在钉钉发消息验证管理者聚合路由。

### 1.2 验证结果

| 检查项 | 结果 |
|---|---|
| 排他检查修复 | ✅ 151 在两个 agent 下都成功保存为 is_manager=1 |
| `find_all_agents_for_manager` SQL | ✅ 返回 2 条记录 |
| pipeline 管理者分叉 | ✅ 日志打印 `★ 管理者模式命中` |
| bridge 聚合 RAG | ✅ 日志打印 `★ 管理者模式：聚合 2 个 agent 的 kb_ids → 1 个唯一 ID` |
| bridge 跳过 memories 注入 | ✅ `if not is_manager_mode:` 生效 |

### 1.3 发现的 bug

**重要 bug（影响画像质量）**：`_get_or_create_conversation` 复用旧会话时只调 `touch(cid)`，**不 UPDATE peer_type 字段**。

```
conv_b0b627b42f61 是 9/14 创建的旧会话，peer_type='friend'
9/16 走管理者路径时，pipeline 内部变量 peer_type='manager' 但 DB 没改
→ 提炼时 bridge.py L5123 s.get("peer_type") != "manager" 过滤失效
→ 管理者和 AI 的对话被误当成普通用户对话 → 混进画像
```

**次要 bug（不影响运行）**：`peer_type` 字段同步缺失——和上面同一个根因，只是这次暴露在记忆提炼环节。

### 1.4 决策：先不修 bug，先梳理架构

bug 本身是**架构缺陷的症状**（per-agent 一份 profile 混多人），先理清记忆与进化的整体定位再修，避免头疼医头。

---

## 二、视觉锚定法：回到「记忆与进化」前端面板

### 2.1 前端是什么

```
智能体配置 → 记忆与进化 Tab
├── 开关：记忆进化 enable/disable
├── 画像区：user_profile（长期画像）条目列表
├── 重点区：episodic（近期重点）条目列表
└── 操作：刷新 / 编辑 / 导入
```

**per-agent scope**——这个面板属于「当前选中的智能体」，前端只看当前 agent 的 memories。

### 2.2 刷新做了什么

```
用户点「刷新」
  → 前端调 refresh_memory(agent_id)
  → 后端 _do_memory_extract_pure(agent_id)
    → conv_dao.list_by_agent(agent_id)  查出该 agent 下所有会话
    → 每个会话取最近 40 条 → 合并成一坨 → 喂 LLM 提炼
    → 输出 { user_profile: [...], episodic: [...] }
    → 存回 ai_agent.memories（JSON 字符串）
  → 前端渲染到面板
```

### 2.3 核心问题浮现

> 一个智能体对接 N 个人 → per-agent 一份 profile 混了所有人的对话 → LLM 可能把 A 的偏好和 B 的偏好揉在一起

---

## 三、深挖：per-agent vs per-peer

### 3.1 现状数据层

```
ai_agent.memories（per-agent）
  └── { user_profile: [...], episodic: [...] }

conversation 表（按 agent_id 归档）
  ├── conv_b0b627b42f61  agent=钉钉测试  peer=151
  ├── conv_3c8dbf634a00  agent=钉钉测试  peer=赖恒
  └── conv_xxx           agent=钉钉测试  peer=群聊
```

**没有 per-peer 这一层**。conversation 表里也没有 memories 字段。

### 3.2 两种架构方向

| 方向 | scope | 普通用户 | 管理者（151绑A+B） | 业界评价 |
|---|---|---|---|---|
| 维持现状 | per-agent 一份 | 混人 ❌ | 混人 ❌ | Cross-Contamination |
| **双层架构** | per-agent + per-peer | **各有一份** ✅ | **各有一份** ✅ | ✅ 业界共识 |

### 3.3 per-peer 的 scope 关键决策

| scope | 普通用户 | 管理者 |
|---|---|---|
| (agent_id, channel, peer_id) | 一份 ✅ | **两份** ❌ 画像分裂 |
| **(channel, peer_id)** | **一份** ✅ | **一份** ✅ 不分裂 |

**决策**：scope = `(channel, peer_id)`，DB 层 `UNIQUE (channel, peer_id)` 物理保证——一个渠道一个 peer 只有一份画像，不管绑了几个 agent。

### 3.4 管理者 vs 普通用户的区分

| 角色 | 排他性 | per-peer profile scope |
|---|---|---|
| 普通用户 | 排他（`find_conflict`） | (channel, peer_id) 一份 |
| 管理者 | 不排他（跳过 `find_conflict`） | 也是 (channel, peer_id) 一份 |

**统一**——两种角色用同一套表结构，靠 `role` 字段区分，不搞两张表。

---

## 四、业界调研论证

### 4.1 per-peer 独立画像 = 业界共识

| 来源 | 观点 |
|---|---|
| **Mem0（52.5K Stars，2400万A轮）** | 三层 scope：per-user long-term + per-session task + shared domain。per-user keyed by user_id |
| **LightMem（电子科大+港大 2026.04 arXiv）** | "uses user identifiers to support independent retrieval and incremental maintenance in multi-user settings" |
| **阿里云 AgentRun（2026.08）** | 长期记忆 = per-user 画像 + 会话历史 + 会话状态 |

### 4.2 per-agent 混多个人 = Cross-Contamination

| 来源 | 观点 |
|---|---|
| **AgentixForce（2026.05）** | "Cross-contamination is both a privacy violation and a correctness failure" |
| **Luonghongthuan（2026.07 生产实战）** | "The architecture mistake I see most often: teams build one global knowledge base and retrieve from it for all users" |
| **zylos.ai（2026.07 Evolving User Profile）** | 提炼时 LLM 把不同人的特征揉在一起 → 画像不准 |

### 4.3 scope 物理隔离 = 正确方向

| 来源 | 观点 |
|---|---|
| **Oracle（2026.07 多租户 SaaS）** | "Tenant isolation should be enforced by the database, not just application code. Add tenant_id on every durable memory row" |
| **AgentixForce（2026.05）** | 层级 namespace：`mem:{tenant_id}.{user_id}.{memory_type}.{item_id}`，数据库层物理隔离 |

### 4.4 per-agent profile 仍然有价值

| 来源 | 观点 |
|---|---|
| **Mem0** | shared domain memory = agent 级通用知识 |
| **阿里云 AgentRun** | 长期记忆（per-user）+ 会话历史（per-session）+ 会话状态（per-session） |
| **zylos.ai（2026.07）** | Full-rewrite pipeline：读旧 profile + 新互动 → 完整替换，MVP 现有逻辑就是这个 |

---

## 五、最终方案：双层 Profile 架构

### 5.1 数据层

```
原始数据层
  conversation + chat_message（按 agent_id 归档）
        │
        ├── 按 agent_id 全量汇总提炼 ──→ per-agent profile   ✅ 已有
        │   scope = ai_agent.id
        │   前端「记忆与进化」面板显示
        │
        └── 按 (channel, peer_id) 分组提炼 ──→ per-peer profile   🆕 新增
            scope = UNIQUE(channel, peer_id)，物理保证不分裂
            前端不显示，纯后端资产
```

### 5.2 per-agent vs per-peer 的定位

| 维度 | per-agent profile | per-peer profile |
|---|---|---|
| **scope** | ai_agent.id | UNIQUE(channel, peer_id) |
| **提炼来源** | 该 agent 下所有会话汇总 | 该 peer 在该渠道下的所有会话 |
| **提炼时机** | 刷新按钮 / 自动提炼 | 和 per-agent 同步跑 |
| **存储位置** | ai_agent.memories（JSON） | 新增表 peer_profile |
| **前端显示** | ✅ 记忆与进化面板 | ❌ 不显示 |
| **用途** | agent 级通用知识（团队做什么、风格偏好） | 每个人的专属画像 |
| **管理者模式** | 多个 agent 的 per-agent 都聚合 | **一份** per-peer（不随 agent 变） |

### 5.3 回复时 context 组装

```
普通用户路径（单 agent）：
  system_parts = [
    persona,                              # agent 角色
    per-agent profile,                   # agent 级通用知识
    per-peer profile,                    # 该用户专属画像 🆕
    ANCHOR_RULES,                        # 通用底线规则
    RAG 检索结果,                         # 知识库
    历史对话,                             # 上下文
  ]

管理者路径（多 agent 聚合）：
  system_parts = [
    MANAGER_PROMPT,                      # 主人模式预设
    agent_A 的 per-agent profile,        # 聚合多个 agent 的通用知识
    agent_B 的 per-agent profile,
    per-peer profile,                    # 管理者专属画像（只有一份）🆕
    ANCHOR_RULES,
    聚合 RAG 检索结果,
    历史对话,
  ]
```

### 5.4 新增表设计

```sql
CREATE TABLE peer_profile (
  id TEXT PRIMARY KEY,
  channel TEXT NOT NULL,
  peer_id TEXT NOT NULL,
  peer_name TEXT NOT NULL DEFAULT '',
  role TEXT NOT NULL DEFAULT 'user',        -- 'user' | 'manager'
  memories TEXT NOT NULL DEFAULT '{}',      -- JSON: { enabled, user_profile: [], episodic: [] }
  last_refine_at INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL DEFAULT 0,
  updated_at INTEGER NOT NULL DEFAULT 0,
  UNIQUE (channel, peer_id)                 -- ← 核心：物理保证一份画像
);
```

### 5.5 改动量评估

| 模块 | 改动 | 量 | 风险 |
|---|---|---|---|
| DB 加表 `peer_profile` | 新建表 + `UNIQUE(channel, peer_id)` | 小 | 低 |
| 提炼逻辑改 | 加按 peer 分组循环，每组单独跑提炼 | 中 | 中（LLM 调用翻倍） |
| 回复加载改 | 注入时加 per-peer profile | 小 | 低 |
| 管理者聚合改 | 多个 per-agent + 一份 per-peer | 小 | 低 |
| 前端 | **零改动** | 零 | 零 |
| 修 peer_type 同步 bug | `_get_or_create_conversation` 复用旧会话时 UPDATE peer_type | 小 | 低 |

### 5.6 边界与约束

| 边界 | 说明 |
|---|---|
| 前端不改 | per-agent 面板维持，per-peer 不显示 |
| 老数据迁移 | 首次跑提炼时按 peer 分组批量填充 peer_profile |
| 管理者跳过 agent profile 注入 | 保持现有逻辑，但 **per-peer profile 对管理者也要注入** |
| 提炼时机 | MVP：用户点刷新或自动提炼时同时跑 per-agent + per-peer |
| LLM 成本 | 翻倍左右（N 个 peer = N+1 次提炼），MVP 可接受，V2 合并/缓存 |

---

## 六、遗留 bug 跟进

| bug | 根因 | 修法 | 状态 |
|---|---|---|---|
| 会话 peer_type 不同步 | `_get_or_create_conversation` 复用旧会话只 `touch` 不 UPDATE peer_type | 复用旧会话时加 `UPDATE conversation SET peer_type=? WHERE id=?` | **待修**（和双层 profile 一起做） |
| 管理者会话被误提炼 | 同上 + bridge.py L5123 按 peer_type 过滤 | 修了 peer_type 同步后自动解决 | **待修** |

---

## 七、整体影响一览

| 模块 | 影响 |
|---|---|
| **知识库**（之前调研过） | 无影响，per-agent 维持，per-peer profile 不碰 RAG |
| **管理者路由**（已落地） | 无冲突，per-peer profile 和聚合 RAG 互补 |
| **排他检查**（已落地） | 无冲突，per-peer scope 用 UNIQUE 保证一份 |
| **前端** | 零改动 |
| **DB** | 加一张表，老库自动升级 |
| **LLM 成本** | 翻倍左右，MVP 可接受 |

---

## 八、MVP 内部代码位置速查

| 环节 | 文件 | 位置 |
|---|---|---|
| 提炼入口 | bridge.py | `_do_memory_extract_pure` L5092 |
| 提炼 prompt | bridge.py | `MEMORY_REFINE_SYSTEM_PROMPT` L69 |
| 提炼跳过管理者会话 | bridge.py | L5123 `s.get("peer_type") != "manager"` |
| 格式化注入文本 | bridge.py | `_format_memory_for_prompt` L4679 |
| 注入位置 | bridge.py | L5704-5707 |
| 管理者跳过注入 | bridge.py | L5703-5704 `if not is_manager_mode:` |
| 会话创建/复用 | message_pipeline.py | `_get_or_create_conversation` L319 |
| 管理者路由 | binding_router.py | `find_all_agents_for_manager` |

---

## 九、核心决策点回顾

1. ✅ per-peer profile 的 scope = `(channel, peer_id)`，DB `UNIQUE` 物理保证一份
2. ✅ per-agent profile 保留，不删，和 per-peer 互补
3. ✅ 前端零改动
4. ✅ 和之前落地的管理者路由/聚合 RAG 无冲突
5. ✅ 管理者和普通用户用同一张 `peer_profile` 表，靠 `role` 字段区分
