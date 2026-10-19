"""文档解析命令行工具。

用法：
    py -3 -m storage.parse_doc <文件路径>
    py -3 -m storage.parse_doc <文件路径> --json
    py -3 -m storage.parse_doc <文件路径> --preview 5   # 预览前 5 段切片（默认 3）

输出：
- 人类友好模式：文件信息 + 切片统计 + 前 N 段切片预览
- JSON 模式：完整切片内容（便于其他程序调用）
"""
from __future__ import annotations

import argparse
import json
import sys

from .doc_parser import parse_document


def _print_human(result: dict, preview_n: int) -> int:
    print("=" * 60)
    print("  阿维达AI 文档解析")
    print("=" * 60)
    print(f"  文件大小 : {_format_size(result.get('file_size', 0))}")
    print(f"  文件类型 : .{result.get('ext', '?')}")
    print(f"  文本长度 : {len(result.get('text', ''))} 字符")
    print(f"  切片数量 : {result.get('chunk_count', 0)} 段")
    print(f"  目标长度 : 512 字符 / 段")

    if result.get("error"):
        print("-" * 60)
        print(f"  ⚠ 解析错误: {result['error']}")
        print("=" * 60)
        return 1

    chunks = result.get("chunks", [])
    if not chunks:
        print("-" * 60)
        print("  （文件内容为空，无切片）")
        print("=" * 60)
        return 0

    n = min(preview_n, len(chunks))
    print("-" * 60)
    print(f"  前 {n} 段切片预览：")
    print("-" * 60)
    for i in range(n):
        c = chunks[i]
        preview = c["content"][:120].replace("\n", " ")
        if len(c["content"]) > 120:
            preview += "..."
        print(f"  [{c['id']}] {c['char_count']} 字")
        print(f"    {preview}")
        print()
    if len(chunks) > n:
        print(f"  ... 还有 {len(chunks) - n} 段未显示")
    print("=" * 60)
    return 0


def _print_json(result: dict) -> int:
    # JSON 模式只输出关键元数据 + 切片（不带完整原文，避免输出过大）
    payload = {
        "ok": not result.get("error"),
        "file_size": result.get("file_size", 0),
        "ext": result.get("ext", ""),
        "text_length": len(result.get("text", "")),
        "chunk_count": result.get("chunk_count", 0),
        "chunks": result.get("chunks", []),
    }
    if result.get("error"):
        payload["error"] = result["error"]
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not result.get("error") else 1


def _format_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="parse_doc",
        description="阿维达AI 文档解析工具",
    )
    parser.add_argument("file_path", help="待解析的文件路径")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    parser.add_argument("--preview", type=int, default=3,
                        help="预览前 N 段切片（默认 3，仅人类友好模式）")
    args = parser.parse_args(argv)

    result = parse_document(args.file_path)

    if args.json:
        return _print_json(result)
    return _print_human(result, args.preview)


if __name__ == "__main__":
    sys.exit(main())
