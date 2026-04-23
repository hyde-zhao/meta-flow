---
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

- [ ] Python 环境可用（通过 `uv run --python <version> python ...` 入口）
- [ ] `uvx` 命令可用（通过 `uv` 工具链安装）
- [ ] 用户已提供待转换目录路径

## 执行方式

Agent 收到用户提供的目录路径后，执行本 Skill 自带脚本：

```powershell
uv run --python 3.11 python <skill-root>/scripts/file_to_markdown.py "<目录路径>"
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
- Claude Code / Codex 安装后，脚本会随 Skill 一起复制到已安装的 skill 目录
