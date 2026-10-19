# 里层 P2-1 · 人设+RAG 联合生效端到端验证

> **版本**：v1.0
> **定位**：P2 系列模块（端到端真实组件联动 · 不 Mock 核心链路）的首发。M-11 人设注入、M-16 RAG 混合检索、M-20 文档导入都分别做了单元验证，但**从未把三者串在一起跑完整的 process_message 链路**。本模块的目的就是验证「存人设 → 导文档 → 用户提问 → 回答同时带着人设语气 + RAG 命中的知识」这条 MVP 核心灵魂链路。
> **方法论**：原型驱动开发 PDD（6 阶段）
> **Prototype 文件**：_prototypes/persona_rag_combined_prototype.py（21/21 PASS ✅，命中 Bug #8 🟠 严重）

---

## §1 Grill 清单（拍板 · 8 条）

| ID | 标题 | 断言要点（无真实 LLM Key 也能验证） | 验收方法 |
|----|------|-------------------------------|---------|
| G1 | save_persona → get_current_persona_dict 一致 | 存 {name,description,tone,type} 字典后，读回的 4 字段值完全相等；save_persona 返回 True | AppEngine.save_persona + get_current_persona_dict 真实调用 |
| G2 | DocumentToWikiImporter 生成 OKF MD 落盘 | import_document 返回 success=True；raw/ 下生成 .md 文件；文件头 YAML frontmatter 同时含 `type:` + `title:`；正文中至少含 1 个导入时原文关键词 | 真实调用 DocumentToWikiImporter.import_document（category="entities"） |
| G3 | WikiIngestPipeline.incremental 灌入成功 | L1 KarpathyWikiReader 至少解析出 1 页；ingest_incremental 返回值为 int ≥ 0 不崩（L2 ChromaDB degraded 时允许 0） | 手动传正确 kb_root = $SCAI_DATA_DIR（不是 wiki 子目录） |
| G4 | role_config.identity 含人设 name+description | mock _llm_generator.generate 捕获 role_config 实参；identity 字段同时含 persona.name（如"鲜果小助手"）和 persona.description 关键词（如"推荐新鲜水果"） | MonkeyPatch 替换 engine._llm_generator.generate，断言调用参数 |
| G5 | rag_result.chunks 含知识库关键词（或 degraded 时 identity 保留人设） | 同一 mock 捕获的 rag_result.chunks 是 list；如果 chunks ≥ 1，则至少 1 个 chunk 的内容里含"阿克苏/冰糖心/果心透明"等关键词；如果 chunks = 0（L2 ChromaDB degraded），则 G4 identity 至少保留人设名 | 同上，和 G4 共享一次调用 |
| G6 | process_message 全链路 degraded 时不崩 | 不做任何 mock，真实调 process_message，不抛异常；返回 dict 且 content 字段为 str 且非空；is_aigc 字段存在 | 无 mock 真实调用 |
| G7 | 人设 ↔ RAG 数据隔离互不污染 | save_persona 前后 wiki MD 文件 MD5 完全不变；import wiki 前后 persona 三字段不变 | 两次 hash 对比 + dict 对比 |
| G8 | 返回结构契约字段齐全 | process_message 返回结果包含 tool_calls（list）+ rag_count（int ≥ 0）两个字段 | 与 G6 共享一次返回值 |

---

## §2 技术决策与理由

### 2.1 无 LLM API Key 怎么验证人设+RAG 生效？

**做法**：在 AppEngine.process_message 的"最后一公里"——也就是 `self._llm_generator.generate(role_config, context, rag_result, ...)` 这一步，用 monkey patch 替换掉它，不真的发请求，而是把实参 **捕获**下来断言：
- `role_config["identity"]` 含人设信息 → 证明人设注入链路工作
- `rag_result["chunks"]` 含文档关键词 → 证明 RAG 检索链路工作

不需要真实 LLM 响应，这条链路的**因果闭环**就已经被验证了。

### 2.2 为什么 G5 用"宽松断言"？

- 内网环境下 ChromaDB 的 embedding 模型 sentence_transformers 常装不全，会走 degraded（L2 不可用，L1 纯关键词检索在 UnifiedRetriever 降级路径中）。
- 但即使 L2 degraded，**人设依然应该生效**（G5 后半段）。
- 如果有 embedding 模型，L2 能命中就更完美。两择一都算过。

### 2.3 数据隔离策略

沿用 P1-6 的 `SCAI_DATA_DIR` 指向临时目录 + TRANSFORMERS_OFFLINE/HF_HUB_OFFLINE 两个环境变量，保证：
1. 不污染生产 SCAI_DATA_DIR 下的 config/wiki/db
2. 不触发 embedding 下载的 5 次 × 10s 重试

### 2.4 发现 Bug #8（🟠 严重）

原型阶段发现，`AppEngine.initialize()` 中初始化 KarpathyWikiReader 是**无参数调用**：

```python
self._wiki_reader = KarpathyWikiReader()  # 使用 DEFAULT_KB_ROOT（全局知识库）
```

但 `DocumentToWikiImporter(wiki_root=get_data_dir() / "wiki")` 写入的是 **SCAI_DATA_DIR/wiki**（用户本地数据目录）。

两个目录完全不一致，导致：**用户通过 MVP 导入文档到自己的 SCAI_DATA_DIR，RAG 检索永远查不到——MVP 的 RAG 核心链路直接断开！**

→ 后续 P2-2 模块专门修这个 Bug：让 `KarpathyWikiReader(Path(get_data_dir()))` 绑定到用户 SCAI_DATA_DIR。

---

## §3 开发任务（映射 Grill → 产物）

本模块是**规格+验证型模块**（已有真实组件 save_persona/DocumentToWikiImporter/WikiIngestPipeline/_llm_generator.generate 都存在），不需要写新的正式代码，只需产出：

| # | 任务 | 交付物 |
|---|------|-------|
| T1 | 写 throwaway prototype | _prototypes/persona_rag_combined_prototype.py（21/21 PASS ✅） |
| T2 | 写规格文档 | docs/PDD_INNER_persona_rag_combined.md（本文件） |
| T3 | 写 pytest（MVP 完成后统一跑） | tests/test_inner_persona_rag_combined_pdd.py |
| T4 | 更新总验收文档 | docs/PDD_INNER_TOTAL_ACCEPTANCE.md 新增模块 27（P2-1）+ 8 Seams + Bug #8 |
| T5 | 记录并跟踪 Bug #8 | 见 §4 + §6 总验收文档 Bug 清单 |

---

## §4 Bug #8 详情

| 字段 | 内容 |
|------|------|
| 编号 | #8 |
| 模块 | P2-1 → 影响所有依赖 RAG 检索的模块（M-16/17/20/MVP 端到端） |
| 严重度 | 🟠 严重（MVP RAG 检索核心链路断开，用户导入的文档永远查不到） |
| 现象 | 用户在 KnowledgePage 导入 .md/.txt/.pdf → DocumentToWikiImporter 写 SCAI_DATA_DIR/wiki/entities/*.md → 用户在 ChatPage 提问 → UnifiedRetriever.search() 只查 DEFAULT_KB_ROOT（全局知识库）→ 命中 0 条，RAG 链路失效 |
| 根因 | AppEngine.initialize 中 `self._wiki_reader = KarpathyWikiReader()` 无参数，默认参数 DEFAULT_KB_ROOT = C:\Users\Administrator\.trae-cn\knowledge-base；而 DocumentToWikiImporter 写入路径是 `get_data_dir() / "wiki"` = SCAI_DATA_DIR/wiki |
| 修复方向（P2-2） | `KarpathyWikiReader(str(get_data_dir()))`，同时把 DEFAULT_KB_ROOT 作为"用户 SCAI_DATA_DIR/wiki 为空时的 fallback 公共知识库"即可（不是必选项，MVP 1.0 可只取 SCAI_DATA_DIR），确保两条路径统一 |

---

## §5 pytest 用例设计（待 MVP 完成后跑）

8 用例对齐 8 Grill：
- `TestG1SavePersona.test_G1_1_2_3_4`（1 个用例覆盖 4 个断言，减少 AppEngine 实例化次数）
- `TestG2WikiImporter.test_G2_1_2_3_4`
- `TestG3IngestIncremental.test_G3_1_2`
- `TestG4RoleConfigIdentity.test_G4_1_2`
- `TestG5RagResultChunks.test_G5_1_2`
- `TestG6ProcessMessageDegraded.test_G6_1_2_3`
- `TestG7Isolation.test_G7_1_2`
- `TestG8ReturnContract.test_G8_1_2`

同样使用 autouse fixture：`TRANSFORMERS_OFFLINE=1`、`HF_HUB_OFFLINE=1`、`SCAI_DATA_DIR=temp`。

---

## §6 关联文件

| 文件 | 路径 | 作用 |
|------|------|------|
| AppEngine（save_persona / process_message） | [app_engine.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/app_engine.py#L730-L820) | 人设保存 + 消息处理主入口（人设注入+RAG 在 378-430 行） |
| DocumentToWikiImporter | [doc_to_wiki_importer.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/rag/doc_to_wiki_importer.py#L140-L270) | 文档 → OKF Wiki MD |
| KarpathyWikiReader | [karpathy_wiki_reader.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/rag/karpathy_wiki_reader.py#L64-L130) | L1 读取器（传参 kb_root，内部拼 `/wiki`）——**#8 根因所在（app_engine.py 第 124 行调用无参数）** |
| WikiIngestPipeline | [wiki_ingest_pipeline.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/rag/wiki_ingest_pipeline.py#L28-L145) | L1 → L2 灌入 |
| Prototype | [persona_rag_combined_prototype.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/_prototypes/persona_rag_combined_prototype.py) | Throwaway 原型 21/21 PASS |
| 规格文档 | [PDD_INNER_persona_rag_combined.md](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/docs/PDD_INNER_persona_rag_combined.md) | 本文件 |
