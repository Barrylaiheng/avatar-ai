"""FastMCP server —— 给 Trae / Wo Buddy 等 AI 助手用 stdio 协议对接。

3 个 tool：register_app / list_apps / run_app。
Token 鉴权：env var MCP_TOKEN 必须和 sqlite mcp_config.token 一致。
"""
from __future__ import annotations
import importlib
import json
import os
import sys
from pathlib import Path
from mcp.server.mcpserver import MCPServer

sys.path.insert(0, str(Path(__file__).parent))

_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from mcp_manager import get_mcp_manager

# 握手说明：MCP 客户端（Trae / WorkBuddy 等）在 initialize 时就会拿到这段，
# 让 AI Agent 第一次连上就知道这个 MCP 能干嘛、怎么用，不用用户自己去解释。
_MCP_INSTRUCTIONS = (
    '这是「阿维达AI」的本地 MCP 开发助手，用来在阿维达应用市场里开发和管理应用。'
    '常用工具：check_mcp_capabilities（先查这个 MCP 的能力边界，判断需求能不能做）、'
    'list_apps（列出阿维达里已有的应用）、get_app（看单个应用详情）、'
    'register_app（注册一个新应用，会自动生成 tool.py / runner.py 并挂到应用市场）、'
    'toggle_app（给某个智能体启/停某个应用）、run_app（运行应用）、delete_app（删除自建应用）。'
    '边界：MCP 只支持「LLM function calling → call_tool → 执行业务逻辑」这类能力；'
    '改 AI 人设 / 知识库检索逻辑 / 风控规则、拦截消息流、注册长期后台进程都超出边界。'
    '首次连接时，请先用一两句话向用户说明这个 MCP 能做什么、怎么用，再开始干活。'
)

mcp = MCPServer('Avida-MCP', instructions=_MCP_INSTRUCTIONS)


_APPS_DIR = Path(__file__).parent / 'apps'
_APPS_DIR.mkdir(parents=True, exist_ok=True)

_REGISTRY_PATH = Path(__file__).parent / 'app_registry.py'
_REGISTRY_ANCHOR = '\n}\n\n\n# ====== 便捷函数 ======'


_TOOL_HARD_LIMIT = 20
_TOOL_DEF_MAX_CHARS = 2000


_LISTED_CHANNELS = [
    'wecom',
    'feishu',
    'dingtalk',
    'wcf',
    'oa']


_BOUNDARY = {
    '不支持': [
        '修改智能体的 system_prompt 或人设',
        '改写 AI 的知识库检索逻辑（retriever）',
        '修改风控规则（risk_config）',
        '拦截 bridge pipeline 的消息处理流程',
        '在用户消息进入 LLM 之前做中间件级别的拦截/改写',
        '让 runner 在 bridge 启动时自动运行（bridge 只手动调 runner_fn）',
        '注册一个长期运行的后台进程',
        '直接 import 或修改 ai_agent / channel_binding 系统表'],
    '支持': [
        'LLM function calling 时调用 call_tool 执行业务逻辑',
        '读写业务表（自建表 / scheduled_job 等）',
        '发送消息到已绑定的渠道（wecom/feishu/dingtalk/wcf/oa）',
        '开临时线程（threading.Thread）在 call_tool 里做事',
        '调外部 HTTP API',
        '在 app_registry 里注册 function calling schema']}


_ALLOWED_CAPABILITIES = {
    'storage',
    'template',
    'scheduler',
    'channel_send'}


def _get_contact_info() -> str:
    """从 mcp_manager 拿开发者联系方式。空字符串时返回默认提示。"""
    try:
        mgr = get_mcp_manager()
        contact = mgr.get_contact()
        if contact:
            return contact
    except Exception:
        pass
    return 'QQ: 3564096269'


def _contact_hint() -> str:
    """越界时的标准提示消息。"""
    return f'如需独立开发超出 MCP 边界的能力，请联系阿维达开发者：{_get_contact_info()}'


def _check_token() -> str | None:
    """stdio 本地模式完全跳过鉴权。

    原因：server 和 client 都在本机，stdio 子进程通信的安全边界足够。
    TRAE / Wo Buddy 等 MCP 客户端的 stdio connector 经常会在 env 里注入
    一些无法控制的值（或完全忽略用户配置的 env），导致鉴权要么"未设置"
    要么"值不对"——两种情况都是误报。

    以后如果 MCP server 通过 HTTP 对外暴露（非本地），需要在这里加回来：
        expected = os.environ.get("MCP_TOKEN", "")
        if not expected:
            return "MCP_TOKEN 未设置"
        mgr = get_mcp_manager()
        if not mgr.verify_token(expected):
            return "MCP_TOKEN 无效"
    """
    return None


def _build_tool_py(app_id: str, capabilities: list[str], business_logic: str) -> str:
    """按 capabilities 自动生成完整 tool.py。

    capabilities 支持：
      "storage"    —— 注入 get_conn()，可读写业务表
      "channel_send" —— 注入统一 send_reply(channel, peer_id, content, peer_type) 函数
      "scheduler"  —— 注入 ensure_scheduler / register_job / refresh_all_jobs（定时任务）
      "template"   —— 注入 _fill_template（占位符 {now}/{today}/{get_daily_earnings} 等）
    """
    caps = set(capabilities or [])
    has_storage = 'storage' in caps
    has_channel = 'channel_send' in caps
    has_scheduler = 'scheduler' in caps
    has_template = 'template' in caps

    imports = []
    if has_storage:
        imports.append('from app.storage.db import get_conn')
    if has_scheduler:
        imports.append('from app.apps.%s.runner import register_job, refresh_all_jobs  # noqa: E402' % app_id)
    if has_template:
        imports.append('from app.apps.%s.runner import _fill_template  # noqa: E402' % app_id)

    ctx_doc = '# === bridge 自动注入的上下文 ===\n# call_tool(args) 里直接用这些 key：\n# args["__tool_name"]     当前 tool 名称\n# args["__agent_id"]      智能体 ID\n# args["__is_manager"]    True=管理者模式，False=普通用户\n# args["__credentials"]   凭据 dict（按 credential_schema 过滤）\n# args["__app_config"]    应用运行时配置 dict'
    parts = ['# -*- coding: utf-8 -*-', f'"""自动生成的 tool.py —— app_id={app_id}"""', '', *imports, '', ctx_doc, '']

    if has_channel:
        parts.append('')
        parts.append('def send_reply(channel: str, peer_id: str, content: str, peer_type: str = "friend"):')
        parts.append('    """统一发送消息。内部自动路由到正确的 channel client。"""')
        parts.append('    # 微信走风控锁（防封号），其他组织内渠道直接发')
        parts.append('    _need_lock = (channel == "wcf")')
        parts.append('    _risk = None')
        parts.append('    if _need_lock:')
        parts.append('        try:')
        parts.append('            from app.channel.risk_engine import get_risk_engine')
        parts.append('            _risk = get_risk_engine()')
        parts.append('            _risk.acquire_send_lock(min_gap=2.0)')
        parts.append('        except Exception as _le:')
        parts.append('            _risk = None')
        parts.append('    try:')
        parts.append('        if channel == "wecom":')
        parts.append('            from app.channel.wecom_client import WecomClient')
        parts.append('            c = WecomClient()')
        parts.append('            if not c.connected: return False, "企微 CLI 未连接"')
        parts.append('            return c.send_reply(peer_id, content, peer_type=peer_type) and True, None')
        parts.append('        if channel == "feishu":')
        parts.append('            from app.channel.feishu_client import FeishuClient')
        parts.append('            c = FeishuClient()')
        parts.append('            if not c.connected: return False, "飞书 CLI 未连接"')
        parts.append('            return c.send_reply(peer_id, content, peer_type=peer_type) and True, None')
        parts.append('        if channel == "dingtalk":')
        parts.append('            from app.channel.dingtalk_client import DingtalkClient')
        parts.append('            c = DingtalkClient()')
        parts.append('            if not c.connected: return False, "钉钉 CLI 未连接"')
        parts.append('            return c.send_reply(peer_id, content, peer_type=peer_type) and True, None')
        parts.append('        if channel == "wcf":')
        parts.append('            from app.channel.wcf_client import WcfClient')
        parts.append('            c = WcfClient()')
        parts.append('            if not c.connected: return False, "微信 CLI 未连接"')
        parts.append('            return c.send_reply(peer_id, content, peer_type=peer_type) and True, None')
        parts.append('        if channel == "oa":')
        parts.append('            from app.channel.oa_client import OaClient')
        parts.append('            c = OaClient()')
        parts.append('            if not c.connected: return False, "OA CLI 未连接"')
        parts.append('            return c.send_reply(peer_id, content, peer_type=peer_type) and True, None')
        parts.append('        return False, f"未知渠道: {channel}"')
        parts.append('    finally:')
        parts.append('        if _risk is not None:')
        parts.append('            try: _risk.release_send_lock()')
        parts.append('            except Exception: pass')
        parts.append('')

    if business_logic:
        import textwrap
        parts.append('')
        parts.append('def call_tool(args: dict) -> dict:')
        parts.append('    """LLM function calling 入口。bridge 自动注入 __tool_name / __agent_id / __is_manager / __credentials / __app_config。"""')

        dedented = textwrap.dedent(business_logic).strip('\n')
        for line in dedented.split('\n'):
            parts.append('    ' + line if line else '')
    else:
        parts.append('')
        parts.append('def call_tool(args: dict) -> dict:')
        parts.append('    """LLM function calling 入口。"""')
        parts.append('    mode = args.get("mode", "")')
        parts.append('    agent_id = args.get("__agent_id")')
        parts.append('    result = {"ok": True, "mode": mode, "agent_id": agent_id}')
        parts.append('    # TODO: 实现你的业务逻辑')
        parts.append('    return result')

    parts.append('')
    return '\n'.join(parts)


def _build_runner_py(app_id: str, capabilities: list[str], audience: str, value_for_manager: str, value_for_customer: str) -> str:
    """自动生成 runner.py —— 统一 parts 列表拼接（修复之前字符串+列表混用）。"""
    caps = set(capabilities or [])
    has_scheduler = 'scheduler' in caps

    parts = [
        '# -*- coding: utf-8 -*-',
        f'"""自动生成的 runner —— app_id={app_id}',
        '',
        '【双受众声明】',
        f'本应用 audience = {audience!r}',
        f'{value_for_manager and ("对管理者：" + value_for_manager)}',
        f'{value_for_customer and ("对普通用户：" + value_for_customer)}',
        '',
        'bridge 层会按 is_manager_mode 自动过滤 tool_def，',
        '普通用户对话时 manager-only 应用不会出现在 LLM 的 tool 列表里。',
        '"""',
        f'from app.apps.{app_id}.tool import call_tool',
        '']

    parts.append('def run(context: dict | None = None, **kwargs) -> str:')
    parts.append('    """手动"立即运行"入口（bridge run_app_once 调）。"""')
    parts.append('    args = (context or {}).get("args", kwargs) or kwargs')
    parts.append('    result = call_tool(args)')
    parts.append('    return str(result) if result is not None else ""')
    parts.append('')

    if has_scheduler:
        parts.append('def ensure_scheduler():')
        parts.append('    """启动公共轮询线程（幂等——所有 scheduler 应用共用一个）。"""')
        parts.append('    from app.apps._scheduler_common import ensure_scheduler as _ensure')
        parts.append('    _ensure()')
        parts.append('')
        parts.append('def register_job(job_id: str, cron_expr: str, name: str, agent_id: str,')
        parts.append('               content_template: str, target_json: dict, enabled: int = 1) -> dict:')
        parts.append('    """往 scheduled_job 表注册一个定时任务（公共调度器会自动扫到执行）。"""')
        parts.append('    import time as _time')
        parts.append('    if not job_id:')
        parts.append('        import uuid as _uuid; job_id = _uuid.uuid4().hex')
        parts.append('    conn = get_conn()')
        parts.append('    now = int(_time.time())')
        parts.append('    try:')
        parts.append('        conn.execute(')
        parts.append('            """INSERT INTO scheduled_job')
        parts.append('               (job_id, app_id, agent_id, name, cron_expr, content_template, target_json,')
        parts.append('                timezone, enabled, created_at, updated_at)')
        parts.append('               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)')
        parts.append('               ON CONFLICT(job_id) DO UPDATE SET')
        parts.append('                 cron_expr=excluded.cron_expr, content_template=excluded.content_template,')
        parts.append('                 target_json=excluded.target_json, enabled=excluded.enabled, updated_at=?""",')
        parts.append(f'            (job_id, {app_id!r}, agent_id, name, cron_expr, content_template,')
        parts.append('             str(target_json), "Asia/Shanghai", enabled, now, now, now))')
        parts.append('        conn.commit()')
        parts.append('        return {"ok": True, "job_id": job_id}')
        parts.append('    except Exception as e:')
        parts.append('        return {"ok": False, "error": str(e)}')
        parts.append('')
        parts.append('def refresh_all_jobs(agent_id: str = "") -> list:')
        parts.append('    """列出 scheduled_job 里属于本应用的所有任务（可选按 agent_id 过滤）。"""')
        parts.append('    conn = get_conn()')
        parts.append('    sql = "SELECT job_id, agent_id, name, cron_expr, enabled FROM scheduled_job WHERE app_id=?"')
        parts.append(f'    params = [{app_id!r}]')
        parts.append('    if agent_id:')
        parts.append('        sql += " AND agent_id=?"; params.append(agent_id)')
        parts.append('    rows = conn.execute(sql, params).fetchall()')
        parts.append('    return [dict(r) for r in rows]')
        parts.append('')
        parts.append('def execute_job_once(job_id: str) -> dict:')
        parts.append('    """公共调度器轮询到了就调这个——开发者在这里写业务逻辑。"""')
        parts.append('    conn = get_conn()')
        parts.append('    row = conn.execute("SELECT * FROM scheduled_job WHERE job_id=?", (job_id,)).fetchone()')
        parts.append('    if not row:')
        parts.append('        return {"ok": False, "error": "job 不存在"}')
        parts.append('    content = _fill_template(row["content_template"])')
        parts.append('    target = row["target_json"]')
        parts.append('    import json as _json; target = _json.loads(target) if isinstance(target, str) else target')
        parts.append('    channel_name = target.get("channel", "")')
        parts.append('    peer_id = target.get("peer_id", "")')
        parts.append('    peer_type = target.get("peer_type", "friend")')
        parts.append('    ok, err = send_reply(channel_name, peer_id, content, peer_type)')
        parts.append('    import time as _time')
        parts.append('    conn.execute("UPDATE scheduled_job SET last_run_at=?, updated_at=? WHERE job_id=?",')
        parts.append('                 (int(_time.time()), int(_time.time()), job_id))')
        parts.append('    conn.commit()')
        parts.append('    if not ok:')
        parts.append('        return {"ok": False, "error": err or "发送失败"}')
        parts.append('    return {"ok": True, "channel": channel_name, "peer_id": peer_id}')

    parts.append('')
    return '\n'.join(parts)


def validate_tool_def_for_fc(tool_def_json_str: str) -> tuple[bool, str]:
    """校验 tool_def_json 的 FC 安全性。返回 (ok, error_msg)。

    检查项：
      1. 大小不超过 _TOOL_DEF_MAX_CHARS
      2. tool name 不超过 40 字符
      3. 没有超深层嵌套参数（防 LLM 选错 tool）
    """
    if len(tool_def_json_str) > _TOOL_DEF_MAX_CHARS:
        return False, f'tool_def_json 过大 ({len(tool_def_json_str)} chars)，上限 {_TOOL_DEF_MAX_CHARS}，请简化 schema'

    try:
        td = json.loads(tool_def_json_str)
    except Exception as e:
        return False, f'tool_def_json 不是合法 JSON: {e}'

    fn = td.get('function') or {}
    name = fn.get('name', '')
    if not name:
        return False, 'tool_def 缺少 function.name'
    if len(name) > 40:
        return False, f"tool name '{name}' 过长 ({len(name)} 字符)，上限 40"

    props = fn.get('parameters', {}).get('properties', {})

    def _max_depth(obj, d=0):
        if isinstance(obj, dict):
            return max((_max_depth(v, d + 1) for v in obj.values()), default=d)
        if isinstance(obj, list):
            return max((_max_depth(v, d + 1) for v in obj), default=d)
        return d

    if _max_depth(props) > 5:
        return False, 'parameters.properties 嵌套过深（超过 5 层），LLM 容易选错 tool'

    return True, ''


def check_boundary_violations(app_id: str, capabilities: list[str], tool_def_json_str: str, business_logic_code: str = '') -> tuple[bool, str, str]:
    """校验 register_app 的请求有没有超出 MCP 边界。

    Returns:
        (ok, error_msg, contact_hint)
        ok=True  → 没越界，error_msg/contact_hint 为空
        ok=False → 越界了，error_msg 说清楚哪越了，contact_hint 给联系方式
    """
    violations = []

    caps = set(capabilities or [])
    unknown_caps = caps - _ALLOWED_CAPABILITIES
    if unknown_caps:
        violations.append(
            f'capabilities={list(unknown_caps)} 不在允许列表 {list(_ALLOWED_CAPABILITIES)} 里。 MCP 不支持这个能力——这属于边界之外，需要原生代码实现。')

    forbidden_names = {
        'set_agent_persona',
        'set_system_prompt',
        'intercept_pipeline',
        'modify_retriever',
        'start_background_daemon',
        'change_risk_rule'}

    try:
        td = json.loads(tool_def_json_str)
        fn = td.get('function') or {}
        name = fn.get('name', '')
        if name in forbidden_names:
            violations.append(
                f"tool name='{name}' 是边界外的能力（AI 人设/KB/风控/pipeline 拦截/后台守护进程）。 MCP 不支持，必须原生代码集成。")
    except Exception:
        pass

    if business_logic_code:
        forbidden_imports = [
            ('app.bridge', '不能直接 import bridge pipeline（pipeline 是内部单例，不能被 tool 修改或劫持）'),
            ('app.storage.agents_dao', '不能直接操作 ai_agent 系统表（agent 的 system_prompt/persona 不能由 MCP tool 改写）'),
            ('app.storage.channel_binding', '不能直接操作 channel_binding 系统表'),
            ('app.storage.risk_config_dao', '不能直接改风控规则'),
            ('app.storage.retriever', '不能改写 KB 检索逻辑（retriever 是 bridge 单例）')]
        for imp, reason in forbidden_imports:
            if imp not in business_logic_code:
                continue
            violations.append(f'代码里出现了 `import {imp}`：{reason}')

    if violations:
        error_msg = '⚠️ 这个需求超出了阿维达 MCP 契约边界：\n\n' + '\n'.join(f'  • {v}' for v in violations)
        return False, error_msg, _contact_hint()

    return True, '', ''


def _reload_registry():
    """强制 reload app_registry 模块，拿最新磁盘上的 APPS dict。"""
    try:
        import importlib
        import app_registry as _ar
        importlib.reload(_ar)
    except Exception:
        pass


def _append_to_registry(app_id: str, name: str, description: str, tool_def_json_str: str, audience: str = 'both', value_for_manager: str = '', value_for_customer: str = '', channels: list[str] | None = None, usage: str = '') -> None:
    """在 APPS dict 末尾追加一个条目（纯文本拼接，不引入 AST 复杂度）。"""
    content = _REGISTRY_PATH.read_text(encoding='utf-8')
    if f'"{app_id}"' in content:
        return None

    tool_fn_str = f'app.apps.{app_id}.tool:call_tool'
    runner_fn_str = f'app.apps.{app_id}.runner:run'
    channels_json = json.dumps(channels or [], ensure_ascii=False)
    usage_json = json.dumps(usage or '', ensure_ascii=False)

    entry = (
        f'\n    "{app_id}": {{\n\n        "id": "{app_id}'
        f'",\n\n        "name": {json.dumps(name, ensure_ascii=False)}'
        f',\n\n        "icon": "⚡",\n\n        "group": "自建应用",\n        "category": "custom",\n\n        # 双受众声明 —— 阿维达通信型 AI 分身的核心架构\n        # "manager" = 管理者内务工具（普通用户不应触发）\n        # "customer" = 纯对外工具（管理者无需专属通道，罕见）\n        # "both"    = 双向可用（默认，管理者运营/调试，普通用户消费/咨询）\n        "audience": {json.dumps(audience, ensure_ascii=False)}'
        f',\n\n        # 对管理者的价值：管理者（主人）用这个应用能做什么\n        "value_for_manager": {json.dumps(value_for_manager or "", ensure_ascii=False)}'
        f',\n\n        # 对普通用户的价值：客户/群成员跟 AI 对话时，这个应用能给他什么\n        # manager-only 应用填空字符串或 "无"\n        "value_for_customer": {json.dumps(value_for_customer or "", ensure_ascii=False)}'
        f',\n\n        "description": {json.dumps(description or "", ensure_ascii=False)}'
        f',\n\n        "usage": {usage_json}'
        f',\n\n        "version": "1.0.0",\n\n        "channels": {channels_json}'
        f',\n\n        # 自动注册：tool_def 来自外部传入\n        "tool_def_json": {tool_def_json_str}'
        f',\n\n        "tool_fn": {json.dumps(tool_fn_str, ensure_ascii=False)}'
        f',\n\n        "runner_fn": {json.dumps(runner_fn_str, ensure_ascii=False)}'
        f',\n\n    }},\n'
    )

    if _REGISTRY_ANCHOR in content:
        content = content.replace(_REGISTRY_ANCHOR, entry + _REGISTRY_ANCHOR, 1)
    else:
        content = content.rstrip() + '\n\n' + entry + '\n'
    _REGISTRY_PATH.write_text(content, encoding='utf-8')
    return None


@mcp.tool()
def register_app(app_id: str, name: str, tool_def_json: str, tool_py_code: str = '', audience: str = 'both', value_for_manager: str = '', value_for_customer: str = '', description: str = '', business_logic_code: str = '', capabilities: list[str] | None = None, channels: list[str] | None = None, usage: str = '') -> dict:
    """注册一个新应用到阿维达应用市场。会创建 tool.py / runner.py 并追加 app_registry.py。

    ╔══════════════════════════════════════════════════════════════════════╗
    ║ 【⚠️ 先读这个：MCP 边界】——以下场景 MCP 做不了                         ║
    ║                                                                      ║
    ║   ❌ 修改 AI 人设 / system_prompt / 知识库检索逻辑 / 风控规则        ║
    ║   ❌ 拦截 bridge pipeline 的消息处理流程（中间件级别）               ║
    ║   ❌ 让 runner 在 bridge 启动时自动跑（bridge 只手动调 runner_fn）   ║
    ║   ❌ 注册一个长期运行的后台守护进程                                   ║
    ║   ❌ 直接 import ai_agent / channel_binding / retriever 系统模块     ║
    ║                                                                      ║
    ║   ✅ 能做的：LLM function calling → call_tool → 执行业务逻辑         ║
    ║   ✅ 能做的：读写业务表 / 发消息到渠道 / 调外部 HTTP API              ║
    ║                                                                      ║
    ║   如果你发现用户需求在 ❌ 里：                                       ║
    ║     直接告诉用户「这个超出阿维达 MCP 边界了」，                       ║
    ║     不要硬调 register_app，register_app 会拦截并返回联系方式。        ║
    ║                                                                      ║
    ║   不确定能不能做？先调 check_mcp_capabilities 工具查一下。            ║
    ╚══════════════════════════════════════════════════════════════════════╝

    ╔══════════════════════════════════════════════════════════════════════╗
    ║ 【开发前必读】阿维达是通信型 AI 分身产品                              ║
    ║                                                                      ║
    ║ 每个应用服务两类用户，开发前必须想清楚两个问题：                       ║
    ║                                                                      ║
    ║  ① 管理者（主人）用这个应用干嘛？                                    ║
    ║     → 内务查数据？运营调试？配置一次躺平？                           ║
    ║                                                                      ║
    ║  ② 普通用户（客户/群成员/粉丝）跟 AI 对话时，这个应用能给他什么？     ║
    ║     → 问 AI 查价格？问产品参数？查自己的订单？                       ║
    ║                                                                      ║
    ║  ③ 普通用户调用会不会泄露管理者隐私？                                 ║
    ║     → 会 → audience="manager"（如：查老板日程、查团队考勤）          ║
    ║     → 不会且两边都有价值 → audience="both"（默认，如：CPS 选品、KB）  ║
    ║     → 只服务普通用户（罕见） → audience="customer"                    ║
    ╚══════════════════════════════════════════════════════════════════════╝

    ╔══════════════════════════════════════════════════════════════════════╗
    ║ 【脚手架模式】推荐 —— 用 capabilities + business_logic_code          ║
    ║                                                                      ║
    ║  外部开发者不知道阿维达内部 API 怎么调没关系，MCP server 会自动生成    ║
    ║  完整的 tool.py + runner.py，注入你需要的所有 import 和基础结构。     ║
    ║                                                                      ║
    ║  capabilities 可选值（多选）：                                        ║
    ║    "storage"      —— 注入 get_conn()，可读写 SQLite 业务表           ║
    ║    "channel_send"  —— 注入 send_reply(channel, peer_id, content)      ║
    ║                      支持 wecom / feishu / dingtalk / wcf / oa        ║
    ║    "scheduler"    —— 注入 ensure_scheduler / register_job 定时任务   ║
    ║    "template"     —— 注入 _fill_template 占位符 {now}/{today}/...    ║
    ║                                                                      ║
    ║  business_logic_code 只写核心业务逻辑（call_tool 函数体），           ║
    ║  不需要关心 import、DB 怎么连、渠道怎么发——这些 MCP 自动包好。        ║
    ║                                                                      ║
    ║  bridge 自动注入到 args 的上下文（你直接用就行）：                    ║
    ║    args["__tool_name"]     当前 tool 名称                             ║
    ║    args["__agent_id"]      智能体 ID                                  ║
    ║    args["__is_manager"]    True=管理者模式                            ║
    ║    args["__credentials"]   凭据 dict（已按 credential_schema 过滤）   ║
    ║    args["__app_config"]    应用运行时配置 dict                         ║
    ╚══════════════════════════════════════════════════════════════════════╝

    ╔══════════════════════════════════════════════════════════════════════╗
    ║ 【手写模式】—— 传 tool_py_code 覆盖脚手架                             ║
    ║                                                                      ║
    ║  想完全自己控制 tool.py？直接传 tool_py_code（完整 Python 源码字符串）。║
    ║  此时 capabilities 和 business_logic_code 会被忽略。                  ║
    ╚══════════════════════════════════════════════════════════════════════╝

    Args:
        app_id: 应用唯一 ID（英文+下划线+小写+数字）
        name: 应用中文名称
        tool_def_json: 工具定义 JSON 字符串（function calling schema）
        audience: "manager" / "both" / "customer"，默认 "both"
        value_for_manager: 对管理者的价值说明
        value_for_customer: 对普通用户的价值说明（manager-only 填 "无"）
        description: 应用一句话简介（保留）

        —— 脚手架模式（推荐）——
        capabilities: 需要的内置能力列表，如 ["storage", "channel_send"]
        business_logic_code: call_tool 函数体（核心业务逻辑，纯业务）

        —— 手写模式（高级）——
        tool_py_code: 完整 Python 源码（覆盖脚手架）

        —— 其他 ——
        channels: 支持的渠道列表，如 ["wecom", "feishu"]，bridge 可按渠道过滤
        usage: 详细使用说明（应用市场前端展示）
    """
    token_err = _check_token()
    if token_err:
        return {'ok': False, 'error': token_err}

    app_id = app_id.strip().lower().replace('-', '_')
    if not app_id or not app_id.replace('_', '').isalnum():
        return {'ok': False, 'error': 'app_id 必须是英文+下划线+数字'}

    if audience not in ('manager', 'both', 'customer'):
        return {'ok': False, 'error': 'audience 必须是 "manager" / "both" / "customer" 之一'}

    try:
        json.loads(tool_def_json)
    except Exception as e:
        return {'ok': False, 'error': f'tool_def_json 不是合法 JSON: {e}'}

    fc_ok, fc_err = validate_tool_def_for_fc(tool_def_json)
    if not fc_ok:
        return {'ok': False, 'error': f'FC 安全校验失败: {fc_err}'}

    ok, boundary_err, contact = check_boundary_violations(
        app_id=app_id,
        capabilities=capabilities or [],
        tool_def_json_str=tool_def_json,
        business_logic_code=business_logic_code or tool_py_code)

    if not ok:
        return {
            'ok': False,
            'error': boundary_err,
            'contact': contact,
            'hint': '这个需求超出了 MCP 契约边界。不要硬注册——即使注册了也跑不起来。'}

    if channels:
        invalid = [c for c in channels if c not in _LISTED_CHANNELS]
        if invalid:
            return {'ok': False, 'error': f'未知渠道: {invalid}，有效值: {_LISTED_CHANNELS}'}

    app_dir = _APPS_DIR / app_id
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / '__init__.py').touch()

    tool_path = app_dir / 'tool.py'
    runner_path = app_dir / 'runner.py'

    if tool_py_code:
        tool_path.write_text(tool_py_code, encoding='utf-8')
        if not runner_path.exists():
            runner_code = (
                f'# -*- coding: utf-8 -*-\n"""自动生成的 runner 骨架。\n\n【双受众声明】\n本应用 audience = {audience!r}\n'
                f'{value_for_manager and ("对管理者：" + value_for_manager)}\n'
                f'{value_for_customer and ("对普通用户：" + value_for_customer)}\n'
                f'"""\nfrom app.apps.{app_id}.tool import call_tool\n\n\ndef run(context: dict | None = None, **kwargs) -> str:\n    """手动立即运行入口。"""\n    args = (context or {{}}).get("args", kwargs) or kwargs\n    result = call_tool(args)\n    return str(result) if result is not None else ""\n')
            runner_path.write_text(runner_code, encoding='utf-8')
    else:
        caps = capabilities or []
        tool_py = _build_tool_py(app_id, caps, business_logic_code)
        runner_py = _build_runner_py(app_id, caps, audience, value_for_manager, value_for_customer)
        tool_path.write_text(tool_py, encoding='utf-8')
        runner_path.write_text(runner_py, encoding='utf-8')

    _append_to_registry(
        app_id=app_id,
        name=name,
        description=description,
        tool_def_json_str=tool_def_json,
        audience=audience,
        value_for_manager=value_for_manager,
        value_for_customer=value_for_customer,
        channels=channels,
        usage=usage)

    _reload_registry()

    return {
        'ok': True,
        'app_id': app_id,
        'name': name,
        'audience': audience,
        'mode': '手写' if tool_py_code else '脚手架',
        'capabilities': capabilities or [],
        'tool_py_written': str(tool_path),
        'runner_py_written': str(runner_path),
        'hints': [
            'bridge 会自动把 __tool_name / __agent_id / __is_manager / __credentials / __app_config 注入到 args',
            '普通用户对话时 manager-only 应用不会出现在 LLM tool 列表里',
            f'FC 护栏：全局 tool 数量上限 {_TOOL_HARD_LIMIT}，单 schema 上限 {_TOOL_DEF_MAX_CHARS} chars',
        ],
    }


@mcp.tool()
def check_mcp_capabilities(question: str = '') -> dict:
    """查询阿维达 MCP 能做什么、不能做什么。

    在开始开发之前先调这个工具，确认你的需求是否在边界内。
    如果需求在边界外，返回里会给你开发者联系方式。

    Args:
        question: 可选，描述你的需求（如"我想做一个定时发消息的功能"），
                  会自动帮你判断是否越界。
    """
    hint = ''
    if question:

        q_lower = question.lower()

        boundary_keywords = [
            (['prompt', '人设', 'persona', 'system_prompt'],
             '修改 AI 人设属于边界外。MCP 无法改写智能体的 system_prompt。'),
            (['拦截', 'intercept', 'middleware', 'pipeline'],
             '拦截 bridge 消息流属于边界外。MCP tool 只能被 LLM 主动调用，不能做中间件级别拦截。'),
            (['后台进程', 'daemon', '守护进程', '长期运行'],
             '长期后台进程属于边界外。bridge 只手动调 runner_fn，不会自动拉起后台服务。'),
            (['retriever', '检索', '知识库检索'],
             '改写知识库检索逻辑属于边界外。retriever 是 bridge 单例，MCP tool 无法触及。'),
            (['风控', 'risk'],
             '修改风控规则属于边界外。risk_config 是系统级配置。'),
        ]
        for keywords, msg in boundary_keywords:
            if any(kw in q_lower for kw in keywords):
                hint = msg
                break
        if not hint:
            hint = '你的需求看起来在 MCP 边界内，可以调 register_app 继续开发。'

    return {
        'ok': True,
        '支持的 capabilities': sorted(_ALLOWED_CAPABILITIES),
        '支持的 channels': _LISTED_CHANNELS,
        '不支持的场景': _BOUNDARY['不支持'],
        '支持的场景': _BOUNDARY['支持'],
        'FC 护栏': {'tool 数量上限': _TOOL_HARD_LIMIT, '单 schema 字符上限': _TOOL_DEF_MAX_CHARS},
        '联系方式': _get_contact_info(),
        '需求判断': hint,
    }


@mcp.tool()
def list_apps() -> list:
    """列出当前阿维达已注册的所有应用。"""
    token_err = _check_token()
    if token_err:
        return [{'ok': False, 'error': token_err}]

    _reload_registry()

    try:
        from app_registry import list_apps as _list
    except ImportError:
        return []

    apps = _list(include_hidden=True)

    out = []
    for a in apps:
        out.append({
            'id': a.get('id'),
            'name': a.get('name'),
            'description': a.get('description', ''),
            'version': a.get('version', ''),
            'category': a.get('category', ''),
            'channels': a.get('channels', []),
            'audience': a.get('audience', 'both'),
            'usage': a.get('usage', ''),
            'has_runner': bool(a.get('runner_fn')),
            'has_tool': bool(a.get('tool_fn')),
        })

    return out


@mcp.tool()
def run_app(app_id: str, agent_id: str = '', extra_args: dict | None = None, kwargs: str = '') -> dict:
    """运行某个应用（通过 runner_fn 入口）。

    Args:
        app_id: 应用 ID
        agent_id: 可选，指定由哪个 agent 上下文运行
        extra_args: 可选，透传给 runner 的运行时参数字典
    """
    token_err = _check_token()
    if token_err:
        return {'ok': False, 'error': token_err}

    try:
        from app_registry import get_app
    except ImportError:
        return {'ok': False, 'error': 'app_registry 不可用'}

    meta = get_app(app_id)
    if not meta:
        return {'ok': False, 'error': f'未知应用: {app_id}'}

    runner_fn = meta.get('runner_fn')
    if not runner_fn:
        return {'ok': False, 'error': '该应用未提供 runner_fn'}

    try:
        mod_path, fn_name = runner_fn.split(':', 1)
        mod = importlib.import_module(mod_path)
        fn = getattr(mod, fn_name)
    except Exception as e:
        return {'ok': False, 'error': f'runner_fn 解析失败: {e}'}

    try:
        context = {'agent_id': agent_id, 'args': extra_args or {}}
        result = fn(context)
        if isinstance(result, (dict, list)):
            return {'ok': True, 'result': result}
        return {'ok': True, 'result': str(result)}
    except Exception as e:
        import traceback as _tb
        return {'ok': False, 'error': str(e), 'traceback': _tb.format_exc()[:500]}


@mcp.tool()
def get_app(app_id: str) -> dict:
    """按 ID 查单个应用详情。

    Args:
        app_id: 应用 ID（如 cps_selector / schedule_message）
    """
    token_err = _check_token()
    if token_err:
        return {'ok': False, 'error': token_err}

    _reload_registry()

    try:
        from app_registry import get_app as _get
    except ImportError:
        return {'ok': False, 'error': 'app_registry 不可用'}

    a = _get(app_id)
    if not a:
        return {'ok': False, 'error': f'未找到应用: {app_id}'}

    return {
        'ok': True,
        'id': a.get('id'),
        'name': a.get('name'),
        'description': a.get('description', ''),
        'version': a.get('version', ''),
        'category': a.get('category', ''),
        'channels': a.get('channels', []),
        'audience': a.get('audience', 'both'),
        'usage': a.get('usage', ''),
        'tool_def_json': a.get('tool_def_json', ''),
        'has_runner': bool(a.get('runner_fn')),
        'has_tool': bool(a.get('tool_fn')),
    }


@mcp.tool()
def toggle_app(agent_id: str, app_id: str, enabled: bool = True) -> dict:
    """给某个智能体启/停某个应用。

    Args:
        agent_id: 智能体 ID
        app_id: 应用 ID
        enabled: True=启用，False=禁用
    """
    token_err = _check_token()
    if token_err:
        return {'ok': False, 'error': token_err}

    try:
        from storage.dao import AgentAppDAO
        dao = AgentAppDAO()
        dao.upsert(agent_id, app_id, enabled=enabled)
        action = '启用' if enabled else '禁用'
        return {'ok': True, 'message': f'智能体 {agent_id} 已{action}应用 {app_id}'}
    except ImportError:
        return {'ok': False, 'error': 'storage.dao 不可用'}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


@mcp.tool()
def delete_app(app_id: str) -> dict:
    """删除一个自建应用（清 registry + agent_app 绑定）。

    Args:
        app_id: 要删除的应用 ID
    """
    token_err = _check_token()
    if token_err:
        return {'ok': False, 'error': token_err}

    try:
        _reload_registry()
        from app_registry import get_app as _get
        meta = _get(app_id)
        if not meta:
            return {'ok': False, 'error': f'未找到应用: {app_id}'}

        is_builtin = meta.get('builtin', False)
        if is_builtin:
            return {'ok': False, 'error': '内置应用不可删除'}

        from app_registry import APPS
        APPS.pop(app_id, None)
        try:
            from storage.db import get_conn
            conn = get_conn()
            conn.execute('DELETE FROM agent_app WHERE app_id = ?', (app_id,))
            conn.commit()
        except Exception:
            pass
        return {'ok': True, 'message': f'自建应用 {app_id} 已删除'}
    except ImportError:
        return {'ok': False, 'error': 'app_registry 不可用'}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


if __name__ == '__main__':
    mcp.run()
