---
story_id: "UCD-02"
story_title: "use-case-discovery 模板与引用增强"
status: "confirmed"
tier: "S"
confirmed: true
confirmed_by: "meta-po-delegated"
confirmed_at: "2026-04-23T11:47:36+08:00"
created_at: "2026-04-23T11:47:36+08:00"
updated_at: "2026-04-23T11:47:36+08:00"
source_story: "process/stories/STORY-UCD-02.md"
source_hld:
  - "process/HLD.md"
architecture_decision: "process/ARCHITECTURE-DECISION.md"
platform_spec: "process/PLATFORM-INSTALL-SPEC.md"
---

# LLD - UCD-02 use-case-discovery 模板与引用增强

## 1. Goal

为 `use-case-discovery` 配套稳定的参考资料和模板，使治理字段、8 维发现框架和覆盖自检表有统一承载物，并可被上下游直接消费。

## 2. Requirements

### Functional

- F1：新增或补齐 `8-dimensions-framework.md`，明确 D1-D8 与 Dx。
- F2：扩展 `USE-CASES-TEMPLATE.md` frontmatter，容纳治理字段。
- F3：模板正文必须包含治理附录与覆盖自检表。

### Non-Functional

- NF1：模板需保持 Markdown 友好，可直接人工编辑。
- NF2：模板字段名称需与 `use-case-discovery` Skill 输出口径一致。
- NF3：不得把 review gate 专属字段混入用例模板。

## 3. 模块拆分与职责

| 模块 | 职责 | 输入 | 输出 |
|---|---|---|---|
| Reference Doc | 固化 8 维发现框架 | HLD 维度定义 | `8-dimensions-framework.md` |
| Template Frontmatter | 承载治理字段 | Skill 输出字段 | frontmatter 字段规范 |
| Coverage Appendix | 承载覆盖自检与治理附录 | discovery 结果 | 模板附录 |

## 4. 代码结构与文件影响范围

| 动作 | 文件 | 说明 |
|---|---|---|
| 创建/修改 | `delivery/skills/use-case-discovery/references/8-dimensions-framework.md` | 固化 D1-D8 与扩展维 |
| 修改 | `delivery/skills/use-case-discovery/templates/USE-CASES-TEMPLATE.md` | 扩展字段与正文附录 |

## 5. 数据模型与持久化设计

需要固化到模板 frontmatter 的字段：

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `target_artifact_type` | enum | 非空 | 对应 discovery 主分类 |
| `governance_mode` | enum | 非空 | 决定后续是否触发门禁 |
| `review_policy` | enum | 非空 | 决定评审强度 |

无额外持久化模型。

## 6. API / Interface 设计

| 接口 | 输入 | 输出 | 异常 |
|---|---|---|---|
| `use-case-discovery` -> 模板 | 治理字段、用例内容 | 标准化 `USE-CASES.md` 结构 | 字段名不一致 |
| 模板 -> `requirement-extraction` | 已结构化场景与附录 | 可消费的 use case 文档 | 附录缺失导致提取上下文不足 |

## 7. 核心处理流程

1. 从 HLD 和 Skill 主体提炼标准治理字段。
2. 将治理字段加入模板 frontmatter。
3. 为模板正文增加 8 维映射说明、治理附录和覆盖自检表。
4. 确保上下游都能按统一字段读取。

### 异常流程

- 若模板字段与 Skill 输出不一致，以 Skill 输出为准并回写模板。
- 若 8 维框架与模板附录重复定义同一概念，统一引用 reference 文档，模板不重复展开。

## 8. 技术设计细节

- `8-dimensions-framework.md` 只解释维度和使用方法，不承载实例化项目内容。
- `USE-CASES-TEMPLATE.md` 通过锚点划分“主正文 / 治理附录 / 覆盖自检表”。
- frontmatter 名称与 Skill 输出保持 exact match。

## 9. 安全与性能设计

- 均为静态 Markdown 文件，无运行时代码风险。
- 禁止在模板中加入会误导用户的默认结论。

## 10. 测试设计

| 测试点 | 输入场景 | 期望结果 |
|---|---|---|
| T-01 | 打开模板 frontmatter | 可见 3 个治理字段 |
| T-02 | 打开 reference 文档 | 包含 D1-D8 与 Dx |
| T-03 | 检查模板正文 | 包含治理附录与覆盖自检表 |

## 11. 实施步骤

| TASK-ID | 动作 | 目标文件 | 详细步骤 | 验证对应 |
|---|---|---|---|---|
| T1 | 创建/修改 | `delivery/skills/use-case-discovery/references/8-dimensions-framework.md` | 固化 D1-D8 与 Dx 说明 | T-02 |
| T2 | 修改 | `delivery/skills/use-case-discovery/templates/USE-CASES-TEMPLATE.md` | 扩展治理字段 frontmatter | T-01 |
| T3 | 修改 | `delivery/skills/use-case-discovery/templates/USE-CASES-TEMPLATE.md` | 增加治理附录与覆盖自检表 | T-03 |

## 12. 风险、难点与预研建议

| 风险 | 影响 | 应对 |
|---|---|---|
| 字段命名漂移 | 下游读取失败 | 与 UCD-01 / UCD-03 同步 exact match |
| reference 与模板内容重复 | 后续维护成本增大 | 采用“reference 定义、template 引用”模式 |
| 附录过长 | 可读性下降 | 用独立标题和锚点收敛 |

## 13. 回滚与发布策略

- 若新模板影响已有消费链，可先保留旧模板正文结构，仅回滚新增附录。
- 变更仅涉及静态模板和参考文档，无脚本回滚需求。

## 14. Definition of Done + 确认区

### Definition of Done

- [x] 参考文档包含 D1-D8 与 Dx
- [x] 模板 frontmatter 包含 3 个治理字段
- [x] 模板正文包含治理附录与覆盖自检表

### 确认区

- `confirmed`: true
- 待确认事项：
  1. 覆盖自检表是否需要固定为单独二级标题
  2. 治理附录是否保留引用 reference 文档的短说明块
