# -*- coding: utf-8 -*-
"""
知识库「多格式端到端」测试脚本
================================
目标：验证 doc_parser 对多种格式的解析 + 切片 + 入库 + 检索命中都能正常工作。

覆盖 8 种格式：txt / md / json / csv / html / docx / xlsx / pptx
每种格式的测试步骤：
  1. PARSE   : doc_parser.parse_document 提取文本 → 无 error
  2. CHUNK   : chunk_count > 0 && 所有 4 个 QA 锚点（Q1/Q2/Q3/END）均出现在某段 chunk_content 中
  3. DAO     : 写入 docs_dao / save_chunks → status = ok，chunk_count 数一致，kb_chunk 表数量 === save_chunks
  4. RETRIEVE: 对 3 个 Q 问题分别发起检索（top_k=5），确认命中的第一个/前几个结果里包含正确锚点 A

**隔离原则**：
- 用 SCAI_APP_DIR 指向临时目录（tests/data/tmp_kb_format_run_XXXX/），
  保证 DB 文件和测试知识库完全隔离，不污染用户真实数据。
- 结束后删除临时目录（可选）。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

# --- 让 app/ 模块可用
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))

# --- 0. 隔离环境 ---
TEST_ROOT = ROOT / "tests" / "data"
TEST_ROOT.mkdir(parents=True, exist_ok=True)
TMP_APP_DIR = Path(tempfile.mkdtemp(prefix="tmp_kb_format_run_", dir=str(TEST_ROOT)))
os.environ["SCAI_APP_DIR"] = str(TMP_APP_DIR)
# 确保 db.py 的环境变量读取是用当前环境的；延迟 import

from storage.doc_parser import parse_document
from storage.db import reset_db_for_tests
from storage.dao import KnowledgeBaseDAO, DocumentsDAO
from storage.retriever import UnifiedRetriever  # noqa: E402  (env set before import)

reset_db_for_tests()  # 先重置，再用新 env 建库

# --- 1. 取测试样本
SAMPLE_DIR = ROOT / "tests" / "data" / "kb_format_test"
FILES = [
    ("TXT",  SAMPLE_DIR / "test_intro.txt"),
    ("MD",   SAMPLE_DIR / "test_intro.md"),
    ("JSON", SAMPLE_DIR / "test_intro.json"),
    ("CSV",  SAMPLE_DIR / "test_intro.csv"),
    ("HTML", SAMPLE_DIR / "test_intro.html"),
    ("DOCX", SAMPLE_DIR / "test_intro.docx"),
    ("XLSX", SAMPLE_DIR / "test_intro.xlsx"),
    ("PPTX", SAMPLE_DIR / "test_intro.pptx"),
]

# 4 个锚点（只要子串出现在某段 chunk content 里就算命中 — 故意用短锚点，避免 overlap 切断）
ANCHORS = {
    # Q1 产品核心特色 + 三大支柱（2 个关键词同时命中即过）
    "Q1_keywords": ["核心特色", "三大支柱"],
    # Q2 VIP 专业版年费（允许"VIP专业版"或"VIP 专业版"或"年费"三种写法任意组合，各格式标题空格不一样）
    "Q2_keywords": ["VIP", "1999元/年"],
    # Q3 创始团队来源（腾讯/字节/阿里 三个关键词任意命中 2+ 即过，避免跨句被切）
    "Q3_keywords": ["腾讯微信", "字节跳动", "阿里巴巴"],
    # END 结尾唯一指纹（PPTX 由于生成没放结尾slide，放宽到三章末都存在的"核心团队"类词即可；我们在生成样本脚本里给 PPTX 也加上结尾 slide 后再用）
    "END": "END_MARKER_KV_TEST_999777",
}
# 检索查询 → 对应必须命中的"最短特征子句"（任何一个子句命中 top-k 即算该问题通过）
RETRIEVE_QUERIES = {
    "Q1_query": ("阿凡达AI的核心特色是什么？",      ["三大支柱", "AI数字分身", "智能对话中枢", "私域数据运营"]),
    "Q2_query": ("VIP专业版年费多少钱？",              ["1999元/年", "专业版年费", "1999"]),
    "Q3_query": ("创始团队来自哪几家公司？",          ["腾讯微信事业部", "字节跳动 AI Lab", "阿里巴巴淘宝用户增长", "腾讯", "字节跳动", "阿里"]),
}


def _stage_title(t: str) -> str:
    return f"  🏷 {t}"


def main() -> int:
    print("=" * 72)
    print("  知识库 多格式端到端 测试")
    print("=" * 72)
    print(f"  临时数据目录: {TMP_APP_DIR}")
    print(f"  样本目录    : {SAMPLE_DIR}")
    print()

    # --- 创建一个测试专用知识库
    kb_dao = KnowledgeBaseDAO()
    docs_dao = DocumentsDAO()
    retriever = UnifiedRetriever()

    test_kb = kb_dao.create({
        "name": "格式测试专用库",
        "description": "用于多格式解析/切片/入库/检索验证（端到端测试脚本创建，用完可删）",
        "icon": "🧪",
        "kb_type": "document",
    })
    kb_id = test_kb["id"]
    print(f"[🏠] 测试知识库 ID: {kb_id}")
    print()

    report_lines = []  # 最终汇总表
    all_pass = True

    for fmt, fpath in FILES:
        print("-" * 60)
        print(f"📦 {fmt:5s}  {fpath.name}  ({fpath.stat().st_size/1024:.1f} KB)")
        print()

        row = {"fmt": fmt, "file": fpath.name}

        # ==== Stage 1: PARSE ====
        print(_stage_title("Step 1 / 4 · PARSE: 文本提取"), end=" ")
        try:
            parsed = parse_document(str(fpath))
        except Exception as e:
            parsed = {"error": f"抛出异常: {e}", "ext": "", "chunk_count": 0}
        has_error = bool(parsed.get("error"))
        text = parsed.get("text", "") or ""
        s1_pass = not has_error and len(text) >= 200
        row["parse"] = (
            f"OK 文本{len(text)}字" if s1_pass else f"FAIL error={parsed.get('error') or '文本过短'+str(len(text))}"
        )
        print("✅" if s1_pass else f"❌  → {parsed.get('error')}")
        if not s1_pass:
            all_pass = False

        # ==== Stage 2: CHUNK (锚点覆盖率) ====
        print(_stage_title("Step 2 / 4 · CHUNK: 切片 & 锚点覆盖"), end=" ")
        chunks = parsed.get("chunks") or []
        cc = len(chunks)
        all_content = "\n".join((c.get("content") or "") for c in chunks)
        miss = []
        # Q1：同时有"核心特色"和"三大支柱"词
        if any(k not in all_content for k in ANCHORS["Q1_keywords"]):
            miss.append("Q1_keywords")
        # Q2：同时有"VIP专业版"和"1999元/年"词
        if any(k not in all_content for k in ANCHORS["Q2_keywords"]):
            miss.append("Q2_keywords")
        # Q3："腾讯微信/字节跳动/阿里巴巴" 三个词至少命中 2 个
        q3_hit = sum(1 for k in ANCHORS["Q3_keywords"] if k in all_content)
        if q3_hit < 2:
            miss.append(f"Q3_keywords(命中{q3_hit}/3)")
        # END：结尾指纹
        if ANCHORS["END"] not in all_content:
            miss.append("END")
        s2_pass = (cc > 0) and (not miss)
        row["chunk"] = (
            f"OK {cc}段 4锚点全中" if s2_pass
            else f"FAIL chunks={cc} miss={miss}"
        )
        if cc == 0:
            print("❌ chunks=0")
        else:
            print(f"{'✅' if s2_pass else '❌'}  {cc}段 · 缺={miss if miss else '无'}")
        if not s2_pass:
            all_pass = False

        # ==== Stage 3: DAO (入库) ====
        print(_stage_title("Step 3 / 4 · DAO: 写入 docs_dao + kb_chunk 表"), end=" ")
        try:
            doc = docs_dao.create({
                "kb_id": kb_id,
                "name": fpath.name,
                "file_path": str(fpath),
                "size_bytes": fpath.stat().st_size,
                "chunk_count": 0,
                "status": "pending",
            })
            if parsed.get("error"):
                updated = docs_dao.update_status(doc["id"], "error", error=parsed["error"])
                s3_pass = False
                row["dao"] = f"FAIL parse_error={parsed['error'][:40]}"
            else:
                saved_n = docs_dao.save_chunks(doc["id"], kb_id, chunks)
                # 喂 retriever
                retriever.add_text(
                    text, source=fpath.stem, kb_id=kb_id, doc_id=doc["id"]
                )
                updated = docs_dao.update_status(doc["id"], "ok", chunk_count=cc)
                status_ok = updated["status"] == "ok"
                cnt_match = updated["chunk_count"] == cc
                saved_match = saved_n == cc
                s3_pass = status_ok and cnt_match and saved_match
                row["dao"] = (
                    f"OK save={saved_n}/status=ok/chunk={updated['chunk_count']}"
                    if s3_pass else
                    f"FAIL status={updated.get('status')} chunk={updated.get('chunk_count')} vs saved={saved_n} vs expect={cc}"
                )
        except Exception as e:
            s3_pass = False
            row["dao"] = f"FAIL exception: {e}"
        print("✅" if s3_pass else f"❌ → {row['dao']}")
        if not s3_pass:
            all_pass = False

        # ==== Stage 4: RETRIEVE （对 3 个问题检索）====
        print(_stage_title("Step 4 / 4 · RETRIEVE: 3×QA检索命中"), end=" ")
        if not s3_pass:
            row["retrieve"] = "SKIP (DAO失败)"
            print("⏭  SKIP (DAO失败)")
            continue

        r_ok = 0
        r_log = []
        for q_name, (q_txt, need_any) in RETRIEVE_QUERIES.items():
            try:
                hits = retriever.search(q_txt, top_k=5, kb_ids=[kb_id])  # list[dict]
                hit_contents = [(r.get("content") or "") for r in hits]
                # top_k 中任意一条包含任一特征关键词即算命中（同时返回命中的 rank）
                found_rank = None
                matched_term = None
                for idx, c in enumerate(hit_contents, 1):
                    for term in need_any:
                        if term in c:
                            found_rank = idx
                            matched_term = term
                            break
                    if found_rank:
                        break
                if found_rank:
                    r_ok += 1
                    r_log.append(f"{q_name[:2]}=#{found_rank} '{matched_term}'")
                else:
                    top1_preview = (hit_contents[0][:30].replace("\n", " ")) if hit_contents else "empty"
                    r_log.append(f"{q_name[:2]}=miss(top-1:{top1_preview})")
            except Exception as e:
                r_log.append(f"{q_name[:2]}=EXC:{e}")
        s4_pass = (r_ok == 3)
        row["retrieve"] = f"{r_ok}/3  {'OK' if s4_pass else 'FAIL'} [{', '.join(r_log)}]"
        print(("✅ " if s4_pass else "❌ ") + row["retrieve"])
        if not s4_pass:
            all_pass = False
        print()

        report_lines.append(row)

    # ==== 汇总表 ====
    print()
    print("=" * 72)
    print("  📊 测试汇总表")
    print("=" * 72)
    header = [
        ("格式", 6),
        ("文件名", 22),
        ("S1 解析", 24),
        ("S2 切片&锚点", 26),
        ("S3 DAO入库", 42),
        ("S4 检索命中", 58),
    ]
    col_titles = [h[0].ljust(w) for h, w in header]
    print("  ".join(col_titles))
    print("  ".join("-" * w for _, w in header))
    for row in report_lines:
        cells = [
            row["fmt"].ljust(header[0][1]),
            row["file"][:header[1][1]].ljust(header[1][1]),
            str(row["parse"])[:header[2][1]].ljust(header[2][1]),
            str(row["chunk"])[:header[3][1]].ljust(header[3][1]),
            str(row["dao"])[:header[4][1]].ljust(header[4][1]),
            str(row["retrieve"])[:header[5][1]].ljust(header[5][1]),
        ]
        print("  ".join(cells))

    # ==== 统计 ====
    def _sub_pass(r: dict, key: str) -> bool:
        v = str(r[key])
        return v.startswith("OK") or v.startswith("3/3") or "全中" in v
    print()
    s1_pass_n = sum(1 for r in report_lines if str(r["parse"]).startswith("OK"))
    s2_pass_n = sum(1 for r in report_lines if "4锚点全中" in str(r["chunk"]))
    s3_pass_n = sum(1 for r in report_lines if str(r["dao"]).startswith("OK"))
    s4_pass_n = sum(1 for r in report_lines if "3/3" in str(r["retrieve"]))
    total = len(report_lines)
    print(f"  S1 PARSE   : {s1_pass_n}/{total}")
    print(f"  S2 CHUNK   : {s2_pass_n}/{total}")
    print(f"  S3 DAO     : {s3_pass_n}/{total}")
    print(f"  S4 RETRIEVE: {s4_pass_n}/{total}")
    print()

    if all_pass:
        print("🎉 全部格式通过端到端四步测试！")
        rc = 0
    else:
        print("⚠ 有失败项，请根据上表定位问题。")
        rc = 1

    # ==== 可选：清理临时目录（默认保留 24 小时，方便排查）====
    keep_hr = 24
    print(f"\n(临时目录 {TMP_APP_DIR} 保留 {keep_hr}h，之后可手动删除)")

    return rc


if __name__ == "__main__":
    sys.exit(main())
