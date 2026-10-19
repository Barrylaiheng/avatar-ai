# 里层 PDD · 第 2 模块规格文档 · FINAL
## `engine/safety_shield_v2.py` — 免疫 L2 · 关键词检测 + 三击拉黑 + AuditLog 持久化

> **模块 ID**：INNER-SS02
> **定位**：里层 PDD 第 2 模块 = 免疫系统（message_processor S05/S07 的真实持久化后端）
> **五层架构**：L1 免疫
> **覆盖来源**：V1.1 G-05/G-06 + message_processor prototype SS-13~17 + 真版 content_moderation.py 关键词库

---

## 0. 6 阶段完成度

| 阶段 | 状态 | 说明 |
|-----:|------|------|
| ① grill-with-docs | ✅ | SS-01~SS-08 自问自答（规则已在模块 1 G-05/G-06 拍板） |
| ② prototype | ✅ 10/10 | [_prototypes/safety_shield_prototype.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/_prototypes/safety_shield_prototype.py) |
| ③ to-spec | ✅ 10 Seams | 下文 §3 |
| ④ to-tickets | ✅ 3 条 | 下文 §4 |
| ⑤ implement+tdd | ✅ 10/10 | [tests/test_inner_safety_shield_pdd.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/tests/test_inner_safety_shield_pdd.py) |
| ⑥ code-review + 回归 | ✅ | 32 passed（22 MP + 10 SS）双轴评审通过 |

---

## 1. Grill SS-01~SS-08 拍板

| 编号 | 问题 | 决策 |
|-----:|------|------|
| SS-01 | 职责边界 | SafetyShieldV2 只管：① 黑名单查询 ② 关键词检测+三击拉黑 ③ audit_log 写入+查询 ④ 自定义关键词扩展。不管话术发送（那在 message_processor S07） |
| SS-02 | 黑名单 schema | `safety_blacklist(wxid, hit_count, first_hit_at, latest_hit_at, blacklist_until, reason)` |
| SS-03 | audit_log schema | `safety_audit_log(log_id, wxid, msg_id, hit_category, hit_keyword, action_taken, content_snippet, created_at)` |
| SS-04 | 关键词库 | 默认 24 广告+11 砍价在常量里；DB 表 `safety_keywords` 支持用户自定义扩展 |
| SS-05 | 规则缓存 | 每次查询实时从 DB 读（无缓存），保证一致性；后续 v2 可加进程级缓存 |
| SS-06 | 接口 | `check_blacklist(wxid)` + `check_content(wxid, content, msg_id)` + `get_audit_logs(limit, offset)` + `add_keyword(keyword, category)` |
| SS-07 | audit_log 查询 | `get_audit_logs(limit=50, offset=0)` 按 created_at DESC，给 UI 审核页用 |
| SS-08 | 黑名单解禁 | 自动到期（blacklist_until < now → check_blacklist 返回 is_blacklisted=False） |

---

## 2. 核心接口

| 方法 | 入参 | 返回 | 说明 |
|------|------|------|------|
| `check_blacklist(wxid)` | wxid | `BlacklistStatus(is_blacklisted, remain_hours, reason)` | S05 前置调用 |
| `check_content(wxid, content, msg_id)` | wxid, content, msg_id | `SafetyHitResult(hit, category, keyword, warn_message, is_third_hit)` | S07 调用，含关键词扫描+三击拉黑+audit_log 写入 |
| `get_audit_logs(limit, offset)` | limit, offset | `List[dict]` | UI 审核页查询 |
| `add_keyword(keyword, category)` | keyword, category | `bool` | 自定义关键词扩展 |

---

## 3. 10 条 Test Seams

| ID | 标题 | 断言 |
|----|------|------|
| SS-01 | 正常内容不命中 | hit=False, category="", warn_message="" |
| SS-02 | 砍价命中 | hit=True, category="砍价", warn_message 含"砍价" |
| SS-03 | 广告命中 | hit=True, category="广告", warn_message 含"引流" |
| SS-04 | 三击拉黑 | 第 3 次 is_third_hit=True, warn_message="" |
| SS-05 | 黑名单前置拦截 | is_blacklisted=True, remain_hours>0 |
| SS-06 | 黑名单用户普通内容不二次命中 | check_content 只管关键词，不查黑名单 |
| SS-07 | 非黑名单用户放行 | is_blacklisted=False |
| SS-08 | 审计日志可查 | 有 warn + blacklist_7d 两种动作 |
| SS-09 | 自定义关键词扩展 | add_keyword → check_content 命中 |
| SS-10 | 黑名单到期自动解禁 | blacklist_until < now → is_blacklisted=False |

---

## 4. Tickets（3 条）

| ID | 任务 | 关联 Seams |
|----|------|-----------|
| T1 | DB migration v5：新增 3 张表（safety_blacklist/safety_audit_log/safety_keywords） | 全部 |
| T2 | 实现 SafetyShieldV2 类（4 个接口） | SS-01~SS-10 |
| T3 | 接 message_processor S05/S07 真实调用 + 22+10 回归 | 全部 |

---

## 5. 双轴评审

### 轴 1 · Fowler 代码异味
- ✅ 无 God Class：SafetyShieldV2 只 4 个 public 方法，内部 helper 6 个，职责单一
- ✅ 无魔法数字：3 击/24h/7d 都是模块常量
- ✅ 无全局状态：所有状态在 DB 里，不在内存

### 轴 2 · 规格忠实度
- ✅ 10 Seams 逐条对应
- ✅ 关键词库 24+11 与 message_processor prototype 一致
- ✅ 三击拉黑后 warn_message="" 与 G-06 拍板一致
- ✅ audit_log 同时写 warn + blacklist_7d 两条记录

---

## 6. 交付物

| 产物 | 位置 |
|------|------|
| Prototype | [_prototypes/safety_shield_prototype.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/_prototypes/safety_shield_prototype.py) |
| 正式实现 | [src/aibridge/engine/safety_shield_v2.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/engine/safety_shield_v2.py) |
| 测试 | [tests/test_inner_safety_shield_pdd.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/tests/test_inner_safety_shield_pdd.py) |
| DB Migration v5 | [src/aibridge/database/database_migrator.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/database/database_migrator.py#L264-L299) |
| message_processor S05/S07 接入 | [src/aibridge/engine/message_processor.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/engine/message_processor.py#L875-L930) |
