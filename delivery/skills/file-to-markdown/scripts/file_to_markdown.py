#!/usr/bin/env python3
"""
File-to-Markdown batch converter.

Dependency: markitdown (resolved via uvx at runtime)

Usage:
  uv run --python 3.11 python <skill-root>/scripts/file_to_markdown.py <directory>
  uv run --python 3.11 python <skill-root>/scripts/file_to_markdown.py <directory> --output-dir <output-dir>
  uv run --python 3.11 python <skill-root>/scripts/file_to_markdown.py <directory> --recursive
  uv run --python 3.11 python <skill-root>/scripts/file_to_markdown.py <directory> --dry-run
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

SUPPORTED_EXTENSIONS = {
    ".xlsx", ".xls", ".xlsm",
    ".docx", ".doc",
    ".pdf",
    ".pptx", ".ppt",
    ".html", ".htm",
    ".csv",
    ".epub",
    ".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tiff",
    ".xmind",
    ".json", ".xml",
    ".rst", ".rtf",
}


def find_convertible_files(directory: Path, recursive: bool = False) -> list[Path]:
    files: list[Path] = []
    if recursive:
        for root, _dirs, filenames in os.walk(directory):
            for fname in filenames:
                fpath = Path(root) / fname
                if fpath.suffix.lower() in SUPPORTED_EXTENSIONS:
                    files.append(fpath)
    else:
        for item in directory.iterdir():
            if item.is_file() and item.suffix.lower() in SUPPORTED_EXTENSIONS:
                files.append(item)
            elif item.is_dir():
                for sub_item in item.iterdir():
                    if sub_item.is_file() and sub_item.suffix.lower() in SUPPORTED_EXTENSIONS:
                        files.append(sub_item)
    return sorted(files)


def convert_file(input_path: Path, output_path: Path) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            [
                "uvx", "--from", "markitdown[all]",
                "markitdown", str(input_path), "-o", str(output_path),
            ],
            capture_output=True,
            text=True,
            timeout=120,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode == 0:
            if output_path.exists() and output_path.stat().st_size > 0:
                return True, "OK"
            return False, "输出文件为空"
        err_msg = result.stderr.strip()[:200] if result.stderr else "未知错误"
        return False, err_msg
    except subprocess.TimeoutExpired:
        return False, "转换超时（>120s）"
    except FileNotFoundError:
        return False, "uvx 命令未找到，请安装 uv 工具链"
    except Exception as exc:
        return False, str(exc)[:200]


def get_output_path(input_path: Path, output_dir: Path | None) -> Path:
    if output_dir:
        return output_dir / (input_path.stem + ".md")
    return input_path.with_suffix(".md")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="批量将目录下的文件转换为 Markdown 格式",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("directory", help="待转换文件所在目录路径")
    parser.add_argument("--output-dir", "-o", help="输出目录（默认与源文件同目录）")
    parser.add_argument("--recursive", "-r", action="store_true", help="递归扫描子目录（默认扫描一级子目录）")
    parser.add_argument("--dry-run", "-n", action="store_true", help="仅列出待转换文件，不执行转换")
    args = parser.parse_args()

    target_dir = Path(args.directory)
    if not target_dir.exists():
        print(f"❌ 目录不存在: {target_dir}")
        return 1
    if not target_dir.is_dir():
        print(f"❌ 路径不是目录: {target_dir}")
        return 1

    output_dir = Path(args.output_dir) if args.output_dir else None
    if output_dir and not output_dir.exists():
        output_dir.mkdir(parents=True, exist_ok=True)
        print(f"📁 创建输出目录: {output_dir}")

    files = find_convertible_files(target_dir, recursive=args.recursive)
    if not files:
        print(f"📁 目录: {target_dir}")
        print("⚠️  未找到可转换的文件")
        return 0

    print(f"📁 目录: {target_dir}")
    print(f"📄 扫描到 {len(files)} 个可转换文件\n")

    if args.dry_run:
        print("--- DRY RUN（仅预览，不执行转换）---\n")
        for file_path in files:
            out = get_output_path(file_path, output_dir)
            exists = "⚠️ 已存在" if out.exists() else ""
            print(f"  {file_path.suffix:8s}  {file_path.name}")
            print(f"        → {out.name}  {exists}")
        print(f"\n共 {len(files)} 个文件待转换")
        return 0

    success_count = 0
    fail_count = 0
    results: list[tuple[str, str, str, str]] = []

    for index, file_path in enumerate(files, 1):
        out_path = get_output_path(file_path, output_dir)
        print(f"[{index}/{len(files)}] 转换: {file_path.name} ...", end=" ", flush=True)

        ok, msg = convert_file(file_path, out_path)
        if ok:
            size_kb = out_path.stat().st_size / 1024
            print(f"✅ ({size_kb:.1f} KB)")
            success_count += 1
            results.append(("✅", file_path.name, out_path.name, msg))
        else:
            print(f"❌ {msg}")
            fail_count += 1
            results.append(("❌", file_path.name, "", msg))

    print("\n" + "=" * 60)
    print(f"📁 目录: {target_dir}")
    print(f"📄 扫描文件: {len(files)} 个")
    print(f"✅ 转换成功: {success_count} 个")
    print(f"❌ 转换失败: {fail_count} 个")
    print("=" * 60)
    print("\n转换清单:")
    for status, src, dst, msg in results:
        if status == "✅":
            print(f"  {status} {src} → {dst}")
        else:
            print(f"  {status} {src} → 失败（{msg}）")
    return 1 if fail_count > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
