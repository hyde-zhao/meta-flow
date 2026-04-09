---
story_id: STORY-02
title: feature-parser Skill
milestone: M1
wave: W1
priority: P0
status: verified
assigned_to: meta-dev
depends_on: []
requirements: [R1]
---

# STORY-02: feature-parser Skill

## 完成准则

- [x] `.agents/skills/feature-parser/SKILL.md` 创建
- [x] 支持 4 种输入格式（MD/Word/Excel/PDF）
- [x] 需求条目提取流程定义（编号/模块/SR名称/描述）
- [x] 三~五级目录构建规则定义
- [x] 用户确认交互流程定义
- [x] 输出文件格式定义（raw-requirements.md + directory-structure.md）

## 产出物

| 文件 | 状态 |
|------|------|
| `.agents/skills/feature-parser/SKILL.md` | ✅ 已创建 |

## 验证结果

- Skill 定义包含完整的 5 步执行流程
- 支持非 MD 格式的预转换（联动 file-to-markdown）
- 目录结构构建规则清晰（三级=特性，四级=模块，五级=子模块）
- 输出格式与后续 m-analyzer 的输入契约对齐
