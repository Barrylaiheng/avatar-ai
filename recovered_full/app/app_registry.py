"""
应用注册表 — v2.0 应用市场核心

所有内置应用硬编码在 APPS 字典里。应用市场前端、bridge handler、runner 全部从这里读元数据。
新增应用只需在这里加一条，再加 app/apps/<app_id>/ 目录下的 runner + test。
"""
from typing import Any

APPS: dict[str, dict[str, Any]] = {
    "cps_selector": {
        "id": "cps_selector",
        "name": "好单库CPS助手",
        "icon": "🛒",
        "group": "电商微商",
        "category": "ecommerce",
        "description": "自动搜索好单库、计算佣金、推送到企微/飞书/钉钉群。每天帮你盯行业。",
        "version": "1.0.0",
        "channels": ["wecom", "feishu", "dingtalk"],
        "audience": "both",
        "value_for_manager": "选品预览、查当日佣金收入、调试 API 连通性、一键把高佣商品推送到指定群。管理者是配置者，也是运营/调试的使用者。",
        "value_for_customer": "跟 AI 说「有啥优惠」「帮我找 XX 最低价」，AI 直接派好单库的专属优惠券/转链，你省钱，店主赚佣。",
        "credential_schema": {
            "fields": [
                {
                    "key": "haodanku_api_key",
                    "label": "好单库 API Key",
                    "type": "password",
                    "required": True,
                    "placeholder": "在好单库开放平台申请",
                    "help": "一个 Key 通吃淘宝/京东/拼多多/美团等 12 个主流平台",
                    "link": {
                        "text": "前往好单库开放平台注册 →",
                        "url": "https://www.haodanku.com/",
                    },
                }
            ]
        },
        "runtime_schema": {"fields": []},
        "test_fn": "app.apps.cps_selector.test:run",
        "runner_fn": "app.apps.cps_selector.runner:run",
        "tool_def": "app.apps.cps_selector.tool:TOOL_DEF",
        "tool_fn": "app.apps.cps_selector.tool:call_tool",
        **{
            "audience": "both",
            "value_for_manager": "选品预览 / 调试 API / 验证转链效果",
            "value_for_customer": "问'有啥优惠''帮我找 XX' → AI 派券/转链，你省钱、店主赚佣",
        },
    },
    "cps_earnings": {
        "id": "cps_earnings",
        "name": "好单库佣金中心",
        "icon": "💰",
        "group": "电商微商",
        "category": "ecommerce",
        "description": "管理者专属：多平台佣金汇总、结算状态、退款追踪，一句话看'今天赚了多少'",
        "version": "1.1.0",
        "channels": ["wecom", "feishu", "dingtalk"],
        "credential_schema": {
            "fields": [
                {
                    "key": "haodanku_api_key",
                    "label": "好单库 API Key",
                    "type": "password",
                    "required": True,
                    "placeholder": "与好单库CPS助手共用同一 API Key",
                    "help": "一个 Key 通吃淘宝/京东/拼多多/美团等 12 个主流平台",
                    "link": {
                        "text": "前往好单库开放平台注册 →",
                        "url": "https://www.haodanku.com/",
                    },
                }
            ]
        },
        "runtime_schema": {"fields": []},
        "audience": "manager",
        "value_for_manager": "查询各平台预估/实际佣金、结算状态、退款情况，按时间/平台/状态多维度汇总",
        "value_for_customer": "无（管理者专属，普通用户对话时 bridge 层自动屏蔽）",
        "tool_def": "app.apps.cps_selector.tool:TOOL_DEF_EARNINGS",
        "tool_fn": "app.apps.cps_selector.tool:call_tool",
        "runner_fn": "app.apps.cps_selector.runner:run",
    },
    "schedule_message": {
        "id": "schedule_message",
        "name": "定时发送",
        "icon": "⏰",
        "group": "通用应用",
        "category": "general",
        "description": "管理者专属：创建 cron 定时任务，AI 按时间自动发消息到企微/飞书/钉钉/微信群。",
        "version": "1.0.0",
        "channels": ["wecom", "feishu", "dingtalk", "wcf", "oa"],
        "usage": """
【使用说明】

这是管理者专属的定时发送工具。你可以跟 AI（主人模式）对话：

• "每天下午 3 点，把好单库佣金前 3 发到企微大客户群"
• "每周五 18:00，把 cps 佣金汇总发给我的飞书"

AI 会跟你确认时间、内容、目标渠道后存入 DB，APScheduler 在北京时间执行。

时间格式说明：
  cron 表达式（Asia/Shanghai，北京时间）
  格式：分 时 日 月 周
  例：'0 15 * * *' = 每天 15:00；'0 9 * * 1-5' = 工作日 9:00

支持的内容占位符：
  {get_daily_earnings} → 当日 CPS 佣金汇总
  {now} → 当前时间
  {today} → 当前日期
        """.strip(),
        "credential_schema": {"fields": []},
        "runtime_schema": {"fields": []},
        "audience": "manager",
        "value_for_manager": "用自然语言跟 AI 确认时间/内容/目标群 → 定时自动发，不用手动切 App。管理者自己是创建者和确认者。",
        "value_for_customer": "无（管理者专属，普通用户对话时 bridge 层自动屏蔽）。",
        "tool_def_json": {
            "type": "function",
            "function": {
                "name": "schedule_message",
                "description": "管理者专属：定时发送消息到指定渠道。mode 可选 create 创建 / list 列出 / delete 删除 / run_now 立即执行。时间以 Asia/Shanghai 北京时间为准。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "mode": {
                            "type": "string",
                            "enum": ["create", "list", "delete", "run_now"],
                            "description": "操作模式",
                        },
                        "name": {
                            "type": "string",
                            "description": "任务名，如'每日好单推送'",
                        },
                        "cron_expr": {
                            "type": "string",
                            "description": "Cron 表达式，Asia/Shanghai 时区。格式：分 时 日 月 周。如'0 15 * * *'=每天15:00",
                        },
                        "content_template": {
                            "type": "string",
                            "description": "发送内容，可含占位符如{get_daily_earnings}",
                        },
                        "target": {
                            "type": "object",
                            "description": "发送目标",
                            "properties": {
                                "channel": {
                                    "type": "string",
                                    "enum": ["wecom", "feishu", "dingtalk", "wcf", "oa"],
                                },
                                "peer_id": {"type": "string"},
                                "peer_type": {
                                    "type": "string",
                                    "enum": ["friend", "group", "official"],
                                },
                            },
                            "required": ["channel", "peer_id", "peer_type"],
                        },
                        "job_id": {
                            "type": "string",
                            "description": "delete/run_now 时必填",
                        },
                        "agent_id": {
                            "type": "string",
                            "description": "关联哪个智能体，一般不需要填",
                        },
                    },
                    "required": ["mode"],
                },
            },
        },
        "tool_fn": "app.apps.schedule_message.tool:call_tool",
        "runner_fn": "app.apps.schedule_message.runner:start_scheduler",
    },
    "message_summary": {
        "id": "message_summary",
        "name": "消息摘要助手",
        "icon": "📋",
        "group": "通用应用",
        "category": "general",
        "description": "自动总结最近 N 小时的飞书/企微/钉钉/微信消息，提炼要点和待办",
        "version": "1.0.0",
        "channels": ["wecom", "feishu", "dingtalk", "wcf", "oa"],
        "audience": "both",
        "value_for_manager": "跨渠道汇总自己的消息，提炼要点和待办，一眼看完重要的事。",
        "value_for_customer": "群绑定开启时，问 AI「群里刚才聊了啥」「老板今天发了啥通知」，快速回看不爬楼。",
        "usage": """
【使用说明】

这个应用会让 AI 自动读取你最近的渠道消息（飞书/企微/钉钉/微信），提炼出要点和待办。

• 直接打开上面的开关即可，无需额外配置
• AI 调用时可指定时间窗口，比如"帮我总结今天的重要消息"或"看看最近 3 小时有什么紧急的事"
• 也可以指定聚焦方向：urgent（只看紧急的）、todo（只看待办）、brief（精简版）
• 消息来自你在「渠道绑定」tab 已授权的渠道，未绑定的不会被读取
        """.strip(),
        "tool_def_json": {
            "type": "function",
            "function": {
                "name": "message_summary",
                "description": "总结指定智能体最近的渠道消息（飞书/企微/钉钉/微信），提炼要点和待办",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "hours": {
                            "type": "integer",
                            "description": "要总结的时间窗口（小时），默认 24",
                        },
                        "focus": {
                            "type": "string",
                            "description": "聚焦方向（可选）：urgent=只看紧急重要的，todo=只看待办事项，brief=精简版摘要",
                        },
                    },
                    "required": [],
                },
            },
        },
        "tool_fn": "app.apps.message_summary.tool:call_tool",
        "runner_fn": "app.apps.message_summary.runner:run",
    },
    "calendar_today": {
        "id": "calendar_today",
        "name": "今日日程",
        "icon": "📅",
        "group": "组织管理",
        "category": "org_management",
        "description": "跨飞书/钉钉聚合今天的日程安排，一句话看完所有会议",
        "version": "1.0.0",
        "channels": ["feishu", "dingtalk"],
        "audience": "manager",
        "value_for_manager": "一句话问 AI 今天有什么会，跨飞书钉钉合并视图，不用开两个 App 切。",
        "value_for_customer": "无（此工具为管理者专属，普通用户不应触发）。",
        "usage": """
【使用说明】

让 AI 跨飞书和钉钉帮你拉日程安排，合并成一个视图。

• 直接打开上面的开关即可，无需额外配置
• 需要你在「渠道绑定」tab 已授权飞书 / 钉钉
• 飞书和钉钉各自拉各自的日程，阿维达只做合并不做修改
• AI 可以指定只看某个渠道："飞书今天有什么会？"
        """.strip(),
        "tool_def_json": {
            "type": "function",
            "function": {
                "name": "calendar_today",
                "description": "查询今日日程（跨飞书/钉钉合并视图）",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "platform": {
                            "type": "string",
                            "description": "feishu / dingtalk / both（默认 both）",
                            "enum": ["feishu", "dingtalk", "both"],
                        },
                        "days": {
                            "type": "integer",
                            "description": "查询范围（天），默认 1",
                        },
                    },
                    "required": [],
                },
            },
        },
        "tool_fn": "app.apps.calendar_today.tool:call_tool",
        "runner_fn": "app.apps.calendar_today.runner:run",
    },
    "approval_pending": {
        "id": "approval_pending",
        "name": "审批待办汇总",
        "icon": "✅",
        "group": "组织管理",
        "category": "org_management",
        "description": "跨飞书/钉钉拉你的审批待办清单，一眼看完哪些要处理",
        "version": "1.0.0",
        "channels": ["feishu", "dingtalk"],
        "audience": "manager",
        "value_for_manager": "AI 帮你拉飞书钉钉的审批待办，合并成一个清单，一眼看完哪些要批。",
        "value_for_customer": "无（此工具为管理者专属，普通用户不应触发）。",
        "usage": """
【使用说明】

让 AI 帮你从飞书和钉钉拉当前需要你处理的审批待办，合并成一个清单。

• 直接打开上面的开关即可，无需额外配置
• 需要你在「渠道绑定」tab 已授权飞书 / 钉钉
• 只拉"待我审批"的任务，不涉及已提交或已完成的
        """.strip(),
        "tool_def_json": {
            "type": "function",
            "function": {
                "name": "approval_pending",
                "description": "查询飞书/钉钉上需要我处理的审批待办",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "platform": {
                            "type": "string",
                            "description": "feishu / dingtalk / both（默认 both）",
                            "enum": ["feishu", "dingtalk", "both"],
                        },
                    },
                    "required": [],
                },
            },
        },
        "tool_fn": "app.apps.approval_pending.tool:call_tool",
        "runner_fn": "app.apps.approval_pending.runner:run",
    },
    "contact_search": {
        "id": "contact_search",
        "name": "找人",
        "icon": "👥",
        "group": "组织管理",
        "category": "org_management",
        "description": "按姓名或关键字跨飞书/钉钉通讯录模糊搜索同事",
        "version": "1.0.0",
        "channels": ["feishu", "dingtalk"],
        "audience": "manager",
        "value_for_manager": "忘了同事全名或在哪个部门？跟 AI 说名字/关键字直接帮你找到，不用翻通讯录。",
        "value_for_customer": "无（此工具为管理者专属，普通用户不应触发）。",
        "usage": """
【使用说明】

让 AI 帮你跨飞书 / 钉钉通讯录找人，比如想不起来同事全名或在哪个部门。

• 直接打开上面的开关即可，无需额外配置
• 需要你在「渠道绑定」tab 已授权飞书 / 钉钉
• 支持模糊搜索：可以搜姓名、拼音、部门关键字
• 返回姓名、部门、职位、联系方式（有权限时）
        """.strip(),
        "tool_def_json": {
            "type": "function",
            "function": {
                "name": "contact_search",
                "description": "按姓名/关键字在跨渠道通讯录里找人",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "keyword": {
                            "type": "string",
                            "description": "姓名或关键字",
                        },
                        "platform": {
                            "type": "string",
                            "description": "feishu / dingtalk / both（默认 both）",
                            "enum": ["feishu", "dingtalk", "both"],
                        },
                    },
                    "required": ["keyword"],
                },
            },
        },
        "tool_fn": "app.apps.contact_search.tool:call_tool",
        "runner_fn": "app.apps.contact_search.runner:run",
    },
    "tasks_today": {
        "id": "tasks_today",
        "name": "今日待办",
        "icon": "📝",
        "group": "组织管理",
        "category": "org_management",
        "description": "跨飞书/钉钉拉需要你处理的任务清单，合并成一个视图",
        "version": "1.0.0",
        "channels": ["feishu", "dingtalk"],
        "audience": "manager",
        "value_for_manager": "跨飞书钉钉拉待办，合并成一个清单，一句话知道今天要做什么。",
        "value_for_customer": "无（此工具为管理者专属，普通用户不应触发）。",
        "usage": """
【使用说明】

让 AI 跨飞书和钉钉拉你的待办任务，合并成一个清单。

• 直接打开上面的开关即可，无需额外配置
• 需要你在「渠道绑定」tab 已授权飞书 / 钉钉
• 默认只看今日到期的任务，可以指定看全部："帮我列一下所有未完成的待办"
        """.strip(),
        "tool_def_json": {
            "type": "function",
            "function": {
                "name": "tasks_today",
                "description": "查询我的待办任务（飞书 + 钉钉合并），支持过滤今日/全部",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "platform": {
                            "type": "string",
                            "description": "feishu / dingtalk / both（默认 both）",
                            "enum": ["feishu", "dingtalk", "both"],
                        },
                        "scope": {
                            "type": "string",
                            "description": "today=只看今天到期的，all=全部未完成（默认 today）",
                            "enum": ["today", "all"],
                        },
                    },
                    "required": [],
                },
            },
        },
        "tool_fn": "app.apps.tasks_today.tool:call_tool",
        "runner_fn": "app.apps.tasks_today.runner:run",
    },
    "attendance_check": {
        "id": "attendance_check",
        "name": "考勤查询",
        "icon": "📅",
        "group": "组织管理",
        "category": "org_management",
        "description": "查询钉钉考勤打卡（今日/本月），返回正常/迟到/早退/缺卡结果",
        "version": "1.0.0",
        "channels": ["dingtalk"],
        "hidden_in_mvp": True,
        "audience": "manager",
        "value_for_manager": "随手查团队考勤，今日打卡还是本月汇总，AI 一句话报给你。",
        "value_for_customer": "无（此工具为管理者专属，普通用户不应触发）。",
        "usage": """
【使用说明】

让 AI 帮你查钉钉考勤打卡流水和结果。

• 直接打开上面的开关即可，无需额外配置
• 需要你在「渠道绑定」tab 已授权钉钉
• 可以查今日打卡或本月汇总："这个月考勤怎么样" / "今天打卡了吗"
• 只支持钉钉（飞书考勤不在开放 CLI 范围内）
        """.strip(),
        "tool_def_json": {
            "type": "function",
            "function": {
                "name": "attendance_check",
                "description": "查询钉钉考勤打卡（今日/本月），返回正常/迟到/早退/缺卡等结果",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "scope": {
                            "type": "string",
                            "description": "today=今日打卡，month=本月打卡（默认 today）",
                            "enum": ["today", "month"],
                        },
                    },
                    "required": [],
                },
            },
        },
        "tool_fn": "app.apps.attendance_check.tool:call_tool",
        "runner_fn": "app.apps.attendance_check.runner:run",
    },
    "minutes_search": {
        "id": "minutes_search",
        "name": "会议纪要",
        "icon": "🎙️",
        "group": "组织管理",
        "category": "org_management",
        "description": "搜索飞书妙记/钉钉听记的会议纪要，按时间或关键词返回摘要",
        "version": "1.0.0",
        "channels": ["feishu", "dingtalk"],
        "hidden_in_mvp": True,
        "audience": "manager",
        "value_for_manager": "不用开飞书妙记/钉钉听记 App，跟 AI 说关键字或时间范围直接翻纪要。",
        "value_for_customer": "无（此工具为管理者专属，普通用户不应触发）。",
        "usage": """
【使用说明】

让 AI 跨飞书妙记和钉钉听记搜索近期的会议纪要。

• 直接打开上面的开关即可，无需额外配置
• 需要你在「渠道绑定」tab 已授权飞书 / 钉钉
• 可以按关键词搜："找一下上周那个方案评审会"
• 可以调范围："最近 3 天的会议"（默认 7 天）
        """.strip(),
        "tool_def_json": {
            "type": "function",
            "function": {
                "name": "minutes_search",
                "description": "搜索最近的会议纪要（飞书妙记 + 钉钉听记），按时间或关键词返回摘要",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "platform": {
                            "type": "string",
                            "description": "feishu / dingtalk / both（默认 both）",
                            "enum": ["feishu", "dingtalk", "both"],
                        },
                        "query": {
                            "type": "string",
                            "description": "关键词（可选），比如'周会''项目''方案'",
                        },
                        "days": {
                            "type": "integer",
                            "description": "搜索范围（天），默认 7",
                        },
                        "detail": {
                            "type": "boolean",
                            "description": "是否拉取摘要详情（默认 false）",
                        },
                    },
                    "required": [],
                },
            },
        },
        "tool_fn": "app.apps.minutes_search.tool:call_tool",
        "runner_fn": "app.apps.minutes_search.runner:run",
    },
    "kb_search": {
        "id": "kb_search",
        "name": "知识库检索",
        "icon": "📚",
        "group": "通用应用",
        "category": "general",
        "description": "在本地知识库里按关键词搜索相关段落，返回最相关的内容切片",
        "version": "1.0.0",
        "channels": ["oa"],
        "audience": "both",
        "value_for_manager": "灌完知识库后让 AI 帮你搜一段，验证 KB 是否灌对、切片质量如何。",
        "value_for_customer": "问产品参数、售后政策、品牌故事……AI 直接从老板的知识库里挖答案，统一口径。",
        "usage": """
【使用说明】

让 AI 在你已导入的知识库里搜相关内容。

• 直接打开上面的开关即可，无需额外配置
• 知识来源于你在「知识库」tab 导入的文档和切片
• 可以指定只搜某个知识库，不填则全部搜
• 当前用关键词匹配，后续会升级成语义向量检索

典型用法：
  "我之前写的产品方案里关于定价怎么说的"
  "帮我搜知识库里关于 XX 的内容"
        """.strip(),
        "tool_def_json": {
            "type": "function",
            "function": {
                "name": "kb_search",
                "description": "在本地知识库里按关键词搜索相关段落，返回 top N 最相关的切片内容",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "要搜索的关键词或问题",
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "返回多少条，默认 5",
                        },
                        "kb_id": {
                            "type": "string",
                            "description": "可选：限定只搜某个知识库的 id",
                        },
                    },
                    "required": ["query"],
                },
            },
        },
        "tool_fn": "app.apps.kb_search.tool:call_tool",
        "runner_fn": "app.apps.kb_search.runner:run",
    },
}


def get_app(app_id: str) -> dict | None:
    return APPS.get(app_id)


def list_apps(category: str | None = None, include_hidden: bool = False) -> list[dict]:
    """返回所有应用（按 category 可选过滤），默认过滤 hidden_in_mvp 的应用。

    include_hidden=True 时返回全量（给 MCP / bridge 内部用）。
    """
    apps = list(APPS.values())
    if not include_hidden:
        apps = [a for a in apps if not a.get("hidden_in_mvp")]
    if category and category != "all":
        apps = [a for a in apps if a.get("category") == category]
    return sorted(apps, key=lambda a: a["id"])
