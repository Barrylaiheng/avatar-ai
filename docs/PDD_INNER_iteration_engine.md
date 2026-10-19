# 里层 PDD · 第 4 模块规格文档 · FINAL
## `engine/iteration_engine.py` — 迭代 L7 · BadCase 检测 + 规则草案 + 审核闭环

> **模块 ID**：INNER-IE04
> **定位**：里层 PDD 第 4 模块 = 迭代系统（message_processor S14 的真实持久化后端）
> **五层架构**：L7 迭代
> **覆盖来源**：V1.1 G-10 扩展（3 写入点）+ message_processor S14 + 现有 iteration_engine.py

---

## 0. 6 阶段完成度

| 阶段 | 状态 | 说明 |
|-----:|------|------|
| ① grill | ✅ | IE-01~IE-08 自问自答（现有代码已覆盖大部分逻辑） |
| ② prototype | ✅ | 现有代码已完整，直接写测试验证 |
| ③ to-spec | ✅ 8 Seams | 下文 §3 |
| ⑤ implement+tdd | ✅ 8/8 | [tests/test_inner_iteration_engine_pdd.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/tests/test_inner_iteration_engine_pdd.py) |
| ⑥ 回归+评审 | ✅ | 48 passed（22+10+8+8）+ S14 接入 |

---

## 1. Grill 拍板

| 编号 | 问题 | 决策 |
|-----:|------|------|
| IE-01 | 6 维检测 | 安全合规/知识盲区/用户体验 MVP 阶段用正则；事实性/角色一致性/业务规则需 context |
| IE-02 | 写库时机 | S14 标记 write_bad_case=True 时，直接写 badcases 表（不走 detect_async 避免重复检测） |
| IE-03 | reason → 维度映射 | LLM兜底→knowledge_gap/medium；安全命中→safety/high；用户反馈→user_experience/medium |
| IE-04 | 审核流程 | pending → approve → auto generate RuleDraft → approve draft → merge to compliance_rules |

---

## 2. 核心接口

| 方法 | 入参 | 返回 | 说明 |
|------|------|------|------|
| `detect_async(user_input, ai_response, session_id, msg_id, context)` | str + dict | `List[BadCase]` | 6 维检测，自动写 badcases 表 |
| `get_badcases(status, severity, limit)` | str, str, int | `List[BadCase]` | 查询 BadCase 列表 |
| `approve_badcase(case_id, comment)` | str, str | bool | 审核通过 → 自动生成 RuleDraft |
| `approve_rule_draft(draft_id, reviewer)` | str, str | bool | 审核通过 → 合并到 compliance_rules/safety_shell_config |

---

## 3. 8 条 Test Seams

| ID | 标题 | 断言 |
|----|------|------|
| IE-01 | 安全合规检测 | AI 回复含"我是一个AI" → safety 维度, severity=high |
| IE-02 | 知识盲区检测 | AI 回复含"我不知道" → knowledge_gap 维度, severity=low |
| IE-03 | 用户体验检测 | AI 回复 >500 字 → user_experience 维度 |
| IE-04 | 正常回复不检测 | 正常回复 → 0 条 BadCase |
| IE-05 | 查询待审核列表 | get_badcases(status="pending") ≥ 2 条 |
| IE-06 | 审核→生成草案 | approve_badcase → get_drafts ≥ 1 条 |
| IE-07 | 审核草案→合并规则 | approve_rule_draft → compliance_rules 有新规则 |
| IE-08 | S14 衔接 | message_processor bad_case_reasons → write_bad_case=True |

---

## 4. S14 衔接实现

[message_processor.py S14](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/engine/message_processor.py#L1125-L1169)：

```python
# S14 原来只标记，现在真实写 badcases 表
if write_bad:
    from aibridge.engine.iteration_engine import IterationEngine, BadCase, DetectionDimension, BadCaseSeverity
    ie = IterationEngine(self._db)
    # reason → 维度映射
    if "LLM兜底" in reasons_str:
        detected_by = DetectionDimension.KNOWLEDGE_GAP.value
    elif "安全命中" in reasons_str:
        detected_by = DetectionDimension.SAFETY.value
    elif "用户反馈" in reasons_str:
        detected_by = DetectionDimension.USER_EXPERIENCE.value
    case = BadCase(case_id=..., msg_id=msg_id, user_input=content, ai_response=reply, ...)
    ie.detector._save_badcase(case)
```

---

## 5. 双轴评审

### 轴 1 · Fowler
- ✅ 现有代码结构清晰：BadCaseDetector / RuleDraftGenerator / IterationEngine 三类职责分离
- ✅ 无重复检测：S14 直接写 badcases，不走 detect_async
- ✅ 异常安全：S14 写 badcase 失败不影响主流程（logger.warning + continue）

### 轴 2 · 规格忠实度
- ✅ 8 Seams 逐条对应
- ✅ G-10 扩展的 3 写入点全部映射到 badcases 表
- ✅ 审核闭环完整：detect → pending → approve → draft → merge

---

## 6. 交付物

| 产物 | 位置 |
|------|------|
| 正式实现（现有） | [src/aibridge/engine/iteration_engine.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/engine/iteration_engine.py) |
| 测试 | [tests/test_inner_iteration_engine_pdd.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/tests/test_inner_iteration_engine_pdd.py) |
| S14 接入 | [message_processor.py S14](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/engine/message_processor.py#L1125-L1169) |
