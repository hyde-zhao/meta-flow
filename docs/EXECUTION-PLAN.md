# SCOPE-Pack Copilot CLI 实施执行计划

> ⚠️ 历史文档：本文件记录早期实施计划和旧版 `.workflow-meta` / `packages/` 设计，不作为当前使用说明。
> 当前对外使用文档请以 `docs/USER_GUIDE.md`、`docs/AGENT-SKILL-REFERENCE.md`、`README.md` 和 `AGENTS.md` 为准。
> 当前交付源目录为根目录 `agents/`、`skills/`、`rules/`，`packages/` 已移除。

> 文档状态：🔄 执行中
> 最后更新：2026-04-04
> 对应设计文档：`docs/20260403_防火墙测试元工作流融合设计方案.md`

---

## 总体进度

| Phase | 名称 | 状态 | 前置依赖 |
|-------|------|------|---------|
| P0 | 资产盘点与差距分析 | ✅ 已完成 | — |
| P1 | Copilot CLI 接入层 | ✅ 已完成 | P0 |
| P2 | Agent 角色升级 | ✅ 已完成 | P1 |
| P3 | Skill 补全 | ✅ 已完成 | P1 |
| P4 | 对象模板层 | ✅ 已完成 | P2 |
| P5 | 质量门与安全 | ✅ 已完成 | P3 |
| P6 | 平台安装脚本交付 | ✅ 已完成 | P4 + P5 |
| P7 | 端到端验证 | ✅ 已完成（自动化部分） | P6 |

---

## Phase 0：资产盘点与差距分析 ✅

**完成时间**：2026-04-04
**产物**：差距矩阵（见 `docs/20260403_防火墙测试元工作流融合设计方案.md`）

### 关键结论

| 资产类型 | 现有数量 | 可复用 | 需升级 | 需新建 |
|---------|---------|-------|-------|-------|
| Agent | 7 | 0（定位均为防火墙测试） | 5 | 2（meta-dev、meta-doc） |
| Skill | 31 | 21 | 1（dangerous-command-scan） | 5 |
| 脚本 | 6 | 5 | 1（install.py） | 1（跨平台安装脚本） |
| 对象模板 | 0 | — | — | 14 |

---

## Phase 1：Copilot CLI 接入层 ✅

**目标**：让 Copilot CLI 识别项目编排入口，`/agent` 可列出 meta-po，`/skills` 可发现全部 Skills。

### 任务清单

- [x] **T1.1** 分析 Copilot CLI 的 Agent/Skill 发现机制
- [x] **T1.2** 创建 `AGENTS.md`（项目根目录）→ 声明 meta-po 及 6 个功能 Agent
- [x] **T1.3** 创建 `.github/copilot-instructions.md` → 包含 Skill 清单、协议规则、5 个检查点、复杂度分流说明
- [ ] **T1.4** 验证 `/agent` 命令（需在 Copilot CLI 中手动验证）
- [ ] **T1.5** 验证 `/skills` 命令（需在 Copilot CLI 中手动验证）

**产物**：
- `AGENTS.md` ✅
- `.github/copilot-instructions.md` ✅

### T1.2 AGENTS.md 规格

**路径**：`D:\01_workspace\meta-work-flow\AGENTS.md`

**内容要点**：
- 声明本项目为 SCOPE-Pack 元工作流产物工厂
- 声明 meta-po 为主编排器（入口）
- 列出 6 个按需启用的功能 Agent 及其触发条件
- 声明工作目录约定（`.workflow-meta/` 为运行时对象目录）
- 声明对象文件协议（文件系统 Markdown/YAML 优先）

### T1.3 copilot-instructions.md 规格

**路径**：`D:\01_workspace\meta-work-flow\.github\copilot-instructions.md`

**内容要点**：
- 全局系统提示：本会话运行 SCOPE-Pack 元工作流
- Skill 发现路径：`.agents/skills/`（project 层）
- 状态文件路径：`.workflow-meta/STATE.md`
- 人工检查点约定：所有确认由 `ask_user` 工具触发
- 上下文预算约定：编排器不超过总 token 的 30%
- 禁止越级改写规则

### 验收标准

| 验收项 | 验证方式 | 预期结果 |
|--------|---------|---------|
| Agent 发现 | `/agent` | 列出 meta-po 及功能 Agent |
| Skill 发现 | `/skills` | 列出 31+ Skills |
| 触发词响应 | 输入"推进" | state-router 被自动调用 |
| 上下文隔离 | 切换 Agent | 仅加载对应 Agent 声明的上下文 |

---

## Phase 2：Agent 角色升级 ✅

**目标**：7 个新 Agent 文件（SCOPE-Pack 定位），不含防火墙专属硬编码。

### 任务清单

- [x] **T2.1** 创建 `meta-po.md`（升级自 meta-orchestrator）→ 10 状态机、5 个检查点、变更管理
- [x] **T2.2** 创建 `meta-pm.md`（升级自 requirement-analyst）→ 多轮澄清循环
- [x] **T2.3** 创建 `meta-se.md`（新建，方案设计）→ 三档复杂度判定
- [x] **T2.4** 创建 `meta-dm.md`（升级自 workflow-planner）→ Story 拆解、Wave 设计
- [x] **T2.5** 创建 `meta-dev.md`（新建，Story 实现）→ 文件输出规范、阻塞处理
- [x] **T2.6** 创建 `meta-qa.md`（整合 delivery-agent + safety-reviewer）→ 8 维度验收 + 安装脚本交付
- [x] **T2.7** 创建 `meta-doc.md`（新建，文档输出）→ README + USER-MANUAL

**产物**：`.agents/agents/meta-po/pm/se/dm/dev/qa/doc.md`（7 个文件）✅

### 关键设计：meta-po 状态机（10 状态）

```
init
 └─► requirement-clarification
      └─► solution-design
           ├─► [simple]  skill-production
           │                 └─► verification
           └─► [standard/complex]  story-planning
                                        └─► story-development
                                                  └─► verification
                                                           └─► packaging
                                                                    └─► documentation
                                                                              └─► human-final-review
                                                                                        └─► delivered
```

---

## Phase 3：Skill 补全 ✅

**目标**：新建 5 个缺失 Skill，补全 SCOPE-Pack 能力矩阵。

### 任务清单

- [x] **T3.1** 创建 `solution-designer` Skill → 复杂度判定 + 3 输出文件
- [x] **T3.2** 创建 `story-manager` Skill → Story 生命周期 + 三件套模板
- [x] **T3.3** 创建 `package-builder` Skill → 4 平台安装脚本生成
- [x] **T3.4** 创建 `platform-validator` Skill → 5 维度安装目标校验
- [x] **T3.5** 创建 `requirement-clarifier` Skill → 多轮澄清 + 阻断等级
- [x] **T3.6** 升级 `dangerous-command-scan` → 扩展 Prompt 注入检测（4 层扫描）

**产物**：5 个新 Skill 目录 + 1 个升级 Skill ✅

---

## Phase 4：对象模板层 ✅

**目标**：`.workflow-meta/templates/` 下 14 个模板文件，格式完整可用。

### 任务清单

- [x] **T4.1** 创建目录 `.workflow-meta/templates/`（含 stories/、changes/、scripts/）
- [x] **T4.2** `STATE.md` 模板（含 10 状态转换表注释）
- [x] **T4.3** `REQUEST.md` 模板
- [x] **T4.4** `CLARIFICATION-LOG.md` 模板（多轮追加格式）
- [x] **T4.5** `REQUIREMENTS.md` 模板（含状态 Frontmatter）
- [x] **T4.6** `SOLUTION-DESIGN.md` 模板
- [x] **T4.7** `ARCHITECTURE-DECISION.md` 模板（含确认点清单）
- [x] **T4.8** `STORY-BACKLOG.md` 模板
- [x] **T4.9** `STORY-STATUS.md` 模板
- [x] **T4.10** `DEVELOPMENT-PLAN.yaml` 模板（Wave/Lane 结构）
- [x] **T4.11** `STORY-TEMPLATE.md`（三件套 + 8 维度验收标准）
- [x] **T4.12** `VALIDATION-ENV.yaml` 模板
- [x] **T4.13** `VERIFICATION-REPORT.md` 模板
- [x] **T4.14** `INSTALL-MANIFEST.yaml` 模板
- [x] **T4.15** `CR-TEMPLATE.md` 模板
- [x] **T4.16** `.workflow-meta/PLATFORM-INSTALL-SPEC.md`（4 平台完整规范）

**产物**：15 个模板文件 + PLATFORM-INSTALL-SPEC.md ✅

---

## Phase 5：质量门与安全 ✅

**目标**：8 维度 Story 验收体系可执行，安全扫描覆盖 Prompt 注入。

### 任务清单

- [x] **T5.1** 在 meta-qa 中实现 8 维度验收矩阵（含量化校验方式）
- [x] **T5.2** 配置验证环境门控（无 VALIDATION-ENV.yaml 则输出明确阻断提示）
- [x] **T5.3** 升级 dangerous-command-scan（新增 4 层扫描 + Prompt 注入 4 类模式）
- [x] **T5.4** 实现 Story 完整性锁（三件套检查在 story-manager Skill 中强制）

**产物**：meta-qa.md（8 维度）、dangerous-command-scan 升级 ✅

---

## Phase 6：平台安装脚本交付 ✅

**目标**：`scripts/install.py` 可覆盖 4 个平台的项目级与用户级安装。

### 任务清单

- [x] **T6.1** 创建 `scripts/install.py`（含 DryRun 模式）
- [x] **T6.2** 实现 GitHub Copilot 安装目标（`.github/` 或 `~/.copilot/`）
- [x] **T6.3** 实现 Claude Code 安装目标（`.claude/` 或 `~/.claude/`）
- [x] **T6.4** 实现 Codex 安装目标（`.codex/` 或 `~/.codex/`，YAML 格式自动转换）
- [x] **T6.5** 实现 OpenClaw 安装目标（`.openclaw/` 或 `~/.openclaw/` + 自动生成 manifest.yaml）
- [x] **T6.6** 提供 `install.ps1` / `install.sh` 包装脚本
- [x] **T6.7** DryRun、命名规范与入口文件校验

**验证**：`python scripts/install.py --platform claude-code --dry-run`、`python scripts/install.py --platform openclaw --scope user --dry-run` ✅

---

## Phase 7：端到端验证 ✅（自动化部分）

**目标**：三档模式各走通一次完整 Copilot CLI 对话流程。

### 任务清单

- [x] **T7.1** 生成实际 4 平台安装脚本并完成 DryRun 验证
- [x] **T7.2** 创建 Simple 模式示例 STATE.md（`.workflow-meta/demo-simple-STATE.md`）演示完整 10 状态流转
- [x] **T7.3** 最终验收：P1~P7 所有 PASS 项自动化验证通过
- [ ] **T7.4** Standard 模式真实 Copilot CLI 对话（需人工在 CLI 中操作）
- [ ] **T7.5** Complex 模式真实 Copilot CLI 对话 + /fleet 并行（需人工在 CLI 中操作）

### 自动化验证结果

```
[P1] Copilot CLI 接入文件        AGENTS.md ✓  copilot-instructions.md ✓
[P2] Agent 文件（7个）           meta-po/pm/se/dm/dev/qa/doc 全部 PASS
[P3] Skill（5新建+1升级）        全部 PASS
[P4] 对象模板（14个+规范文档）    14/14 PASS + PLATFORM-INSTALL-SPEC.md PASS
[P6] 安装脚本与4平台安装目标      全部 PASS，DryRun 行为通过
```

### 剩余人工验证步骤（上线前）

1. 在 Copilot CLI 中执行 `/skills`，确认 29 个 Skills 被发现
2. 输入"开始新工作流"，确认 meta-po 自动初始化 STATE.md
3. 走完 simple 模式完整对话（预计 4~6 轮）

### 验收标准

| 验收项 | Simple | Standard | Complex |
|--------|--------|----------|---------|
| STATE.md 状态转换完整 | ✓ | ✓ | ✓ |
| 人工检查点触发 | 1 次 | 3 次 | 5 次 |
| 安全扫描通过 | ✓ | ✓ | ✓ |
| 安装脚本验证 | 1 平台 | 2 平台 | 4 平台 |
| Story 并行（/fleet） | — | — | ✓ |

---

## 附录：文件变更总清单

### 新建文件（Phase 1 起）

```
AGENTS.md
.github/copilot-instructions.md
.agents/agents/meta-po.md
.agents/agents/meta-pm.md
.agents/agents/meta-se.md
.agents/agents/meta-dm.md
.agents/agents/meta-dev.md
.agents/agents/meta-qa.md
.agents/agents/meta-doc.md
.agents/skills/solution-designer/SKILL.md
.agents/skills/story-manager/SKILL.md
.agents/skills/package-builder/SKILL.md
.agents/skills/platform-validator/SKILL.md
.agents/skills/requirement-clarifier/SKILL.md
.workflow-meta/templates/STATE.md
.workflow-meta/templates/REQUEST.md
.workflow-meta/templates/CLARIFICATION-LOG.md
.workflow-meta/templates/REQUIREMENTS.md
.workflow-meta/templates/SOLUTION-DESIGN.md
.workflow-meta/templates/ARCHITECTURE-DECISION.md
.workflow-meta/templates/STORY-BACKLOG.md
.workflow-meta/templates/STORY-STATUS.md
.workflow-meta/templates/DEVELOPMENT-PLAN.yaml
.workflow-meta/templates/STORY-TEMPLATE.md
.workflow-meta/templates/VALIDATION-ENV.yaml
.workflow-meta/templates/VERIFICATION-REPORT.md
.workflow-meta/templates/INSTALL-MANIFEST.yaml
.workflow-meta/templates/CR-TEMPLATE.md
.workflow-meta/PLATFORM-INSTALL-SPEC.md
scripts/install.py
```

### 升级文件（保留原文件）

```
.agents/skills/dangerous-command-scan/SKILL.md  ← 扩展 Prompt 注入检测
scripts/install.py                               ← 新增 scope-pack 模式
```

### 保留不动（防火墙测试资产）

```
.fw-meta/                           ← 完整保留
.agents/agents/meta-orchestrator.md
.agents/agents/requirement-analyst.md
.agents/agents/vendor-adapter.md
.agents/agents/workflow-planner.md
.agents/agents/plan-checker.md
.agents/agents/safety-reviewer.md
.agents/agents/delivery-agent.md
scripts/（现有 6 个脚本，除 install.py）
```
