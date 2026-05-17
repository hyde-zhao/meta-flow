---
complexity: standard
confirmed: true
confirmed_by: "meta-po-delegated"
confirmed_at: "2026-04-23T11:47:36+08:00"
last_updated: "2026-05-15T00:00:00+08:00"
---

# 架构决策（Story Planning）

## Agent/Skill 组合方案

### 已确认的主题 HLD 组合

1. `process/HLD.md`：负责 `use-case-discovery` 的产物类型感知与治理字段生产
2. `process/HLD-review-gate.md`：负责阶段出口文档并行评审门禁
3. `process/HLD-lld-writing-method.md`：负责 Story 级 LLD 写作方法与消费契约

### Story-Planning 采用的 Skill 组合

| 目标 | Skill / 机制 | 用途 |
|---|---|---|
| Story 边界收敛 | `story-manager` | 生成 Story 卡片与状态汇总 |
| 依赖映射 | `dependency-mapper` | 显式建立 Story `depends_on` |
| Wave 划分 | `wave-planner` | 根据依赖与并行安全性收敛 Wave |
| DAG 校验 | `dag-validator` | 校验 `DEVELOPMENT-PLAN.yaml` 无环且无无效引用 |

### 关键决策

| ADR | 决策 | 说明 |
|---|---|---|
| ADR-SP-01 | 保持 3 份 HLD 分离，不再合并 | 避免 use-case 发现、review gate、LLD 方法混层 |
| ADR-SP-02 | 采用 12 Story 基线 | UCD 3 + LLD 4 + RG 5 |
| ADR-SP-03 | LLD 采用方案 A | **所有 Tier 都保持 14 个可见章节**；Tier-S 只允许内容极简，不允许裁成 8 章 |
| ADR-SP-04 | 正式 Wave 以依赖图为准 | 将先前 4-Wave 草案细化为 **6-Wave** 正式计划 |
| ADR-SP-05 | Review gate 不新增专职 reviewer Agent | 复用现有子 Agent 的 `review_mode=true` |
| ADR-SP-06 | LLD 复杂度分级保留，但不影响章节外形 | `tier: S/M/L` 只影响深度与图示，不影响章节数量 |
| ADR-SP-07 | 平台路径以 `delivery/doc/PLATFORM-CONTRACTS.yaml` 为单一真相源 | 安装器、DryRun、平台校验与规划说明都从该契约派生；禁止按同平台目录类比推断路径 |
| ADR-SP-08 | Codex 编排采用 `meta-po` 单例 + role/task registry | 同一工作流最多 1 个 `meta-po`；下游 agent 通过 `workflow_id/change_id/wave_id/story_id` 精确复用，检查点或交接完成后关闭 |
| ADR-SP-09 | Codex 上下文控制采用最小 handoff 包而非全量 fork | 默认 `fork_context=false`；只传 STATE 当前片段、当前 CR、当前 Story/Wave、必要设计对象和路径契约，禁止传完整会话历史与全量 stories |
| ADR-SP-10 | Story 计划确认与 LLD 确认合并为 Story Package 确认 | `meta-se` 产出 Story Package 草案后，由 `meta-dev` 为当前 Wave 产出 LLD 包；meta-po 发起一次合并确认后才允许实现 |
| ADR-SP-11 | 安装 CLI 使用 `scope-pack install` 与 `--component rules|agent|full` | user scope 默认 `rules`；project scope 默认 `agent`；legacy `--content` 只作兼容入口 |
| ADR-SP-12 | 平台确认协议保留结构化优先但 Codex 默认 exact 文本 | Claude Code 优先结构化选择；Codex 仅在当前工具面明确提供可用 `request_user_input` / 选择 UI 时使用结构化选择，否则只向用户展示 `approve`、`修改: <具体修改点>`、`reject` 三个推荐回复，历史别名仅兼容解析 |
| ADR-SP-13 | 交付出口按 engagement mode 路由 | `meta-self-dev` 写当前仓库 `delivery/`；production 先读目标 README/docs 约定，无约定则提建议并等待确认 |

## 平台适配差异

| 平台 | Agent 安装位置 | Skill 安装位置 | 关键约束 |
|---|---|---|---|
| Claude Code | `.claude/agents/*.md` | `.claude/skills/<skill>/` | `CLAUDE.md` 作为项目规则入口 |
| Codex | `.codex/agents/*.toml` | `.agents/skills/<skill>/` | Agent 需转换为 TOML；内建 agent 名称不可冲突 |
| Copilot | `.github/agents/*.agent.md` | `.github/copilot/skills/<skill>/` | 规则入口为 `.github/copilot-instructions.md` |
| OpenClaw | `.openclaw/agents/*.md` | `.openclaw/skills/<skill>/` | 与 canonical delivery 结构保持一对一映射 |

### 规划阶段适配原则

1. `delivery/doc/PLATFORM-CONTRACTS.yaml` 作为平台安装路径单一真相源；`PLATFORM-INSTALL-SPEC.md` 是 story-planning 阶段的可读说明。
2. Story 卡片若涉及安装路径、模板路径、规则入口，必须直接写明目标平台差异。
3. `delivery/skills/README.md` 必须同步维护 Agent/Skill 关系和模板交叉引用。
4. Codex Agent 与 Skill 发现路径必须分开断言：Agent 在 `.codex/agents` / `~/.codex/agents`，Skill 在 `.agents/skills` / `~/.agents/skills`。
5. `scope-pack install --component rules|agent|full` 是新安装入口；`--content all|agents|skills|rules` 仅保留 legacy 兼容。
6. production 项目的交付出口不得从 meta-flow 当前仓库 `delivery/` 推断，必须先读取目标 README/docs 或获得用户确认。

## 设计确认点（需人工确认）

1. **12 Story 边界是否认可**
2. **6-Wave 正式计划是否认可**
3. **LLD 保持 14 个可见章节** 是否认可
4. `RG-02` 中 review 共享资产是否收敛为 `delivery/skills/review-artifact-protocol/`
5. `LLD-04` 试点 Story 是否作为 story-execution 的首个试点 Wave 收尾项

## 变更记录

| 版本 | 日期 | 变更人 | 说明 |
|---|---|---|---|
| 1.0 | 2026-04-23 | meta-se | 基于 3 份已确认 HLD 与用户确认的 Story 拆分方向，产出 story-planning 阶段架构决策 |
| 1.1 | 2026-04-28 | meta-po | CR-001：补充平台契约单一真相源与 Codex Agent/Skill 路径分离原则 |
| 1.2 | 2026-05-15 | meta-po | CR-004：新增 `meta-po` 单例、上下文最小 handoff、Story Package 确认、安装组件 CLI、平台确认协议和交付出口路由决策 |
