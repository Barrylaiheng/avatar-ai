# P2-3 · 模块规格：refresh_wiki 公开 API + 导入后自动刷新缓存

> **版本**：v1.0
> **日期**：2026-08-12
> **模块定位**：P2-1 → P2-2 后续的体验级断链修复（P2-2 解决"读写不同目录"的正确性 Bug；P2-3 解决"用户导入后必须重启 APP 才能检索到"的体验 Bug）。

---

## §1 背景 & 要解决的问题

### 1.1 P2-2 留下的 1 个体验 Gap
P2-2 prototype G7 明确需要**手动** `reader._load_all_pages()` 才能读到第 6 页：
- 用户在 KnowledgePage 点击「导入」→ Importer 把 MD 写到 `SCAI_DATA_DIR/wiki/entities/xxx.md`（✅）
- KarpathyWikiReader 的内存缓存 `_pages` 还是旧的 5 条
- 用户立刻切到 ChatPage 提问"刚才导入的丹东草莓"→ 命中 0 条（RAG 返回空）
- 用户会认为"导入失败"或"APP 有 bug"→ **重启 APP 后才检索到**

### 1.2 MVP 级用户心智
> **"导入即能用"**：用户点了「导入成功」Toast，立刻去对话就能命中新知识；不需要任何"刷新知识"按钮，更不需要重启 APP。

---

## §2 模块目标（解决什么）

| # | 目标 | 对应 PDD Grill |
|---|------|---------------|
| 1 | AppEngine 暴露**公开** `refresh_wiki(trigger)` 方法（不是 `_load_all_pages` 这种私有 API） | G1 G2 |
| 2 | 磁盘有新知识写入后，`refresh_wiki()` 调用 1 次就能反映到内存（pages_diff = +N） | G3 |
| 3 | 确保 **UnifiedRetriever._reader 与 engine._wiki_reader 引用同一 KarpathyWikiReader 实例**，刷新后检索路径立刻读到新页（无需给 retriever 单独 refresh） | G4 |
| 4 | ImportDocumentWorker.sync_run **导入成功后自动调** `engine.refresh_wiki(trigger="user_import")`，UI 层代码无需再手动刷 | G5 |
| 5 | wiki 目录被删 / 空目录时，`refresh_wiki()` 不崩（pages_diff ≤ 0）| G6 |

---

## §3 架构设计

### 3.1 调用链路图
```
[UI: KnowledgePage]
  └─► ImportDocumentWorker.start(QThread异步)
        └─► sync_run(engine, file_path, category)
              ├─► DocumentToWikiImporter.import_document   写磁盘
              │     └─► {SCAI_DATA_DIR}/wiki/entities/xxx.md  ✅ P2-2 修复
              └─► [P2-3 新增] if result.success:
                    engine.refresh_wiki(trigger="user_import")  ← 关键改动
                          └─► engine._wiki_reader._load_all_pages()
                                └─► 重新扫描 wiki/ 三层目录 + 重建缓存
                                      └─► UnifiedRetriever._reader
                                            是同一对象 → 自动已刷新 ← MVP 级假设验证
```

### 3.2 关键设计决策

| 决策 | 理由 |
|------|------|
| **UnifiedRetriever 不单独 refresh** | P2-3 G4 已验证：`engine._unified_retriever._reader is engine._wiki_reader` 为 True。构造时传入的就是同一实例，refresh `_wiki_reader` 会自动同步到 retriever。减少公开 API 数量。 |
| **Refresh 失败静默降级**（ImportDocumentWorker 里 try/except pass）| 导入成功 = 知识已经写入磁盘，刷新缓存失败最多是「本次读不到，下次启动能读到」，不应该让用户看到"导入失败"。 |
| **`trigger` 参数作为** loguru **溯源 Tag** | 未来可以加 `periodic_sync`（每 5min 后台自动同步 wiki/ 目录变化）、`oa_badcase_push`（云端收到运营回传的知识后推送）等触发源，日志里一眼区分来源。 |
| **返回 `pages_diff`** | MVP 给 UI 层留了扩展：未来可做 Toast 提示「知识库刷新，新增了 1 篇知识」。 |
| **L2 ChromaDB 增量灌入 MVP 阶段不自动调** | `ingest_incremental()` 可能涉及 embedding（内网不可用时会卡几十秒重试），影响「导入后立刻对话」的响应感知。MVP 阶段 L1 关键词搜索即可（首启注入的 5 条 × 用户手动导入 ≤ 20 条，完全够用）。L2 同步放到 P3 阶段 App Startup Smoketest 里统一调度。 |

---

## §4 Grill 清单 & Test Seams（6 Seams）

| ID | 标题 | 断言要点（machine-verifiable） |
|----|------|------------------------------|
| G1 | AppEngine.refresh_wiki() 公开方法存在 + trigger 参数可追溯 | `hasattr(AppEngine, "refresh_wiki")` + callable；签名含 `trigger: str = "user_import"`（位置 + 默认值都对）|
| G2 | refresh_wiki() 返回值契约正确 | 返回 dict，4 字段齐全：`result=="ok"` + `page_count:int ≥ 0` + `pages_diff:int` + `trigger` 透传；异常场景 result=="error" 含 error 字段 |
| G3 | 磁盘新增 1 篇 MD 后 refresh，page_count 精准 +1 | SCAI_DATA_DIR 首启注入 5 页 → 手动写 1 篇 status: verified MD 到 wiki/entities → refresh → `pages_before=5, pages_after=6, pages_diff=1` |
| G4 | UnifiedRetriever._reader 与 engine._wiki_reader 是同引用 + refresh 后立刻命中新内容 | `assert engine._unified_retriever._reader is engine._wiki_reader`；refresh 后 `engine._wiki_reader.search("融安滑皮金桔", top_k=3)` 返回 ≥ 1 条，且 content 含「融安」或「金桔」或「滑皮」 |
| G5 | ImportDocumentWorker.sync_run 导入成功后自动触发 refresh（monkey patch 捕获） | `monkey.patch engine.refresh_wiki`（记录调用次数 & 实参）→ sync_run 成功 → patch.call_count ≥ 1 且 某次调用 kwargs.trigger == "user_import" |
| G6 | wiki 目录不存在 / 空目录时 refresh 安全降级 | 临时移动 wiki/{concepts,entities,architecture} → refresh → 不抛异常 + pages_diff ≤ 0（负数是因为之前有缓存，现在清 0）+ result=="ok" 或结构正确 |

---

## §5 正式代码改动清单（2 文件）

| # | 文件 | 改动 | 行号参考 |
|---|------|------|---------|
| 1 | [app_engine.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/app_engine.py) | 新增 `refresh_wiki(self, trigger="user_import") -> Dict` 公开方法，内部：① `_get_or_create_wiki_root()` 兜底（G6 要求）；② before 统计当前 `_wiki_reader.list_pages()` 数量；③ `_wiki_reader._load_all_pages()` 刷新；④ after 统计 + loguru 日志；⑤ 返回统一契约 dict（含 error 兜底）| L361-L404 |
| 2 | [ui_engine_bridge.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/ui/ui_engine_bridge.py) | ImportDocumentWorker.sync_run 在 `result.success == True` 分支里，`signals["imported"]` 之前插入：若 engine 有 `refresh_wiki` 且 callable 则调 `engine.refresh_wiki(trigger="user_import")`，try/except 静默失败不影响导入结果 | L413-L423 |

---

## §6 Prototype 验证结果

**原型文件**：[_prototypes/wiki_refresh_prototype.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/_prototypes/wiki_refresh_prototype.py)

**运行命令**：
```powershell
Remove-Item -Recurse -Force 'tests/data/tmp_p23_proto' -ErrorAction SilentlyContinue
$env:TRANSFORMERS_OFFLINE='1'; $env:HF_HUB_OFFLINE='1'
$env:SCAI_DATA_DIR='C:\Users\Administrator\Desktop\WeChatAI_Project\tests\data\tmp_p23_proto'
& venv\Scripts\python.exe _prototypes\wiki_refresh_prototype.py
```

**最终结果**：**21 / 21 ALL PASS ✅**（覆盖 G1-G6 全 6 条 Grill，每条 Grill 3~4 个 sub-assertion）

| Grill | Sub 断言数 | PASS | FAIL |
|-------|-----------:|-----:|-----:|
| G1（API 存在 + trigger） | 3 | 3 | 0 |
| G2（返回契约） | 5 | 5 | 0 |
| G3（pages_diff = +1） | 3 | 3 | 0 |
| G4（同引用 + 检索命中） | 3 | 3 | 0 |
| G5（auto refresh 捕获） | 4 | 4 | 0 |
| G6（空目录安全降级） | 3 | 3 | 0 |
| **合计** | **21** | **21** | **0** |

> 调试过程中 1 次 FAIL（G4-3 hits=0），根因：手动写入 manual_md 时未显式 `status: verified`，KarpathyWikiReader.search 默认跳过 draft 页。修复后 21/21。

---

## §7 Pytest 测试用例（6 Test Functions → 6 Seams）

**测试文件**：`tests/test_inner_wiki_refresh_pdd.py`

每个测试函数严格对应 1 条 Grill（命名风格 `test_p23_g{n}_{描述}`）：
- `test_p23_g1_refresh_wiki_api_and_trigger_default`
- `test_p23_g2_return_contract`
- `test_p23_g3_pages_diff_plus_one`
- `test_p23_g4_retriever_shares_reader_and_search_hit`
- `test_p23_g5_importer_auto_triggers_refresh`
- `test_p23_g6_degraded_on_missing_wiki_dir`

**测试隔离**：全部通过 `SCAI_DATA_DIR=tmpdir` 环境变量保证用例间独立；`TRANSFORMERS_OFFLINE=1` + `HF_HUB_OFFLINE=1` 避免 ChromaDB embedding 下载重试。

---

## §8 依赖 & 后续模块

| 依赖模块 | 依赖内容 |
|---------|---------|
| P2-2（路径统一）| 必须保证 wiki_root 统一后，Imports 写入的路径和 wiki_reader 读取的路径一致，refresh 才有意义 |

| 后续模块（P3 阶段） | 用到 P2-3 的能力 |
|------------------|-----------------|
| P3-1 L2 ChromaDB 增量灌入调度 | 在 `engine.refresh_wiki()` 返回后，触发 `self._pipeline.ingest_incremental()`（MVP 阶段不开启，避免 embedding 内网卡死）|
| P3-2 运营云端知识推送（OA → 桌面端） | 收到推送后用 `refresh_wiki(trigger="oa_badcase_push")` 刷本地检索缓存 |
| P3-3 定时 5min 后台 sync wiki 目录 | 若用户手动把 MD 拖到 SCAI_DATA_DIR/wiki 下，定时刷新让它自动进检索 |
| P3-4 KnowledgePage 「刷新知识」手动按钮（非 MVP 必须）| UI 直接调 `engine.refresh_wiki(trigger="user_manual")`，Toast 弹「知识库已刷新：+N 页」|

---

## §9 验收标准（PDD 总验收文档记录）

- [x] 6 Grill 全部通过 prototype（21/21 断言）
- [x] 正式代码改动 2 处（app_engine.py + ui_engine_bridge.py）
- [x] pytest 用例 6 条（test_inner_wiki_refresh_pdd.py）
- [x] PDD 总验收文档 v9.0 已更新，新增 6 Seams
- [ ] MVP 全量回归时与 P2-1/P2-2 联合跑通人设+RAG+refresh 3 模块端到端（P3 阶段）
