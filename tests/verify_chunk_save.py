# -*- coding: utf-8 -*-
"""模拟上传文档，验证切片是否真实存入 kb_chunk 表"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.storage.db import get_conn
from app.storage.doc_parser import parse_document
from app.storage import docs_dao

# 获取 test 知识库
db = get_conn()
kb = db.execute("SELECT id FROM knowledge_base WHERE name='test'").fetchone()
if not kb:
    print("错误：找不到 test 知识库")
    sys.exit(1)
kb_id = kb['id']

# 文档路径
file_path = r"C:\Users\Administrator\Desktop\智能家电客服知识手册.docx"
print(f"目标知识库: {kb_id}")
print(f"文档路径: {file_path}")

# 1. 创建文档记录
doc = docs_dao.create({
    "kb_id": kb_id,
    "name": "智能家电客服知识手册.docx",
    "file_path": file_path,
    "size_bytes": os.path.getsize(file_path),
    "chunk_count": 0,
    "status": "pending",
})
did = doc['id']
print(f"\nStep 1: 创建文档记录, doc_id={did}")

# 2. 解析文档
print("\nStep 2: 解析文档...")
parsed = parse_document(file_path)
if parsed.get("error"):
    print(f"解析失败: {parsed['error']}")
    sys.exit(1)
chunks = parsed["chunks"]
print(f"解析成功，共 {len(chunks)} 块切片")

# 3. 将切片存入数据库（核心验证）
print("\nStep 3: 存入切片到 kb_chunk 表...")
saved = docs_dao.save_chunks(did, kb_id, chunks)
print(f"存入完成，共保存 {saved} 块切片")

# 4. 更新文档状态
docs_dao.update_status(did, "ok", chunk_count=len(chunks))

# 5. 验证读取
print("\nStep 4: 从数据库读取切片验证...")
db_chunks = docs_dao.get_chunks_by_doc(did)
print(f"从数据库读取到 {len(db_chunks)} 块切片")
for i, c in enumerate(db_chunks):
    content_preview = c['content'][:80].replace('\n', ' ')
    print(f"  Chunk {i+1}: {content_preview}...")
    # 验证内容正确性
    has_valid = len(c['content']) > 50
    has_appliance = '家电' in c['content'] or 'E1' in c['content'] or '维修' in c['content']
    has_wrong = '核心概念' in c['content'] or '数据完整性' in c['content']
    print(f"    -> 有效内容: {has_valid}, 含关键词: {has_appliance}, 含错误内容: {has_wrong}")

# 6. 最终结论
if len(db_chunks) > 0 and any('E1' in c['content'] or '家电' in c['content'] for c in db_chunks):
    print("\n" + "=" * 60)
    print("✅ 验证通过！切片内容已真实落库，且内容正确！")
    print("=" * 60)
else:
    print("\n❌ 验证失败，切片内容为空或不正确")
