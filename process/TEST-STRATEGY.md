---
project_id: "meta-flow"
wave_scope: "W1-W6"
created_at: "2026-04-23T11:47:36+08:00"
---

# 测试策略

## 测试设计方法选择

| 方法 | 适用场景 | 本项目适用性 | 应用说明 |
|------|---------|------------|---------|
| 等价分区 | 不同产物类型、不同治理字段取值 | 高 | 对 `tool/skill/agent/workflow/mixed` 与 `direct/review-gated/conditional` 的说明完整性做分区检查 |
| 边界值分析 | Frontmatter 字段是否存在、可选附录是否完整 | 中 | 检查治理字段从“缺失”到“存在”的边界，以及 `Dx` 自定义维度说明 |
| 状态转换测试 | Skill/流程含显式阶段机 | 高 | 检查 `use-case-discovery` 的 Phase 0/1A/1B/2/3 与 `lld-designer` 的 6 阶段 |
| 错误推测 | 文档类产物常见缺陷 | 高 | 检查危险命令模式、遗漏治理字段、遗漏失败路径 |

## ISO 25010 质量特征优先级

| 质量特征 | 优先级 | 验证重点 | 对应验收维度 |
|---------|--------|---------|------------|
| 功能适合性 | P0 | W1/W2 产物是否完整覆盖 Story 目标 | 完整性、验收标准覆盖 |
| 可靠性 | P0 | 文档结构是否稳定、阶段和字段是否清晰可读 | Frontmatter 完整性、状态机可读性 |
| 安全性 | P0 | 无危险命令或注入型指令模式 | 安全合规 |
| 可维护性 | P1 | 命名、章节、字段语义是否统一 | 命名规范、Frontmatter 完整性 |
| 可移植性 | P1 | 交付文件路径是否符合 `delivery/` canonical 结构 | 平台适配、可安装性 |
| 易用性 | P2 | 触发词、步骤、附录是否足够明确 | 文档覆盖 |
| 兼容性 | P2 | 与现有 `meta-pm` / `meta-dev` 消费方式不冲突 | 验收标准覆盖 |
| 性能效率 | P3 | 文档长度合理 | 非本轮重点 |

## 质量门定义

### 入口准则（Entry Criteria）

- [x] Story 状态为 `ready-for-verification`
- [x] `VALIDATION-ENV.yaml` 存在且 `approval.confirmed=true`
- [x] W1 产物文件均已创建
- [x] `DEV-LOG.md` 已提供实现文件清单与验证入口

### 出口准则（Exit Criteria）

- [x] W1 的 BLOCKING 维度全部通过
- [x] 所有 REQUIRED 维度通过
- [x] 选定的测试设计方法已执行
- [x] `VERIFICATION-REPORT.md` 结论为 PASS

## 8 维度验收矩阵

| # | 维度 | 检查内容 | 阻断等级 | W1 验证方式 |
|---|------|---------|---------|------------|
| 1 | 完整性 | 产物文件数量 >= 期望输出数 | BLOCKING | 检查 4 个目标文件存在 |
| 2 | 平台适配 | 路径符合 `PLATFORM-INSTALL-SPEC.md` | BLOCKING | 检查均位于 `delivery/skills/...` canonical 树 |
| 3 | 验收标准覆盖 | 每条 W1 验收标准均有验证记录 | BLOCKING | 结构化关键字检查 |
| 4 | 安全合规 | 无危险命令模式 | BLOCKING | `grep` 风险模式检查 |
| 5 | 命名规范 | 文件名与目录结构规范 | REQUIRED | 检查 `SKILL.md` / `USE-CASES-TEMPLATE.md` / reference 路径 |
| 6 | Frontmatter 完整性 | 必填字段存在 | REQUIRED | 检查治理字段和状态字段 |
| 7 | 可安装性 | 交付目录满足安装脚本复制前提 | REQUIRED | 检查文件均位于 canonical `delivery/` 目录 |
| 8 | 文档覆盖 | 触发词、阶段、失败路径可读 | OPTIONAL | 结构化人工检查 |

## W3-W6 补充策略

### 重点验证对象

| Wave | 重点对象 | 重点方法 |
|------|---------|---------|
| W3 | review 模板、validator、LLD 消费契约 | 结构检查、脚本 dry-run、一致性检查 |
| W4 | 5 个 Agent 的 review mode / contract 文案 | 角色边界检查 |
| W5 | reviewer dispatch 与 rollout 文案 | README / rules 对照检查 |
| W6 | `STORY-PILOT-01.md`、`STORY-PILOT-01-LLD.md` | 14 章节检查、试点可消费性检查 |

### W3-W6 额外质量门

- [x] review 模板可被 validator 脚本通过
- [x] `validate_review_artifact.py` 不依赖第三方包
- [x] rollout 顺序保持“先 HLD/LLD，后广泛文档”
- [x] 试点 LLD 可被 review gate / meta-dev / meta-qa 三方读取
