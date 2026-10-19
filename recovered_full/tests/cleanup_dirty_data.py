# -*- coding: utf-8 -*-
"""清理旧的脏数据，为重新上传文档做准备"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.storage.db import get_conn

db = get_conn()

# 查找刚才上传的那个文档
doc = db.execute("SELECT id, name FROM kb_document WHERE name LIKE '%智能家电%'").fetchone()
if doc:
    print(f"找到旧文档: id={doc['id']}, name={doc['name']}")
    # 删 kb_chunk
    db.execute("DELETE FROM kb_chunk WHERE doc_id = ?", (doc['id'],))
    # 删 kb_document
    db.execute("DELETE FROM kb_document WHERE id = ?", (doc['id'],))
    print("已删除旧的脏数据")
else:
    print("未找到旧文档，无需清理")

# 重置 test 知识库的计数
kb = db.execute("SELECT id FROM knowledge_base WHERE name = 'test'").fetchone()
if kb:
    db.execute(
        "UPDATE knowledge_base SET doc_count=0, chunk_count=0 WHERE id = ?",
        (kb['id'],)
    )
    print(f"已重置 test 知识库的计数 (id={kb['id']})")

db.commit()

# 验证
rows = db.execute("SELECT * FROM kb_document").fetchall()
print(f"\n当前 kb_document 表记录数: {len(rows)}")
if kb:
    kb_info = db.execute(
        "SELECT id, name, doc_count, chunk_count FROM knowledge_base WHERE id=?",
        (kb['id'],)
    ).fetchone()
    print(f"test 知识库状态: docs={kb_info['doc_count']}, chunks={kb_info['chunk_count']}")
