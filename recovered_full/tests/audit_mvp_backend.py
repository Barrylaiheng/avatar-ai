# -*- coding: utf-8 -*-
"""
核对 App 真实运行时的后台数据：
  - kb_document 表：列出每个文档的 id / 文件名 / status / chunk_count / size_bytes
  - kb_chunk   表：按 doc_id 聚合出每个文档的真实切片数
  - RAG Retriever 统计：索引中的 doc_count / chunk_count / 每 1 个 chunk 的 content 关键词预览（抽前 60 字）
  - 对每个 chunk 搜索 "三大支柱/1999元/腾讯微信/智能家电/E1 传感器" 等特征词，判断 Graph View 里的"家电内容"是否真实存在于用户 DB
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))

from storage.db import get_conn
from storage.dao import KnowledgeBaseDAO, DocumentsDAO
from storage.retriever import UnifiedRetriever


def main():
    print("=" * 80)
    print("  🔍 MVP 后台数据硬核核对（真实 APP_DATA 环境）")
    print("=" * 80)
    from storage.db import get_db_path
    print(f"  DB 文件路径: {get_db_path()}")
    print()

    conn = get_conn()
    kb_dao = KnowledgeBaseDAO()
    docs_dao = DocumentsDAO()

    # --- 1. knowledge_base ---
    print("📚 一、knowledge_base 表：")
    kbs = kb_dao.list_all()
    if not kbs:
        print("  (空)")
    for kb in kbs:
        print(f"  • [{kb['id']}] {kb['name']}  icon={kb['icon']}  docs={kb['doc_count']}  "
              f"chunks={kb['chunk_count']}  kb_type={kb['kb_type']}  src={kb['source_type']}")
    print()

    # --- 2. kb_document ---
    print("📄 二、kb_document 表：")
    if not kbs:
        print("  (无知识库)")
    for kb in kbs:
        print(f"  【{kb['name']}】 (kb_id={kb['id']})")
        docs = docs_dao.list_by_kb(kb['id'])
        if not docs:
            print("    (无文档)")
            continue
        # 聚合 kb_chunk 每个 doc 的真实切片数
        chunk_cnts = dict(conn.execute(
            "SELECT doc_id, COUNT(*) AS n FROM kb_chunk GROUP BY doc_id"
        ).fetchall())
        print(f"    {'id':<24s}  {'status':<8s}  {'chunks(dao)':>10s}  {'chunks(db)':>10s}  "
              f"{'size(KB)':>9s}  name")
        for d in docs:
            db_cc = chunk_cnts.get(d['id'], 0)
            print(f"    {d['id']:<24s}  {d.get('status','?'):<8s}  "
                  f"{d.get('chunk_count',0):>10d}  {db_cc:>10d}  "
                  f"{(d.get('size_bytes',0)/1024):>9.2f}  {d.get('name','')}")
            if d.get("error"):
                print(f"        ⚠ error: {d['error'][:120]}")
    print()

    # --- 3. kb_chunk content 关键词扫描 ---
    markers = [
        ("🌳 新上传·产品介绍",  "三大支柱"),
        ("💰 新上传·价格",      "1999元/年"),
        ("🏢 新上传·团队",      "腾讯微信事业部"),
        ("🧷 结尾指纹",         "END_MARKER_KV_TEST_999777"),
        ("📺 旧·家电空调",      "智能家电知识库"),
        ("📺 旧·故障代码E1",    "E1 传感器故障"),
        ("📺 旧·退换货",        "三包政策"),
    ]
    print("🔎 三、kb_chunk content 关键词扫描 (判断 Graph View 上看到的内容是否真实存在)")
    print()
    rows = conn.execute(
        "SELECT c.id, c.doc_id, d.name AS doc_name, k.name AS kb_name, c.content "
        "FROM kb_chunk c "
        "LEFT JOIN kb_document d ON d.id = c.doc_id "
        "LEFT JOIN knowledge_base k ON k.id = c.kb_id "
        "ORDER BY k.name, d.name, c.sort_order"
    ).fetchall()
    print(f"  共 {len(rows)} 条切片")
    print()
    for label, needle in markers:
        matches = [r for r in rows if needle in (r["content"] or "")]
        if matches:
            print(f"  ✅ [{label}]  🔍 '{needle}' 命中 {len(matches)} 条：")
            for r in matches[:3]:
                preview = (r["content"] or "").replace("\n", " ")[:70]
                print(f"       · kb={r['kb_name']} / doc={r['doc_name']} / chunk_id={r['id']}")
                print(f"         '{preview}…'")
            if len(matches) > 3:
                print(f"       · ... 还有 {len(matches) - 3} 条")
        else:
            print(f"  ❌ [{label}]  🔍 '{needle}' 无任何命中")
    print()

    # --- 4. RAG Retriever stats ---
    print("🧠 四、RAG Retriever 索引状态 (UnifiedRetriever.stats)")
    try:
        ret = UnifiedRetriever()
        stats = ret.stats()
        import json
        print(json.dumps(stats, ensure_ascii=False, indent=4))
    except Exception as e:
        print(f"  ⚠ Retriever 初始化失败: {e}")
    print()

    # --- 5. Graph View 真实性判定结论 ---
    print("=" * 80)
    print("  🧭 结论")
    print("=" * 80)
    have_new_intro = any(
        needle in (r["content"] or "")
        for needle in ("三大支柱", "1999元/年", "腾讯微信事业部", "END_MARKER_KV_TEST_999777")
        for r in rows
    )
    have_old_home_appliance = any(
        needle in (r["content"] or "")
        for needle in ("智能家电知识库", "E1 传感器故障", "三包政策")
        for r in rows
    )
    print(f"  - 真实 DB 中是否存在「阿凡达AI产品手册」(新上传 8 个格式)的内容：{'✅ YES' if have_new_intro else '❌ NO'}")
    print(f"  - 真实 DB 中是否存在「智能家电客服手册」(Graph View 显示的内容)：{'✅ YES' if have_old_home_appliance else '❌ NO'}")
    if not have_old_home_appliance and not have_new_intro:
        print("  ⚠ 两边内容都没找到，说明用户还没真的上传成功（或上传到了别的DB实例）")
    elif have_new_intro and not have_old_home_appliance:
        print("  🚨 ⚠ 用户直觉正确：Graph View 上展示的「智能家电客服」是前端写死的 mock 数据，和真实 DB/kb_chunk 毫无关系！")
    elif have_old_home_appliance and have_new_intro:
        print("  ℹ DB 里既有老家电手册又有新上传文件，Graph View 可能是基于某一份老内容渲染的（可能不是 mock，但也没把新内容加进去）")
    elif have_old_home_appliance:
        print("  ℹ Graph View 上那套「家电」正好就是用户真实存的，那说明用户新上传文件没成功（但 UI 显示成功？）—— 需要核对 kb_document.status")


if __name__ == "__main__":
    sys.exit(main())
