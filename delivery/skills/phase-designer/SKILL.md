---
name: phase-designer
description: >-
  当需要将需求和场景组织为执行阶段时使用。
  触发词包括：阶段划分、设计阶段、Phase 设计、执行顺序、阶段目标、长期路线、Roadmap。
  适用场景：工作流计划设计的第一步。
argument-hint: "REQUIREMENTS.md 和 SCENARIOS.yaml 路径"
user-invokable: true
status: active
---


## vNext 过程引用契约

- `process/...` 是过程仓逻辑引用，不是发布仓中的相对物理路径。
- 首次文件系统 I/O 前必须调用 `meta-flow project resolve-ref --project-root <release-root> --logical-ref <process/...> --format json`。
- 只可瞬时使用成功 JSON 中的 `resolved_path`；不得把绝对路径写入治理文件、Prompt 产物或 Git。
- 命令以退出码 2 返回 BLOCKED 时必须停止；不得自行拼 sibling、去掉 `process/`、恢复软链接或回退 legacy。
- legacy-only 操作必须交还 Host Orchestrator，并使用独立 typed authorization；本 Skill 不构造 legacy capability。

## 目标

根据需求、场景、风险、现有长期 Roadmap 和依赖关系，将执行活动组织为有序阶段（Phase）；规划前先证明目标不能由现有 Phase 的 Work/工作流承载，再允许提出新 Phase。

## 适用场景

- Story / 工作流计划设计的第一步
- 需要决定阶段边界、顺序与进入 / 退出条件
- 需要判断新目标应进入现有 Phase，还是形成新的长期 Phase
- 用户要求比较当前长期路线与候选实施阶段

## 前置条件

- [ ] 若本 skill 需要写入任何 `process/*` 文件，必须先确认 Host Orchestrator 已完成 process route health check；未确认时先交还 Host Orchestrator 执行 `meta-flow workspace check`，不得自行创建、修复或重建 `process`。
- [ ] `REQUIREMENTS.md` 已确认
- [ ] `SCENARIOS.yaml` 已生成
- [ ] 对已有项目，已按 `PROJECT → roadmap_ref → 全部 declared phase_refs` 读取现有长期路线；新项目可明确标记 N/A

## 必须读取的输入

- `docs/product/REQUIREMENTS.md`
- `docs/product/SCENARIOS.yaml`
- 已有项目的 `process/PROJECT.yaml`、其声明的 `roadmap_ref` 和 Roadmap 中全部 `phase_refs`
- active Phase `result_refs` 中声明的实施计划（仅在需要判定详细重叠时）
- 相关约束或平台限制（若存在）

## 知识来源

- 需求优先级、场景类型与依赖关系
- 现有阶段设计规则：前置检查优先、清理阶段兜底
- Project/Roadmap/Phase 是长期阶段机器真相；memory、目录命名和最近对话不是 Phase 发现机制
- Phase 表示独立生命周期结果；Story、CR、Wave 和短期步骤默认是 Phase 内执行对象

## 执行步骤

1. 对已有项目，通过 resolver 读取 `process/PROJECT.yaml`，只沿 `roadmap_ref` 读取 Roadmap，再按声明顺序读取全部 `phase_refs`；禁止 sibling discovery、目录扫描或按编号猜测。
2. 核对现有 Phase 的状态、目标、进入/退出边界和非目标。若 active Phase 的详细边界不在机器字段中，只按其 `result_refs` 读取声明的实施计划/治理基线。
3. 为候选目标生成 Phase 重叠矩阵：

   | 比较项 | 现有 Phase | 候选目标 | 判定 |
   |---|---|---|---|
   | 生命周期结果 |  |  | overlap/distinct |
   | 进入条件 |  |  | overlap/distinct |
   | 退出条件 |  |  | overlap/distinct |
   | 非目标 |  |  | compatible/conflict |
   | 时间跨度 |  |  | work/phase |

4. 若候选目标能在 active/planned Phase 内通过 Work、工作流或 Wave 完成，复用现有 Phase；只有生命周期结果、进入/退出条件和非目标均具有独立边界时，才提出新 Phase。
5. 对确需新增或调整的 Phase，按目标、风险和依赖关系定义顺序、进入条件、退出条件、非目标和失败行为。
6. 回答区分 `机器事实`、`解释/推断`、`规划建议`；建议不构成创建 Phase、Work、CR 或实施授权。
7. 将批准后的执行阶段写入 `process/DEVELOPMENT-PLAN.yaml`；长期 Roadmap/PHASE 变更必须另走其 owner 和人工决策，不能由本 Skill 静默改写。

## 输出文件 / 输出模板

输出为 `process/DEVELOPMENT-PLAN.yaml` 中的阶段结构；不直接依赖模板文件。

## 约束

- 阶段间串行，阶段内任务可交给后续 Wave 规划决定
- 清理 / 收尾阶段不得省略
- 依赖需求与场景内容契约，而非模板可用性
- 默认查询预算为 5 对象；长期路线允许 `PROJECT + ROADMAP + 全部 declared phase_refs` 的有界例外，不授权 Work/CR/legacy 全历史扩读
- 已有 Phase 可以承载时禁止为展示整齐或编号连续而新建 Phase
- project memory 只作线索；与仓库冲突时以 Project/Roadmap/Phase 为准

## 验收标准

- [ ] 每个阶段有明确目标与顺序
- [ ] 阶段边界合理，清理阶段存在
- [ ] 全部场景被纳入至少一个阶段
- [ ] 已读取 PROJECT、roadmap_ref 和全部 declared phase_refs，或明确记录新项目 N/A
- [ ] 已输出 Phase 重叠矩阵，且每个新 Phase 都有不能复用现有 Phase 的证据
- [ ] active Phase 详细计划只来自其 result_refs；sibling discovery=0
- [ ] 输出区分机器事实、解释/推断和规划建议

## 不适用边界

- 当前任务只需生成测试场景，不需要阶段设计
- 需求与场景尚未收敛

## Gotchas

- 阶段设计过细会导致后续 Wave 规划碎片化
- 把高风险任务和普通任务混在同一阶段会削弱隔离效果
- 把五个实施步骤直接命名为五个长期 Phase，会制造与既有 Roadmap 重叠的双重真相
- “当前没有 active Work”只说明运行态空闲，不说明长期 Phase 已完成或不存在
- 默认 5 对象预算不能成为漏读 declared Phase 的理由；应使用有界例外，而不是目录扫描
- 不要依据 memory 或旧 HLD 创建 Phase；先恢复当前机器真相和重叠矩阵
