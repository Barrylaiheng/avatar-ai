"""RAG 闭环 smoke test：建库 → 加文档 → 检索 → 删除 → 重启恢复索引。

测试目标：
- 验证 Bridge._handle_add_kb_document 真正调用 doc_parser 解析 + 切片
- 验证 Bridge._handle_search_kb L1+L2 融合检索
- 验证 Bridge._handle_delete_kb_document 同步删 UnifiedRetriever
- 验证 _rebuild_index_from_db 模拟重启后从 SQLite 恢复索引

环境隔离：通过 SCAI_APP_DIR 环境变量指向临时目录，不污染真实 APPDATA。
依赖：PyQt6（BridgeServer 继承 QObject，需先建 QApplication）。
"""
from __future__ import annotations
import os
import sys
import tempfile
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent  # app/
sys.path.insert(0, str(APP_ROOT))

os.environ.setdefault("SCAI_APP_DIR", str(Path(tempfile.mkdtemp(prefix="scai_rag_"))))
TEST_DIR = Path(os.environ["SCAI_APP_DIR"])
print(f"[TEST] 测试目录: {TEST_DIR}")

from PyQt6.QtWidgets import QApplication
from storage import kb_dao, docs_dao, reset_db_for_tests
from storage.db import get_db_path
from bridge import BridgeServer


def step(msg):
    print(f"\n=== {msg} ===", flush=True)


def assert_eq(actual, expected, hint=""):
    if actual != expected:
        raise AssertionError(f"断言失败 {hint}: actual={actual!r}, expected={expected!r}")
    print(f"  OK {hint}")


# ---------- 初始化 ----------
step("Step0: 初始化环境 + QApplication + BridgeServer")
# 隔离 DB（用 reset_db_for_tests 清空旧表）
reset_db_for_tests()
print(f"  DB 路径: {get_db_path()}")

app = QApplication.instance() or QApplication(sys.argv)
bridge = BridgeServer()
print("  BridgeServer 实例化完成")
print(f"  初始 retriever stats: {bridge._retriever.stats()}")

# ---------- Step1: 准备测试文档 ----------
step("Step1: 准备测试文档")
doc_dir = TEST_DIR / "docs"
doc_dir.mkdir(exist_ok=True)

doc1_path = doc_dir / "产品介绍.txt"
doc1_path.write_text(
    "阿维达AI 是一款桌面端 AI 数字分身工具，帮助用户创建一个懂自己的 AI 分身。"
    "核心能力包括智能体管理、知识库管理、渠道对接、LLM 调用。"
    "商业模式为一次买断，扫码激活 ¥199，绑定机器码后离线永久可用。",
    encoding="utf-8",
)

doc2_path = doc_dir / "微信FAQ.txt"
doc2_path.write_text(
    "微信渠道对接的常见问题：好友列表拉取失败、消息回调超时、AIGC 标识未附。"
    "解决方法：检查 WCF 注入服务是否启动、确认微信客户端版本兼容。",
    encoding="utf-8",
)
print(f"  文档1: {doc1_path} ({doc1_path.stat().st_size} bytes)")
print(f"  文档2: {doc2_path} ({doc2_path.stat().st_size} bytes)")

# ---------- Step2: 建库 + 加文档 ----------
step("Step2: 建库 + 加文档")
kb1 = kb_dao.create({"name": "产品知识库", "description": "阿维达AI 产品相关"})
kb2 = kb_dao.create({"name": "FAQ 知识库", "description": "渠道对接常见问题"})
kid1 = kb1["id"]
kid2 = kb2["id"]
print(f"  建库: kb1={kid1} kb2={kid2}")

# 加文档1 到 kb1
r1 = bridge._handle_add_kb_document({
    "kb_id": kid1,
    "file_path": str(doc1_path),
})
print(f"  加文档1: added={r1['added']} chunk_count={r1.get('chunk_count')}")
assert_eq(r1["added"], True, "文档1 加入成功")
assert_eq(r1["doc"]["status"], "ok", "文档1 status=ok")
assert r1.get("chunk_count", 0) > 0, "文档1 切片数 > 0"

# 加文档2 到 kb2
r2 = bridge._handle_add_kb_document({
    "kb_id": kid2,
    "file_path": str(doc2_path),
})
print(f"  加文档2: added={r2['added']} chunk_count={r2.get('chunk_count')}")
assert_eq(r2["added"], True, "文档2 加入成功")
assert_eq(r2["doc"]["status"], "ok", "文档2 status=ok")

print(f"  当前 retriever stats: {bridge._retriever.stats()}")

# ---------- Step3: 检索 ----------
step("Step3: RAG 检索")
# 全局检索：查询「AI 分身」应命中 kb1
r = bridge._handle_search_kb({"query": "AI 分身", "top_k": 3})
print(f"  查询「AI 分身」→ {len(r['results'])} 条结果")
assert len(r["results"]) > 0, "查询「AI 分身」应有结果"
top = r["results"][0]
print(f"  top1: score={top['score']} layer={top['source_layer']} "
      f"kb={top['kb_id']} doc={top['doc_id']}")
assert_eq(top["kb_id"], kid1, "top1 应属于 kb1")

# 全局检索：查询「微信 WCF」应命中 kb2
r = bridge._handle_search_kb({"query": "微信 WCF", "top_k": 3})
print(f"  查询「微信 WCF」→ {len(r['results'])} 条结果")
assert len(r["results"]) > 0, "查询「微信 WCF」应有结果"
top = r["results"][0]
print(f"  top1: score={top['score']} kb={top['kb_id']}")
assert_eq(top["kb_id"], kid2, "top1 应属于 kb2")

# kb_id 隔离：在 kb1 检索「微信」不应命中（doc1 里有「微信」字样吗？）
r = bridge._handle_search_kb({"query": "微信", "top_k": 3, "kb_ids": [kid1]})
print(f"  在 kb1 检索「微信」→ {len(r['results'])} 条结果")
# doc1 里有「微信」吗？没有，但 doc1 里有「微信、公众号」（不，是「渠道对接」）
# 实际 doc1 文本：「渠道对接」无「微信」，所以应 0 条
assert_eq(len(r["results"]), 0, "kb1 内检索「微信」应为 0 条（doc1 无微信内容）")

# 在 kb2 检索「微信」应命中
r = bridge._handle_search_kb({"query": "微信", "top_k": 3, "kb_ids": [kid2]})
print(f"  在 kb2 检索「微信」→ {len(r['results'])} 条结果")
assert len(r["results"]) > 0, "kb2 内检索「微信」应有结果"

# ---------- Step4: 切片预览 ----------
step("Step4: 文档切片预览")
chunks_r = bridge._handle_get_kb_document_chunks({
    "doc_id": r1["doc"]["id"],
    "preview": 80,
})
print(f"  文档1 切片数: {chunks_r['chunk_count']}")
assert chunks_r["chunk_count"] > 0, "切片数 > 0"
assert len(chunks_r["chunks"]) == chunks_r["chunk_count"], "切片预览数一致"
preview0 = chunks_r["chunks"][0]["preview"]
print(f"  第1片预览: {preview0[:60]}...")

# ---------- Step5: 删除文档 + 验证索引同步 ----------
step("Step5: 删除文档1 + 验证索引同步")
doc1_id = r1["doc"]["id"]
del_r = bridge._handle_delete_kb_document({"id": doc1_id})
print(f"  删除: deleted={del_r['deleted']} chunks_removed={del_r['chunks_removed']}")
assert_eq(del_r["deleted"], True, "docs_dao 删除成功")
assert del_r["chunks_removed"] > 0, "UnifiedRetriever 同步删除 chunks"

# 删除后检索「AI 分身」应 0 条（doc1 已删，doc2 无此内容）
r = bridge._handle_search_kb({"query": "AI 分身", "top_k": 3})
print(f"  删除后查询「AI 分身」→ {len(r['results'])} 条结果（应为 0）")
assert_eq(len(r["results"]), 0, "删除后「AI 分身」无结果")

# 删除后检索「微信」应仍能命中 kb2
r = bridge._handle_search_kb({"query": "微信", "top_k": 3})
print(f"  删除后查询「微信」→ {len(r['results'])} 条结果（应仍命中 kb2）")
assert len(r["results"]) > 0, "删除 doc1 后 doc2 仍可命中"

# ---------- Step6: 模拟重启 → 从 SQLite 恢复索引 ----------
step("Step6: 模拟重启 → 从 SQLite 恢复索引")
# 用新 BridgeServer 实例模拟重启
bridge2 = BridgeServer()
print(f"  新 Bridge 初始 stats: {bridge2._retriever.stats()}")
assert_eq(bridge2._retriever.stats()["keyword"]["chunk_count"], 0, "新实例索引为空")

# 调用 _rebuild_index_from_db（_handle_ready 内部会调，这里直接调）
rebuild = bridge2._rebuild_index_from_db()
print(f"  恢复结果: {rebuild}")
assert_eq(rebuild["rebuilt"], True, "索引恢复成功")
assert_eq(rebuild["docs_added"], 1, "恢复 1 个文档（doc2 还在）")
assert rebuild["chunks_added"] > 0, "恢复 chunks > 0"

# 恢复后检索「微信」应仍命中
r = bridge2._handle_search_kb({"query": "微信", "top_k": 3})
print(f"  恢复后查询「微信」→ {len(r['results'])} 条结果")
assert len(r["results"]) > 0, "重启恢复后「微信」仍可命中"

# 重复调用 _rebuild_index_from_db 应跳过（_index_ready 标记）
rebuild2 = bridge2._rebuild_index_from_db()
assert_eq(rebuild2["rebuilt"], False, "重复调用跳过")

print("\n[TEST] RAG 闭环 smoke test 全部通过 ✅")
