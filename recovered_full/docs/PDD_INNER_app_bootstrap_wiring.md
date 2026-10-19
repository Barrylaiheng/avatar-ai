# SCAI · PDD 内层 · 模块 10：App Bootstrap Wiring

> **模块编号**：Module 10  
> **目标**：AppEngine 启动装配 + 真实组件注入，让 UI ↔ Engine 数据流不再跑 Mock  
> **验收基准**：15 条 Test Seams 100% 通过（原型验证 + pytest 双固化）  
> **前序依赖**：模块 7（UI ↔ Engine 契约）、模块 9（UIEngineBridge 桥接层）

---

## 1. Grill 清单（业务验收标准，大白话版）

| Grill ID | 验收问题（= 这个模块必须解决的问题） |
|----------|-----------------------------------|
| **G1** | 真实 `AppEngine.initialize()` 能跑通不抛异常（哪怕没 API Key，13 个核心组件都能实例化完成） |
| **G2** | `process_message()` 返回 **标准 8 字段**（content/is_aigc/tool_calls/rag_count/persona_name/success/error_message/session_id），缺任何一个字段 UI 层 ChatPage 直接崩溃 |
| **G3** | `persona_name` 字段能正确返回，默认"影分身 AI"，自定义人设后返回新名字 |
| **G4** | `AppEngine.save_persona()` 方法存在、可调用、返回 bool，能把人设字典写入配置 |
| **G5** | `get_channel_messages("wechat")` 返回真实 dict 列表结构（含 id/sender/content/time），新数据库空列表也属正常 |
| **G6** | `save_settings → get_settings → test_llm_connection` 完整流程跑通：写入 → 读回 → 连通性测试 |
| **G7** | 无 API Key 时，`process_message` 走 fallback 路径，返回"请检查 API Key 配置"友好提示，绝不抛异常 |
| **G8** | `safety_check` 字段在所有返回路径都存在（passed/blocked），blocked 时必须附带 `safety_reason` |
| **G9** | `kb_enabled=False` 时，`process_message` 严格跳过 RAG 检索，`rag_count=0` |
| **G10** | `kb_enabled=True` + SEARCH/GUIDE 意图时，RAG 检索绝不崩溃（哪怕 ChromaDB 为空、Embedding 模型加载失败降级） |
| **G11** | `SendMessageWorker.sync_run` 用真实 AppEngine 调用成功，`ok=True`，结果含标准 8 字段 |
| **G12** | `SavePersonaWorker.sync_run` 用真实 AppEngine 调用成功，`saved=True` |
| **G13** | `SaveSettingsWorker` + `TestLLMConnectionWorker` 用真实 AppEngine 完整流程不抛异常 |
| **G14** | `GetChannelMessagesWorker.sync_run("wechat")` 返回 list，即使空列表也算通过 |
| **G15** | `main.py` 启动流程静态串联完整：导入 → 实例化 → `initialize()` → `MainWindow(engine)` → `engine_status.setText` → 失败兜底 |

---

## 2. Test Seams 定义（机器可验证断言）

### Seam G1 · initialize 真实跑通
```python
assert engine.initialize() is True
assert engine.is_initialized() is True
# 13 个组件全部非 None
for k, v in components.items():
    assert v is not None, f"组件 {k} 缺失"
```

### Seam G2 · 标准 8 字段
```python
result = engine.process_message("你好")
assert isinstance(result, dict)
for f in ["content","is_aigc","tool_calls","rag_count",
          "persona_name","success","error_message","session_id"]:
    assert f in result
# 类型校验
assert isinstance(result["content"], str)
assert isinstance(result["is_aigc"], bool)
assert isinstance(result["rag_count"], int)
...
```

### Seam G3 · persona_name
```python
r = engine.process_message("你好")
assert isinstance(r["persona_name"], str)
assert len(r["persona_name"]) > 0
assert r["persona_name"] == "影分身 AI"  # 默认值
```

### Seam G4 · save_persona
```python
assert hasattr(engine, "save_persona")
assert callable(engine.save_persona)
result = engine.save_persona({"name": "测试"})
assert isinstance(result, bool)
assert result is True
# 配置读回
assert engine._config.get("persona.name") == "测试"
```

### Seam G5 · 渠道消息结构
```python
msgs = engine.get_channel_messages("wechat", limit=10)
assert isinstance(msgs, list)
# 有消息时每条必含 id/sender/content/time
if msgs:
    assert "id" in msgs[0]
    assert "sender" in msgs[0]
    assert "content" in msgs[0]
    assert "time" in msgs[0]
```

### Seam G6 · 设置流程
```python
assert engine.save_settings({"aigc_prefix": "[T]"}) is True
read = engine.get_settings()
assert read["aigc_prefix"] == "[T]"
test = engine.test_llm_connection()
assert "success" in test
assert "message" in test
```

### Seam G7 · fallback 友好返回
```python
r = engine.process_message("解释 SCAI")  # 无 API Key
assert isinstance(r["content"], str)
assert len(r["content"]) > 0
# 命中 fallback 特征
assert (r["success"] is False or len(r["error_message"]) > 0
        or any(kw in r["content"] for kw in ["API Key", "配置", "无法连接", "检查"]))
```

### Seam G8 · safety_check
```python
r = engine.process_message("你好")
assert "safety_check" in r
assert r["safety_check"] in ("passed", "blocked")
if r["safety_check"] == "blocked":
    assert "safety_reason" in r
    assert len(r["safety_reason"]) > 0
```

### Seam G9 · KB 关闭跳过 RAG
```python
engine.set_kb_enabled(False)
r = engine.process_message("SCAI 架构是什么？")
assert r["rag_count"] == 0
```

### Seam G10 · KB 开启 RAG 不崩
```python
engine.set_kb_enabled(True)
r = engine.process_message("什么是知识蒸馏？")
assert isinstance(r["rag_count"], int)
assert r["rag_count"] >= 0
```

### Seam G11~G14 · 4 个 Worker 真实调用
```python
# G11: SendMessageWorker
ok, result, sig = SendMessageWorker.sync_run(engine, "你好")
assert ok is True and "success" in sig

# G12: SavePersonaWorker
ok, result, sig = SavePersonaWorker.sync_run(engine, {"name": "W"})
assert ok is True and "saved" in sig

# G13: Settings Workers
ok1, _, sig1 = SaveSettingsWorker.sync_run(engine, {})
assert ok1 and "saved" in sig1
ok2, _, sig2 = TestLLMConnectionWorker.sync_run(engine)
assert ok2 and "connected" in sig2

# G14: GetChannelMessagesWorker
ok, msgs, sig = GetChannelMessagesWorker.sync_run(engine, "wechat")
assert ok is True and isinstance(msgs, list) and "loaded" in sig
```

### Seam G15 · main.py 启动流程（静态检查）
读取 `main.py` 源码，检查以下字符串存在：
- `from aibridge.app_engine import AppEngine`
- `from aibridge.ui.main_window import MainWindow`
- `AppEngine()` / `engine.initialize()`
- `MainWindow(engine)`（传参，不传则 Engine 还是 Mock）
- `engine_status.setText`（UI 启动后更新状态）
- `QMessageBox.critical` / `sys.exit(1)`（初始化失败兜底）

---

## 3. 开发任务清单

| # | 任务 | 交付物 | 关联 Seams |
|---|------|--------|-----------|
| T1 | 探查 AppEngine 装配现状 | 现状报告 + 缺口清单 | 全部 |
| T2 | `process_message()` 补全返回字段 | 所有 return 路径补齐 8 字段 + safety_check | G2,G3,G7,G8,G9,G10 |
| T3 | 新增 `AppEngine.save_persona()` 方法 | 写入 persona.* 配置 + save_config | G4, G12 |
| T4 | 提前初始化 `rag_results = []`，避免 SEARCH/GUIDE 之外变量未定义 | process_message 代码修复 | G9, G10 |
| T5 | persona_name 从 ConfigManager 读取（兼容 persona.name 和 persona_name） | process_message 内获取逻辑 | G3 |
| T6 | 原型验证脚本 | `_prototypes/app_bootstrap_wiring_prototype.py` | G1~G15 |
| T7 | 正式 pytest 测试 | `tests/test_inner_app_bootstrap_pdd.py` | G1~G15 |
| T8 | 规格文档 | `docs/PDD_INNER_app_bootstrap_wiring.md`（本文件） | — |

---

## 4. 修复清单（具体变更点）

### 4.1 `app_engine.py::process_message` 5 处 return 全部补字段

**之前**（合规拦截返回示例，缺 5 字段）：
```python
return {
    "content": "您的消息不符合安全规范",
    "is_aigc": False,
    "safety_check": "blocked",
    "safety_reason": compliance_result.reason,
    "tool_calls": [],
}
```

**之后**（补全 rag_count/persona_name/success/error_message/session_id）：
```python
return {
    "content": "您的消息不符合安全规范",
    "is_aigc": False,
    "safety_check": "blocked",
    "safety_reason": compliance_result.reason,
    "tool_calls": [],
    "rag_count": 0,
    "persona_name": persona_name,
    "success": False,
    "error_message": compliance_result.reason,
    "session_id": session_id,
}
```

**需要修复的 return 路径**（共 5 处）：
1. 合规拦截 return（line ~159）
2. 业务安全拦截 return（line ~175）
3. LLM 调用异常 fallback return（line ~226）
4. 正常成功 return（line ~258）
5. 最外层 except 兜底 return（line ~278）

### 4.2 新增 `AppEngine.save_persona(persona_dict) -> bool`

```python
def save_persona(self, persona_dict: Dict[str, Any]) -> bool:
    with self._lock:
        if not self._initialized: return False
        try:
            persona_name = str(persona_dict.get("name", "影分身 AI")).strip()
            self._config.set("persona.name", persona_name)
            self._config.set("persona_name", persona_name)  # 向后兼容
            self._config.set("persona.description", str(persona_dict.get("description", "")))
            self._config.set("persona.tone", str(persona_dict.get("tone", "专业、友好")))
            self._config.set("persona.type", str(persona_dict.get("type", "通用客服")))
            # avatar/background_story 等附加字段自动扩展
            for extra in ["avatar", "background_story", "language_style", "keywords"]:
                if extra in persona_dict:
                    self._config.set(f"persona.{extra}", str(persona_dict[extra]))
            self._config.save_config()
            # 可选：通知 ContextAssembler.reload_persona()（如果存在）
            if hasattr(self._context_assembler, "reload_persona"):
                self._context_assembler.reload_persona()
            return True
        except Exception as e:
            logger.error(f"保存人设失败: {e}")
            return False
```

### 4.3 `rag_results` 提前初始化

```python
# 之前：只在 if kb_enabled 分支内定义，分支外会 NameError
rag_results = self._rag_engine.retrieve(...)

# 之后：提前初始化为空 list
rag_results: list = []
if self._kb_enabled and (...):
    rag_results = self._rag_engine.retrieve(user_input, limit=3) or []
```

---

## 5. 验证结果

### 原型验证（`_prototypes/app_bootstrap_wiring_prototype.py`）
```
总计: 15 条 | ✅ 通过: 15 | ❌ 失败: 0 | 通过率: 100%
```

| Seam | 结果 | 备注 |
|------|------|------|
| G1 initialize 13 组件 | ✅ | — |
| G2 标准 8 字段 | ✅ | — |
| G3 persona_name | ✅ | 默认"影分身 AI" |
| G4 save_persona | ✅ | 新增方法 |
| G5 渠道消息 | ✅ | 空列表（新 DB） |
| G6 设置流程 | ✅ | test_llm_connection 返回 success=False（无 API Key，正确） |
| G7 fallback 友好 | ✅ | content="当前无法连接到 LLM 服务..." |
| G8 safety_check | ✅ | safety_check=passed |
| G9 KB 关闭 rag_count=0 | ✅ | — |
| G10 KB 开启 RAG 不崩 | ✅ | Embedding 降级也不崩 |
| G11 SendMessageWorker | ✅ | — |
| G12 SavePersonaWorker | ✅ | saved=True |
| G13 Settings Workers | ✅ | — |
| G14 ChannelMessagesWorker | ✅ | 0 条消息 |
| G15 main.py 静态检查 | ✅ | — |

### 正式 pytest（`tests/test_inner_app_bootstrap_pdd.py`）
运行命令：
```bash
cd c:\Users\Administrator\Desktop\WeChatAI_Project
python -m pytest tests/test_inner_app_bootstrap_pdd.py -v
```

---

## 6. 对 UI 层的影响（零破坏性改进）

所有修复都在 Engine 契约层内完成，**UI 层不需要改一行代码**即可受益：

| UI 页面 | 之前行为 | 现在行为 |
|---------|---------|---------|
| **ChatPage** | process_message 返回缺字段，Bridge 里 `raw.get("persona_name", "")` 取到空串，AI 气泡**人设名显示为空** | persona_name 默认"影分身 AI"，AI 气泡人设名正常显示 |
| **ChatPage** | success 字段缺失，Bridge 里 `bool(raw.get("success", True))` 误判为成功，fallback 场景**错误状态显示为成功** | success=False，Bridge 正确渲染失败气泡 |
| **ChatPage** | rag_count 字段缺失，`int(raw.get("rag_count", 0))` 虽有兜底但非契约保证 | rag_count 强契约，KB 开关语义准确 |
| **PersonaEditor** | 点击保存 → SavePersonaWorker 调 `engine.save_persona()` → **AttributeError: has no attribute 'save_persona'** → toast 保存失败 | save_persona=True，配置持久化，toast"人设已保存" |
| **全部页面** | safety_check 字段缺失，UI 无法区分"AI 正常回复"vs"内容被安全壳拦截" | safety_check=passed/blocked，UI 后续可加安全拦截视觉提示 |

---

## 7. 下一步建议

1. **端到端 UI 手动验证**：用户启动 `python src/aibridge/main.py`，在 ChatPage 发消息验证：
   - AI 气泡人设名显示"影分身 AI"（不是空）
   - 无 API Key 场景显示"请检查 API Key 配置"fallback 文案
   - PersonaEditor 保存人设不报错，下次重启人设名持久化
2. **接入真实 API Key 验证 LLM 连通性**：测试 G6/G7 在有 Key 时 success=True + 真实 LLM 返回
3. **推进模块 11（PersonaEditor → ContextAssembler 人设注入）**：目前 save_persona 只写配置，process_message 里 role_config 的 name 虽然用了 persona_name，但 ContextAssembler 内人设还需 reload_persona() 真正生效
