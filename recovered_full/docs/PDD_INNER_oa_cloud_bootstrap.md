# SCAI PDD 模块 17 · OA Cloud Bootstrap（公众号云端自启动装配）规格文档

> 对应源码目录：`src/aibridge/oa_service/bootstrap.py` / `src/aibridge/oa_service/__main__.py`
> 测试用例：`tests/test_inner_oa_cloud_bootstrap_pdd.py`
> Grill 原始文档：`raw/2026-08-12-scai-m17-oa-cloud-bootstrap-grill.md`

---

## 1. 业务背景

用户战略："我可以不做微信，都一定要做公众号。"
公众号渠道是销售案例核心，必须 24/7 独立部署（云端自闭环），不依赖本地 AppEngine（本地跑微信渠道），不能加载 PyQt6 桌面 UI 依赖，部署极简（一条命令 + 一份 config）。

## 2. 阻塞断点（根因分析）

| 断点 | 根因 | 影响 |
|------|------|------|
| B1: 无自启动装配 | `OACloudService.__init__(mp=None)` 时 self.mp = None，需外部手动注入 7 个组件 | 非技术用户无法直接启动 |
| B2: 无独立知识库目录 | 云端无自己的 KB 目录，KarpathyWikiReader 默认指向本地 Windows 硬编码路径，Linux 不存在 | RAG 无法工作 |
| B3: LLM/人设/RAG 未对接 | ContextAssemblerV2 未 set_rag_reader 注入 UnifiedRetriever，未 set_persona 注入人设 | 云端回复"裸 LLM" |
| B4: 启动入口不完整 | `python -m aibridge.oa_service.app` 启动后 mp=None，异步处理被跳过，用户只收到占位语 | 永远 Bad Case |

## 3. Grill 清单（12 条，PDD 验收标准）

| Grill | 断言（机器可验证） |
|-------|-------------------|
| G1 | `OACloudService.auto_bootstrap(config)` 不传 mp 也能返回非 None 的完整装配实例，OACloudService.mp 不为 None |
| G2 | 启动时自动创建 OKF 合规结构：`kb_root/{concepts,entities,architecture}/` + `index.md` + `log.md`，index.md 含 `type: index` frontmatter |
| G3 | KarpathyWikiReader + WikiIngestPipeline + UnifiedRetriever 被自动创建并注入 ctx，`ctx.assemble(query)` 返回 rag_count ≥ 1（知识库非空时） |
| G4 | 人设自动加载：优先读 `config.persona_file`，缺省时写入 DEFAULT_OA_PERSONA 到 persona.json，`ctx.get_persona()["name"] == "影分身 AI"` |
| G5 | LLM 无 Key 时不崩：process 返回 `action == "fallback_reply"` + `bad_case_written == True`，BadCase 队列已入队 1 条 |
| G6 | 任意组件装配失败不崩（try-except 包裹），返回 `(mp, degraded=True, degraded_details=[...])` 元组 |
| G7 | ChromaDB / RAG 组件不可用时降级为纯 L1 检索，assemble 不抛异常，rag_count ≥ 0（纯关键词也可返回 0） |
| G8 | 云端运行不加载 PyQt6 / QtCore / QtGui 等 UI 依赖，sys.modules 中无 `PyQt*` 前缀 |
| G9 | `python -m aibridge.oa_service --config config.json` 能直接启动 Flask（模块 `__main__.py` 存在 + 解析参数 + 调用 auto_bootstrap + serve） |
| G10 | 全链路：签名验证 GET/200 → POST 返回占位 XML → 异步 mp.process → WeChatClient.send_text 被调用 1 次（mock 断言） |
| G11 | config.example.json 包含：`kb_root` / `persona_file` / `llm_provider` / `llm_api_key` / `llm_base_url` / `llm_model` 6 个新字段 |
| G12 | deploy/oa_service/README_DEPLOY.md 包含 `python -m aibridge.oa_service --config config.json` 一键启动命令 + 配置说明 |

## 4. 技术决策

### TD-1 · 云端独立知识库目录
- 路径：`config.kb_root`，默认值：`./data/oa_service/wiki/`（相对部署进程 cwd）
- 不共享本地 `data/wiki/`，避免 Git 部署时文件所有权冲突
- 理由：云端是 Linux，本地是 Windows；知识库需独立 Git 管理

### TD-2 · auto_bootstrap() 为静态工厂
```python
@staticmethod
def auto_bootstrap(config) -> Tuple["OACloudService", bool, List[str]]:
    """返回 (service_instance, degraded, degraded_details)"""
```
- 理由：不修改 `__init__` 签名，保持现有调用方兼容（外部注入 mock 的测试仍可工作）

### TD-3 · 云端精简版 ContextAssembler（不依赖 Qt / DatabaseManager）
- 新增类：`OALiteContextAssembler`，放在 bootstrap.py 内部
- 方法：`assemble(user_input, kb_enabled=True) -> {"messages": [...], "rag_count": int}`
- 方法：`set_rag_reader(reader)` / `set_persona(dict)` / `get_persona()`
- 理由：ContextAssemblerV2 依赖 DatabaseManager / SQLite 太重，云端只需 RAG + 人设

### TD-4 · `__main__.py` 作为入口
- 新增：`src/aibridge/oa_service/__main__.py`
- 功能：argparse 解析 `--config` → load_config → `OACloudService.auto_bootstrap` → `Flask app.run()` / `gunicorn` 友好
- 理由：符合 Python 包规范，部署时 `python -m aibridge.oa_service --config config.json` 非常简洁

## 5. 模块职责 / 代码布局

```
aibridge/oa_service/
  ├── bootstrap.py          # NEW: auto_bootstrap + OALiteContextAssembler + OKF 初始化
  ├── __main__.py           # NEW: CLI 入口 (python -m aibridge.oa_service --config)
  ├── app.py                # MODIFY: 新增 OACloudService.auto_bootstrap 静态方法
  ├── config_loader.py      # 保留：加载配置
  ├── pipeline.py           # 保留：MessageProcessorLite（接收 OALiteContextAssembler）
  ├── cs_tracker.py         # 保留：WeChatClient
  ├── token_manager.py      # 保留：AccessTokenManager
  ├── crypto_utils.py       # 保留：签名/加解密
  ├── message_parser.py     # 保留：parse_xml_to_msg
  └── monitor.py            # 保留：BadCase 队列

deploy/oa_service/
  ├── config.example.json   # MODIFY: 新增 6 个配置字段
  └── README_DEPLOY.md      # MODIFY: 新增 auto_bootstrap 启动说明 + 自检步骤
```

## 6. 规格映射到断言（Test Seams）

| Grill | pytest 用例类 | 断言核心 |
|-------|--------------|----------|
| G1 | TestG1AutoBootstrap | `svc.mp is not None` |
| G2 | TestG2OKFDirs | 5 个路径存在 + index frontmatter |
| G3 | TestG3RAGInjected | `assemble(...).rag_count >= 1`（含测试种子页） |
| G4 | TestG4Persona | `ctx.get_persona()["name"] == "影分身 AI"` |
| G5 | TestG5LLMFallback | `process(...).action == "fallback_reply"` |
| G6 | TestG6DegradedMode | 人为抛异常 → `degraded is True, len(details) >= 1` |
| G7 | TestG7RAGDegradedPureL1 | `assemble(...)` 不抛 |
| G8 | TestG8NoPyQtDep | `not any(k.startswith("PyQt") for k in sys.modules)` |
| G9 | TestG9MainEntry | `import aibridge.oa_service.__main__` 成功，argparse 不崩 |
| G10 | TestG10FullChain | mock cs_client.send_text 断言 called_once |
| G11 | TestG11ConfigNewFields | 6 字段在 `config.example.json` 中存在 |
| G12 | TestG12ReadmeDeploy | 启动命令字符串在 README_DEPLOY.md 中出现 |

## 7. 边界 / 不做什么

- ❌ 不做微信渠道（WCF/群聊/主人同步）
- ❌ 不加载 PyQt6
- ❌ 不做菜单管理 / 素材管理
- ❌ 不做 Chunk 语义分割 / 重排
- ❌ 不做人设/知识库的在线管理后台（MVP 手动改 JSON/Markdown）

## 8. 错误处理策略

| 场景 | 处理 |
|------|------|
| KB root 目录无写权限 | degraded=True，跳过 OKF 骨架文件创建，RAG 降级为纯 Mock |
| persona.json 是非法 JSON | 使用 DEFAULT_OA_PERSONA，不写回原文件，记录 degraded_details |
| LLM 初始化失败（如 requests 未安装） | 使用 "AI 服务配置中" 兜底语，不崩 |
| ChromaDB 不可用 | 降级为纯 L1（KarpathyWikiReader），M-16 同款策略 |
| Flask 端口被占用 | `__main__` 捕获 OSError，打印友好错误后退出 |
