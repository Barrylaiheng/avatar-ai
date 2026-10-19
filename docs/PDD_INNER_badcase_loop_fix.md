# P3-4 · BadCase 闭环修复（Bug #13~#16）规格文档

> **模块**：里层 P3 · 迭代引擎闭环修复
> **等级**：P0~P3 · 多级混合（4 个断裂点）
> **父模块**：P3 · 微信渠道消息链路 → 迭代引擎集成
> **前置依赖**：P3-3（15 步流水线集成，S14 写入 BadCase）、T4（IterationEngine 基础）
> **关联 Bug**：#13（P0）、#14（P1）、#15（P2）、#16（P3）

---

## §1 · Bug 描述与根因

### Bug #13 (P0) · review_rule_draft 方法不存在
- **现象**：AppEngine.review_rule_draft 调用 `self._iteration_engine.review_rule_draft(draft_id, approved)`，但 IterationEngine 类只有 `approve_rule_draft(draft_id, reviewer)`，没有 `review_rule_draft`。
- **后果**：规则草案审核功能完全失效，except 吞掉 AttributeError 返回 False。迭代闭环最后一环断裂。
- **修复**：IterationEngine 新增 `review_rule_draft(draft_id, approved)` 方法，approved=True 调 approve_rule_draft，approved=False 标记 rejected。

### Bug #14 (P1) · metadata 字段三处缺失
- **现象**：badcases 表无 metadata 列；_save_badcase INSERT 不含 metadata；get_badcases SELECT 不回填 metadata。
- **后果**：S14 写入的 `{"reasons": [...], "source": "S14_auto"}` 完全丢失，无法回溯 BadCase 成因。RuleDraftGenerator 拿不到 matched_pattern/expected_tone，规则草案内容空洞。
- **修复**：① migration v6 新增 `metadata TEXT DEFAULT '{}'` 列；② INSERT 加 metadata 字段（json.dumps）；③ SELECT 回填 metadata（json.loads）。

### Bug #15 (P2) · IterationEngine 初始化参数错配
- **现象**：`IterationEngine(self._db, self._config)` 第二参数应为 `llm_client`，却传入 ConfigManager。
- **后果**：detector 和 draft_generator 的 LLM 深度检测/生成功能失效（虽然当前未真正调用 LLM，但未来扩展受限）。
- **修复**：改为 `IterationEngine(self._db)`，不传第二参数。

### Bug #16 (P3) · get_bad_cases 排序 key 错误
- **现象**：`merged.sort(key=lambda c: c.get("timestamp", 0))` 但 BadCase.to_dict() 返回的是 `created_at`，没有 `timestamp` 字段。
- **后果**：排序 key 永远取默认值 0，排序无效，UI 显示顺序不可预期。
- **修复**：改为 `c.get("created_at", "")`。

---

## §2 · Grill 清单（6 条 19 断言）

| Grill | 断言 | 验证点 |
|-------|------|--------|
| G1 | review_rule_draft 方法存在 + 签名含 draft_id/approved | Bug #13 |
| G2 | metadata 写入后读回 + reasons/source/custom 保留 | Bug #14 |
| G3 | review_rule_draft approve=True → status=approved；approve=False → status=rejected；不存在 → False | Bug #13 |
| G4 | get_bad_cases 按 created_at 降序排列 | Bug #16 |
| G5 | IterationEngine detector._llm_client 不是 ConfigManager | Bug #15 |
| G6 | S14 BadCase 通过 get_bad_cases 读回含 metadata | 端到端闭环 |

---

## §3 · Test Seams（pytest 10 个）

| ID | 用例 |
|----|------|
| T1 | review_rule_draft 方法存在 + 签名正确 |
| T2 | metadata write → read roundtrip（reasons/source/custom 保留） |
| T3 | review_rule_draft approve=True → status=approved |
| T4 | review_rule_draft approve=False → status=rejected |
| T5 | 不存在的 draft_id 返回 False |
| T6 | get_bad_cases 按 created_at 降序排列 |
| T7 | IterationEngine detector._llm_client 不是 ConfigManager |
| T8 | S14 BadCase 通过 get_bad_cases 读回含 metadata |
| T9 | AppEngine.review_rule_draft 调用不抛异常 |
| T10 | metadata 为空时不崩溃（默认空 dict） |

---

## §4 · 修改文件清单

| 文件 | 修改 |
|------|------|
| `src/aibridge/database/database_migrator.py` | MIGRATIONS 新增 v6 + `_migrate_v6_add_badcase_metadata` 方法（ALTER TABLE 加 metadata 列） |
| `src/aibridge/engine/iteration_engine.py` | `_save_badcase` INSERT 加 metadata；`get_badcases` SELECT 回填 metadata；新增 `review_rule_draft` 方法 |
| `src/aibridge/app_engine.py` | `IterationEngine(self._db)` 去掉 config 参数；`get_bad_cases` 排序 key 改为 created_at |

---

## §5 · 验收标准

- [x] **prototype 验证**：19/19 ALL PASS
- [x] **pytest 回归**：10/10 ALL PASS
- [x] **PDD 总验收文档更新**：版本 v13.0，含 P3-4 模块
