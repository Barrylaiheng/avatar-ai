# -*- coding: utf-8 -*-
"""
生成「多格式测试包」用于知识库上传 & 解析 & 切片 & 检索验证。

每个测试文件都包含相同的「三章 + QA锚点」内容：
  第一章：产品介绍（含 1 个 QA 锚点：Q1 产品的核心特色是什么？A1: 三大支柱 AI分身·智能沟通·私域运营）
  第二章：会员权益（含 1 个 QA 锚点：Q2 VIP 年费是多少？A2: 1999 元 / 年）
  第三章：团队介绍（含 1 个 QA 锚点：Q3 创始团队来自哪几家公司？A3: 腾讯、字节、阿里）
  结尾：统一结尾段

产出：tests/data/kb_format_test/ 目录下 8 个文件：
  - test_intro.txt   (UTF-8 纯文本)
  - test_intro.md    (Markdown)
  - test_intro.json  (JSON, 结构化包裹的文本字段)
  - test_intro.csv   (CSV, 每行"章节号, 标题, 正文"三列)
  - test_intro.html  (HTML, 用 h1/p/section 结构)
  - test_intro.docx  (DOCX, python-docx 生成)
  - test_intro.xlsx  (XLSX, openpyxl 生成, 2 Sheet)
  - test_intro.pptx  (PPTX, python-pptx 生成, 3 Slide)
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent / "data" / "kb_format_test"
OUT_DIR.mkdir(parents=True, exist_ok=True)


# ============ 统一的核心内容（中文，便于 QA 锚点验证） ============
CHAPTERS = [
    {
        "no": 1,
        "title": "第一章 产品介绍",
        "body": (
            "阿凡达AI（AvatarAI）是一款面向个体创业者和中小企业的私域AI分身平台，"
            "它可以在用户授权下接管微信、视频号等个人渠道进行智能沟通和业务拓展。"
            "【Q1 锚点】Q1: 阿凡达AI产品的核心特色是什么？A1: 产品核心特色由三大支柱构成——"
            "第一是AI数字分身，基于大模型复刻用户的表达风格和业务知识进行自动沟通；"
            "第二是智能对话中枢，支持多通道（微信私聊/群聊/视频号评论）统一的意图识别和内容生成；"
            "第三是私域数据运营，自动沉淀客户标签、跟进状态和转化漏斗，生成经营报表。"
            "产品的核心理念是：让每一个人都拥有一个懂你、替你工作的AI数字分身，永不失联，不知疲倦。"
        ),
    },
    {
        "no": 2,
        "title": "第二章 会员权益",
        "body": (
            "阿凡达AI目前提供三档会员：免费版（基础版）、VIP 专业版、旗舰版。"
            "免费版仅提供1个AI分身、每日50次对话额度、不支持知识库上传；"
            "【Q2 锚点】Q2: 阿凡达AI VIP 专业版年费是多少？A2: 1999元/年，包含5个AI分身、"
            "无限对话、10GB知识库容量、20个第三方工具插件以及高级数据分析看板。"
            "旗舰版年费 9999元/年，支持 50 个 AI 分身、企业 SSO、私有化部署选项、"
            "专属客服经理以及 100GB 知识库容量，适合 20 人以上的团队使用。"
            "所有会员版本均提供 7 天无理由退款保障；学生、教师及公益机构凭有效证件享受 8 折优惠。"
        ),
    },
    {
        "no": 3,
        "title": "第三章 团队介绍",
        "body": (
            "阿凡达AI的创始团队拥有深厚的人工智能和社交产品背景。"
            "【Q3 锚点】Q3: 阿凡达AI的核心创始团队分别来自哪几家公司？"
            "A3: CEO 林辰曾任职于腾讯微信事业部，历任高级产品经理；CTO 苏雪曾任字节跳动 AI Lab 技术负责人，"
            "主导过多项大模型落地项目；CPO 陈默曾任阿里巴巴淘宝用户增长团队总监，"
            "拥有超过10年的私域增长和会员运营经验。核心团队 80% 以上拥有硕士及以上学历，"
            "毕业于清华、北大、中科院、浙大、CMU 等知名院校。公司总部位于深圳，"
            "在北京、上海设有分公司，现有全职员工 120 余人，研发团队占比超过 65%。"
        ),
    },
]

END_PARAGRAPH = (
    "以上为阿凡达AI产品手册 v1.0 的精简摘要内容。"
    "【结尾锚点】END_MARKER_KV_TEST_999777"
)

QA_ANCHORS = {
    "Q1": "三大支柱——第一是AI数字分身",
    "Q2": "1999元/年",
    "Q3": "CEO 林辰曾任职于腾讯微信事业部，历任高级产品经理；CTO 苏雪曾任字节跳动 AI Lab",
    "END": "END_MARKER_KV_TEST_999777",
}


def _plain_text() -> str:
    lines = []
    for ch in CHAPTERS:
        lines.append(f"{ch['title']}")
        lines.append("")
        lines.append(ch["body"])
        lines.append("")
    lines.append(END_PARAGRAPH)
    return "\n".join(lines)


def _markdown_text() -> str:
    lines = ["# 阿凡达AI 产品手册", ""]
    for ch in CHAPTERS:
        lines.append(f"## {ch['title']}")
        lines.append("")
        # 按中文句号拆成几条 bullet，更有 MD 味道
        paras = [s + "。" for s in ch["body"].split("。") if s.strip()]
        lines.extend([f"- {p}" for p in paras])
        lines.append("")
    lines.append(f"---\n*{END_PARAGRAPH}*")
    return "\n".join(lines)


def _html_text() -> str:
    sections = []
    for ch in CHAPTERS:
        paras_html = "".join(
            f"<p>{s}。</p>" for s in ch["body"].split("。") if s.strip()
        )
        sections.append(
            f"<section class='chapter'><h2>{ch['title']}</h2>{paras_html}</section>"
        )
    body = "\n".join(sections) + f"<footer><p>{END_PARAGRAPH}</p></footer>"
    return (
        "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>"
        "<title>阿凡达AI产品手册</title></head><body>"
        f"<h1>阿凡达AI 产品手册 v1.0</h1>{body}</body></html>"
    )


def _csv_rows() -> list[list[str]]:
    rows = [["章节号", "标题", "正文"]]
    for ch in CHAPTERS:
        rows.append([str(ch["no"]), ch["title"], ch["body"]])
    rows.append(["0", "结尾段", END_PARAGRAPH])
    return rows


def _json_payload() -> dict:
    return {
        "document": {
            "name": "阿凡达AI产品手册v1.0",
            "version": "1.0",
            "chapters": [
                {"no": ch["no"], "title": ch["title"], "body": ch["body"]}
                for ch in CHAPTERS
            ],
            "footer": END_PARAGRAPH,
            "qa_anchors": QA_ANCHORS,
        },
        "updated_at": "2026-08-29",
    }


# ============ 生成文件 ============
def gen_txt():
    (OUT_DIR / "test_intro.txt").write_text(_plain_text(), encoding="utf-8")


def gen_md():
    (OUT_DIR / "test_intro.md").write_text(_markdown_text(), encoding="utf-8")


def gen_json():
    (OUT_DIR / "test_intro.json").write_text(
        json.dumps(_json_payload(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def gen_csv():
    p = OUT_DIR / "test_intro.csv"
    with p.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(_csv_rows())


def gen_html():
    (OUT_DIR / "test_intro.html").write_text(_html_text(), encoding="utf-8")


def gen_docx():
    try:
        import docx
    except ImportError as e:
        print(f"  [!] 跳过 DOCX 生成：{e}")
        return
    doc = docx.Document()
    doc.add_heading("阿凡达AI 产品手册 v1.0", level=0)
    for ch in CHAPTERS:
        doc.add_heading(ch["title"], level=1)
        doc.add_paragraph(ch["body"])
    doc.add_paragraph(END_PARAGRAPH)
    # 加一个小表格，验证表格提取功能
    doc.add_heading("会员套餐速查表（表格）", level=2)
    table = doc.add_table(rows=4, cols=3)
    headers = ["版本", "价格（元/年）", "AI分身数"]
    for i, h in enumerate(headers):
        table.rows[0].cells[i].text = h
    rows_data = [
        ("免费版", "0", "1"),
        ("VIP专业版", "1999", "5"),
        ("旗舰版", "9999", "50"),
    ]
    for r, (a, b, c) in enumerate(rows_data, 1):
        table.rows[r].cells[0].text = a
        table.rows[r].cells[1].text = b
        table.rows[r].cells[2].text = c
    doc.save(str(OUT_DIR / "test_intro.docx"))


def gen_xlsx():
    try:
        from openpyxl import Workbook
    except ImportError as e:
        print(f"  [!] 跳过 XLSX 生成：{e}")
        return
    wb = Workbook()
    # Sheet1：章节内容（模仿 CSV）
    ws1 = wb.active
    ws1.title = "章节内容"
    for row in _csv_rows():
        ws1.append(row)
    # Sheet2：会员价格
    ws2 = wb.create_sheet("会员价格表")
    ws2.append(["版本", "价格（元/年）", "AI分身数", "知识库容量"])
    ws2.append(["免费版", 0, 1, "0GB"])
    ws2.append(["VIP专业版", 1999, 5, "10GB"])
    ws2.append(["旗舰版", 9999, 50, "100GB"])
    wb.save(str(OUT_DIR / "test_intro.xlsx"))
    wb.close()


def gen_pptx():
    try:
        from pptx import Presentation
    except ImportError as e:
        print(f"  [!] 跳过 PPTX 生成：{e}")
        return
    prs = Presentation()
    # Slide 1：封面
    slide1 = prs.slides.add_slide(prs.slide_layouts[0])
    slide1.shapes.title.text = "阿凡达AI 产品介绍"
    slide1.placeholders[1].text = "v1.0 多格式测试文档"
    # Slide 2-4：三章
    for ch in CHAPTERS:
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = ch["title"]
        tf = slide.placeholders[1].text_frame
        # 按句号切 bullet 点
        sentences = [s + "。" for s in ch["body"].split("。") if s.strip()]
        for i, s in enumerate(sentences):
            if i == 0:
                tf.paragraphs[0].text = s
            else:
                p = tf.add_paragraph()
                p.text = s
    # Slide 5：结尾（含 END 指纹，保证格式统一）
    s_end = prs.slides.add_slide(prs.slide_layouts[1])
    s_end.shapes.title.text = "结尾"
    tf = s_end.placeholders[1].text_frame
    tf.paragraphs[0].text = END_PARAGRAPH
    prs.save(str(OUT_DIR / "test_intro.pptx"))


def main():
    print(f"[+] 生成测试文件到：{OUT_DIR}")
    jobs = [
        ("TXT",  gen_txt),
        ("MD",   gen_md),
        ("JSON", gen_json),
        ("CSV",  gen_csv),
        ("HTML", gen_html),
        ("DOCX", gen_docx),
        ("XLSX", gen_xlsx),
        ("PPTX", gen_pptx),
    ]
    for name, fn in jobs:
        try:
            fn()
            print(f"  ✅ {name}")
        except Exception as e:
            print(f"  ❌ {name}: {e}")

    # 打印文件列表和大小
    print("\n[生成结果]")
    for f in sorted(OUT_DIR.iterdir()):
        if f.is_file():
            size_kb = f.stat().st_size / 1024
            print(f"  - {f.name:25s}  {size_kb:7.2f} KB")
    print(f"\nQA 锚点（用于后续验证检索命中）：")
    for k, v in QA_ANCHORS.items():
        print(f"  {k}: {v[:40]}{'…' if len(v) > 40 else ''}")


if __name__ == "__main__":
    main()
