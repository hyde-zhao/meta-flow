---
request_id: "REQ-meta-flow-retro-20260424"
submitted_at: "2026-04-24T09:56:41+08:00"
submitted_by: "user"
engagement_mode: meta-self-dev
scenario_subject_type: implementation-carrier
scenario_subject_id: "meta-flow"
---

# REQUEST：meta-flow 当前项目追溯补录

> 本文件根据当前仓库已有 HLD、Story、交付物和本轮会话上下文追溯补录，用于恢复当前项目在 `process/` 层的最小必要请求上下文。

## 用户目标

1. 将当前仓库沉淀为一个可持续演进的 **SCOPE-Pack 元工作流产物工厂**。
2. 让该工作流能够覆盖：场景发现、需求结构化、HLD、Story 拆解、LLD、实现、验证、文档与安装交付。
3. 使交付结果可同时面向 **GitHub Copilot / Claude Code / Codex / OpenClaw** 安装与运行。
4. 在不破坏生产模式默认行为的前提下，支持对 **meta 工作流自身**做结构化优化、整改和规则收敛。
5. 通过规则、Skill、Agent、模板和仓库护栏，减少路径漂移、命名漂移、资产归属错误和安装后不可执行等问题。

## 目标平台

- [x] GitHub Copilot
- [x] Claude Code
- [x] Codex
- [x] OpenClaw

## 交付预期

1. `delivery/` 下具备可安装的 Agent、Skill、rules、scripts、README 和 USER-MANUAL。
2. `process/` 下具备支撑工作流运行的 HLD、架构决策、Story Backlog、Development Plan、LLD 方法、验证与状态文档。
3. 关键运行契约通过正式文件显式表达，而不是依赖会话中的隐式推理。
4. 交付资产遵守输出隔离、Skill 私有资产同树安装、跨平台安装和 guardrail 检查约束。

## 补充约束

1. 当前请求属于 **meta 工作流自我开发 / 优化**，因此：
   - `engagement_mode = meta-self-dev`
   - `scenario_subject_type = implementation-carrier`
   - `scenario_subject_id = meta-flow`
2. Python 命令统一使用 `uv run --python 3.11 python ...` 作为仓库默认入口。
3. `delivery/scripts/` 仅保留安装器入口；Skill 运行时脚本和模板必须下沉到各自 Skill 目录。
4. Story 与 LLD 文档命名必须带上名称 slug：
   - `STORY-{id}-{story_slug}.md`
   - `STORY-{id}-{story_slug}-LLD.md`
5. 若用户未显式声明 meta 工作流优化，后续新请求默认仍应回到 `production`，而不是继续沿用当前模式。
