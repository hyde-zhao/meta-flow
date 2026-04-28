---
version: "1.0"
confirmed: true
confirmed_by: "meta-po-delegated"
confirmed_at: "2026-04-23T11:47:36+08:00"
last_updated: "2026-04-28T00:00:00+08:00"
derived_from: "delivery/doc/PLATFORM-CONTRACTS.yaml"
---

# 平台安装规范（Story Planning）

## 1. 目的

为后续 Story 规划和实现提供统一的平台安装目标、规则入口和产物映射，避免 Story 在实现阶段各自定义安装结构。

本文件是可读规划说明；平台路径事实以 `delivery/doc/PLATFORM-CONTRACTS.yaml` 为单一真相源。若二者不一致，必须先修正 `PLATFORM-CONTRACTS.yaml` 并重新生成 / 同步本说明。

## 2. Canonical 源目录

所有可安装产物以 `delivery/` 为 canonical 源：

- `delivery/agents/`
- `delivery/skills/`
- `delivery/rules/`
- `delivery/scripts/`
- `delivery/.github/agents/`

## 3. 平台安装映射（项目级）

| 平台 | 项目级 Agent | 项目级 Skill | 规则入口 |
|---|---|---|---|
| Claude Code | `.claude/agents/` | `.claude/skills/` | `.claude/CLAUDE.md` |
| Codex | `.codex/agents/` | `.agents/skills/` | `AGENTS.md` |
| Copilot | `.github/agents/` | `.github/copilot/skills/` | `.github/copilot-instructions.md` |
| OpenClaw | `.openclaw/agents/` | `.openclaw/skills/` | `.openclaw/manifest.yaml` |

## 4. 平台安装映射（用户级）

| 平台 | 用户级 Agent | 用户级 Skill | 规则入口 |
|---|---|---|---|
| Claude Code | `~/.claude/agents/` | `~/.claude/skills/` | `~/.claude/CLAUDE.md` |
| Codex | `~/.codex/agents/` | `~/.agents/skills/` | `~/.codex/AGENTS.md` |
| Copilot | `~/.copilot/agents/` | `~/.copilot/skills/` | `~/.copilot/copilot-instructions.md` |
| OpenClaw | `~/.openclaw/agents/` | `~/.openclaw/skills/` | `~/.openclaw/manifest.yaml` |

## 5. Codex 官方契约断言

1. Codex Agent 与 Skill 不是同一发现路径：Agent 使用 `.codex/agents` / `~/.codex/agents`，Skill 使用 `.agents/skills` / `~/.agents/skills`。
2. Codex 项目级 Skill 禁止写入 `.codex/skills`。
3. Codex 用户级 Skill 禁止写入 `~/.codex/skills`。
4. 安装器、DryRun、平台校验和文档必须共同引用 `delivery/doc/PLATFORM-CONTRACTS.yaml`，不得凭平台目录类比推断路径。
5. 安装器写入任何目标前必须检查路径组件冲突：目标父路径任一级存在但不是目录时，必须输出 `安装路径被非目录占用: <path>` 并终止，不得暴露 Python traceback。

## 6. Story 规划期强制规则

1. Story 若修改 Agent/Skill/Rule 文件，卡片中必须写明其目标平台路径。
2. Skill 模板文件必须随 Skill 树一并安装；不得落到不会被安装脚本复制的随机目录。
3. 任何新增模板目录若需要安装到目标平台，应优先挂在 `delivery/skills/<skill>/templates/` 下。
4. 若确需仓库内部专用模板（如 review gate 汇总模板），必须在 Story 卡片中写明“**不随平台安装，仅供仓库运行态使用**”。
5. 涉及平台路径、schema 或发现机制时，必须引用官方文档或 `delivery/doc/PLATFORM-CONTRACTS.yaml` 中已记录来源；禁止用“同平台统一目录”之类类比替代事实。
6. 涉及安装器生成或修改时，验收必须包含“目标路径组件被普通文件占用”的负向用例。

## 7. 本轮 Story 计划中的平台影响

| Story | 平台影响 | 说明 |
|---|---|---|
| UCD-01 | 全平台 | 修改 `use-case-discovery` Skill 主体 |
| UCD-02 | 全平台 | 修改 `use-case-discovery` references/templates |
| UCD-03 | 全平台 | 修改 `meta-pm`、`requirement-extraction`、`skills/README` |
| LLD-01 | 全平台 | 修改 `lld-designer` Skill 主体 |
| LLD-02 | 全平台 | 修改 `lld-designer` 模板 |
| LLD-03 | 全平台 | 修改 `meta-dev` / `meta-qa` / rules 对 LLD 的消费契约 |
| RG-01 | 全平台 | 修改 `meta-po` 行为与 gate 协调 |
| RG-02 | 仓库运行态优先 | review 模板与静态检查脚本主要服务仓库内元工作流 |
| RG-03 | 全平台 | 修改 `meta-pm` / `meta-se` / `meta-qa` review mode |
| RG-04 | 全平台 | 修改 `meta-dev` / `meta-doc` review mode |
| RG-05 | 全平台 | 同步 README / rules / rollout 规则 |
| LLD-04 | 试点验证 | 验证新 LLD 写法与 gate 在实际 Story 中的可用性 |

## 8. 已收敛项 / 待确认点

1. RG-02 的共享评审资产已收敛到 `delivery/skills/review-artifact-protocol/`
2. RG-02 的静态前置检查脚本已收敛到 `delivery/skills/review-artifact-protocol/scripts/validate_review_artifact.py`
3. OpenClaw 的规则入口是否需要在本轮一并标准化
4. CR-001 已引入 `delivery/doc/PLATFORM-CONTRACTS.yaml` 和 Codex Skill 路径负向断言
5. CR-002 已引入安装路径组件冲突的前置校验与负向安装验证
