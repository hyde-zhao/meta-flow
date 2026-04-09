---
story_id: STORY-05
title: Excel 批注读写工具
milestone: M2
wave: W1
priority: P0
status: verified
assigned_to: meta-dev
depends_on: []
requirements: [R4, R7]
---

# STORY-05: Excel 批注读写工具

## 完成准则

- [x] `scripts/excel_coupling_tool.py` 创建
- [x] 支持 openpyxl 解析（首选）+ zipfile+XML 回退
- [x] 三个子命令：read / write / query
- [x] 实际测试：从耦合矩阵 Excel 中成功读取 522 条批注
- [x] 查询功能：按特性名检索相关耦合点
- [x] 回写功能：支持新耦合点以批注形式写回 Excel

## 产出物

| 文件 | 状态 |
|------|------|
| `scripts/excel_coupling_tool.py` | ✅ 已创建 |

## 验证结果

- openpyxl 已安装并可用
- 实测读取 `NGFW系列 V60R1C00 特性树&耦合矩阵&形态差异三表.xlsx`：
  - 总批注数：522
  - 识别为耦合点：509（已过滤审阅类批注）
- 查询 "日志" 返回 43 条相关耦合点
- 图模型已保存为 `.mfq-work/f-analysis/coupling-graph.json`
- 支持强度推断（strong/weak/normal）
