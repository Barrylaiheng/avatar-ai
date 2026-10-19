# 企微 CLI 智能机器人控制方案说明

> 基于 2026-09-10 实战验证，所有命令均已在生产环境测试通过。

## 一、方案概述

通过 `wecom-cli` 初始化扫码，创建企微智能机器人，实现以**用户本人身份**发送和接收企业微信消息。

### 核心特性

| 特性 | 说明 |
|---|---|
| 消息身份 | **继承创建者头像和名字**，对方看到的是你本人在发消息 |
| 消息位置 | 出现在正常聊天流中（单聊/群聊），不在应用 Tab 里 |
| 回调 URL | **不需要** |
| 公网 IP | **不需要** |
| IP 白名单 | **不需要** |
| WebSocket | **不需要**（轮询即可收消息） |
| 凭证存储 | CLI 自动加密存储在 `~/.config/wecom/` |

### 与其他方案对比

| 方案 | 凭证 | 回调URL | IP白名单 | 消息身份 | 难度 |
|---|---|---|---|---|---|
| **wecom-cli 智能机器人** | Bot ID + Secret | ❌ | ❌ | 用户本人头像 | ⭐ 最简 |
| 自建应用 API | CorpID + AgentId + Secret | ✅ 需要 | ✅ 需要 | 应用图标 | ⭐⭐⭐ |
| 群机器人 Webhook | Webhook URL | ❌ | ❌ | 群机器人图标 | ⭐⭐ |

## 二、初始化配置

### 2.1 安装 wecom-cli

```bash
# 下载安装后验证
wecom-cli --version
```

### 2.2 扫码初始化

```bash
wecom-cli init
```

执行后会弹出企业微信扫码界面，用**你的企微账号**扫码授权。

扫码完成后，CLI 会自动：
1. 在企微后台创建一个智能机器人
2. 获取 Bot ID 和 Secret
3. 加密存储到 `~/.config/wecom/bot.enc`

### 2.3 验证配置

```bash
wecom-cli cache --help
```

配置文件位置（Windows）：
```
C:\Users\<用户名>\.config\wecom\
├── bot.enc              # 机器人凭证（加密）
├── mcp_config.enc       # MCP 配置（加密）
└── cache/
    ├── service_contact.json
    └── service_msg.json
```

## 三、已验证的 API 能力

### 3.1 查询通讯录

```bash
# v1.2.1+：keywords 必须是 array，用多关键词穷尽搜
wecom-cli contact users search --json '{"search_mode":"list","keywords":["@","_",".","-","a","e","i","o","u"]}'
```

**返回示例：**
```json
{
  "extra_identity_context": "...",
  "users_count": 7,
  "users": [
    {"userid": "womaoTLgAAfMy4k5kxAAXzaVMA2RhViw", "name": "打杂@PlanB烘焙计划(打杂)", "alias": "打杂"},
    {"userid": "womaoTLgAAQtgfDGSlzE80yjlBxoZSGw", "name": "赖恒", "alias": ""}
  ]
}
```

> ⚠️ v1.2.1 变化：userid 从可读（如 `LaiHeng`）变为加密长串（如 `womaoTLgAAQtgf...`）。旧数据库里的 peer_id 需重新绑定。

### 3.2 发送消息

```bash
# v1.2.1+：message send，参数 chat_id + msg_type + text.content
wecom-cli message send --json '{"chat_id":"womaoTLgAAQtgfDGSlzE80yjlBxoZSGw","msg_type":"text","text":{"content":"你好"}}'
```

**参数说明：**

| 参数 | 类型 | 说明 |
|---|---|---|
| `chat_id` | string | 单聊时为对方 userid，群聊时为群 ID |
| `msg_type` | string | 目前仅支持 `"text"` |
| `text.content` | string | 消息内容，最大 2048 字符 |

**返回：**
```json
{"errcode": 0, "errmsg": "ok"}
```

> 消息发送成功后，对方在企微客户端看到的消息头像为**你的企微头像**，名字为**你的企微名字**。

### 3.3 接收消息（轮询）

```bash
# v1.2.1+：chat messages list，不需要 chat_type
wecom-cli chat messages list --json '{"chat_id":"womaoTLgAAQtgfDGSlzE80yjlBxoZSGw","begin_time":"2026-09-14 00:00:00","end_time":"2026-09-14 23:59:59"}'
```

**参数说明：**

| 参数 | 类型 | 说明 |
|---|---|---|
| `chat_id` | string | 单聊时为对方 userid，群聊时为群 ID |
| `begin_time` | string | 开始时间，格式 `YYYY-MM-DD HH:mm:ss` |
| `end_time` | string | 结束时间，格式 `YYYY-MM-DD HH:mm:ss` |

**返回示例：**
```json
{
  "extra_identity_context": "...",
  "messages": [
    {
      "userid": "womaoTLgAAfMy4k5kxAAXzaVMA2RhViw",
      "user_name": "打杂@PlanB烘焙计划(打杂)",
      "send_time": "2026-09-14 19:12:39",
      "msg_type": "text",
      "text": {"content": "还在吗"}
    }
  ]
}
```

> ⚠️ v1.2.1 变化：
> - 命令从 `msg get_message` → `chat messages list`，不再需要 `chat_type`
> - 字段 `msgtype` → `msg_type`
> - 新增 `user_name` 字段（直接返回发送者姓名）
> - userid 全加密，**self-filter 不能靠 `@` 判断**，需用 `(AI 生成内容)` 文本标记 + 机器人 ID 匹配
> - 每次调用都返回 `extra_identity_context`（含机器人 ID 解析）

### 3.4 获取会话列表

```bash
wecom-cli msg get_msg_chat_list --json "{\"begin_time\": \"2026-09-10 00:00:00\", \"end_time\": \"2026-09-10 23:59:59\"}"
```

> 返回最近有消息的会话列表，只支持获取 7 天内的会话。

### 3.5 获取消息媒体

```bash
wecom-cli msg get_msg_media --json "{\"file_id\": \"xxxxxx\"}"
```

> 根据文件 ID 获取图片/文件/语音/视频的内容（base64 编码）。

## 四、消息身份机制说明

### 4.1 为什么消息显示为用户本人

wecom-cli 智能机器人模式在创建时，机器人会**绑定创建者的企微身份**：

```
用户扫码 → 企微后台创建智能机器人 → 机器人继承创建者头像和名字
                                      ↓
                              发消息时 → 对方看到的是【你的头像 + 你的名字】
```

这不是 bug，是 wecom-cli 智能机器人的设计特性。从视觉效果上，等同于"控制了你的企微账号发消息"。

### 4.2 身份对比

| 场景 | 对方看到的头像 | 对方看到的名字 |
|---|---|---|
| 你手动在企微发消息 | 你的头像 | 你的名字 |
| wecom-cli 机器人发消息 | **你的头像** | **你的名字** |
| 自建应用发消息 | 应用图标 | 应用名称 |
| 群机器人发消息 | 群机器人图标 | 机器人名称 |

### 4.3 权限范围

- 机器人只能与**创建者**对话（单聊）
- 创建者可将机器人**拉入群聊**，之后机器人可与群内成员交互
- 通讯录权限：可查看企业全量成员列表
- 消息权限：可向任何企业成员发消息（单聊）

## 五、实战验证记录（2026-09-10）

| 步骤 | 命令 | 结果 |
|---|---|---|
| 1. 扫码初始化 | `wecom-cli init` | ✅ 创建机器人 Bot ID: `aibWyANBUpMZYr116c8zlBm-YpiTEorHorC` |
| 2. 拉通讯录 | `wecom-cli contact users search --json '{"keywords":[...]}'` | ✅ 返回 7 个成员 |
| 3. 发消息 | `wecom-cli message send --json '{"chat_id":...,"msg_type":"text","text":{"content":"..."}}'` | ✅ 对方收到 |
| 4. 拉消息 | `wecom-cli chat messages list --json '{"chat_id":...,"begin_time":...,"end_time":...}'` | ✅ 收到回复 |
| 5. 拉群列表 | `wecom-cli chat groups list --set begin_time=...` | ✅ 返回群聊 |

## 六、轮询收消息方案（MVP 推荐）

由于 `get_message` 是拉取式 API，MVP 阶段用轮询方式接收消息：

```python
import subprocess
import json
from datetime import datetime, timedelta

def poll_messages(userid, interval_seconds=5):
    """轮询拉取与指定用户的聊天消息"""
    last_time = datetime.now() - timedelta(seconds=interval_seconds)
    
    while True:
        begin = last_time.strftime("%Y-%m-%d %H:%M:%S")
        end = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        cmd = [
            "wecom-cli", "msg", "get_message",
            "--json", json.dumps({
                "chat_type": 1,
                "chatid": userid,
                "begin_time": begin,
                "end_time": end
            })
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        data = json.loads(result.stdout)
        
        if data.get("messages"):
            for msg in data["messages"]:
                # 过滤掉自己发的消息
                if msg["userid"] != MY_USERID:
                    handle_incoming_message(msg)
        
        last_time = datetime.now()
        import time
        time.sleep(interval_seconds)
```

## 七、注意事项与限制

1. **消息保留期：** `get_message` 和 `get_msg_chat_list` 只支持拉取最近 7 天内的数据
2. **消息类型：** `send_message` 目前仅支持发送文本消息，不支持图片/文件/语音
3. **会话限制：** 机器人默认只能与创建者对话，需拉入群才能与群成员交互
4. **机器人模式：** 企微后台机器人需设为"多人使用"模式，否则部分功能受限
5. **凭证安全：** `bot.enc` 和 `mcp_config.enc` 为加密文件，不要泄露或提交到 Git
6. **时间格式：** 所有时间参数使用北京时间（UTC+8），格式 `YYYY-MM-DD HH:mm:ss`
7. **JSON 转义：** Windows PowerShell 中 `--json` 参数需要用 `\"` 转义内部引号

## 八、相关文件

| 文件/目录 | 说明 |
|---|---|
| `~/.config/wecom/bot.enc` | 机器人凭证（加密） |
| `~/.config/wecom/mcp_config.enc` | MCP 配置（加密） |
| `~/.config/wecom/cache/` | 缓存目录 |
| 企微后台 → 工作台 → 智能机器人 | 机器人管理页面 |

---

*文档创建：2026-09-10*
*验证环境：Windows + PowerShell + wecom-cli*
*企业：PlanB烘焙计划（≤10人企业）*
