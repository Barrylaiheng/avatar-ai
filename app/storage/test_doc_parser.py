"""doc_parser 单元测试 — 切片逻辑 + 文件解析。

测试覆盖：
1. chunk_text 边界场景（空/短/长/带句号/带换行）
2. parse_document 文件级解析（TXT/MD/CSV/HTML/不存在/不支持格式）
3. 切片质量：每段接近 512 字符、内容连贯、无遗漏
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_ROOT))

from storage.doc_parser import (
    chunk_text,
    parse_document,
    DEFAULT_CHUNK_SIZE,
)


def assert_eq(actual, expected, hint=""):
    if actual != expected:
        raise AssertionError(f"断言失败 {hint}: actual={actual!r}, expected={expected!r}")
    print(f"  OK {hint}")


def test_chunk_text_empty():
    print("\n=== chunk_text: 空字符串 ===")
    assert_eq(chunk_text(""), [], "空字符串返回空数组")
    assert_eq(chunk_text("   "), [], "纯空白返回空数组")
    assert_eq(chunk_text(None), [], "None 返回空数组")


def test_chunk_text_short():
    print("\n=== chunk_text: 短文本（< 512）===")
    text = "这是一段短文本。"
    chunks = chunk_text(text)
    assert_eq(len(chunks), 1, "短文本只 1 段")
    assert_eq(chunks[0]["content"], text, "内容完整保留")
    assert_eq(chunks[0]["char_count"], len(text), "字符数正确")
    assert_eq(chunks[0]["position"], 0, "position=0")
    assert_eq(chunks[0]["id"], "chunk_0", "id=chunk_0")


def test_chunk_text_long_with_sentences():
    print("\n=== chunk_text: 长文本（含句号，应按句号切分）===")
    # 构造 ≥ 2000 字符文本，每 100 字符一个句号，至少能切 3 段
    sentences = ["这是第{}句话，内容中等长度，用于测试切片逻辑。".format(i) for i in range(80)]
    text = "".join(sentences)
    chunks = chunk_text(text, target_size=DEFAULT_CHUNK_SIZE)
    print(f"  长度 {len(text)} 字符 → {len(chunks)} 段")
    assert len(chunks) >= 3, f"应有至少 3 段，实际 {len(chunks)}"
    # 每段应在 512 附近（允许 100~720 范围）
    for i, c in enumerate(chunks):
        n = c["char_count"]
        assert 100 <= n <= 720, f"第 {i} 段长度 {n} 超出 [100, 720] 范围"
    # 拼接还原应等于原文（去掉 strip 的空白后）
    restored = "".join(c["content"] for c in chunks)
    # 注意：strip 会去掉每段首尾空白，原文本里句间无空白，所以应一致
    assert_eq(restored.replace(" ", ""), text.replace(" ", ""), "拼接还原（去空白后）")
    print(f"  OK 每段长度合理，拼接还原一致")


def test_chunk_text_newlines():
    print("\n=== chunk_text: 多换行文本 ===")
    # 每行约 80 字符，共 20 行 = 1600 字符
    lines = ["行 {}: 这是一条比较长的测试数据，用来验证换行切分逻辑是否正常工作。".format(i) for i in range(20)]
    text = "\n".join(lines)
    chunks = chunk_text(text, target_size=DEFAULT_CHUNK_SIZE)
    print(f"  长度 {len(text)} 字符 → {len(chunks)} 段")
    assert len(chunks) >= 2, "应有至少 2 段"
    # 应优先在换行处切分（_SENTENCE_END 含 \n）
    for i, c in enumerate(chunks):
        # 不以换行开头（已 strip）
        assert not c["content"].startswith("\n"), f"第 {i} 段不应以换行开头"
    print(f"  OK 切分正常，每段开头无换行")


def test_chunk_text_no_separator():
    print("\n=== chunk_text: 无标点长文本（硬切兜底）===")
    text = "字" * 1500  # 1500 个相同字符，无任何标点
    chunks = chunk_text(text, target_size=DEFAULT_CHUNK_SIZE)
    print(f"  长度 {len(text)} 字符 → {len(chunks)} 段")
    assert len(chunks) >= 2, "无标点也应切分（硬切）"
    # 第一段应等于 target_size（硬切）
    assert_eq(chunks[0]["char_count"], DEFAULT_CHUNK_SIZE, "硬切第一段=target_size")
    # 拼接还原应等于原文（无 strip 损失）
    assert_eq("".join(c["content"] for c in chunks), text, "拼接还原等于原文")


def test_parse_document_txt():
    print("\n=== parse_document: TXT 文件 ===")
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write("这是测试文档。\n" * 200)  # 约 2000 字符
        path = f.name
    try:
        result = parse_document(path)
        assert not result["error"], f"不应有错误: {result['error']}"
        assert_eq(result["ext"], "txt", "扩展名正确")
        assert result["chunk_count"] >= 3, f"应有至少 3 段，实际 {result['chunk_count']}"
        assert result["file_size"] > 0, "文件大小 > 0"
        print(f"  OK TXT 解析：{result['chunk_count']} 段")
    finally:
        os.unlink(path)


def test_parse_document_md():
    print("\n=== parse_document: Markdown 文件 ===")
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write("# 标题\n\n段落一，介绍背景。\n\n段落二，深入分析。\n" * 100)
        path = f.name
    try:
        result = parse_document(path)
        assert not result["error"], f"不应有错误: {result['error']}"
        assert_eq(result["ext"], "md", "扩展名正确")
        assert result["chunk_count"] >= 2, "应有至少 2 段"
        print(f"  OK MD 解析：{result['chunk_count']} 段")
    finally:
        os.unlink(path)


def test_parse_document_csv():
    print("\n=== parse_document: CSV 文件 ===")
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8", newline="") as f:
        f.write("name,age,city\n张三,30,北京\n李四,25,上海\n" * 100)
        path = f.name
    try:
        result = parse_document(path)
        assert not result["error"], f"不应有错误: {result['error']}"
        assert_eq(result["ext"], "csv", "扩展名正确")
        assert "张三" in result["text"], "CSV 内容应包含中文"
        assert result["chunk_count"] >= 1, "应有至少 1 段"
        print(f"  OK CSV 解析：{result['chunk_count']} 段")
    finally:
        os.unlink(path)


def test_parse_document_html():
    print("\n=== parse_document: HTML 文件 ===")
    html = "<html><body><p>第一段。</p><p>第二段。</p></body></html>" * 100
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html)
        path = f.name
    try:
        result = parse_document(path)
        assert not result["error"], f"不应有错误: {result['error']}"
        assert_eq(result["ext"], "html", "扩展名正确")
        # HTML 标签应被剥掉
        assert "<p>" not in result["text"], "HTML 标签应被剥掉"
        assert "第一段" in result["text"], "正文内容应保留"
        print(f"  OK HTML 解析：标签已剥除，{result['chunk_count']} 段")
    finally:
        os.unlink(path)


def test_parse_document_not_exist():
    print("\n=== parse_document: 不存在的文件 ===")
    result = parse_document("C:/nonexistent/file.txt")
    assert result["error"], "应返回错误"
    assert_eq(result["chunk_count"], 0, "切片数为 0")
    assert "不存在" in result["error"], "错误信息应包含'不存在'"
    print(f"  OK 错误处理：{result['error']}")


def test_parse_document_unsupported_pdf():
    print("\n=== parse_document: PDF（未安装依赖，应返回 NotImplementedError 提示）===")
    # 用一个伪 PDF 文件（实际是空文件）触发 NotImplementedError
    with tempfile.NamedTemporaryFile("wb", suffix=".pdf", delete=False) as f:
        f.write(b"%PDF-1.4 fake content")
        path = f.name
    try:
        result = parse_document(path)
        assert result["error"], "应返回错误"
        assert "pypdf" in result["error"], "错误信息应提示安装 pypdf"
        print(f"  OK 未支持格式提示：{result['error']}")
    finally:
        os.unlink(path)


def test_parse_document_unsupported_docx():
    print("\n=== parse_document: DOCX（未安装依赖）===")
    with tempfile.NamedTemporaryFile("wb", suffix=".docx", delete=False) as f:
        f.write(b"fake docx")
        path = f.name
    try:
        result = parse_document(path)
        assert result["error"], "应返回错误"
        assert "python-docx" in result["error"], "错误信息应提示安装 python-docx"
        print(f"  OK 未支持格式提示：{result['error']}")
    finally:
        os.unlink(path)


def main():
    print("=" * 60)
    print("  doc_parser 单元测试")
    print("=" * 60)

    tests = [
        test_chunk_text_empty,
        test_chunk_text_short,
        test_chunk_text_long_with_sentences,
        test_chunk_text_newlines,
        test_chunk_text_no_separator,
        test_parse_document_txt,
        test_parse_document_md,
        test_parse_document_csv,
        test_parse_document_html,
        test_parse_document_not_exist,
        test_parse_document_unsupported_pdf,
        test_parse_document_unsupported_docx,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            print(f"  ✗ FAIL: {e}")
            failed += 1
        except Exception as e:
            print(f"  ✗ ERROR: {type(e).__name__}: {e}")
            failed += 1

    print("\n" + "=" * 60)
    if failed == 0:
        print(f"  全部通过（{len(tests)} 项测试）")
    else:
        print(f"  {failed} 项失败 / {len(tests)} 项")
    print("=" * 60)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
