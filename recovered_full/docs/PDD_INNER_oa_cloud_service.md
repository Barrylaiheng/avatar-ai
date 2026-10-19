# SCAI MVP · 里层 PDD 规格文档 · 模块 7'
# 模块：INNER-OA07 · 公众号云端服务代码包

> **版本**：v1.0
> **生成日期**：2026-08-10
> **前置**：[PDD_INNER_TOTAL_ACCEPTANCE.md](./PDD_INNER_TOTAL_ACCEPTANCE.md)（v3.0）
> **原型**：[_prototypes/oa_cloud_service_prototype.py](../_prototypes/oa_cloud_service_prototype.py)（15 Seams 全绿）
> **对应 grill 文档**：OA-G1~G10（见上方对话记录）

---

## §1 模块定位

**一句话**：实现一套可以独立部署到用户云端服务器的"公众号 AI 分身服务包"——复用 SCAI engine 层（MessageProcessorLite / SafetyShield / ContextAssemblerV2 / KarpathyWikiReader / IterationEngine），对外提供 wechatpy 标准签名验证、access_token 自动刷新、5s 占位回复、客服消息异步推送、BadCase 回传五大能力。

### 为什么独立模块？

运营战略反转：**公众号渠道是 SCAI MVP 的"公域销售案例"核心卖点**（私域承接用微信，公域展示用公众号），所以公众号渠道代码包必须在 MVP 阶段完成，不能拖到 V2。

云端自闭环（非本地中转）原因：
1. 服务号官方能力——客服消息接口合法合规，无微信敏感地带
2. 搭搭 DaDa 已验证此模式（362 次回复成功率 98.1%）
3. 24/7 可用，不依赖用户本地 PC 开机

---

## §2 Grill 清单（已拍板）

| # | 决策 | 拍板 |
|---|------|------|
| OA-G1 | 云端框架 | Flask + wechatpy 2.x（搭搭 DaDa 已验证） |
| OA-G2 | 部署目录结构 | `scai_oa_service/`：app.py + config.json + engine/ + kb/ + persona.json |
| OA-G3 | 签名验证+解密 | GET check_signature 验签；POST WeChatCrypto decrypt_message |
| OA-G4 | token 刷新 | SQLite oa_tokens 表；提前 5 分钟刷新；3 次指数退避重试 |
| OA-G5 | 5s 超时策略 | 收到消息立刻返回被动回复 XML（占位语）；后台线程处理真实回复后用客服消息推送 |
| OA-G6 | 占位语文案 | `"正在思考，请稍候..."` |
| OA-G7 | engine 复用 | 打包 SCAI engine 代码（msg_proc/safety/ctx/rag/iter）；云端用精简版 process（无 WCF/管理群/主人同步） |
| OA-G8 | BadCase 回传 | HTTP GET `/monitor/pull_badcases`；消费后清空；48h 未送达也写回 |
| OA-G9 | 48h 限制 | LastUserMessageTracker；过期则 send_text 失败 + BadCase 标「cs_timeout」 |
| OA-G10 | 失败兜底 | 解密失败→200 success；签名失败→403；token 失败→刷新重试→兜底语+BadCase |

---

## §3 Test Seams 定义（15 条）

| ID | 标题 | 输入 | 断言要点 |
|----|------|------|---------|
| OA-01 | GET 签名通过 | 正确签名 + echostr | status=200，body=echostr |
| OA-02 | GET 签名失败 | 错误签名 | status=403，body=""（不回 echostr） |
| OA-03 | POST XML→InternalMessage | 合法签名 + 含 text/Content 的 XML | 返回 status=200 + 占位语；parse_xml_to_msg 解析后 sender_id=OpenID，content 完整 |
| OA-04 | 占位语 5s 内返回 | POST 合法消息 | handle_post 返回耗时 < 100ms（mock 肯定<5s）；XML Content=占位语 |
| OA-05 | token 首次获取写入 SQLite | 启动服务 get_token() | token 非空；DB oa_tokens 表有行；expires_at ≈ now+7200s |
| OA-06 | token 提前 5 分钟自动刷新 | 手动将 expires_at 改成 now+120s，再 get_token() | new_expires_at - near_expire >= 6000s（从 120s → 7200s 差约 7080s） |
| OA-07 | token 获取失败指数退避 3 次 | app_secret="FORCE_FAIL_2_TIMES" 调 refresh() | refresh() 返回 True（第 3 次成功）；最终 get_token() 非空 |
| OA-08 | engine 处理 15 步流水线精简版 | process(InternalMessage(text)) | action=reply；content 非空；回复符合语义 |
| OA-09 | 客服消息推送成功 | send_text(openid, content) + 48h 内用户 | 返回 success=True；client._calls 队列+1 |
| OA-10 | 48h 限制拦截 | 手动将用户最后消息时间戳设为 49h 前，send_text() | success=False；bad_case=True；reason="客服消息超过 48 小时未送达" |
| OA-11 | RAG 命中 system prompt | init(kb_root) + 发 "PDD 是什么？" | rag_count >= 1 |
| OA-12 | BadCase 回传接口可消费 | 造 cs_timeout + 无 Key fallback 两类 BadCase，pull_badcases(10) | 返回 len >= 2；消费后 bad_cases_for_pull 清空为 [] |
| OA-13 | 解密失败返回 success | crypto.set_decrypt_fail(True) + POST | status=200，body="success"（防微信重试 3 次） |
| OA-14 | LLM 无 Key 兜底 | 不配 llm_api_key + process 一条消息 | action=fallback_reply；content 含「AI 配置未完成」；bad_case_written=True |
| OA-15 | 完整端到端 | POST 真实用户 XML → wait 异步线程 → 查客服消息 + Store | 占位语返回；客服消息推送 1 次以上；MessageStore 至少 1 条记录含 reply_content |

---

## §4 开发任务清单

### §4.1 代码包结构

```
src/aibridge/oa_service/          ← 云端服务代码包（Python 源，可 scp 打包）
├── __init__.py
├── app.py                        ← Flask 路由：GET/POST /callback + GET /monitor/pull_badcases
├── config_loader.py              ← 读取 config.json（appid/secret/llm/KB/AIGC）
├── crypto_utils.py               ← wechat_check_signature + build_passive_reply_xml
├── token_manager.py              ← AccessTokenManager（SQLite + 3 次重试）
├── message_parser.py             ← XML → InternalMessage（parse_xml_to_msg）
├── cs_tracker.py                 ← LastUserMessageTracker（48h）+ MockWeChatClient
├── pipeline.py                   ← MockMessageProcessorLite（精简版 15 步流水线）
└── monitor.py                    ← BadCase 回传 pull_badcases 队列管理
```

### §4.2 Ticket 清单

| TID | 任务 | 对应 Seam |
|-----|------|----------|
| T-OA-01 | crypto_utils.py：wechat_check_signature + build_passive_reply_xml 纯函数 | OA-01/02/04 |
| T-OA-02 | token_manager.py：AccessTokenManager 完整 SQLite 持久化 + 提前 5min 刷新 + 指数退避 | OA-05/06/07 |
| T-OA-03 | message_parser.py：parse_xml_to_msg 提取 FromUserName/Content/MsgId → InternalMessage | OA-03 |
| T-OA-04 | cs_tracker.py：LastUserMessageTracker（时间戳）+ MockWeChatClient.send_text（含 48h 判断） | OA-09/10 |
| T-OA-05 | pipeline.py：精简版 process（去重/空内容/安全/装配/LLM/AIGC/写历史） | OA-08/11/14 |
| T-OA-06 | monitor.py：bad_cases_for_pull 队列 + pull_badcases(limit) 消费式读取 | OA-12 |
| T-OA-07 | app.py：Flask 路由（GET/POST /callback + /monitor/pull_badcases），异步线程处理 | OA-01/02/03/04/13/15 |
| T-OA-08 | config_loader.py：读取 config.json 验证必填字段 | 全部 |
| T-OA-09 | pytest tests/test_inner_oa_service_pdd.py：15 Seams 实现 | 全部 |

---

## §5 关键接口契约

### config.json 格式（MVP 阶段）
```json
{
  "app_id": "wx_xxxx",
  "app_secret": "xxxx",
  "token": "scai_token_xxx",
  "encoding_aes_key": "43 chars",
  "llm_provider": "deepseek",
  "llm_api_key": "sk-xxxx",
  "kb_root": "./kb",
  "aigc_explicit": false,
  "db_path": "./data/oa_service.db"
}
```

### handle_post 返回（5s 内同步响应，之后异步线程推送客服消息）
```xml
<xml>
  <ToUserName><![CDATA[openid_user]]></ToUserName>
  <FromUserName><![CDATA[gh_appid]]></FromUserName>
  <CreateTime>1700000000</CreateTime>
  <MsgType><![CDATA[text]]></MsgType>
  <Content><![CDATA[正在思考，请稍候...]]></Content>
</xml>
```

---

## §6 Acceptance 运行命令

```bash
cd C:\Users\Administrator\Desktop\WeChatAI_Project
python -m pytest tests/test_inner_oa_service_pdd.py -v
```

预期：**15 passed**。
