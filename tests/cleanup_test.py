# -*- coding: utf-8 -*-
"""清理测试数据"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.storage import docs_dao
from app.storage.db import get_conn

db = get_conn()

# 查找并删除测试文档
cursor = db.execute("SELECT id, name FROM kb_document")
for row in cursor.fetchall():
    if "智能家电" in row['name']:
        docs_dao.delete(row['id'])
        print(f"已删除文档: id={row['id']}, name={row['name']}")

db.commit()

# 验证清空
doc_count = db.execute("SELECT COUNT(*) as c FROM kb_document").fetchone()['c']
chunk_count = db.execute("SELECT COUNT(*) as c FROM kb_chunk").fetchone()['c']
print(f"\n清理完成:")
print(f"  kb_document 表记录数: {doc_count}")
print(f"  kb_chunk 表记录数: {chunk_count}")
