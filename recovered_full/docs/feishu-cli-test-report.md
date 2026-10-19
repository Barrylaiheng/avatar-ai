# 飞书 CLI 连接与收发测试 · 分析总结

> 测试日期：2026-09-12
> 测试目标：验证 lark-cli 在 MVP 场景下的完整能力边界，对比企微差异，输出产品交互需求

---

## 一、测试环境

| 项 | 值 |
|----|-----|
| 飞书组织 | 用户648854的组织（自建立） |
| 测试账号 | 用户648854（Barry@DaDa，组织所有者）、151（内部成员）、用户520861（外部联系人） |
| 测试应用 | 用户648854的飞书 CLI（cli_aa2ee13677f8dbfb） |
| lark-cli | TRAE 插件内置版本 |
| 权限 scope | 扫码创建时自动勾选了消息收发全套 scope（14项免审 + 6项需审） |

---

## 二、扫码绑定流程复盘

| 步骤 | 做了什么 | lark-cli 自动做了？ |
|------|---------|-------------------|
| 1. 生成二维码 | `config init --new` → 出二维码 | ✅ |
| 2. 手机扫码 | 飞书 App 扫码 → 弹出"创建飞书 CLI 应用" | ✅ |
| 3. 确认创建 | 选头像 → 点"创建" → 自动审核通过 → 已发布 | ✅ |
| 4. 权限 scope | 自动勾选 im:message.p2p_msg:readonly 等全套 | ✅ |
| 5. **事件订阅** | 飞书开放平台 → 事件与回调 → 开启 → 勾选 im.message.receive_v1 | ❌ **没做！** |

> **关键发现：扫码创建 ≠ 全部就绪。** 事件订阅开关是飞书开放平台的独立配置项，scope 勾上了但推送管道没开，`event consume` 永远收不到消息。这是 MVP 的坑点——用户扫码后可能不知道还要去开放平台开事件订阅。

---

## 三、bot 身份 vs user 身份

| 维度 | bot 身份 | user 身份 |
|------|---------|----------|
| 获取方式 | 扫码创建应用自动有 | 额外 `auth login --scope "..." --no-wait --json` → device code 授权 |
| 拉通讯录 | ❌ 只能列 bot 被加入的群，p2p 被隐私保护屏蔽 | ✅ 列出用户所有会话（p2p + 群），能区分内部/外部 |
| 收消息 | ✅ `event consume` 实时收发给 bot 的（单聊 + 群@bot） | ❌ 只能轮询拉历史，非实时 |
| 发消息 | ⚠️ 只能发给**曾给 bot 发过消息**的用户 | ✅ 能发给内部任何人/群；外部会话被组织策略拦截 |
| 适用场景 | 被动回复（用户找 bot 聊） | 主动服务（AI 代用户回复所有人） |

> **核心洞察：MVP 飞书路径应该以 user 身份为主。** 企微应用是企业身份延伸，天生能看到所有成员；飞书 bot 是独立 Chatbot 实体，要代表"人"去工作必须走 user OAuth。

---

## 四、收发能力边界矩阵

### 4.1 收消息（拉历史）

| 会话类型 | user `+chat-messages-list` | bot `event consume` |
|---------|---------------------------|---------------------|
| 内部 p2p（Barry ↔ 151） | ✅ | ❌ bot 不在会话里 |
| **内部群**（Barry + 151） | ✅ | ❌ bot 不在群里 |
| 外部 p2p（Barry ↔ 520861） | ✅ | ❌ bot 不在会话里 |
| 外部群（Barry + 520861） | ✅ | ❌ bot 不在群里 |
| 用户 ↔ bot 单聊 | ✅ | ✅ |
| 群里 @bot | ✅（如果 bot 在群里） | ✅ |

### 4.2 发消息

| 目标 | user `+messages-send` | bot `+messages-send` |
|------|----------------------|---------------------|
| 内部用户（151） | ✅ | ❌ bot 不在会话里 |
| 内部群（Barry + 151） | ✅ | ❌ bot 不在群里 |
| 外部用户（520861） | ❌ **230027 组织策略** | ❌ 组织策略 + bot 不在 |
| 外部群 | ❌ 230027 组织策略 | ❌ 组织策略 + bot 不在 |
| 自己 ↔ bot p2p | ✅ | ❌ bot 不能给自己发 |
| 回复 bot 会话 | ✅ | ✅ |

> **规律总结：内部会话 user 身份全通，外部会话 user 能看不能发（组织策略拦截）。**

---

## 五、与企微的差异对照

| 维度 | 企微 | 飞书 |
|------|------|------|
| 创建应用 | 扫码 → 自动绑定企业身份，能枚举所有成员/群 | 扫码 → bot 身份，只能被动收发给 bot 的 |
| 枚举通讯录 | 直接可用 | **额外需要 user OAuth 授权** |
| 主动发消息 | 应用身份直接发 | **额外需要 user OAuth 授权** |
| 事件订阅 | 自动开启 | **需手动去开放平台开事件订阅开关** |
| 用户感知 | 扫码 → 完事 | 扫码 → 还需 device code 授权（约 1 分钟） |
| 外部会话 | 企微本身就是封闭系统 | 能看外部会话历史但发消息被组织策略拦截 |

---

## 六、对 MVP 用户交互的影响

| 环节 | 企微 | 飞书（需要补的） |
|------|------|-----------------|
| 连接管理 | 扫码绑定 → 完事 | 扫码绑定 bot → **可选：引导做 user OAuth 授权** → 如果用户跳过，后续枚举通讯录/主动发消息会失败 |
| 权限检测 | 不需要 | **需要**——扫码后要检查事件订阅是否已开启，没开要引导用户去开放平台配置 |
| 智能体连接配置 | 直接枚举企业成员 ✅ | user 身份枚举内部会话（需要先完成 OAuth） |
| 消息收发 | 应用身份 ✅ | user 身份（能发给内部人）+ bot 身份（回复找 bot 的） |
| 错误提示 | "连接失败" | 需要区分：**bot 未配置** vs **user 未授权** vs **事件订阅未开** vs **组织策略限制** |

---

## 七、MVP 飞书连接管理 · 推荐交互流程

```
[连接管理 · 飞书 tab]
    │
    ▼
点"生成二维码"
    │
    ▼
飞书 App 扫码 → 创建/选择应用 → 绑定成功 ✅
    │
    ▼
MVP 检测：bot 身份 ok 吗？
    ├─ ✅ ok → 继续
    └─ ❌ → 提示"绑定失败，请重试"
    │
    ▼
MVP 检测：user OAuth 授权了吗？
    ├─ ❌ 没授权 → 弹授权引导
    │   "飞书需要一次额外授权才能枚举通讯录和主动发消息"
    │   [现在授权] [稍后再说]
    │   │
    │   ▼ [现在授权]
    │   显示 device code URL + user_code
    │   用户用飞书打开 → 确认授权 → MVP 轮询完成
    │
    ▼
MVP 检测：事件订阅开了吗？
    ├─ ❌ 没开 → 弹引导
    │   "飞书开放平台需开启事件订阅才能实时收消息"
    │   [去开放平台配置]（打开 open.feishu.cn/app/xxx/event）
    │   [我已配置好]
    │
    ▼
飞书连接完成 ✅ → 状态灯变绿
```

---

## 八、MVP 飞书架构定稿

```
┌───────────────────────────────────────────────────────┐
│                    飞书 MVP 架构                       │
├───────────────────────────────────────────────────────┤
│                                                       │
│  双 identity：                                        │
│    bot 身份（扫码创建时自动获得）                       │
│    user 身份（额外 device code OAuth 授权获得）         │
│                                                       │
│  收消息：                                              │
│    主路径：user 身份 +chat-messages-list 定时轮询       │
│            内部会话（p2p + 群）增量监听                 │
│    辅路径：bot 身份 event consume                      │
│            实时收发给 bot 的单聊 / 群@bot              │
│                                                       │
│  发消息：                                              │
│    主路径：user 身份 +messages-send --as user          │
│            内部 p2p / 内部群 → ✅                      │
│            外部会话 → ❌ 跳过（组织策略）               │
│    辅路径：bot 身份 +messages-send --as bot             │
│            仅用于回复 bot event consume 收到的会话      │
│                                                       │
│  通讯录枚举：                                           │
│    user 身份 +chat-list --types p2p,group --as user    │
│    过滤 external=false 的内部会话 → 供智能体绑定选择    │
│                                                       │
└───────────────────────────────────────────────────────┘
```

---

## 九、待验证项

| # | 问题 | 状态 |
|---|------|------|
| 1 | 事件订阅能否通过 API 自动开启？还是必须手动去开放平台 | ❓ 未验证 |
| 2 | `config init --new` 时能不能带参数自动开事件订阅？ | ❓ 未验证 |
| 3 | user OAuth 的 scope 最小集合是什么？当前用了 `im:chat:read im:message.send_as_user im:message` | ⚠️ 可能有精简空间 |
| 4 | 飞书组织策略（外部聊天限制）能不能通过管理后台开放？ | ❓ 未验证 |
| 5 | bot 身份 `event consume` 在事件订阅开启后是否能收到消息 | ❓ 已配置但未实测 |

---

## 十、快速参考 · 常用 lark-cli 命令

```bash
# 状态检测
lark-cli auth status

# 扫码创建应用（bot 身份）
lark-cli config init --new

# 解绑
lark-cli config remove

# user OAuth 授权
lark-cli auth login --scope "im:chat:read im:message.send_as_user im:message" --no-wait --json
# → 拿到 verification_url + user_code 让用户飞书打开授权
# → 授权完成后执行：
lark-cli auth login --device-code <device_code>

# 拉通讯录（p2p）
lark-cli im +chat-list --types p2p --as user

# 拉通讯录（群）
lark-cli im +chat-list --types group --as user

# 拉会话历史
lark-cli im +chat-messages-list --chat-id <chat_id> --as user

# 发消息
lark-cli im +messages-send --chat-id <chat_id> --text "hello" --as user
lark-cli im +messages-send --chat-id <chat_id> --text "hello" --as bot

# 实时收消息（事件订阅开启后）
lark-cli im event consume im.message.receive_v1 --as bot
```
