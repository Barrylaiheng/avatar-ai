# PDD_INNER · P3-2 · wxid 会话隔离修复

> **模块 ID**: P3-2
> **Bug 编号**: Bug #11（P0 级隐私泄露）
> **版本**: v1.0
> **日期**: 2026-08-12
> **状态**: ✅ 闭环

---

## §1 Bug 描述

### 1.1 问题描述
`AppEngine.process_message` 方法中，调用 `ContextAssembler.get_or_create_session` 时硬编码 `wxid="ui_user"`，导致所有微信用户共用同一个会话上下文。

### 1.2 影响
- **隐私泄露**：用户 A 的对话历史（如"我喜欢吃辣"）会出现在用户 B 的上下文中
- **上下文污染**：用户 A 触发安全拦截后，整个 session 状态被污染，影响其他用户
- **违反 MVP 核心原则**：每个微信用户应有独立的会话上下文

### 1.3 根因
`_handle_wechat_message` 正确地将 `msg.sender_id` 作为 `session_id` 传入 `process_message`，但 `process_message` 内部调用 `get_or_create_session` 时未使用该值，而是硬编码 `wxid="ui_user"`。`session_id` 参数仅用于返回值，未传递给 ContextAssembler。

### 1.4 同类问题
`process_message_stream` 方法存在相同的硬编码问题。

---

## §2 修复方案

### 2.1 核心改动
1. `process_message` 新增 `wxid: str = "ui_user"` 参数（默认值保 UI 向后兼容）
2. `process_message_stream` 同步新增 `wxid` 参数
3. `_handle_wechat_message` 调用时传入 `wxid=msg.sender_id`
4. 两处 `get_or_create_session(wxid="ui_user")` 改为 `get_or_create_session(wxid=wxid)`

### 2.2 向后兼容性
- UI 路径（`worker_threads.py`、`ui_engine_bridge.py`）不传 `wxid` → 使用默认 `"ui_user"` → 行为不变
- 优化路径（`app_engine.py:1451`）不传 `wxid` → 使用默认 `"ui_user"` → 行为不变
- 微信路径传入 `wxid=msg.sender_id` → 每个用户独立 session → 修复隐私泄露

### 2.3 改动文件清单

| 文件 | 行号 | 改动 |
|------|------|------|
| `src/aibridge/app_engine.py` | L406 | `process_message` 签名新增 `wxid: str = "ui_user"` |
| `src/aibridge/app_engine.py` | L457 | `wxid="ui_user"` → `wxid=wxid` |
| `src/aibridge/app_engine.py` | L601-603 | `process_message_stream` 签名新增 `wxid: str = "ui_user"` |
| `src/aibridge/app_engine.py` | L683 | `wxid="ui_user"` → `wxid=wxid` |
| `src/aibridge/app_engine.py` | L1630 | `_handle_wechat_message` 传入 `wxid=msg.sender_id` |

---

## §3 Grill 清单（6 条）

| ID | 标题 | 断言要点 | 状态 |
|----|------|---------|------|
| G1 | process_message 签名含 wxid 参数 | `wxid` in params；默认值="ui_user"；位于 session_id 之后 | ✅ |
| G2 | 不同 wxid → 不同 session | session_a.wxid != session_b.wxid；session_id 不同；同 wxid 复用 | ✅ |
| G3 | _handle_wechat_message 传 wxid=sender_id | process_message 被调用；kwargs 含 wxid；wxid==msg.sender_id | ✅ |
| G4 | process_message_stream 含 wxid 参数 | `wxid` in params；默认值="ui_user" | ✅ |
| G5 | UI 路径向后兼容 | 不传 wxid 仍成功；sessions 表有 wxid='ui_user' 记录 | ✅ |
| G6 | 两个 wxid 用户上下文隔离 | sessions 表有 2 条记录；wxid 各异；session_id 不同 | ✅ |

---

## §4 开发任务

| # | 任务 | 文件 | 状态 |
|---|------|------|------|
| 1 | prototype 验证修复方案 | `_prototypes/wxid_session_isolation_prototype.py` | ✅ 21/21 PASS |
| 2 | process_message 签名修改 + wxid 透传 | `app_engine.py` L406, L457 | ✅ |
| 3 | process_message_stream 签名修改 + wxid 透传 | `app_engine.py` L601-603, L683 | ✅ |
| 4 | _handle_wechat_message 传 wxid=sender_id | `app_engine.py` L1630 | ✅ |
| 5 | pytest 测试用例 | `tests/test_inner_wxid_session_isolation_pdd.py` | ✅ 10/10 PASS |
| 6 | 规格文档 | `docs/PDD_INNER_wxid_session_isolation.md` | ✅ |
| 7 | 更新 PDD 总验收文档 v11.0 | `docs/PDD_INNER_TOTAL_ACCEPTANCE.md` | ✅ |

---

## §5 验证结果

### 5.1 Prototype
```
P3-2 wxid 会话隔离 prototype: 21/21 PASS, 0 FAIL
```

### 5.2 Pytest
```
10 passed in 2.47s
```

### 5.3 向后兼容验证
- UI 路径（不传 wxid）→ 使用默认 "ui_user" → ✅ 通过
- 微信路径（传 wxid=sender_id）→ 独立 session → ✅ 通过

---

## §6 后续依赖模块

- **P3-3**: 15 步流水线集成（process_v2 接入 AppEngine 主流程）— 修复后需验证 process_v2 也正确传递 wxid
- **公众号云端**: OALiteContextAssembler 已独立实现，不受本次修改影响
