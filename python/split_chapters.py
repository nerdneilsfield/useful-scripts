#!/usr/bin/env python3
"""
pdf_split_chapters.py — 按书签/Outline 切分 PDF 章节

用法:
    python pdf_split_chapters.py input.pdf
    python pdf_split_chapters.py input.pdf -o ./chapters
    python pdf_split_chapters.py input.pdf -l 1          # 子章节层级
    python pdf_split_chapters.py input.pdf --list        # 只列出书签不切分
    python pdf_split_chapters.py input.pdf --min-pages 3 # 忽略不足3页的条目
    python pdf_split_chapters.py input.pdf --dry-run     # 演习模式
"""

import argparse
import os
import re
import sys
from pathlib import Path

try:
    from pypdf import PdfReader, PdfWriter
except ImportError:
    sys.exit("[错误] 缺少依赖: pip install pypdf")


# ──────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────


def sanitize_filename(name: str, max_len: int = 80) -> str:
    """移除文件名非法字符，截断过长标题"""
    name = name.strip()
    name = re.sub(r'[\\/*?:"<>|\r\n\t]', "_", name)
    name = re.sub(r"_+", "_", name)  # 连续下划线合并
    name = name.strip("_. ")
    return name[:max_len] or "untitled"


def get_outline_items(reader: PdfReader) -> list[tuple[int, str, int]]:
    """
    递归遍历 PDF Outline，返回 [(level, title, page_index), ...]
    page_index 从 0 开始。
    """
    items: list[tuple[int, str, int]] = []

    def walk(nodes, level: int):
        for node in nodes:
            if isinstance(node, list):
                walk(node, level + 1)
                continue
            title = getattr(node, "title", None) or "(无标题)"
            try:
                page_idx = reader.get_destination_page_number(node)
            except Exception:
                # 部分书签指向外部链接或损坏，跳过
                continue
            # 页码夹紧到合法范围
            page_idx = max(0, min(page_idx, len(reader.pages) - 1))
            items.append((level, title.strip(), page_idx))

    if not reader.outline:
        return []
    walk(reader.outline, level=0)
    return items


def filter_by_level(items, level: int | None) -> list[tuple[int, str, int]]:
    """None 表示保留所有层级；否则只保留指定层级"""
    if level is None:
        return items
    return [(l, t, p) for l, t, p in items if l == level]


def build_chapters(
    items: list[tuple[int, str, int]], total_pages: int, min_pages: int
) -> list[dict]:
    """
    将 (level, title, start_page) 列表转成
    [{'index': n, 'title': t, 'start': s, 'end': e, 'pages': n}, ...]
    并过滤掉页数不足 min_pages 的条目。
    """
    chapters = []
    for i, (_, title, start) in enumerate(items):
        end = items[i + 1][2] if i + 1 < len(items) else total_pages
        page_count = end - start
        if page_count < min_pages:
            continue
        chapters.append(
            {
                "index": len(chapters) + 1,
                "title": title,
                "start": start,  # inclusive, 0-based
                "end": end,  # exclusive, 0-based
                "pages": page_count,
            }
        )
    return chapters


# ──────────────────────────────────────────────
# 核心操作
# ──────────────────────────────────────────────


def list_outline(reader: PdfReader, level: int | None):
    """打印书签树"""
    items = get_outline_items(reader)
    if not items:
        print("[!] 该 PDF 没有书签/Outline")
        return

    total = len(reader.pages)
    print(f"共 {total} 页，找到 {len(items)} 条书签：\n")
    print(f"{'层级':>4}  {'起始页':>6}  标题")
    print("─" * 60)
    for lvl, title, page in items:
        marker = "  " * lvl + ("▸ " if lvl == 0 else "· ")
        flag = "" if (level is None or lvl == level) else "  (跳过)"
        print(f"{lvl:>4}  {page + 1:>6}  {marker}{title}{flag}")


def split_pdf(reader: PdfReader, chapters: list[dict], output_dir: Path, dry_run: bool):
    """执行切分，dry_run=True 时只打印不写文件"""
    output_dir.mkdir(parents=True, exist_ok=True)

    pad = len(str(len(chapters)))  # 序号补零位数
    ok = skipped = 0

    for ch in chapters:
        filename = f"{ch['index']:0{pad}d}_{sanitize_filename(ch['title'])}.pdf"
        out_path = output_dir / filename
        label = (
            f"  [{ch['index']:>{pad}}] "
            f"页 {ch['start'] + 1:>4}–{ch['end']:>4}  "
            f"({ch['pages']:>3}p)  {ch['title']}"
        )

        if dry_run:
            print(label, "→", filename, "[dry-run]")
            ok += 1
            continue

        # 目标文件已存在时跳过（加 --overwrite 可覆盖，见 argparse）
        if out_path.exists():
            print(label, "→ [已存在，跳过]")
            skipped += 1
            continue

        try:
            writer = PdfWriter()
            for p in range(ch["start"], ch["end"]):
                writer.add_page(reader.pages[p])
            with open(out_path, "wb") as f:
                writer.write(f)
            print(label, "→", filename)
            ok += 1
        except Exception as e:
            print(label, f"→ [失败: {e}]", file=sys.stderr)

    print()
    if dry_run:
        print(f"[dry-run] 共 {ok} 个章节（未写入任何文件）")
    else:
        print(
            f"完成：{ok} 个章节已保存到 {output_dir}"
            + (f"，{skipped} 个已跳过" if skipped else "")
        )


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────


def parse_args():
    parser = argparse.ArgumentParser(
        prog="pdf_split_chapters",
        description="按 PDF 书签（Outline/TOC）切分章节",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "input",
        metavar="INPUT.pdf",
        help="输入 PDF 路径",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        metavar="DIR",
        default=None,
        help="输出目录（默认：与输入文件同目录下的 <stem>_chapters/）",
    )
    parser.add_argument(
        "-l",
        "--level",
        metavar="N",
        type=int,
        default=0,
        help="书签层级，0=顶级章节（默认），1=二级，-1=所有层级",
    )
    parser.add_argument(
        "--min-pages",
        metavar="N",
        type=int,
        default=1,
        help="忽略页数少于 N 的章节条目（默认 1）",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="只列出书签结构，不切分文件",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="演习模式：打印计划但不写文件",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="覆盖已存在的输出文件",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # ── 输入校验 ──
    input_path = Path(args.input)
    if not input_path.exists():
        sys.exit(f"[错误] 文件不存在: {input_path}")
    if not input_path.is_file():
        sys.exit(f"[错误] 不是文件: {input_path}")
    if input_path.suffix.lower() != ".pdf":
        print(f"[警告] 文件扩展名不是 .pdf，尝试继续…")

    # ── 读取 PDF ──
    try:
        reader = PdfReader(str(input_path))
    except Exception as e:
        sys.exit(f"[错误] 无法打开 PDF: {e}")

    if len(reader.pages) == 0:
        sys.exit("[错误] PDF 页数为 0")

    # ── --list 模式 ──
    level_arg = None if args.level == -1 else args.level
    if args.list:
        list_outline(reader, level_arg)
        return

    # ── 提取书签 ──
    all_items = get_outline_items(reader)
    if not all_items:
        sys.exit(
            "[错误] PDF 没有书签/Outline，无法自动按章节切分。\n"
            "       → 可改用文本正则识别（方案三），或手动指定页范围。"
        )

    items = filter_by_level(all_items, level_arg)
    if not items:
        sys.exit(
            f"[错误] 层级 {args.level} 下没有书签条目。\n"
            f"       → 运行 --list 查看可用层级。"
        )

    chapters = build_chapters(items, len(reader.pages), args.min_pages)
    if not chapters:
        sys.exit(
            f"[错误] 过滤后（min-pages={args.min_pages}）没有可切分的章节。\n"
            f"       → 降低 --min-pages 阈值或运行 --list 检查书签。"
        )

    # ── 输出目录 ──
    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = input_path.parent / f"{input_path.stem}_chapters"

    # ── 执行 ──
    print(f"输入：{input_path}  ({len(reader.pages)} 页)")
    print(f"输出：{output_dir}")
    print(
        f"章节：{len(chapters)} 个（层级={args.level}，min-pages={args.min_pages}）\n"
    )

    # 临时把 overwrite 注入到 split_pdf（简单处理）
    if args.overwrite:
        # monkey-patch：让 split_pdf 直接覆盖
        import builtins

        _orig_open = builtins.open

        def _open_overwrite(path, mode="r", **kw):
            return _orig_open(path, mode, **kw)

        # 直接在 split_pdf 里已经是写模式，overwrite 只需跳过"已存在"判断
        for ch in chapters:
            pad = len(str(len(chapters)))
            filename = f"{ch['index']:0{pad}d}_{sanitize_filename(ch['title'])}.pdf"
            out_path = output_dir / filename
            # 提前删掉旧文件让 split_pdf 正常写入
            if out_path.exists():
                out_path.unlink()

    split_pdf(reader, chapters, output_dir, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
