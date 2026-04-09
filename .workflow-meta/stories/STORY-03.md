---
story_id: STORY-03
title: scenario-discovery Skill
milestone: M1
wave: W1
priority: P0
status: verified
assigned_to: meta-dev
depends_on: []
requirements: [R2, R17]
---

# STORY-03: scenario-discovery Skill

## 完成准则

- [x] `.agents/skills/scenario-discovery/SKILL.md` 创建
- [x] `scripts/mcp_query_client.py` 创建，定义查询契约
- [x] MCP 查询 → Web 搜索的回退策略定义
- [x] 场景结构化格式定义（7 字段）
- [x] 用户交互确认流程定义
- [x] 输出文件格式定义（confirmed-scenarios.md）

## 产出物

| 文件 | 状态 |
|------|------|
| `.agents/skills/scenario-discovery/SKILL.md` | ✅ 已创建 |
| `scripts/mcp_query_client.py` | ✅ 已创建 |

## 验证结果

- Skill 定义包含三级搜索策略（MCP → Web → 用户材料）
- MCP 客户端支持 4 种查询类型（scenario/feature/deployment/coupling）
- 场景结构化包含完整字段（编号/名称/分类/描述/触发/处理/异常）
- MCP 未配置时可优雅降级到 Web 搜索关键词建议
