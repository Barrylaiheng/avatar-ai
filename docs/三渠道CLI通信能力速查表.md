# 企微 · 飞书 · 钉钉 CLI 通信能力速查表

> 测试日期：2026-09-14
> 目标：MVP 通信模块开发时直接查表，不用重新翻 CLI help
> 覆盖：**拉通讯录 · 收消息 · 发消息** 三要素 + 认证方式 + 外部联系人支持

---

## 一、CLI 版本与认证方式

### 1.1 版本信息

| 渠道 | CLI 名 | 版本 | 安装方式 | 认证方式 |
|------|--------|------|----------|----------|
| 企微 | `wecom-cli` | **1.2.1**（2026-09-08） | `npm install -g @wecom/cli` | 扫码 → 自动创建智能机器人，加密存储 Bot ID + Secret |
| 飞书 | `lark-cli` | TRAE 插件内置 | 随 TRAE 插件分发 | 两段：扫码创建 bot 应用 → device code 授权 user 身份 |
| 钉钉 | `dws` | — | TRAE 插件内置（`~/.local/bin/dws.exe`） | 一段：device code 扫码登录 → 自动获取 user 身份 |

### 1.2 凭证存储位置

| 渠道 | 存储路径 | 格式 |
|------|---------|------|
| 企微 | `~/.config/wecom/bot.enc`、`mcp_config.enc` | 加密文件 |
| 飞书 | `lark-cli config list` 管理 | 本地配置文件 |
| 钉钉 | `~/.dws/profiles.json`、`token.json`、`identity.json` | 明文 JSON + 加密混合 |

### 1.3 认证状态检查

```bash
# 企微
wecom-cli auth show

# 飞书
lark-cli auth status

# 钉钉
dws auth status
```

---

## 二、外部联系人 / 客户联系支持情况

> **MVP 设计前提：三个 CLI 均只支持企业内部通信，不支持对接微信个人用户。**

| 渠道 | CLI 支持外部联系人？ | 说明 |
|------|-------------------|------|
| **企微** wecom-cli | ❌ 不支持 | CLI 只有内部通讯录搜索（`contact.users.search`），没有 `externalcontact` 系列命令，也没有 raw API escape hatch |
| **飞书** lark-cli | ⚠️ 有限 | 有 `--exclude-external-users` 参数和 `is_cross_tenant` / `external` 字段，能**识别和收发跨租户会话**，但飞书本身不连接微信生态 |
| **钉钉** dws | ❌ 不适用 | 钉钉跟飞书一样，不连接微信个人用户，contact 域全是内部员工 |

**结论：MVP 通信模块统一按「企业内部」设计，不考虑客户联系场景。**

---

## 三、企微 wecom-cli v1.2.1

### ⚠️ 版本升级注意

旧版 v0.1.8 命令是 `wecom-cli contact get_userlist` / `wecom-cli msg send_message`，v1.2.1 全面重构为资源式命令。如果项目里已有旧命令，需要同步更新。

### 3.1 拉通讯录

```bash
# 按关键词搜索企业内部成员
wecom-cli contact users search --help

# 查看 schema
wecom-cli contact --schema
```

**能力边界：**
- 只有关键词搜索，没有"列出全员"命令
- 只返回**企业内部成员**，不含外部联系人

### 3.2 收消息

```bash
# 列出有消息的会话（目前仅群聊）
wecom-cli chat groups list --help

# 拉取指定会话的消息历史
wecom-cli chat messages list --help
```

**注意：**
- `chat.groups.list` 官方描述写着 **"目前仅群聊"**
- 单聊会话列表 CLI 暂时没有暴露
- 消息拉取只支持**最近 7 天内**的数据

### 3.3 发消息

```bash
# 发送文本消息
wecom-cli message send \
  --chat-id <userid或群ID> \
  --msg-type text \
  --text '{"content": "你好"}' \
  --dry-run           # 先 dry-run 预览，确认无误再去掉
```

**参数说明：**

| 参数 | 说明 |
|------|------|
| `--chat-id` | 单聊传成员 userid，群聊传群会话 ID |
| `--msg-type` | 目前仅支持 `text` |
| `--text` | JSON 字符串：`{"content": "内容"}` |

**限制：**
- 只支持文本消息，不支持图片/文件/语音
- 消息大小最大 2048 字节
- **chat-id 只能是企业成员 userid，不能是 external_userid**

### 3.4 快速验证清单

| # | 动作 | 命令 | 预期 |
|---|------|------|------|
| 1 | 检查认证 | `wecom-cli auth show` | 输出 authorized |
| 2 | 拉通讯录 | `wecom-cli contact users search` | 有命令可用 |
| 3 | 列会话 | `wecom-cli chat groups list` | 返回群列表（仅群聊） |
| 4 | 拉消息 | `wecom-cli chat messages list --help` | 有帮助输出 |
| 5 | 发消息（dry-run） | `wecom-cli message send --chat-id 某userid --msg-type text --text '{"content":"test"}' --dry-run` | 预览成功 |

---

## 四、飞书 lark-cli

### 4.1 拉通讯录

```bash
# 列出所有会话（p2p + 群）—— MVP 推荐用这个
lark-cli im +chat-list --types p2p,group --as user --page-all --format json

# 按关键词搜索用户
lark-cli contact +search-user --query "张三" --as user --format json

# 获取自己的信息
lark-cli contact +get-user --as user --format json
```

**返回关键字段：**
- `external: true/false` — 是否跨租户
- `is_cross_tenant: true/false` — 是否外部用户（search-user 返回）
- `p2p_chat_id` — p2p 会话 ID（search-user 返回，可直接用来发消息）
- `chat_id` — 群聊 / p2p 会话统一 ID

### 4.2 收消息

```bash
# 拉取指定会话消息历史（MVP 主路径：轮询）
lark-cli im +chat-messages-list \
  --chat-id <chat_id> \
  --as user \
  --format json

# 实时收消息（需先手动开事件订阅，辅路径）
lark-cli event consume im.message.receive_v1 --as bot
```

### 4.3 发消息

```bash
# 向群聊或 p2p 发消息（user 身份，MVP 主路径）
lark-cli im +messages-send \
  --chat-id <chat_id> \
  --text "你好" \
  --as user \
  --format json

# 向指定用户发消息（通过 open_id）
lark-cli im +messages-send \
  --user-id <open_id> \
  --text "你好" \
  --as user \
  --format json
```

**已知限制：**
- user 身份发外部（跨租户）会话会被组织策略拦截（230027 错误码）
- bot 身份只能发给**曾主动找 bot 聊过**的用户

### 4.4 快速验证清单

| # | 动作 | 命令 | 预期 |
|---|------|------|------|
| 1 | 检查认证 | `lark-cli auth status` | user + bot 都 ok |
| 2 | 列所有会话 | `lark-cli im +chat-list --types p2p,group --as user --page-all --format json` | 返回 chats 数组 |
| 3 | 搜用户 | `lark-cli contact +search-user --query "名字" --as user --format json` | 返回 users 数组 |
| 4 | 拉消息 | `lark-cli im +chat-messages-list --chat-id <chat_id> --as user --format json` | 返回 messages 数组 |
| 5 | 发消息 | `lark-cli im +messages-send --chat-id <chat_id> --text "test" --as user --format json` | ok:true |

---

## 五、钉钉 dws

### 5.1 拉通讯录

```bash
# 列出我加入的所有会话（含单聊 + 群聊）—— MVP 推荐用这个
dws chat +conversation-list --page-all --limit 100 --format json

# 列出我加入的群
dws chat +my-groups --limit 100 --format json

# 按部门拉成员
dws contact +list-dept-members --help

# 按关键词搜用户
dws contact +search-user --help

# 按手机号搜
dws contact +by-mobile --help

# 查自己
dws contact +me --format json
```

**conversation-list 返回关键字段：**
- `conversationName` — 会话名
- `openConversationId` — 会话唯一 ID（发消息和拉消息都用这个）

### 5.2 收消息

```bash
# 拉取群聊消息历史
dws chat +messages-list \
  --group <openConversationId> \
  --time "2026-09-14 00:00:00" \
  --limit 20 \
  --format json

# 拉取单聊消息历史
dws chat +messages-list-direct \
  --open-dingtalk-id <对方openDingTalkId> \
  --time "2026-09-14 00:00:00" \
  --format json

# 列出有未读消息的会话
dws chat +unread-chats --format json
```

**messages-list 返回关键字段：**
- `sender` — 发送者昵称
- `senderId` — 发送者 ID
- `text` — 消息文本
- `createTime` — 发送时间
- `messageId` — 消息唯一 ID

### 5.3 发消息

```bash
# 向群聊发消息（user 身份）—— MVP 主路径
dws chat +messages-send \
  --as user \
  --chat-id <openConversationId> \
  --text "在的，有什么事？" \
  --yes

# 向单聊发消息（通过姓名自动解析 openDingTalkId）
dws chat +dm --help   # 按姓名直接发，最方便

# 向群聊发 Markdown
dws chat +messages-send \
  --as user \
  --chat-id <openConversationId> \
  --markdown "## 标题\n内容" \
  --yes
```

**参数说明：**

| 参数 | 说明 |
|------|------|
| `--as` | 发送身份：`user` / `bot` / `webhook`，MVP 用 `user` |
| `--chat-id` | 群聊或单聊的 openConversationId |
| `--text` | 纯文本内容 |
| `--markdown` | Markdown 内容 |
| `--yes` | 跳过安全确认（AI Agent 模式必需） |
| `--ai-tag` | 是否带 AI 发送角标，默认 true |

### 5.4 实战记录（2026-09-14 验证通过）

| # | 动作 | 命令 | 结果 |
|---|------|------|------|
| 1 | 列出所有会话 | `dws chat +conversation-list --page-all --limit 100 --format json` | ✅ 返回 29 个会话（含单聊+群聊） |
| 2 | 列未读会话 | `dws chat +unread-chats --format json` | ✅ 返回有未读的会话列表 |
| 3 | 拉群消息 | `dws chat +messages-list --group cidUwBUI4... --time "2026-09-14 00:00:00" --limit 10 --format json` | ✅ 返回 4 条消息，含发送者昵称和文本 |
| 4 | **发群消息** | `dws chat +messages-send --as user --chat-id cidUwBUI4... --text "在的，有什么事？" --yes` | ✅ ok:true，openTaskId: DRsC6atI... |

### 5.5 MVP Bridge API 签名（已调通）

钉钉三动作都通过 Bridge.py 注册成 pyqtBridge.call() 的 action，前端 index.html 通过 qt.webChannel 调用：

| action | 后端函数 | 入参 | 返回 |
|--------|----------|------|------|
| get_dingtalk_status | _handle_get_dingtalk_status | {} | {connected: bool, username: str, cli_version: str \| null, cli_compat: str, verified_version: str} |
| generate_dingtalk_qr | _handle_generate_dingtalk_qr | {} | {qr_url, qr_image(base64 PNG), user_code, expires_in: 900} |
| unbind_dingtalk | _handle_unbind_dingtalk | {} | {ok: bool, removed: [file names]} |

**后端关键细节：**

- CLI 路径：shutil.which('dws') + 兜底 ~/.local/bin/dws.exe（Windows）
- 认证流程：dws auth login --device --no-browser（--no-browser 防止自动弹浏览器，device code 模式）
- 凭据路径：~/.dws/identity.json（存在 = 已绑定；不等于已连接）
- 连接判定：已绑定（identity.json 存在）且 `dws auth status` 返回 `authenticated=true` 才算 connected；CLI 探测不出结论（超时/网络）时回退为“已绑定即连接”，避免误判离线。auth status 结果带 30s TTL 缓存
- self-filter：主判据为消息字段 `messageAiSendFlag` 非空（dws CLI 发送必带）；兜底为 `senderId == 本账号 openDingTalkId`（经 `dws contact +search-user` 解析）
- 解绑流程：优先 dws auth logout（退出当前账号），兜底手动删 ~/.dws/{identity.json, token.json, profiles.json}
- 二维码进程管理：_dingtalk_qr_proc 持有 Popen 句柄，解绑/重新生成时 	erminate→wait(2)→kill 三级清理
- 输出解析：daemon thread 逐行读 stdout，regex 匹配 login.dingtalk.com/...verify... 和 授权码: XXXX

**前端关键细节：**

- 三态渲染：未连接 → 扫码中（倒计时 + 2s 轮询）→ 已连接
- 已绑定态隐藏底部流程提示文字
- 解绑恢复未连接态时必须重置 genBtn.disabled = false（bug 修复点：三渠道同步修复）
- 外链统一 cceptNavigationRequest 拦截走系统浏览器（钉钉开发者平台、外部文档等）
### 5.5 快速验证清单

| # | 动作 | 命令 | 预期 |
|---|------|------|------|
| 1 | 检查认证 | `dws auth status` | authorized |
| 2 | 列所有会话 | `dws chat +conversation-list --page-all --limit 100 --format json` | 返回 conversations 数组 |
| 3 | 搜用户 | `dws contact +search-user --help` | 有帮助输出 |
| 4 | 拉消息 | `dws chat +messages-list --help` | 有帮助输出 |
| 5 | 发消息 | `dws chat +messages-send --as user --chat-id <id> --text "test" --yes` | ok:true |

---

## 六、三要素对照速查表

### 6.1 拉通讯录（MVP 用来枚举可绑定的人/群）

| 渠道 | 命令 | 说明 |
|------|------|------|
| **企微** | `wecom-cli contact users search` | 仅关键词搜索，无"列全员" |
| **飞书** | `lark-cli im +chat-list --types p2p,group --as user --page-all` | 枚举所有会话，含 p2p 和群 |
| **钉钉** | `dws chat +conversation-list --page-all --limit 100` | 枚举所有会话，含单聊和群聊 |

### 6.2 收消息（MVP 轮询拉取）

| 渠道 | 命令 | 时间窗 |
|------|------|--------|
| **企微** | `wecom-cli chat messages list` | 最近 7 天 |
| **飞书** | `lark-cli im +chat-messages-list --chat-id <id> --as user` | 不限（服务端） |
| **钉钉** | `dws chat +messages-list --group <id> --time "YYYY-MM-DD HH:mm:ss"` | 不限（服务端） |

### 6.3 发消息（MVP AI 回复）

| 渠道 | 命令 | 发送身份 | 消息类型 |
|------|------|----------|----------|
| **企微** | `wecom-cli message send --chat-id <id> --msg-type text --text '{"content":"..."}'` | 机器人（继承用户头像） | text only |
| **飞书** | `lark-cli im +messages-send --chat-id <id> --text "..." --as user` | user | text / markdown / rich text |
| **钉钉** | `dws chat +messages-send --chat-id <id> --text "..." --as user --yes` | user | text / markdown / 卡片 |

### 6.4 会话 ID 格式

| 渠道 | 单聊 ID | 群聊 ID | 从哪获取 |
|------|---------|---------|---------|
| **企微** | 成员 userid（如 `LaiHeng`） | 群会话 ID | `get_msg_chat_list`（旧版）/ `chat groups list`（新版） |
| **飞书** | `oc_xxxxxxxx...`（p2p_chat_id） | `oc_xxxxxxxx...`（chat_id） | `im +chat-list` / `contact +search-user` |
| **钉钉** | `cidxxxxxxxx...==`（openConversationId） | `cidxxxxxxxx...==`（openConversationId） | `chat +conversation-list` |

> **关键：飞书和钉钉的 ID 格式统一都是 `oc_xxx` / `cidxxx==` 这种不透明字符串，企微是可读 userid。**

---

## 七、MVP 架构建议

```
┌─────────────────────────────────────────────────┐
│               ChannelClient 抽象层               │
│  get_contacts() / poll_messages() / send_reply() │
└────────┬──────────────┬──────────────┬──────────┘
         │              │              │
         ▼              ▼              ▼
    WecomClient    FeishuClient    DingtalkClient
         │              │              │
    wecom-cli      lark-cli          dws
    (subprocess)   (subprocess)      (subprocess)
```

**统一流程：**
1. 启动时调用 `get_contacts()` 拉通讯录 → 存本地 SQLite 供 UI 选择
2. 后台轮询：每隔 N 秒调用各渠道的消息拉取命令
3. 收到消息 → 进入统一 message pipeline（去重 → AI 处理 → 回复）
4. AI 回复 → 调用各渠道的发消息命令

---

*文档创建：2026-09-14*
*后续如有新版 CLI 发布，更新版本号和命令即可*

