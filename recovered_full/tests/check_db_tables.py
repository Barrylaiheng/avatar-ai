# -*- coding: utf-8 -*-
"""检查数据库表结构和切片存储位置"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.storage.db import get_conn

db = get_conn()

# 查所有表
cursor = db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
print('===== 数据库里所有表 =====')
for row in cursor:
    print(f'  - {row["name"]}')

# 查 kb_chunk 表
print('\n===== 检查 kb_chunk 表 =====')
try:
    cursor = db.execute('PRAGMA table_info(kb_chunk)')
    print('kb_chunk 表结构:')
    for row in cursor:
        print(f'  {row[1]:20s} {row[2]}')
    # 查数据
    rows = db.execute('SELECT * FROM kb_chunk LIMIT 5').fetchall()
    print(f'kb_chunk 表记录数: {len(rows)}')
    for r in rows:
        print(f'  chunk: id={r.get("id")}, doc_id={r.get("doc_id")}, content={str(r.get("content",""))[:100]}')
except Exception as e:
    print(f'kb_chunk 表不存在或查询失败: {e}')

# 查 chunks 相关的全局搜索
print('\n===== 搜索所有表结构中含 chunk 的字段 =====')
tables = ['knowledge_base', 'kb_document', 'kb_chunk', 'kb_vector']
for t in tables:
    try:
        cursor = db.execute(f'PRAGMA table_info({t})')
        for col in cursor:
            if 'chunk' in col[1].lower():
                print(f'  [{t}].{col[1]} ({col[2]})')
    except Exception:
        pass
