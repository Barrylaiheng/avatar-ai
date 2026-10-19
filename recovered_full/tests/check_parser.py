# -*- coding: utf-8 -*-
"""直接解析测试，验证 doc_parser 是否正确读取文档内容"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.storage.doc_parser import parse_document, chunk_text

file_path = r"C:\Users\Administrator\Desktop\智能家电客服知识手册.docx"
print("=" * 60)
print("【Step 1】直接解析桌面文档，看原始文本")
print("=" * 60)
result = parse_document(file_path)
text = result.get("text", "")
print(f"解析返回 text 长度: {len(text)} 字符")
print(f"前 500 字符预览:")
print(text[:500])
print("...")
print(f"后 500 字符预览:")
print(text[-500:])

print("\n" + "=" * 60)
print("【Step 2】切片并检查内容")
print("=" * 60)
chunks = chunk_text(text, target_size=512, overlap_ratio=0.1)
print(f"共切出 {len(chunks)} 块")
for i, chunk in enumerate(chunks):
    content_preview = chunk["content"][:100]
    print(f"Chunk {i+1} (id={chunk['id']}, size={chunk['char_count']}): {content_preview}...")
    has_e1 = "E1" in chunk["content"]
    has_contractor = "维修" in chunk["content"] or "上门" in chunk["content"]
    has_script = "话术" in chunk["content"] or "开场白" in chunk["content"]
    print(f"    -> 含 'E1': {has_e1}, 含 '维修/上门': {has_contractor}, 含 '话术/开场白': {has_script}")
