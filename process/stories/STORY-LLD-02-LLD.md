---
story_id: "LLD-02"
story_title: "STORY-LLD 模板增强（14 章节固定）"
status: "confirmed"
tier: "M"
confirmed: true
confirmed_by: "meta-po-delegated"
confirmed_at: "2026-04-23T12:09:47+08:00"
created_at: "2026-04-23T12:09:47+08:00"
updated_at: "2026-04-23T12:09:47+08:00"
source_story: "process/stories/STORY-LLD-02.md"
source_hld:
  - "process/HLD-lld-writing-method.md"
architecture_decision: "process/ARCHITECTURE-DECISION.md"
platform_spec: "process/PLATFORM-INSTALL-SPEC.md"
---

# LLD - LLD-02 STORY-LLD 模板增强（14 章节固定）

## 1. Goal

把 `STORY-LLD-TEMPLATE.md` 固化为 14 个可见章节不变的统一模板，并补齐 `tier`、OPEN/Spike、共享片段引用、图示触发和接口/测试配对提示。

## 2. Requirements（Functional / Non-Functional）

### 2.1 Functional

- F1：frontmatter 必须增加 `tier`。
- F2：模板必须保留 14 个可见章节。
- F3：模板必须包含 OPEN / Spike 跟踪表。
- F4：模板必须补共享片段引用、图示触发和接口/测试配对提示。

### 2.2 Non-Functional

- NF1：不允许 Tier-S 压缩章节数。
- NF2：保持 Markdown 可直接填写。

## 3. 模块拆分与职责

| 模块 / 文件组 | 职责 | 说明 |
|---|---|---|
| `delivery/skills/lld-designer/templates/STORY-LLD-TEMPLATE.md` | 承载统一模板 | 供所有 Story LLD 起草使用 |

## 4. 代码结构与文件影响范围

| 动作 | 文件路径 | 变更内容 |
|---|---|---|
| 修改 | `delivery/skills/lld-designer/templates/STORY-LLD-TEMPLATE.md` | 补 `tier`、OPEN/Spike、共享片段、图示触发与配对提示 |

## 5. 数据模型与持久化设计

模板新增 frontmatter 字段：

| 对象 / 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `tier` | enum | S / M / L | 仅影响深度，不影响章节数 |
| `shared_fragments` | list | 可空 | 共享片段引用 |
| `open_items` | int | `>=0` | OPEN/Spike 项计数 |

## 6. API / Interface 设计

| 接口 / 入口 | 输入 | 输出 | 调用方 | 说明 |
|---|---|---|---|---|
| meta-dev -> 模板 | Story / HLD / ADR | `STORY-{id}-LLD.md` 草稿 | meta-dev | 起草入口 |
| 模板 -> meta-po | 确认区 | LLD 检查点④ | meta-po | 人工确认入口 |
| 模板 -> meta-qa | 测试设计章节 | 验证输入 | meta-qa | 接口与测试必须配对 |

## 7. 核心处理流程

1. 在 frontmatter 标注 `tier`、shared fragments 和 open_items。
2. 保留 14 个章节固定外形。
3. 在第 7 节补图示触发规则。
4. 在第 10/11/12 节补测试配对、TASK 配对和 OPEN/Spike 跟踪。

## 8. 技术设计细节

- 图示触发条件内联写在模板中，避免起草时遗忘。
- 接口↔测试、文件↔TASK 配对通过模板注释强提示。
- 共享片段使用 `process/shared/{file}#{section}` 格式。

## 9. 安全与性能设计

| 维度 | 设计措施 | 验证方式 |
|---|---|---|
| 安全 | 无命令与脚本示例 | 文本检查 |
| 性能 | 模板字段最小增量 | 文本检查 |

## 10. 测试设计

| 测试场景 | 前置条件 | 操作 | 预期结果 | 验证方式 |
|---|---|---|---|---|
| frontmatter 检查 | 模板已更新 | 查看头部 | 可见 `tier` / `shared_fragments` / `open_items` | 文本检查 |
| 章节数量检查 | 模板已更新 | 查看正文 | 14 个可见章节仍然保留 | 文本检查 |
| OPEN/Spike 检查 | 模板已更新 | 查看第 12 节 | 存在 OPEN/Spike 跟踪表 | 文本检查 |
| 配对提示检查 | 模板已更新 | 查看第 6/10/11 节 | 接口↔测试、TASK↔文件提示存在 | 文本检查 |

## 11. 实施步骤

| TASK-ID | 动作 | 目标文件 | 详细描述 |
|---|---|---|---|
| TASK-LLD-02-01 | 修改 | `delivery/skills/lld-designer/templates/STORY-LLD-TEMPLATE.md` | 新增 `tier` 等 frontmatter 字段 |
| TASK-LLD-02-02 | 修改 | `delivery/skills/lld-designer/templates/STORY-LLD-TEMPLATE.md` | 保持 14 章节并补图示/共享片段提示 |
| TASK-LLD-02-03 | 修改 | `delivery/skills/lld-designer/templates/STORY-LLD-TEMPLATE.md` | 增加 OPEN/Spike 跟踪表 |
| TASK-LLD-02-04 | 修改 | `delivery/skills/lld-designer/templates/STORY-LLD-TEMPLATE.md` | 增加接口↔测试、TASK↔文件配对提示 |

## 12. 风险、难点与预研建议

| 风险 / 难点 | 影响 | 缓解措施 / 预研建议 |
|---|---|---|
| 14 章节被误裁剪 | 下游消费破坏 | 用模板正文显式约束 |

## 13. 回滚与发布策略

- 发布方式：更新模板文件
- 回滚触发条件：模板与 lld-designer Skill 口径冲突
- 回滚动作：回退模板并以 Skill 契约重同步

## 14. Definition of Done

- [x] 14 个章节全部填写完成
- [x] 文件影响范围、接口、测试与实施步骤可直接指导编码
- [x] `confirmed=false` 时不进入实现
- [x] 人工确认意见已收敛

## 人工确认区

> 已按委托方式确认并进入实现。

