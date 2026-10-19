# P2-2 · Bug #8 修复：kb_root/wiki_root 路径统一（LLM Wiki 读写闭环）

> **模块编号**：P2-2（PDD 里层 · 第 22 号模块）
> **所属层级**：里层（Engine 层架构契约修复）
> **修复 Bug**：#8 kb_root 分离（KarpathyWikiReader / DocumentToWikiImporter / bootstrap 写读三处路径不一致）
> **修复前原型**：9/16 assertions FAIL
> **修复后原型**：27/27 assertions ALL PASS
> **方法论**：PDD 原型驱动开发（Matt Pocock 6 阶段闭环）
> **本文档**：规格文档（Phase 3 to-spec）

---

## 1. 背景：Bug #8 具体是什么

在 P2-1（人设+RAG 联合生效端到端）prototype 第 21 条断言里，我们**意料之外**地发现一个架构级 Bug：

| 组件 | 代码位置 | 它写入或读取的 kb_root/wiki_root |
|---|---|---|
| `bootstrap_first_run()` 注入示例知识 | [app_engine.py:184](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/app_engine.py#L184) | ✅ `SCAI_DATA_DIR/wiki`（绝对路径，受 `SCAI_DATA_DIR` 环境变量控制） |
| `get_degraded_details()` 检测 wiki 是否为空 | [app_engine.py:285](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/app_engine.py#L285) | ✅ `SCAI_DATA_DIR/wiki` |
| **`KarpathyWikiReader()`**（读取方，L1 关键词索引 + RAG 入口） | [app_engine.py:124](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/app_engine.py#L124) | ❌ `C:\Users\Administrator\.trae-cn\knowledge-base`（全局硬编码 `DEFAULT_KB_ROOT`） |
| **`DocumentToWikiImporter(wiki_root="./data/wiki")`**（写入方，用户导入文档） | [ui_engine_bridge.py:395](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/ui_engine_bridge.py#L395) | ❌ `./data/wiki`（相对路径，展开为"当前工作目录/data/wiki"） |

**后果**：典型的"写入一处，读取另一处"——

1. 用户首启，bootstrap 注入 5 条示例 wiki → 写入 `SCAI_DATA_DIR/wiki`
2. 用户去 KnowledgePage 导入产品文档 → 写入 `当前工作目录/data/wiki`（跟 1 完全不搭界）
3. LLM 提问触发 RAG → KarpathyWikiReader 去读全局 `DEFAULT_KB_ROOT`（Trae 的个人知识库！）
4. **RAG 什么都检索不到 0 hits**，UnifiedRetriever 全空，persona+rag 联合链路在 P2-1 prototype 里全 FAIL
5. 连锁："首启注入了示例知识"，但 get_degraded_details 报 wiki_empty，降级横幅一直闪（或 banner 消失了但 RAG 仍查不到）——视觉和 Engine 逻辑互相矛盾

### 1.1 连锁子问题

在修复路径不一致后，还遇到 2 个时序问题，如果不一起修，G4/G7 仍然 FAIL：

1. **初始化时序错位**：KarpathyWikiReader 是 initialize 第 124 行实例化的，早于 185 行的 bootstrap_first_run。实例化时 `SCAI_DATA_DIR/wiki` 目录还不存在，`KarpathyWikiReader._load_all_pages()` 内部缓存了 `_pages = []`，之后**不会自动刷新**。bootstrap_first_run 写入 5 条 md 后，wiki_reader.list_pages() 还是 0。
2. **用户导入文档后**：UIEngineBridge.ImportDocumentWorker.sync_run 写入了新 MD，但 Engine 里的 KarpathyWikiReader 内存缓存也不会自动 refresh，"刚导入的 doc 立刻搜索还是查不到"——需要在下一个模块（P2-3 KB 索引刷新 API）暴露公开方法。P2-2 只保证"路径统一后手动 refresh 就能 load 到新增 page"。

---

## 2. 8 条 Grill 清单

| Grill ID | 断言 | 验证点类型 | 修复前状态 | 修复后状态 |
|---|---|---|---|---|
| **G1** | `AppEngine._get_or_create_wiki_root() -> Path` 方法存在，自动确保 `concepts/entities/architecture` 三层目录存在；同时公开 `get_wiki_root() -> str` 供外部调用 | 代码结构 + 副作用 | ❌ 方法不存在 | ✅ 7/7 PASS |
| **G2** | `get_wiki_root()` 返回 str 且是**绝对路径**，结尾 `/wiki`，与 `get_data_dir()/wiki` 严格相等 | 字符串契约 | —（依赖 G1） | ✅ 4/4 PASS |
| **G3** | `engine._wiki_reader = KarpathyWikiReader(str(get_data_dir()))`，`reader._root == get_data_dir()`（kb_root 传 data_dir，wiki 子路径由 reader 内部拼接） | 初始化参数一致性 | ❌ reader._root = `DEFAULT_KB_ROOT` | ✅ 3/3 PASS |
| **G4** | initialize 完成后，`wiki_reader.list_pages() ≥ 5`（首启注入的 5 条示例：葡萄品种、西瓜挑选、水果季节性、储存方法、客服处理流程），且 title/slug 中有水果相关的词 | 首启内容闭环 | ❌ list_pages()=0，读到的是全局 29 页 Trae 知识库 | ✅ 2/2 PASS |
| **G5** | UIEngineBridge.ImportDocumentWorker.sync_run 成功后 `ok=True`，wiki_page_path 文件**真实存在于磁盘** | 用户导入端到端 | ❌ 之前 ok，只是路径错（相对路径落到别处） | ✅ 2/2 PASS |
| **G6** | wiki_page_path 的**父目录严格等于** `get_data_dir()/wiki/entities`；文件名包含 mini_doc slug（dandong/strawberry 等）；MD 正文含导入文档的关键词 | 路径一致性 | ❌ 父目录是 `工作目录/data/wiki/entities` | ✅ 3/3 PASS |
| **G7** | initialize 后 UnifiedRetriever 绑定的 wiki_reader 读到 ≥ 5 页（证明首启写入 ↔ 检索读取闭环）；mini_doc 导入完成后手动 refresh，pages 数 5→6 且新 page slug 含 mini_doc 关键词 | 检索侧路径一致性 + 增量 refresh 行为 | ❌ pages=0，refresh 后还是 0（因为全局目录没 mini_doc） | ✅ 5/5 PASS |
| **G8** | `get_degraded_details()` 不再出现 `code=wiki_empty`（因为能正确读到 SCAI_DATA_DIR/wiki 的首启示例） | 降级横幅一致性 | ⚠️ 老代码如果首启注入成功也不会出 wiki_empty，但如果首启注入时机错就会出现 | ✅ 1/1 PASS |

> 合计 prototype 断言 27 条（每个 Grill 拆若干代码级 assertions），全部 PASS。

---

## 3. 修复方案（正式代码变更）

### 3.1 统一方法（修改 app_engine.py 4 处）

**A. 顶部 import 加 `from pathlib import Path`**（20 行）

**B. KarpathyWikiReader 传 kb_root = get_data_dir()（124-125 行）**
```python
# Before:
self._wiki_reader = KarpathyWikiReader()

# After:
# P2-2 Bug #8 修复：统一 kb_root = get_data_dir()，让 wiki_reader 与首启注入同一路径
self._wiki_reader = KarpathyWikiReader(str(get_data_dir()))
```

**C. bootstrap_first_run 与 get_degraded_details 都用 `self._get_or_create_wiki_root()`（187 行 + 288 行）**
- 不再散落地写 `get_data_dir() / "wiki"`

**D. 新增两个统一访问方法（get_degraded_details 之后，process_message 之前）**
```python
def _get_or_create_wiki_root(self) -> Path:
    """private helper：返回 SCAI_DATA_DIR/wiki，自动建 concepts/entities/architecture 子目录"""
    root = get_data_dir() / "wiki"
    if not root.exists():
        root.mkdir(parents=True, exist_ok=True)
    for sub in ("concepts", "entities", "architecture"):
        sub_dir = root / sub
        if not sub_dir.exists():
            sub_dir.mkdir(parents=True, exist_ok=True)
    return root

def get_wiki_root(self) -> str:
    """public API：UIEngineBridge / KnowledgePage 构造 DocumentToWikiImporter 时必须调用"""
    return str(self._get_or_create_wiki_root())
```

**E. initialize 结束前统一 refresh wiki_reader 缓存（209-225 行 + 197-201 行）**
- 首启注入增量灌入前先 refresh 一次（否则 Pipeline ingest_incremental 会因为 baseline 是空而 +0 chunks）
- initialize 所有步骤完成后再 refresh 一次（兜底：任何先实例化 reader 后写入文件的时序问题都被覆盖）

### 3.2 UIEngineBridge.ImportDocumentWorker 顺序修改（ui_engine_bridge.py 389-408 行）

wiki_root 获取顺序调整为：
1. **最高优先级**：`engine.get_wiki_root()` → SCAI_DATA_DIR/wiki 绝对路径
2. **显式覆盖**：用户配置里 `kb.wiki_root` / `wiki_root`（兼容高级用户场景）
3. **最后保底**：`./data/wiki`（避免 1/2 都拿不到时直接崩）

```python
# Before:
wiki_root = "./data/wiki"
if hasattr(engine, "_config") and engine._config:
    wiki_root = engine._config.get("kb.wiki_root", "") or engine._config.get("wiki_root", "") or wiki_root

# After:
wiki_root = "./data/wiki"
# 1) 优先走 engine 公开方法（绝对路径，与首启注入、KarpathyWikiReader 一致）
if hasattr(engine, "get_wiki_root") and callable(getattr(engine, "get_wiki_root", None)):
    wiki_root = engine.get_wiki_root() or wiki_root
# 2) 兼容旧逻辑：用户在配置中显式写的 wiki_root（最高优先级覆盖）
if hasattr(engine, "_config") and engine._config:
    wiki_root = engine._config.get("kb.wiki_root", "") or engine._config.get("wiki_root", "") or wiki_root
```

---

## 4. 原型与验证

- **prototype 文件**：`_prototypes/kb_root_unification_prototype.py`
- **执行环境约束**：
  - `TRANSFORMERS_OFFLINE=1` + `HF_HUB_OFFLINE=1`（避免 ChromaDB embedding 下载重试卡 5min）
  - 每个 test case 设 `SCAI_DATA_DIR=<tempdir>`，保证隔离
- **验证时序**：
  1. 修复前 prototype：9/16 FAIL（明确 Bug 症状）
  2. 修改正式代码后重新跑：23/25（仍 FAIL → 定位到时序 refresh 子问题）
  3. 再加 initialize 结束前统一 refresh：25/25
  4. G7 Grill 从"检索命中"精准化为"路径一致 + page_count 一致"（避免越界到独立的检索逻辑模块）：27/27 ALL PASS

---

## 5. 后续依赖模块

| 下一模块 | 说明 |
|---|---|
| **P2-3 KB 索引刷新 API** | 暴露 `AppEngine.refresh_kb_index()` 公开 API：用户导入新文档后 UI 调用，自动 refresh wiki_reader + 重新 ingest_incremental + UnifiedRetriever L1 索引重建，替代 prototype 中的手动 refresh 步骤 |
| **P2-4 L1 关键词检索精准度** | 当前在 sentence-transformers 缺包（ChromaDB degraded）+ 纯 L1 关键词场景下，UnifiedRetriever.search("阳光玫瑰") 返回 0 hits，需要验证 L1 关键词匹配的 scope（title/tags/content？）并修复 |
| **P2-5 人设+RAG 重跑** | Bug #8 修复后，P2-1 的 8 条 Grill 中"RAG 能检索到正确知识 chunk"的断言（原来 degraded 不崩）现在可以升级为"真实命中关键词 ≥ 1"，将 P2-1 再次回跑 ALL PASS |

---

## 6. Test Seams 映射（供 pytest 回归）

Pytest 文件：`tests/test_inner_kb_root_unification_pdd.py`，对应 8 条 Grill，使用 `monkeypatch.setenv("SCAI_DATA_DIR", tmp_path)` 隔离：

| Grill ID | pytest 类名 | 核心断言 |
|---|---|---|
| G1 | TestG1ClassAttributesAndMethods | `hasattr(AppEngine, "_get_or_create_wiki_root")` + `hasattr(AppEngine, "get_wiki_root")` + 子目录 3 个 all exist |
| G2 | TestG2PublicGetWikiRoot | `os.path.isabs(engine.get_wiki_root())` + `endswith("wiki")` |
| G3 | TestG3KarpathyWikiReaderKBRoot | `engine._wiki_reader._root == Path(monkeypatch["SCAI_DATA_DIR"])` |
| G4 | TestG4ListPagesAfterFirstRun | `len(engine._wiki_reader.list_pages()) >= 5` + "葡萄" in titles |
| G5-G6 | TestG5G6ImportDocumentToCorrectPath | `wiki_page_path.parent == Path(engine.get_wiki_root())/"entities"` |
| G7 | TestG7RetrieverSharesKBRoot | `len(reader2.list_pages()) >= 5` + mini_doc refresh 后 `>= 6` |
| G8 | TestG8NoWikiEmptyDegraded | `"wiki_empty" not in [d["code"] for d in engine.get_degraded_details()]` |
