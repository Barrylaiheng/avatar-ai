"""文档解析：读取文件 → 切片 → 返回 chunks。

支持格式（零依赖/纯标准库）：
- TXT / MD ：直接读 UTF-8 文本
- CSV      ：按行读，拼接为文本
- HTML     ：用正则剥标签后按文本处理
- LOG      ：按 TXT 处理

需要额外依赖（延迟 import 友好错误，装了即激活）：
- PDF  → pypdf（已安装）
- DOCX → python-docx（已安装）
- DOC  → 暂不支持（旧版二进制格式）
- PPTX → python-pptx（已安装）
- XLSX → openpyxl（已安装）
- XLS  → xlrd（已安装，旧版二进制 Excel）
- EPUB → ebooklib + beautifulsoup4

切片策略（语义分割 + overlap 兜底）：
- 目标长度 512 字符
- 在 [target-100, target+200] 区间找最近的句末标点（。\n！？!?;；）切分
- 找不到句末标点时找逗号（，,、）切分
- 都找不到时按 target_size 硬切
- 默认 10% overlap（边界重叠，防止跨 chunk 的语义被切断）
"""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path
from typing import Any

# 切片目标长度（字符）
DEFAULT_CHUNK_SIZE = 512

# 句末标点（优先切分点）
_SENTENCE_END = "。\n！？!?;；"
# 次级分隔符（兜底切分点）
_SENTENCE_SOFT = "，,、"


def parse_document(file_path: str | Path) -> dict[str, Any]:
    """读取文件，提取纯文本，按 512 字符切片。

    返回字段：
        text         : 提取的纯文本（完整）
        chunks       : [{id, content, char_count, position}, ...]
        chunk_count  : 切片数
        file_size    : 文件字节数
        ext          : 文件扩展名（小写）
        error        : 错误信息（成功为空串）

    任一格式解析失败时返回 error，不抛异常（便于上层统一处理）。
    """
    p = Path(file_path)
    if not p.exists():
        return _err_result(f"文件不存在: {file_path}", ext=p.suffix.lstrip('.').lower())

    ext = p.suffix.lstrip('.').lower()
    try:
        text = _extract_text(p, ext)
    except NotImplementedError as e:
        return _err_result(str(e), ext=ext, file_size=p.stat().st_size)
    except Exception as e:
        return _err_result(f"读取失败: {e}", ext=ext, file_size=p.stat().st_size)

    chunks = chunk_text(text, target_size=DEFAULT_CHUNK_SIZE)
    return {
        "text": text,
        "chunks": chunks,
        "chunk_count": len(chunks),
        "file_size": p.stat().st_size,
        "ext": ext,
        "error": "",
    }


def _extract_text(p: Path, ext: str) -> str:
    """按扩展名分发到对应提取器。"""
    if ext in ("txt", "md", "markdown", "log", "json"):
        return _read_text(p)
    if ext == "csv":
        return _read_csv_as_text(p)
    if ext in ("html", "htm"):
        return _strip_html(_read_text(p))
    if ext == "pdf":
        return _extract_pdf(p)
    if ext == "docx":
        return _extract_docx(p)
    if ext == "doc":
        raise NotImplementedError("DOC（旧版二进制）暂不支持，请转 DOCX 后上传")
    if ext == "pptx":
        return _extract_pptx(p)
    if ext == "xlsx":
        return _extract_xlsx(p)
    if ext == "xls":
        return _extract_xls(p)
    if ext == "epub":
        return _extract_epub(p)
    # 未识别的扩展名，按文本尝试读取
    return _read_text(p)


# ============ 延迟 import 提取器（包未装时返回友好错误，装了即激活） ============

def _extract_pdf(p: Path) -> str:
    """用 pypdf 提取 PDF 每页文本，页间加换行。

    延迟 import：包未装时抛 NotImplementedError，上层会转为 error 结果。
    回电脑激活：pip install pypdf
    """
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise NotImplementedError(
            f"PDF 解析需要 pypdf，请安装：pip install pypdf（{e}）"
        )
    reader = PdfReader(str(p))
    pages = []
    for page in reader.pages:
        # extract_text() 在某些扫描版 PDF 上返回空串，属正常
        t = page.extract_text() or ""
        if t:
            pages.append(t.strip())
    return "\n\n".join(pages)


def _extract_docx(p: Path) -> str:
    """用 python-docx 提取段落文本，段落间加换行。

    延迟 import：包未装时抛 NotImplementedError。
    回电脑激活：pip install python-docx
    """
    try:
        import docx  # python-docx 的模块名是 docx
    except ImportError as e:
        raise NotImplementedError(
            f"DOCX 解析需要 python-docx，请安装：pip install python-docx（{e}）"
        )
    doc = docx.Document(str(p))
    paras = []
    for para in doc.paragraphs:
        t = (para.text or "").strip()
        if t:
            paras.append(t)
    # 表格内容也提取（按单元格拼接）
    for table in doc.tables:
        for row in table.rows:
            cells = [(c.text or "").strip() for c in row.cells]
            if any(cells):
                paras.append(" | ".join(cells))
    return "\n".join(paras)


def _extract_pptx(p: Path) -> str:
    """用 python-pptx 提取幻灯片文本。

    回电脑激活：pip install python-pptx
    """
    try:
        from pptx import Presentation
    except ImportError as e:
        raise NotImplementedError(
            f"PPTX 解析需要 python-pptx，请安装：pip install python-pptx（{e}）"
        )
    prs = Presentation(str(p))
    slides_text = []
    for i, slide in enumerate(prs.slides, 1):
        texts = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    t = (para.text or "").strip()
                    if t:
                        texts.append(t)
        if texts:
            slides_text.append(f"--- Slide {i} ---\n" + "\n".join(texts))
    return "\n\n".join(slides_text)


def _extract_xlsx(p: Path) -> str:
    """用 openpyxl 提取 Excel 所有 sheet 的单元格文本。

    回电脑激活：pip install openpyxl
    """
    try:
        from openpyxl import load_workbook
    except ImportError as e:
        raise NotImplementedError(
            f"XLSX 解析需要 openpyxl，请安装：pip install openpyxl（{e}）"
        )
    wb = load_workbook(str(p), read_only=True, data_only=True)
    sheets_text = []
    for ws in wb.worksheets:
        rows = []
        for row in ws.iter_rows(values_only=True):
            cells = [str(c) if c is not None else "" for c in row]
            if any(cells):
                rows.append(" | ".join(cells))
        if rows:
            sheets_text.append(f"--- Sheet: {ws.title} ---\n" + "\n".join(rows))
    wb.close()
    return "\n\n".join(sheets_text)


def _extract_xls(p: Path) -> str:
    """用 xlrd 提取旧版二进制 Excel (.xls) 所有 sheet。

    延迟 import：xlrd 2.0+ 仅支持 .xls（不再支持 .xlsx），所以 xls/xlsx 明确分工。
    激活：pip install xlrd
    """
    try:
        import xlrd
    except ImportError as e:
        raise NotImplementedError(
            f"XLS（旧版Excel）解析需要 xlrd，请安装：pip install xlrd（{e}）"
        )
    wb = xlrd.open_workbook(str(p))
    sheets_text = []
    for sheet in wb.sheets():
        rows = []
        for r in range(sheet.nrows):
            cells = []
            for c in range(sheet.ncols):
                cell = sheet.cell_value(r, c)
                if cell is None:
                    cells.append("")
                elif isinstance(cell, float) and cell == int(cell):
                    cells.append(str(int(cell)))
                else:
                    cells.append(str(cell))
            if any(c.strip() for c in cells):
                rows.append(" | ".join(cells))
        if rows:
            sheets_text.append(f"--- Sheet: {sheet.name} ---\n" + "\n".join(rows))
    return "\n\n".join(sheets_text)


def _extract_epub(p: Path) -> str:
    """用 ebooklib + beautifulsoup4 提取 EPUB 文本。

    回电脑激活：pip install ebooklib beautifulsoup4
    """
    try:
        import ebooklib
        from ebooklib import epub
        from bs4 import BeautifulSoup
    except ImportError as e:
        raise NotImplementedError(
            f"EPUB 解析需要 ebooklib + beautifulsoup4，"
            f"请安装：pip install ebooklib beautifulsoup4（{e}）"
        )
    book = epub.read_epub(str(p))
    parts = []
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        soup = BeautifulSoup(item.get_content(), "html.parser")
        t = soup.get_text(separator="\n").strip()
        if t:
            parts.append(t)
    return "\n\n".join(parts)


def _read_text(p: Path) -> str:
    """读 UTF-8 文本（自动剥 BOM），失败时尝试 GBK 兜底。"""
    try:
        # utf-8-sig 会自动剥掉 UTF-8 BOM（无 BOM 时也能正常读）
        return p.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return p.read_text(encoding="gbk", errors="replace")


def _read_csv_as_text(p: Path) -> str:
    """读 CSV，按行拼接为文本（每行用 | 分隔字段，行间换行）。"""
    rows = []
    with p.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            rows.append(" | ".join(row))
    return "\n".join(rows)


def _strip_html(html: str) -> str:
    """剥 HTML 标签 + 折叠空白。"""
    # 去 script/style 整段
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # 去所有标签
    text = re.sub(r"<[^>]+>", "", html)
    # 折叠连续空白
    text = re.sub(r"\s+", " ", text).strip()
    return text


def chunk_text(
    text: str,
    target_size: int = DEFAULT_CHUNK_SIZE,
    overlap_ratio: float = 0.1,
) -> list[dict]:
    """按语义切片。

    Args:
        text: 待切片原文
        target_size: 目标长度（字符），默认 512
        overlap_ratio: 重叠比例，0-1，默认 10%（约 50 字符）
                       用于避免切断跨 chunk 的完整语义
    切分策略：
      在 [target-100, target+200] 区间从后往前找句末标点切分
      → 找不到句末标点时找次级分隔符（逗号/顿号）
      → 都找不到时按 target_size 硬切
    overlap 机制：
      chunk n 的结尾 N% 字符 = chunk n+1 的开头 N% 字符
      overlap_size = int(target_size * overlap_ratio)
    """
    if not text or not text.strip():
        return []

    overlap_size = max(0, int(target_size * max(0.0, min(1.0, overlap_ratio))))

    chunks: list[dict] = []
    pos = 0
    chunk_idx = 0
    text_len = len(text)

    while pos < text_len:
        end_ideal = pos + target_size
        # 最后一段直接收尾
        if end_ideal >= text_len:
            content = text[pos:].strip()
            if content:
                chunks.append(_make_chunk(chunk_idx, content))
                chunk_idx += 1
            break

        # 在 end_ideal 附近找最佳切分点
        search_start = max(pos + 100, end_ideal - 100)
        search_end = min(text_len, end_ideal + 200)
        cut = _find_cut_point(text, search_start, search_end, _SENTENCE_END)
        if cut < 0:
            cut = _find_cut_point(text, search_start, search_end, _SENTENCE_SOFT)
        if cut < 0:
            cut = end_ideal  # 兜底硬切

        content = text[pos:cut].strip()
        if content:
            chunks.append(_make_chunk(chunk_idx, content))
            chunk_idx += 1

        # 下一个 chunk 的起点 = 当前切分点 - overlap_size
        # 保证 chunk n 的结尾和 chunk n+1 的开头有重叠，不丢失跨边界语义
        next_pos = cut - overlap_size
        if next_pos <= pos:
            next_pos = cut  # 避免重叠过大导致死循环
        pos = next_pos

    return chunks


def _find_cut_point(text: str, start: int, end: int, separators: str) -> int:
    """在 [start, end) 区间从后往前找最近的分隔符，返回切分点（分隔符位置 +1）。"""
    for i in range(end - 1, start - 1, -1):
        if i < len(text) and text[i] in separators:
            return i + 1
    return -1


def _make_chunk(idx: int, content: str) -> dict:
    return {
        "id": f"chunk_{idx}",
        "content": content,
        "char_count": len(content),
        "position": idx,
    }


def _err_result(error: str, ext: str = "", file_size: int = 0) -> dict:
    return {
        "text": "",
        "chunks": [],
        "chunk_count": 0,
        "file_size": file_size,
        "ext": ext,
        "error": error,
    }
