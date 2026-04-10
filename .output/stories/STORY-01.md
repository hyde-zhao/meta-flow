---
story_id: STORY-01
title: Agent 编排器骨架
milestone: M1
wave: W1
priority: P0
status: verified
assigned_to: meta-dev
depends_on: []
requirements: []
---

# STORY-01: Agent 编排器骨架

## 完成准则

- [x] `agents/ptm-tde.md` 创建，包含完整状态机定义
- [x] `.github/agents/ptm-tde.agent.md` 创建（Copilot CLI 入口）
- [x] 10 步主流程 + 2 扩展分支定义完整
- [x] Skill 触发词映射表完整
- [x] `mfq/` 目录结构定义完整
- [x] 用户确认点定义（4 个节点）

## 产出物

| 文件 | 状态 |
|------|------|
| `agents/ptm-tde.md` | ✅ 已创建 |
| `.github/agents/ptm-tde.agent.md` | ✅ 已创建 |

## 验证结果

- Agent 定义包含 10 步状态机 + 2 扩展分支
- 14 个 Skill 触发词映射完整
- 运行时目录结构定义完整
- 物理用例字段规范和优先级定义已嵌入
