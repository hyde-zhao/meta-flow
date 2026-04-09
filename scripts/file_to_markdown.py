#!/usr/bin/env python3
"""
File-to-Markdown 批量转换工具
将指定目录下的所有非 Markdown 文件转换为 Markdown 格式。

依赖：markitdown (通过 uvx 自动安装)

用法：
  python scripts/file_to_markdown.py <目录路径>
  python scripts/file_to_markdown.py <目录路径> --output-dir <输出目录>
  python scripts/file_to_markdown.py <目录路径> --recursive
  python scripts/file_to_markdown.py <目录路径> --dry-run
  python scripts/file_to_markdown.py --install   # 安装 SKILL.md 到 .agents/skills/
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

SKILL_MD_CONTENT = r'''---
name: file-to-markdown
description: >-
  当需要将目录下的非 Markdown 文件（Excel、Word、PDF、PPT、图片等）批量转换为 Markdown 格式时使用。
  触发词包括：转换文件、转为MD、文件转换、批量转换、导入文档。
  适用场景：元工作流任意阶段，需要将外部文档批量纳入工作流时。
argument-hint: "待转换文件所在目录路径"
user-invokable: true
status: active
---

## 目标

使用 `markitdown` CLI 工具，将用户指定目录下的所有非 Markdown 文件批量转换为 Markdown 文档，
使其可被工作流中的 Agent 和 Skill 读取和处理。

## 适用范围

- 适用阶段：元工作流任意阶段（需求输入、设计参考、耦合矩阵导入等）
- 典型场景：
  - 将整个特性资料目录（含 Excel/Word/PDF）批量转为 Markdown
  - 将耦合矩阵 Excel 文件转为 Markdown 供 F 分析使用
  - 将产品文档目录批量导入为可处理格式

## 支持的文件格式

| 格式 | 扩展名 | 说明 |
|------|--------|------|
| Excel | `.xlsx`, `.xls`, `.xlsm` | 表格转为 Markdown 表格，多 Sheet 用标题分隔 |
| Word | `.docx` | 保留标题层级和段落结构 |
| PDF | `.pdf` | 提取文本内容 |
| PowerPoint | `.pptx` | 逐页提取文本 |
| 图片 | `.jpg`, `.png`, `.bmp` | OCR 提取文本（需 OCR 支持） |
| HTML | `.html`, `.htm` | 转为 Markdown 格式 |
| CSV | `.csv` | 转为 Markdown 表格 |
| EPUB | `.epub` | 电子书转 Markdown |
| XMind | `.xmind` | 思维导图（可能部分支持） |

## 前置条件

- [ ] Python 环境可用（`python` 或 `python3`）
- [ ] `uvx` 命令可用（通过 `uv` 工具链安装）
- [ ] 用户已提供待转换目录路径

## 执行方式

Agent 收到用户提供的目录路径后，执行以下命令：

```powershell
python scripts/file_to_markdown.py "<目录路径>"
```

### 可选参数

| 参数 | 说明 |
|------|------|
| `--output-dir <路径>` | 指定输出目录（默认与源文件同目录） |
| `--recursive` | 递归扫描所有子目录 |
| `--dry-run` | 仅预览待转换文件，不执行转换 |

### 执行流程

1. 扫描目录及一级子目录，列出所有可转换文件
2. 对每个文件执行 `uvx --from "markitdown[all]" markitdown` 转换
3. 输出与源文件同目录的同名 `.md` 文件
4. 输出转换摘要（成功/失败/跳过计数）

## Gotchas

- Excel 含多 Sheet 时，所有 Sheet 依次转换，用二级标题分隔
- 含合并单元格的 Excel 转换后可能出现空列，需人工检查
- PDF 扫描件（图片型）依赖 OCR，转换质量取决于清晰度
- 中文文件名需确保路径用引号包裹
- 大文件（>10MB）转换可能较慢
- 同名 `.md` 文件已存在时会被覆盖

## 验收标准

- 目录下所有支持格式的文件均尝试转换
- 每个成功转换的 `.md` 文件存在且非空
- 输出转换摘要（成功/失败/跳过计数）
- 命令执行无未处理异常
'''

# 支持的文件扩展名
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

# 跳过的扩展名
SKIP_EXTENSIONS = {".md", ".markdown", ".txt"}


def find_convertible_files(directory: Path, recursive: bool = False) -> list[Path]:
    """扫描目录，返回所有可转换文件列表。"""
    files = []
    if recursive:
        for root, _dirs, filenames in os.walk(directory):
            for fname in filenames:
                fpath = Path(root) / fname
                if fpath.suffix.lower() in SUPPORTED_EXTENSIONS:
                    files.append(fpath)
    else:
        # 非递归：扫描当前目录 + 一级子目录
        for item in directory.iterdir():
            if item.is_file() and item.suffix.lower() in SUPPORTED_EXTENSIONS:
                files.append(item)
            elif item.is_dir():
                for sub_item in item.iterdir():
                    if sub_item.is_file() and sub_item.suffix.lower() in SUPPORTED_EXTENSIONS:
                        files.append(sub_item)
    return sorted(files)


def convert_file(input_path: Path, output_path: Path) -> tuple[bool, str]:
    """使用 markitdown 转换单个文件。返回 (成功, 消息)。"""
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
            # 检查输出文件是否非空
            if output_path.exists() and output_path.stat().st_size > 0:
                return True, "OK"
            else:
                return False, "输出文件为空"
        else:
            err_msg = result.stderr.strip()[:200] if result.stderr else "未知错误"
            return False, err_msg
    except subprocess.TimeoutExpired:
        return False, "转换超时（>120s）"
    except FileNotFoundError:
        return False, "uvx 命令未找到，请安装 uv 工具链"
    except Exception as e:
        return False, str(e)[:200]


def get_output_path(input_path: Path, output_dir: Path | None) -> Path:
    """计算输出文件路径。"""
    if output_dir:
        return output_dir / (input_path.stem + ".md")
    else:
        return input_path.with_suffix(".md")


def install_skill():
    """安装 SKILL.md 到 .agents/skills/file-to-markdown/ 目录。"""
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    skill_dir = project_root / ".agents" / "skills" / "file-to-markdown"

    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(SKILL_MD_CONTENT.strip() + "\n", encoding="utf-8")
    print(f"✅ SKILL.md 已安装到: {skill_file}")
    print(f"   Skill 目录: {skill_dir}")


def main():
    parser = argparse.ArgumentParser(
        description="批量将目录下的文件转换为 Markdown 格式",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("directory", nargs="?", help="待转换文件所在目录路径")
    parser.add_argument("--output-dir", "-o", help="输出目录（默认与源文件同目录）")
    parser.add_argument("--recursive", "-r", action="store_true",
                        help="递归扫描子目录（默认扫描一级子目录）")
    parser.add_argument("--dry-run", "-n", action="store_true",
                        help="仅列出待转换文件，不执行转换")
    parser.add_argument("--install", action="store_true",
                        help="安装 SKILL.md 到 .agents/skills/file-to-markdown/")
    args = parser.parse_args()

    if args.install:
        install_skill()
        sys.exit(0)

    if not args.directory:
        parser.error("请提供待转换目录路径，或使用 --install 安装 Skill")

    target_dir = Path(args.directory)
    if not target_dir.exists():
        print(f"❌ 目录不存在: {target_dir}")
        sys.exit(1)
    if not target_dir.is_dir():
        print(f"❌ 路径不是目录: {target_dir}")
        sys.exit(1)

    output_dir = Path(args.output_dir) if args.output_dir else None
    if output_dir and not output_dir.exists():
        output_dir.mkdir(parents=True, exist_ok=True)
        print(f"📁 创建输出目录: {output_dir}")

    # 扫描文件
    files = find_convertible_files(target_dir, recursive=args.recursive)
    if not files:
        print(f"📁 目录: {target_dir}")
        print("⚠️  未找到可转换的文件")
        sys.exit(0)

    print(f"📁 目录: {target_dir}")
    print(f"📄 扫描到 {len(files)} 个可转换文件\n")

    if args.dry_run:
        print("--- DRY RUN（仅预览，不执行转换）---\n")
        for f in files:
            out = get_output_path(f, output_dir)
            exists = "⚠️ 已存在" if out.exists() else ""
            print(f"  {f.suffix:8s}  {f.name}")
            print(f"        → {out.name}  {exists}")
        print(f"\n共 {len(files)} 个文件待转换")
        sys.exit(0)

    # 执行转换
    success_count = 0
    fail_count = 0
    results = []

    for i, fpath in enumerate(files, 1):
        out_path = get_output_path(fpath, output_dir)
        rel_name = fpath.name
        print(f"[{i}/{len(files)}] 转换: {rel_name} ...", end=" ", flush=True)

        ok, msg = convert_file(fpath, out_path)
        if ok:
            size_kb = out_path.stat().st_size / 1024
            print(f"✅ ({size_kb:.1f} KB)")
            success_count += 1
            results.append(("✅", rel_name, out_path.name, msg))
        else:
            print(f"❌ {msg}")
            fail_count += 1
            results.append(("❌", rel_name, "", msg))

    # 输出摘要
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

    sys.exit(1 if fail_count > 0 else 0)


if __name__ == "__main__":
    main()
