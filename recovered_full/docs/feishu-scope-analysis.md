# 飞书 MVP · user OAuth scope 需求分析

> 分析日期：2026-09-13
> 目标：确定阿维达AI 控制飞书账号所需的完整 user OAuth scope 清单
> 参考：2026-09-12 实机测试结论（feishu-cli-test-report.md）

---

## 一、当前状态

### 1.1 应用已配置的 scope（扫码创建时自动勾选）

从飞书管理后台审核页截图确认，应用「用户648854的飞书 CLI」已具备：

| 模块 | scope | 状态 |
|------|-------|------|
| 通讯录 | `contact:contact.base:readonly`（获取通讯录基本信息） | ✅ 已配置 |
| 消息与群组 | `im:message`、`im:chat`、`im:resource` 等全套 | ✅ 已配置 |
| 云文档 | `docs:doc`、`drive:drive` 等全套 | ✅ 已配置 |
| 应用信息 | `application:*` | ✅ 已配置 |
| 卡片 | `card:*` | ✅ 已配置 |
| **日历** | — | ❌ 未配置 |
| **任务** | — | ❌ 未配置 |
| **多维表格** | — | ❌ 未配置 |
| **电子表格** | — | ❌ 未配置 |
| **知识库** | — | ❌ 未配置 |

### 1.2 当前 user OAuth scope（bridge.py 第 2817 行）

```
im:chat:read im:message.send_as_user im:message
```

仅覆盖了"文本消息收发 + 枚举通讯录"，**缺少文件、文档等能力**。

---

## 二、业务场景与 scope 映射

按 MVP 核心诉求「控制飞书账号，对组织内成员/群进行通信 + 使用飞书特色功能」拆解：

### 2.1 核心通信（必须）

| 业务场景 | 所需 scope | 用途 | 当前是否已加 |
|---------|-----------|------|------------|
| 拉取会话列表（p2p + 群） | `im:chat:read` | 枚举通讯录 | ✅ |
| 拉取消息历史 | `im:message` | 收消息（含增量轮询） | ✅ |
| 以用户身份发文本消息 | `im:message.send_as_user` | 代用户回复 | ✅ |
| **发图片/文件/语音/视频** | `im:resource` | 上传媒体资源 | ❌ **缺失** |

> **说明**：`im +messages-send --image/--file` 会自动上传并发送，但上传动作需要 `im:resource` scope（user 身份）。bot 身份上传文件也需要此 scope。

### 2.2 飞书文档（特色功能）

| 业务场景 | 所需 scope | 用途 | 应用是否已配 |
|---------|-----------|------|------------|
| 读取云文档内容 | `docx:document:readonly` 或 `docs:doc:readonly` | AI 读取文档总结 | ✅ |
| 创建/编辑云文档 | `docx:document` 或 `docs:doc` | AI 生成文档 | ✅ |
| 云空间文件上传/下载 | `drive:drive` | 文档附件、文件管理 | ✅ |
| 知识库节点 | `wiki:wiki` | 知识库 | ❌ 应用未配 |

### 2.3 通讯录增强

| 业务场景 | 所需 scope | 用途 | 应用是否已配 |
|---------|-----------|------|------------|
| 搜索用户 | `contact:contact.base:readonly` | 按姓名搜人 | ✅ |
| 获取用户详情 | `contact:contact.base:readonly` | 姓名/部门/邮箱 | ✅ |

### 2.4 其他办公能力（后续扩展）

| 业务场景 | 所需 scope | 应用是否已配 | 备注 |
|---------|-----------|------------|------|
| 日历查看/创建 | `calendar:calendar` | ❌ | 需去开放平台加 scope |
| 任务查看/创建 | `task:task` | ❌ | 需去开放平台加 scope |
| 多维表格读写 | `bitable:app` | ❌ | 需去开放平台加 scope |
| 电子表格读写 | `sheets:spreadsheet` | ❌ | 需去开放平台加 scope |
| 审批处理 | `approval:approval` | ❌ | 需去开放平台加 scope |
| 邮件收发 | `mail:mail` | ❌ | 需去开放平台加 scope |
| 妙记 | `minutes:minutes` | ❌ | 需去开放平台加 scope |

---

## 三、推荐 scope 清单

### 3.1 MVP 阶段（当前可实现，应用已有 scope）

```
im:chat:read
im:message
im:message.send_as_user
im:resource
contact:contact.base:readonly
docs:doc
docx:document
drive:drive
```

**共 8 个 scope**，覆盖：
- ✅ 文本消息收发
- ✅ 图片/文件/语音/视频消息
- ✅ 枚举通讯录（群 + p2p + 搜人）
- ✅ 飞书文档读取/创建/编辑
- ✅ 云空间文件管理

### 3.2 增强阶段（需先在开放平台给应用加 scope）

在 MVP 8 个 scope 基础上追加：

```
calendar:calendar
task:task
bitable:app
sheets:spreadsheet
wiki:wiki
approval:approval
mail:mail
minutes:minutes
```

覆盖：日历、任务、多维表格、电子表格、知识库、审批、邮件、妙记。

**前提**：用户需先去 [飞书开放平台](https://open.feishu.cn/app) → 应用 → 权限管理 → 勾选上述 scope → 重新发布应用。

---

## 四、scope 与身份的关系

飞书有两层 scope 配置：

```
┌─────────────────────────────────────────────┐
│  应用配置 scope（开放平台）                    │
│  = 应用"拥有"的权限池                          │
│  扫码创建时 lark-cli 自动勾了一部分             │
│  其余需手动去开放平台加                         │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│  user OAuth 请求的 scope（MVP 第二步授权）     │
│  = 从应用 scope 池里选一个子集                 │
│  不能超过应用已配置的 scope                    │
│  即：应用没配的 scope，OAuth 请求了也会失败     │
└─────────────────────────────────────────────┘
```

**关键规则**：
- user OAuth 请求的 scope **必须是应用已配置 scope 的子集**
- 如果 OAuth 请求了应用没有的 scope → 授权页面会报错或该 scope 被忽略
- 所以增强阶段的 scope，**必须先让用户去开放平台给应用加上**，OAuth 才能要

---

## 五、推荐的 MVP 交互改动

### 5.1 第二步 user OAuth scope 升级

修改 `bridge.py` 第 2817 行：

```python
# 改前
scope = "im:chat:read im:message.send_as_user im:message"

# 改后（MVP 8 scope）
scope = " ".join([
    "im:chat:read",
    "im:message",
    "im:message.send_as_user",
    "im:resource",
    "contact:contact.base:readonly",
    "docs:doc",
    "docx:document",
    "drive:drive",
])
```

### 5.2 授权页面文案提示

飞书授权页会列出所有请求的权限。8 个 scope 对应用户看到的权限项大致是：
- 查看群信息
- 获取与发送单聊、群组消息
- 以用户身份发送消息
- 上传图片/文件
- 获取通讯录基本信息
- 查看、编辑云文档
- 查看、编辑云空间文件

### 5.3 增强 scope 的引导（可选，后续做）

如果用户想用日历/任务等能力，MVP 可以：
1. 检测到应用缺少某 scope
2. 弹出引导：「如需使用日历功能，请先去开放平台添加 `calendar:calendar` scope」
3. 用户加完后，重新触发 user OAuth（会增量授权新 scope）

---

## 六、scope 最小化建议

如果觉得 8 个 scope 太多，可以按优先级分级：

| 优先级 | scope | 不授权的影响 |
|--------|-------|------------|
| P0 必须 | `im:chat:read` | 无法枚举通讯录 |
| P0 必须 | `im:message` | 无法收发消息 |
| P0 必须 | `im:message.send_as_user` | 无法代用户发消息 |
| P1 建议 | `im:resource` | 无法发图片/文件 |
| P1 建议 | `contact:contact.base:readonly` | 无法按姓名搜人（但 chat-list 仍能列出会话） |
| P2 可选 | `docs:doc` + `docx:document` | 无法读/写飞书文档 |
| P2 可选 | `drive:drive` | 无法管理云空间文件 |

**P0 三个是核心通信闭环，P1 是消息丰富度，P2 是飞书特色功能。**

---

## 七、待确认项

| # | 问题 | 状态 |
|---|------|------|
| 1 | `im:message` 是否已包含 `im:message:readonly`？是否需要单独加 | 需验证 |
| 2 | `im:resource` 是否是 user 身份发文件的唯一 scope | 需实机验证 |
| 3 | `docs:doc` 和 `docx:document` 是否都需要（老版文档 vs 新版文档） | 建议都加 |
| 4 | 应用当前配置的 scope 完整列表（用 API 拉取） | 未验证 |
| 5 | 增强 scope 添加后，OAuth 是增量授权还是需要重新全量授权 | 需验证 |
