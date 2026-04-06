---
name: story-manager
description: >-
  当需要拆分 Story、管理 Story 生命周期、生成 Story 卡片或更新 Story 状态时使用。
  触发词包括：拆分 Story、Story 状态、Story 卡片、Story 管理、生成 Story。
  适用场景：story-planning 和 story-development 阶段。
argument-hint: "可选：指定 Story ID 或操作类型（create/update/status）"
user-invokable: true
status: active
---

## 目标

管理 Story 的完整生命周期：从 `ARCHITECTURE-DECISION.md` 拆解 Story 卡片，维护状态流转，并汇总输出 `STORY-STATUS.md`。

## Story 生命周期

```
draft → approved → in-development → ready-for-verification → verified → done
```

| 状态 | 说明 | 允许操作 |
|------|------|---------|
| `draft` | Story 初始草稿，由 meta-dm 生成 | 审查、修改 |
| `approved` | meta-po 确认，可开始开发 | meta-dev 认领 |
| `in-development` | meta-dev 正在实现 | 更新日志、上抛阻塞 |
| `ready-for-verification` | 实现完成，等待 meta-qa 验证 | meta-qa 认领 |
| `verified` | meta-qa 验证通过 | meta-po 收敛 |
| `done` | 归档完成 | 只读 |

## Story 卡片三件套（缺一不可）

每张 Story 卡片必须同时包含：

1. **开发上下文（dev_context）**：输入文件、输出文件、设计约束、命名规范、平台目标
2. **验证上下文（validation_context）**：验证入口、验证方式、依赖环境
3. **量化验收标准（acceptance_criteria）**：8 维度验收清单（见下方）

缺少任一件套，Story 不得从 `approved` 状态推进到 `in-development`。

## 8 维度验收标准模板

在每张 Story 卡片中插入：

```markdown
## 量化验收标准
- [ ] 完整性：产物文件数量 >= expected_outputs 数量
- [ ] 平台适配：至少 1 个平台安装目录符合 PLATFORM-INSTALL-SPEC.md 规范
- [ ] 验收标准覆盖：verified_criteria == total_criteria
- [ ] 安全合规：dangerous-command-scan 返回 0 个风险项
- [ ] 命名规范：文件名符合 kebab-case 正则 `^[a-z][a-z0-9-]+\.md$`
- [ ] Frontmatter 完整：title、version、description 字段均非空
- [ ] 可安装性：目录树结构比对通过（DryRun 或结构校验）
- [ ] 文档覆盖：（OPTIONAL）功能在 USER-MANUAL.md 中有对应说明
```

## 执行步骤

### 操作：create（拆解 Story）

1. 读取 `ARCHITECTURE-DECISION.md` 和 `DEVELOPMENT-PLAN.yaml`
2. 为每个 Story 生成卡片文件 `.workflow-meta/stories/STORY-{id}.md`
3. 填写三件套（dev_context + validation_context + acceptance_criteria）
4. 设置初始状态为 `draft`，分配 wave 和 priority
5. 更新 `STORY-STATUS.md` 汇总视图

### 操作：update（更新状态）

1. 读取指定 Story 卡片
2. 校验状态转换是否合法（不允许跳级）
3. 更新状态字段和 `updated_at`
4. 回写 `STORY-STATUS.md`

### 操作：status（查看汇总）

1. 读取所有 `.workflow-meta/stories/STORY-*.md`
2. 输出当前各 Wave 的 Story 状态汇总
3. 高亮阻塞项和未决项

## 执行约束

- 不允许直接修改 `ARCHITECTURE-DECISION.md` 或 `REQUIREMENTS.md`
- Story 状态只能单向推进，不允许跳级（`draft` 不能直接变为 `ready-for-verification`）
- 回退只能由 meta-po 发起（携带回退原因）
- 每次状态变更必须更新 `STORY-STATUS.md`

## 输出文件

| 文件 | 路径 | 操作 |
|------|------|------|
| Story 卡片 | `.workflow-meta/stories/STORY-{id}.md` | create/update |
| Story 状态汇总 | `.workflow-meta/STORY-STATUS.md` | 每次操作后更新 |

## 验收标准

- [ ] 每张 Story 卡片包含完整三件套
- [ ] `STORY-STATUS.md` 状态与各卡片一致
- [ ] 无跳级状态转换记录
