# 里层 PDD · 第 5 模块规格文档 · FINAL
## `bridges/` — 桥接层 · 多渠道适配器 + InternalMessage 映射 + 处理闭环

> **模块 ID**：INNER-BR05
> **定位**：里层 PDD 第 5 模块 = 桥接层（WCF / 公众号双渠道）
> **五层架构**：L0 接入层（外部渠道 ↔ 引擎层的翻译器）
> **覆盖来源**：现有 `bridges/` 代码 + V1.1 Path B 双渠道拍板

---

## 0. 6 阶段完成度

| 阶段 | 状态 | 说明 |
|-----:|------|------|
| ① Grill | ✅ | BR-01~BR-10 自问自答（从现有代码结构推导拍板）|
| ② Prototype | ✅ 10/10 | [_prototypes/bridges_prototype.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/_prototypes/bridges_prototype.py) |
| ③ to-spec | ✅ 10 Seams | 下文 §3 |
| ⑤ implement+tdd | ✅ 10/10 | [tests/test_inner_bridges_pdd.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/tests/test_inner_bridges_pdd.py) |
| ⑥ 回归+评审 | ✅ | 58 passed（22+10+8+8+10）5 套件全绿 |

---

## 1. Grill 拍板

| 编号 | 问题 | 决策 |
|-----:|------|------|
| BR-01 | 渠道抽象层 | `BaseChannelAdapter` 抽象基类（4 方法 + 3 可选），WCF/公众号都实现之 |
| BR-02 | Router 调度 | `MessageRouter` 统一按 `channel` 字段分发，去硬编码 |
| BR-03 | 入参映射 | `map_internal_to_processor()` 函数：InternalMessage → process_v2 kwargs |
| BR-04 | 公众号渠道名 | `"wechat_mp"`（不和 WCF `"wechat"` 混淆）|
| BR-05 | WCF → 引擎 session_type | `"chat"` |
| BR-06 | 公众号 → 引擎 session_type | `"mp"` |
| BR-07 | 主人标识注入 | `map_internal_to_processor` 支持 `master_wxid_set` 参数 |
| BR-08 | Router dedup 策略 | 10000 msg_id 滑窗，和 S04 滑窗协同 |
| BR-09 | 响应回发逻辑 | 群聊用 group_id，私聊用 receiver_id（公众号需专门重写）|
| BR-10 | 新增渠道路径 | 继承 BaseChannelAdapter + 实现 4 方法 + Router.register_adapter |

---

## 2. 交付物清单

| 文件 | 说明 |
|------|------|
| `bridges/__init__.py` | 新增 `OfficialAccountAdapter` + `map_internal_to_processor` 导出 |
| `bridges/base_adapter.py` | 原有，已验证抽象契约 |
| `bridges/internal_message.py` | 原有，跨渠道统一消息格式 |
| `bridges/wcf_adapter.py` | 原有，实现完整（含 wcferry 注入模式）|
| **NEW**: `bridges/official_account_adapter.py` | 公众号骨架，实现 BaseChannelAdapter 契约 |
| **NEW**: `bridges/utils.py` | `map_internal_to_processor()` 函数 + CHANNEL_TO_SESSION_TYPE 映射表 |
| `bridges/message_router.py` | 原有，v2.0 去硬编码版 |

---

## 3. 10 条 Test Seams

| ID | 标题 | 断言 |
|----|------|------|
| BR-01 | WCF + MP 适配器注册 | channels 列表含 "wechat" + "wechat_mp" |
| BR-02 | get_adapter | 返回实例 / None |
| BR-03 | WCF 私聊入参映射 | sender_wxid 对，group_* 全空，session_type=chat |
| BR-04 | WCF 群聊+@我映射 | group_wxid/group_name/is_at_me 全齐 |
| BR-05 | 公众号映射 | session_type=mp，sender_wxid=openid |
| BR-06 | Router.route 去重 | 同 msg_id 处理器只调用 1 次 |
| BR-07 | WCF 回发 | adapter._sent[0][0] = receiver_id |
| BR-08 | MP 回发 | adapter.send_message 被调（内容正确）|
| BR-09 | 双渠道独立路由 | WCF 处理器只收到 WCF 消息，MP 同理 |
| BR-10 | BaseAdapter 契约一致性 | get_channel_name/is_connected/send_message/health_check 全对齐 |

---

## 4. 双轴评审

### 轴 1 · Fowler
- ✅ 单一职责：桥接层只管「渠道 ↔ InternalMessage ↔ process_v2 入参」翻译，不处理业务逻辑
- ✅ 无重复逻辑：Router dedup 是自己的滑窗（和 S04 滑窗职责不同）
- ✅ 可扩展：新增渠道只需要加 Adapter 文件 + 注册，不改 Router

### 轴 2 · 规格忠实度
- ✅ 10 Seams 逐条对应
- ✅ 公众号骨架实现所有 BaseChannelAdapter 抽象方法
- ✅ `map_internal_to_processor` 暴露 `master_wxid_set` 扩展口

---

## 5. 全局 PDD 验收

| 层 | 模块 | Seams | 状态 |
|----|------|------:|------|
| 表层 PDD | 14 模块 | 283 | ✅ |
| 里层 PDD | 模块 1 · MessageProcessor | 22 | ✅ |
| 里层 PDD | 模块 2 · SafetyShieldV2 | 10 | ✅ |
| 里层 PDD | 模块 3 · ContextAssemblerV2 | 8 | ✅ |
| 里层 PDD | 模块 4 · IterationEngine | 8 | ✅ |
| 里层 PDD | 模块 5 · Bridges 桥接层 | 10 | ✅ |
| **合计** | **19 模块** | **341 Seams** | **100%** |
