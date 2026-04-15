---
name: solution-designer
description: >-
  当需要根据已确认需求设计可执行方案时使用。该 Skill 作为历史兼容入口，
  现统一输出可评审的 HLD 候选方案与推荐结论，并交由人工确认。
  触发词包括：方案设计、架构设计、复杂度判定、设计方案、simple/standard/complex 判断。
  适用场景：需求确认后的第一个设计步骤。
argument-hint: "可选：指定目标平台（如 copilot、claude-code）或约束条件"
user-invokable: true
status: active
---

## 目标

读取已确认的 `REQUIREMENTS.md`，先提炼问题边界，再生成至少 2 个候选方案与推荐结论，并将结果写入 `.output/doc/HLD.md`。该 Skill 是旧触发词到 HLD 流程的兼容入口；若需要正式 HLD 交付，优先使用 `hld-designer`。

## 核心原则

1. **边界先行**：先定义问题边界，再给方案
2. **多方案比较**：强制 ≥2 方案 + 六维度对比
3. **人工确认门控**：HLD 必须人工确认，未确认不输出下游规划文件
4. **可执行导向**：内容必须可直接用于 Story 拆解
5. **风险显性化**：每个方案必须列出风险与应对策略

## 前置条件

- [ ] `.output/doc/REQUIREMENTS.md` 存在且 `confirmed=true`
- [ ] `.output/doc/USE-CASES.md` 存在且 `status=confirmed`

## 执行步骤

1. 读取 `REQUIREMENTS.md`、`USE-CASES.md` 与补充约束
2. 输出问题定义：目标、约束、非目标、成功标准、关键假设、缺失信息
3. 设计至少 2 个候选方案，每个方案包含核心思路、关键模块、Mermaid 架构图、技术选型理由
4. 输出六维度对比：复杂度、成本、扩展性、风险、实施周期、维护性
5. 明确推荐方案，并写出推荐理由、局限性和演进路径
6. 将结果写入 `.output/doc/HLD.md`，设置 `status: ready-for-review` 与 `confirmed: false`
7. 停止，等待 meta-po 发起 HLD 确认

## 输出文件

| 文件 | 路径 | 输出时机 |
|------|------|---------|
| 高层设计 | `.output/doc/HLD.md` | 方案比较完成后 |

## 验收标准

- [ ] `HLD.md` 包含问题定义、候选方案对比、推荐方案、风险与待确认问题
- [ ] 至少 2 个候选方案，每个包含 Mermaid 架构图
- [ ] HLD 在人工确认前保持 `confirmed=false`
- [ ] 未修改 `REQUIREMENTS.md` 或 `USE-CASES.md`

## 不适用边界

- 需要的是某个 Story 的实现级设计（应使用 `lld-designer`）
- HLD 已经确认，当前任务是 Story 拆解或实现阶段
