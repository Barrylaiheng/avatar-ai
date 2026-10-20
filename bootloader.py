"""Bootloader: pyc-only 入口。

打包时这个文件是唯一的 .py 入口。EXE 运行时：
1. 用 SourcelessFileLoader 加载所有打包进来的 .cpython-312.pyc
2. 按依赖顺序 + 短别名注册（源码里有 from storage import xxx）
3. 加载 storage 包单例
4. 调用 app.main.main() 启动

PyInstaller 会把 .pyc 解压到 sys._MEIPASS/app/__pycache__ 下，
所以 pathex 里加 sys._MEIPASS 让 loader 能找到。
"""
import sys
import os
import importlib
import importlib.machinery
import importlib.util

# PyInstaller onefile 解压后的临时目录
if hasattr(sys, '_MEIPASS'):
    sys.path.insert(0, sys._MEIPASS)


def _detect_mcp_mode(argv=None):
    """判断本次启动是否为 MCP stdio 服务模式。

    打包版（onefile exe）自身就是解释器，MCP 客户端（Trae / Wo Buddy）会执行
        "Avatar AI.exe" -m app.mcp_server
    这时代码必须直接进入 MCP 服务，而不是弹出 GUI。
    """
    argv = sys.argv[1:] if argv is None else argv
    if '--mcp-server' in argv:
        return True
    for i, a in enumerate(argv):
        if a == '-m' and i + 1 < len(argv) and argv[i + 1].strip() in ('app.mcp_server', 'app/mcp_server'):
            return True
    return False


# 模块级常量：main() 里要靠它决定走 MCP 还是 GUI
_MCP_MODE = _detect_mcp_mode()

# MCP 模式下不加载这两个模块：它们会把 PyQt6 / 整个 GUI 依赖拖进来，
# 既拖慢握手速度，也让一个无界面的 stdio 子进程白白初始化 Qt。
_MCP_SKIP = {'app.bridge', 'app.main'}


def _log(msg):
    """打印诊断信息。

    MCP 模式下 stdout 是 JSON-RPC 数据通道，诊断信息必须走 stderr，
    否则会污染协议流导致客户端握手失败。
    """
    stream = sys.stderr if _MCP_MODE else sys.stdout
    if stream is None:
        stream = sys.stdout
    try:
        print(msg, file=stream, flush=True)
    except Exception:
        pass


def _ensure_stdio():
    """windowed exe 下 stdin/stdout/stderr 可能为 None；stdio 协议必须有真实流。"""
    for fd, name, mode in ((0, 'stdin', 'r'), (1, 'stdout', 'w'), (2, 'stderr', 'w')):
        if getattr(sys, name, None) is not None:
            continue
        try:
            setattr(sys, name, open(fd, mode, encoding='utf-8', errors='replace', closefd=False))
        except Exception:
            pass


def load_pyc(name, path):
    """从 pyc 文件加载模块"""
    if name in sys.modules:
        return sys.modules[name]
    if not os.path.exists(path):
        raise FileNotFoundError(f'pyc not found: {path}')
    loader = importlib.machinery.SourcelessFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    loader.exec_module(mod)
    return mod

def resolve_path(rel_path):
    """找 pyc 文件：先 _MEIPASS，再当前目录"""
    candidates = []
    if hasattr(sys, '_MEIPASS'):
        candidates.append(os.path.join(sys._MEIPASS, rel_path))
    candidates.append(rel_path)
    for c in candidates:
        if os.path.exists(c):
            return c
    return candidates[0]  # 返回最后一个（让它抛 FileNotFound）

# ---- 包容器 ----
# 注意：'app' / 'app.storage' / 'app.channel' 必须带 __path__，成为「真正的包」。
# 否则运行期动态导入会失败：应用市场 app_registry 的 tool_fn/runner_fn 是
# "app.apps.<id>.tool:call_tool" 这类字符串引用，解析时要用 importlib.import_module，
# 而容器模块没有 __path__ 时会报 `module 'app' has no attribute '__path__'`
# → 应用市场拿到空列表（前端显示「没有应用」）。
_PKG_DIRS = {
    'app': 'app',
    'app.storage': 'app/storage',
    'app.channel': 'app/channel',
    'storage': 'app/storage',
    'channel': 'app/channel',
}
for p in ['app', 'app.storage', 'app.channel', 'storage', 'channel',
          'storage.cloud_license', 'storage.retriever', 'storage.doc_parser',
          'storage.llm_provider', 'channel.wcf_client', 'channel.oa_client',
          'channel.wecom_client', 'channel.feishu_client', 'channel.dingtalk_client',
          'channel.message_pipeline', 'app_registry', 'mcp_manager', 'bridge',
          'logger', 'health']:
    if p in sys.modules:
        continue
    _m = type(sys)(p)
    _d = _PKG_DIRS.get(p)
    if _d:
        _m.__path__ = [resolve_path(_d)]
    sys.modules[p] = _m

# ---- 加载顺序 ----
LOAD_ORDER = [
    # 底层
    ('app.logger',         'app/__pycache__/logger.cpython-312.pyc'),
    ('app.health',         'app/__pycache__/health.cpython-312.pyc'),
    ('app.storage.crypto', 'app/storage/__pycache__/crypto.cpython-312.pyc'),
    ('app.storage.db',     'app/storage/__pycache__/db.cpython-312.pyc'),
    # storage 中层
    ('app.storage.machine',    'app/storage/__pycache__/machine.cpython-312.pyc'),
    ('app.storage.doc_parser', 'app/storage/__pycache__/doc_parser.cpython-312.pyc'),
    ('app.storage.dao',        'app/storage/__pycache__/dao.cpython-312.pyc'),
    ('app.storage.llm_provider', 'app/storage/__pycache__/llm_provider.cpython-312.pyc'),
    ('app.storage.cloud_license', 'app/storage/__pycache__/cloud_license.cpython-312.pyc'),
    ('app.storage.payment',    'app/storage/__pycache__/payment.cpython-312.pyc'),
    ('app.storage.license',    'app/storage/__pycache__/license.cpython-312.pyc'),
    ('app.storage.retriever',  'app/storage/__pycache__/retriever.cpython-312.pyc'),
    # channel 中层
    ('app.channel.base',              'app/channel/__pycache__/base.cpython-312.pyc'),
    ('app.channel.binding_router',    'app/channel/__pycache__/binding_router.cpython-312.pyc'),
    ('app.channel.wcf_client',        'app/channel/__pycache__/wcf_client.cpython-312.pyc'),
    ('app.channel.wecom_client',      'app/channel/__pycache__/wecom_client.cpython-312.pyc'),
    ('app.channel.feishu_client',     'app/channel/__pycache__/feishu_client.cpython-312.pyc'),
    ('app.channel.dingtalk_client',   'app/channel/__pycache__/dingtalk_client.cpython-312.pyc'),
    ('app.channel.risk_engine',       'app/channel/__pycache__/risk_engine.cpython-312.pyc'),
    ('app.channel.media_downloader',  'app/channel/__pycache__/media_downloader.cpython-312.pyc'),
    ('app.channel.oa_client',         'app/channel/__pycache__/oa_client.cpython-312.pyc'),
    ('app.channel.message_pipeline',  'app/channel/__pycache__/message_pipeline.cpython-312.pyc'),
    # 顶层
    ('app.app_registry',  'app/__pycache__/app_registry.cpython-312.pyc'),
    ('app.mcp_manager',   'app/__pycache__/mcp_manager.cpython-312.pyc'),
    ('app.mcp_server',    'app/__pycache__/mcp_server.cpython-312.pyc'),
    ('app.bridge',        'app/__pycache__/bridge.cpython-312.pyc'),
    ('app.main',          'app/__pycache__/main.cpython-312.pyc'),
]


def _load_app_modules():
    """扫描并加载 app/apps 下的应用市场模块（pyc-only，非致命）。

    应用市场模块（app.apps.<app_id>.tool / runner）由 bridge 用
    importlib.import_module 动态导入，PyInstaller 静态分析不到，
    所以打包产物里必须由 bootloader 主动装载。
    任一应用加载失败只告警、不中止主流程。
    """
    base = resolve_path('app/apps')
    if not base or not os.path.isdir(base):
        _log('[bootloader] app/apps 目录不存在，跳过应用市场加载')
        return
    # 注册包容器（带 __path__，供动态导入兜底）
    m = sys.modules.get('app.apps')
    if m is None or not hasattr(m, '__path__'):
        m = type(sys)('app.apps')
        m.__path__ = [base]
        sys.modules['app.apps'] = m
    loaded = 0
    for root, _dirs, files in os.walk(base):
        rel = os.path.relpath(root, base)
        pkg = 'app.apps' if rel == '.' else 'app.apps.' + rel.replace(os.sep, '.')
        if pkg != 'app.apps':
            pm = sys.modules.get(pkg)
            if pm is None or not hasattr(pm, '__path__'):
                pm = type(sys)(pkg)
                pm.__path__ = [root]
                sys.modules[pkg] = pm
        for fn in files:
            if not fn.endswith('.cpython-312.pyc'):
                continue
            mod = fn.split('.')[0]
            if mod == '__init__':
                continue
            name = pkg + '.' + mod
            try:
                load_pyc(name, os.path.join(root, fn))
                loaded += 1
            except Exception as e:
                _log(f'  WARN app module {name}: {e}')
    _log(f'[bootloader] app.apps 模块加载 {loaded} 个')


def load_all() -> int:
    """按 LOAD_ORDER 装载核心模块（含短别名与 storage 单例），再装载应用市场模块。

    返回核心模块装载失败数。可脱离 GUI 单独调用，便于打包前自检。
    """
    _log('[Avatar AI bootloader] loading...')
    errors = 0
    for name, rel in LOAD_ORDER:
        if _MCP_MODE and name in _MCP_SKIP:
            continue
        try:
            path = resolve_path(rel)
            mod = load_pyc(name, path)
            
            # 注册别名
            aliases = {
                'app.logger': 'logger',
                'app.health': 'health',
                'app.mcp_manager': 'mcp_manager',
                'app.app_registry': 'app_registry',
                'app.bridge': 'bridge',
            }
            if name in aliases:
                sys.modules[aliases[name]] = mod
            if name.startswith('app.storage.'):
                sys.modules['storage.' + name[12:]] = mod
            if name.startswith('app.channel.'):
                sys.modules['channel.' + name[12:]] = mod
            
            # dao 加载后手动创建 storage 单例
            if name == 'app.storage.dao':
                dao = mod
                storage_pkg = sys.modules['storage']
                if hasattr(dao, 'now_ts'):
                    setattr(storage_pkg, 'now_ts', dao.now_ts)
                class_to_instance = [
                    ('AgentsDAO', 'agents_dao'), ('KnowledgeBaseDAO', 'kb_dao'),
                    ('DocumentsDAO', 'docs_dao'), ('ChannelsDAO', 'channels_dao'),
                    ('LLMConfigDAO', 'llm_dao'), ('ActivationDAO', 'activation_dao'),
                    ('ActivationOrdersDAO', 'activation_orders_dao'),
                    ('ConversationDAO', 'conv_dao'), ('ChatMessageDAO', 'msg_dao'),
                    ('RiskConfigDAO', 'risk_config_dao'),
                    ('PeerProfileDAO', 'peer_profile_dao'),
                    ('AgentAppDAO', 'agent_app_dao'),
                    ('AppCredentialDAO', 'app_credential_dao'),
                ]
                for cls_name, inst_name in class_to_instance:
                    cls = getattr(dao, cls_name, None)
                    if cls is not None:
                        try:
                            setattr(storage_pkg, inst_name, cls())
                        except Exception:
                            pass
            
        except Exception as e:
            _log(f'  FAIL {name}: {e}')
            errors += 1
    
    # 加载应用市场模块（动态导入，PyInstaller 静态分析不到；非致命）
    _load_app_modules()
    return errors


def _run_mcp_stdio() -> None:
    """把当前进程变成 MCP stdio 服务（供 Trae / Wo Buddy 等 MCP 客户端连接）。

    打包版 MCP 客户端配置里的 command 就是 exe 自身：
        "Avatar AI.exe" -m app.mcp_server
    所以这里必须直接跑 MCP 服务，不能走 GUI 分支。
    """
    mod = sys.modules.get('app.mcp_server')
    if mod is None:
        mod = load_pyc('app.mcp_server', resolve_path('app/__pycache__/mcp_server.cpython-312.pyc'))
    server = getattr(mod, 'mcp', None)
    if server is None:
        _log('[bootloader] MCP server 实例不存在，无法启动')
        sys.exit(2)
    _log('[bootloader] 进入 MCP stdio 模式')
    try:
        server.run()  # 默认 transport="stdio"
    except Exception as e:
        _log(f'[bootloader] MCP server 异常退出: {e}')
        sys.exit(3)


def main():
    if _MCP_MODE:
        _ensure_stdio()

    errors = load_all()

    if errors > 0:
        _log(f'[bootloader] {errors} modules failed. Abort.')
        sys.exit(1)

    if _MCP_MODE:
        _run_mcp_stdio()
        return

    _log('[bootloader] all modules loaded, starting main()...')
    app_main = sys.modules['app.main']
    app_main.main()


if __name__ == '__main__':
    main()
