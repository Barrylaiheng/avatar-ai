# P3-1 · 模块规格：WCF 私聊回复地址修复 + 回复链路验证

> **版本**：v1.0
> **日期**：2026-08-12
> **模块定位**：P0 级 Bug 修复 — 微信渠道私聊场景下 AI 回复发送给机器人自己，用户收不到回复。

---

## §1 Bug 描述

### 1.1 根因
`message_router.py` 第 136 行（修复前）：
```python
receiver_id = msg.receiver_id if msg.is_private else msg.group_id
```

`wcf_adapter.py` 第 338 行构造 InternalMessage 时：
```python
receiver_id=group_id if is_group else self._self_wxid
```

私聊场景下 `receiver_id = self._self_wxid`（机器人自己的 wxid），而 `send_response` 用 `msg.receiver_id` 作为回复目标 → **回复发给机器人自己，用户收不到**。

### 1.2 影响范围
- **微信私聊场景完全不可用**：用户发消息给机器人，AI 生成回复后发送给机器人自己
- 群聊场景不受影响（`group_id` 在两个地方一致）
- 公众号场景不受影响（OA 适配器直接用 `sender_id` 发送）

### 1.3 对比 OA 渠道的正确实现
`oa_service/app.py` 第 380 行：`self.client.send_text(msg.sender_id, reply_content)` — 直接用 `sender_id`，所以公众号渠道没有这个 bug。

---

## §2 修复方案

### 2.1 核心改动（1 行代码）
`message_router.py` `send_response` 方法：
```python
# 修复前（BUG）：
receiver_id = msg.receiver_id if msg.is_private else msg.group_id
# 修复后：
receiver_id = msg.sender_id if msg.is_private else msg.group_id
```

### 2.2 设计决策
| 决策 | 理由 |
|------|------|
| 修 `message_router.py` 而非 `wcf_adapter.py` | `receiver_id` 在 InternalMessage 中的语义是"消息的接收者"（收消息时 = 机器人自己），这个语义没问题。问题在于 `send_response` 不应该用 `receiver_id` 做回复目标，而应该用 `sender_id`（回复给发送者）|
| 不改 `wcf_adapter.py` 的 `receiver_id` 赋值 | `receiver_id = self._self_wxid` 在私聊场景下语义正确（消息接收方确实是机器人），改了会影响其他依赖 `receiver_id` 的逻辑 |
| 群聊逻辑不变 | 群聊时 `group_id` 在两个地方一致，回复到群里是正确的 |

---

## §3 Grill 清单 & Test Seams（6 Seams）

| ID | 标题 | 断言要点 |
|----|------|---------|
| G1 | 私聊回复地址 = sender_id | mock adapter 捕获 send_message 的 receiver_id == USER_WXID；!= BOT_WXID |
| G2 | 群聊回复地址 = group_id | mock adapter 捕获 send_message 的 receiver_id == GROUP_ID |
| G3 | send_response 源码正确 | 源码含 `sender_id` + `is_private`；不含 `msg.receiver_id if msg.is_private` |
| G4 | 多用户私聊各自收到回复 | 3 个不同用户私聊，各自回复地址 == 各自 sender_id |
| G5 | 多群聊各自收到回复 | 2 个不同群聊，各自回复地址 == 各自 group_id |
| G6 | 修复前后对比 | buggy 逻辑 receiver_id == BOT_WXID；修复后 == USER_WXID；两者不同 |

---

## §4 Prototype 验证结果

**原型文件**：[_prototypes/wcf_reply_fix_prototype.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/_prototypes/wcf_reply_fix_prototype.py)

**结果**：修复前 8/17 PASS（9 FAIL，全部是私聊场景）→ 修复后 **17/17 ALL PASS ✅**

---

## §5 正式代码改动

| 文件 | 改动 | 行号 |
|------|------|------|
| [message_router.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/bridges/message_router.py#L136-L139) | `send_response` 方法第 136 行：`msg.receiver_id` → `msg.sender_id`（私聊分支） | L136-L139 |

---

## §6 Pytest 测试用例

**测试文件**：`tests/test_inner_wcf_reply_fix_pdd.py`

6 个测试函数对应 6 条 Grill，使用 MockAdapter 捕获 `send_message` 调用实参。
