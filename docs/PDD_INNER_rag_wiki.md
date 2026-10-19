# 里层 PDD 模块 6 · 神经 L3 · RAG → LLM Wiki 衔接

> **方法论**：原型驱动开发 PDD（Matt Pocock 6 阶段闭环）
> **阶段**：Phase 1 grill-with-docs → Phase 2 prototype → Phase 3 to-spec → Phase 4 to-tickets → Phase 5 implement+tdd → Phase 6 code-review+回归
> **架构位置**：五层架构 L3 神经（知识检索）→ 接入 L4 ContextAssemblerV2
> **关联模块**：[ContextAssemblerV2](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/engine/context_assembler_v2.py) 的 `MockRagEngine` 替换

---

## §0 背景

V1.1 业务对齐拍板：MVP 的 RAG 部分应往 **LLM Wiki 方向衔接**，不是推翻，而是格式对齐主流标准（Karpathy LLM Wiki + Obsidian 兼容），让用户通过其他工具（Workbody / Obsidian / Trae）搭好的知识库可以直接导入。

## §1 现状探查

### 1.1 现有 RAG 代码

| 文件 | 类 | 状态 | 备注 |
|------|----|------|------|
| [rag_engine.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/rag/rag_engine.py) | `RAGEngine` | 完整 | 基于 ChromaDB + 规则注入 + 融合，依赖 `IntentType` 枚举，接口 `retrieve(kb_id, query, intent, top_k) -> RAGResult` |
| [chromadb_manager.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/rag/chromadb_manager.py) | `ChromaDBManager` | 完整 | bge-small-zh-v1.5 中文 Embedding，嵌入式模式 |
| [wiki_manager.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/rag/wiki_manager.py) | `LLMWikiManager` | **不兼容** | 期望 `entries/KB-XX-XXX.md` 扁平结构 |
| [hybrid_retriever.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/rag/hybrid_retriever.py) | `HybridRetriever` | 简化版 | 依赖 `LLMWikiManager`，向量计算用 Jaccard 简化版 |
| [context_assembler_v2.py](file:///C:/Users/Administrator/Desktop/WeChatAI_Project/src/aibridge/engine/context_assembler_v2.py#L98-L118) | `MockRagEngine` | 待替换 | 接口 `search(query, top_k=3) -> List[RagHit]` |

### 1.2 实际 KB 结构（Karpathy 标准）

路径：`C:\Users\Administrator\.trae-cn\knowledge-base\`

```
knowledge-base/
├── schema.md            ← 宪法（结构规则）
├── purpose.md           ← 知识库目标
├── raw/                 ← 不可变源
│   └── YYYY-MM-DD-xxx.md
└── wiki/
    ├── index.md         ← 全局目录
    ├── log.md           ← 操作日志
    ├── concepts/        ← 概念页（8 个）
    ├── entities/        ← 实体页（3 个）
    └── architecture/    ← 架构页（7 个）
```

页面格式：
```markdown
---
type: concept | entity | architecture | source-summary | system
title: 页面标题
sources:
  - raw/2026-08-08-xxx.md
tags: [tag1, tag2]
created: 2026-08-08
updated: 2026-08-08
status: verified | unverified | draft
---

# 页面标题

正文。用 [[page-name]] 创建双向链接。
```

### 1.3 核心矛盾

`LLMWikiManager` 期望 `entries/KB-XX-XXX.md` 扁平结构 + `entry_id` 字段，与实际 KB 的 `wiki/{type}/{page-name}.md` 三层结构 + 文件名 ID **完全不兼容**。

## §2 Grill 清单（Phase 1 拍板）

| # | 问题 | 决策 | 理由 |
|---|------|------|------|
| G1 | 适配器接口契约？ | **保持 `search(query, top_k=3) -> List[RagHit]` 不变** | ContextAssemblerV2 无感知切换，最小侵入 |
| G2 | KB 路径从哪读？ | **从 config_manager 读取 `knowledge_base.path`，默认 `C:\Users\Administrator\.trae-cn\knowledge-base\`** | 支持后续多 KB 扩展 |
| G3 | 现有 `LLMWikiManager` 不兼容怎么办？ | **重写 `KarpathyWikiReader`，保留旧代码不动** | 重写比适配简单；旧代码是 PRD v3.0 遗产 |
| G4 | 检索策略？ | **混合检索：阶段 1 关键词过滤 → 阶段 2 ChromaDB 向量重排（可选）** | MVP 优先关键词，确保跑通；ChromaDB 可用时增强 |
| G5 | 索引何时构建？ | **启动时全量扫描 wiki/ 目录，内存缓存** | 中等规模 < 100 文件够用 |
| G6 | 多渠道支持？ | **MVP 不区分，统一一个 KB** | 后续按 kb_id 扩展 |
| G7 | 容错策略？ | **KB 空 → 返回空 list；ChromaDB 不可用 → 降级关键词；无超时限制** | KB 小，通常 < 200ms |
| G8 | `RagHit.source` 字段填什么？ | **页面文件名（不含 .md），如 `llm-wiki-pattern`** | 符合 Obsidian 双向链接习惯 |
| G9 | `RagHit.content` 字段填什么？ | **title + 正文前 500 字符** | 避免 token 爆炸；后续可扩展分段 |
| G10 | 如何接入 ContextAssemblerV2？ | **通过 `set_rag_engine()` 注入，启动时由 Application 装配** | 解耦，便于测试 |

## §3 接口规格

### 3.1 KarpathyWikiReader

```python
class KarpathyWikiReader:
    """Karpathy LLM Wiki 标准读取器

    直接读取 wiki/{concepts,entities,architecture}/*.md 三层结构。
    不依赖 entry_id，用文件名作为唯一标识。
    """

    def __init__(
        self,
        kb_root: str | Path,
        chromadb_manager: Optional[ChromaDBManager] = None,
    ) -> None: ...

    def search(
        self,
        query: str,
        top_k: int = 3,
    ) -> List[RagHit]:
        """
        混合检索：
        1. 关键词匹配（title + tags + 正文）→ 候选集
        2. ChromaDB 向量重排（如果可用）
        3. Top-K 截取
        """
```

### 3.2 RagHit 数据契约（不变）

```python
@dataclass
class RagHit:
    content: str    # title + 正文前 500 字符
    source: str     # 文件名（不含 .md），如 "llm-wiki-pattern"
    score: float    # 0.0 ~ 1.0
```

### 3.3 与 ContextAssemblerV2 集成

```python
# Application 启动装配
wiki_reader = KarpathyWikiReader(
    kb_root=config.get("knowledge_base.path", DEFAULT_KB_ROOT),
    chromadb_manager=chromadb_manager,  # 可选
)
context_assembler.set_rag_engine(wiki_reader)
```

## §4 Test Seams（Phase 3 待定义）

| ID | 标题 | 断言要点 |
|----|------|---------|
| RW-01 | KB 空目录 → 返回空 list | `search() == []` |
| RW-02 | 单页命中（title 匹配） | `len(results)==1`, `source==文件名` |
| RW-03 | 多页命中 → Top-K 截取 | `len(results) <= top_k` |
| RW-04 | 关键词在 tags 命中 | `score > 0` |
| RW-05 | 关键词在正文命中 | `score > 0` |
| RW-06 | 无命中 → 返回空 list | `search() == []` |
| RW-07 | source 是文件名不含 .md | `not source.endswith(".md")` |
| RW-08 | content 含 title | `title in content` |
| RW-09 | ChromaDB 不可用 → 降级关键词 | 仍能返回结果 |
| RW-10 | 跳过 draft 状态页面 | draft 页面不参与检索 |
| RW-11 | 跳过 raw/ 目录 | 只读 wiki/ 下页面 |
| RW-12 | 三层目录都扫 | concepts + entities + architecture 全覆盖 |
| RW-13 | 双向链接 `[[xxx]]` 不破坏检索 | 正常解析 |
| RW-14 | 接入 ContextAssemblerV2 | `assemble_prompt` 的 system 含"检索到的知识" |
| RW-15 | 真实 KB 检索（端到端） | 查"PDD" → 命中 `prototype-driven-development` |

## §5 开发任务（Phase 4 to-tickets）

| # | 任务 | 文件 | 优先级 |
|---|------|------|--------|
| T1 | 实现 `KarpathyWikiReader` | `src/aibridge/rag/karpathy_wiki_reader.py` | P0 |
| T2 | 写 15 条 Test Seams | `tests/test_inner_rag_wiki_pdd.py` | P0 |
| T3 | 端到端接入 ContextAssemblerV2 | 修改 `engine/context_assembler_v2.py` | P0 |
| T4 | Application 启动装配 | `src/aibridge/app.py` 或 main 入口 | P1 |
| T5 | 配置项 `knowledge_base.path` | `config/defaults.yaml` | P1 |
| T6 | 文档凝固到 `PDD_INNER_TOTAL_ACCEPTANCE.md` | `docs/PDD_INNER_TOTAL_ACCEPTANCE.md` | P2 |

## §6 验收标准

- [ ] 15 条 Test Seams 全绿
- [ ] 现有 48 + 8 = 56 Seams 全量回归通过
- [ ] 真实 KB 端到端：查"PDD" → 命中 `prototype-driven-development`
- [ ] ContextAssemblerV2.assemble_prompt 的 system message 含"【检索到的知识】"
- [ ] ChromaDB 不可用时降级正常
