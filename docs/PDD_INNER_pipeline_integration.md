# P3-3 · 15 步流水线集成到 AppEngine 主流程（Bug #12 P0-1 修复）规格文档

> **模块**：里层 P3 · 微信渠道消息链路核心能力补全
> **等级**：P0-1 · 架构级缺口（主流程未接入核心流水线）
> **父模块**：P3 · 微信渠道消息链路
> **前置依赖**：T1~T6（MessageProcessor.process_v2 15 步完成）、map_internal_to_processor、AppEngine._handle_wechat_message（M-19）
> **关联 Bug**：#12

---

## §1 · Bug 描述与根因

### Bug 现象
AppEngine._handle_wechat_message（M-19）调用的是简化版 `process_message` 方法，而不是里层 PDD 定义的 15 步流水线 `MessageProcessor.process_v2()`。

导致以下 **11 项核心能力** 在微信渠道主流程中完全缺失：

| 步骤 | 缺失能力 | 业务影响（严重度） |
|------|---------|-----------------|
| S01 | 消息类型过滤（图片/视频/系统消息跳过） | 非文本消息进入 LLM，API Key 浪费 / 报错 |
| S02 | 群聊未@机器人 / 未触发关键词 → 静默丢弃 | 机器人在群里乱回复，刷爆群，被踢 🔴 P0 |
| S03 | 空消息提前跳过 | 空内容进入 LLM |
| S04 | (wxid, content) 10 秒去重 | 用户重复发送，LLM 重复调用 🔴 P0 浪费 |
| S05 | 黑名单前置检查（被拉黑用户不回复） | 拉黑机制形同虚设 🟠 P1 |
| S06 | 管理群命令快捷通道 | 管理群指令不能被机器识别 |
| S07 | 安全壳 + 三击拉黑（广告/砍价/违规拦截） | 违规消息无拦截，合规风险 🔴 P0 |
| S08 | 主人消息仅同步历史（不被 AI 回复） | 主人发消息被 AI 打断 🔴 P0 |
| S11 | AIGC 盖章 + 兜底 3 档（配置异常/API故障） | 回复无免责声明，合规风险 🟠 P1 |
| S12/S13 | ChatHistory + AuditLog 双写 | 无会话记录可追溯 🟠 P1 |
| S14 | BadCase 自动写入 | 兜底 / 安全命中无法被迭代系统发现 🟠 P1 |
| S15 | action 语义（reply / silent_drop / block） | 回发决策无统一标准 |

### 根因分析
M-19（微信渠道适配层）在实现时，`MessageProcessor.process_v2` 尚未完工，因此采用了简化的 `process_message`（UI 路径）作为临时方案。
v3.1 process_v2 完成后未回填 AppEngine 主流程，导致架构层错位：**最复杂的微信渠道用了最简化的路径，而能力最强的 process_v2 只在 E2E 测试里跑过。**

---

## §2 · 修复方案

### §2.1 组件新增
在 `AppEngine` 中新增两个属性：

```python
self._message_processor: Optional[MessageProcessor] = None
self._master_wxid_set: set = set()
```

### §2.2 初始化时序（initialize 末尾）
在 `self._initialized = True` 之前追加两段：

1. **实例化 MessageProcessor**：
   ```
   MessageProcessor(config_manager=self._config,
                    db_manager=self._db,
                    rag_engine=self._rag_engine)
   ```
   - 初始化失败时 `self._message_processor = None`，回退到简化路径
   - 不阻断 AppEngine 启动（非致命）

2. **构造 master_wxid_set**：
   - 合并 `config["master_wxid"]`（单值）+ `config["master_wxid_list"]`（多值）
   - 结果统一为 `set[str]`，传入 `map_internal_to_processor(msg, master_wxid_set=...)`

### §2.3 主流程改造（_handle_wechat_message）
优先路径（process_v2）+ 回退路径（process_message）：

```
_handle_wechat_message(msg):
  1. user_input 空 → skip
  2. if _message_processor is not None:
       2a. kwargs = map_internal_to_processor(msg, master_wxid_set=self._master_wxid_set)
       2b. result = _message_processor.process_v2(**kwargs)
       2c. action=reply 且 content 非空 → send_response(msg, content)
           action=silent_drop → skip（打 info 日志）
           action=block → skip（审计已写入）
           其他兼容：content 非空就发（避免误丢）
       2d. return
       2e. 异常：打 warning，回退到简化路径
  3. 回退路径：
       session_id = msg.sender_id
       result = process_message(user_input, session_id, wxid=msg.sender_id)
       result.content 非空 → send_response
```

### §2.4 向后兼容保证
- `process_message` / `process_message_stream` 保持原有签名和返回契约，UI ChatPage 不受影响
- `_message_processor = None` 时完全走回退路径，等价于修复前的行为
- 新增日志前缀 `[v2]` / `[v2·compat]` / `[fallback]` 便于排查路径

---

## §3 · Grill 清单（6 条 14 断言）

| Grill | 断言 | 验证点 |
|-------|------|--------|
| G1 | AppEngine._message_processor 在 initialize() 后非 None | 属性存在 + 类型正确 |
| G2 | AppEngine._master_wxid_set 为集合类型 | set 类型 + 配置值在集合中 |
| G3 | 群聊无@机器人 → send_response 不被调用 | S02/S15 silent_drop 生效 |
| G4 | 私聊文本 → send_response 被调用 + reply 非空 | S15 action=reply 生效 |
| G5 | 砍价消息 → result.content 含警告关键词 + write_audit_log=True | S07 安全命中 + S13 双写 |
| G6 | process_message (UI 路径) 仍返回 dict 且 content 非空 | 向后兼容 |

---

## §4 · Test Seams（pytest）

### Fixture 共享
```python
@pytest.fixture
def engine(tmp_scai_data_dir, write_valid_llm_config):
    ...
```

### 10 个断言用例
| ID | 用例 |
|----|------|
| T1 | `engine._message_processor` 是 MessageProcessor 实例 |
| T2 | `engine._master_wxid_set` 是 set，配置的 master_wxid 在集合中 |
| T3 | 群聊无@消息进入后 `send_response` 未被调用 |
| T4 | 群聊@机器人消息进入后 `send_response` 被调用（is_at_me=True） |
| T5 | 私聊文本消息进入后 `send_response` 被调用，参数为 (msg, reply_content) |
| T6 | 砍价消息进入后回复内容含 "砍价" 或 "⚠️" 或 "禁止" |
| T7 | process_v2 返回的 result.write_audit_log 为 True（安全命中场景） |
| T8 | 主人消息（sender_wxid in master_wxid_set）→ send_response 不被调用 |
| T9 | engine.process_message("你好") 返回 dict，含 content 键，值为字符串 |
| T10 | process_v2 抛异常时 → 回退路径被触发（send_response 仍被调用） |

---

## §5 · 风险与回滚

| 风险 | 缓解方案 |
|------|---------|
| MessageProcessor 初始化异常导致 AppEngine 启动失败 | try/except 包裹，失败时 `self._message_processor = None`，回退到简化路径 |
| process_v2 抛异常导致消息丢失 | process_v2 内部异常 → 打 warning → 走简化路径 process_message |
| 群聊@机器人被误判为 silent_drop | S02 逻辑同时支持 `is_at_me=True` + `含关键词`；prototype 已验证 |
| 主人消息被 AI 回复 | map_internal_to_processor 传入 `master_wxid_set`，S08 已实现 sender_is_master |
| UI 路径受影响 | process_message 完全未修改，只在其外部多了一层 process_v2 分流 |

**回滚方案**：删除 `AppEngine.initialize()` 中的 MessageProcessor 实例化代码 + 恢复 `_handle_wechat_message` 到 M-19 版本（约 20 行）。

---

## §6 · 后续依赖模块

| 模块 | 依赖关系 | 描述 |
|------|---------|------|
| P3-4 | 本模块完成后 → 接入公众号渠道（M-21）同样走 process_v2 | 公众号目前用的是 MessageProcessorV2（精简版），与 15 步流程能力对齐后可复用三写点 |
| P3-5 | 群聊触发词配置 + 管理群命令路由 | S02/S06 需要更细粒度的触发配置（目前只看 is_at_me + 关键词包含） |
| P3-6 | 微信渠道真实 WCF 联调测试 | 验证群聊@/私聊/主人/安全拦截真实消息 |
| P4 | BadCase 回传 + 迭代引擎闭环 | S14 写入 badcases 表 → P4 读取并触发迭代 |

---

## §7 · 验收标准

- [x] **prototype 验证**：14/14 ALL PASS
- [ ] **pytest 回归**：10 个断言用例 ALL PASS，且不影响既有 P1-1~P1-4、P2-1~P2-3、P3-1、P3-2 模块
- [ ] **PDD 总验收文档更新**：版本 v12.0，含 P3-3 模块 Grill + Test Seams
- [ ] **E2E 回归**：`tests/test_e2e_integration.py` 全绿（run_pipeline 与 AppEngine 实际路径一致）
