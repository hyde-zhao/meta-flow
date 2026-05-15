---
story_id: "STORY-{id}"
title: ""
story_slug: ""
status: "draft"
priority: "P0"
wave: "W1"
depends_on: []
dependency_contracts: []
file_ownership:
  primary: []
  shared: []
  merge_owner: ""
  forbidden: []
lld_gate:
  required_inputs: ["HLD", "ADR", "Story"]
  status: "not-started"
dev_gate:
  lld_confirmed: false
  dependencies_satisfied: false
  file_conflict_free: false
task_count: 0
created_at: ""
updated_at: ""
---

## 目标

[一句话描述本 Story 要实现什么]

## 开发上下文（dev_context）

- **输入文件**：
- **输出文件**：
- **设计约束**：
- **命名规范**：Story 卡片文件名必须为 `STORY-{id}-{story_slug}.md`，其中 `story_slug` 是 `title` 的 kebab-case 稳定片段
- **平台目标**：

### 依赖与并行门控

> `depends_on` 必须声明依赖类型，供 meta-po 计算 `lld_ready` 与 `dev_ready`。

| 上游 Story | 类型（contract/runtime/file-conflict） | LLD 门控 | 开发门控 | 说明 |
|------------|-----------------------------------------|----------|----------|------|
| STORY-XXX | contract | upstream_lld_or_story_contract_declared | upstream_contract_frozen | |

### 文件所有权

| 类型 | 文件 | Owner / 合并规则 |
|------|------|------------------|
| primary | | 当前 Story 独占写入 |
| shared | | 必须指定 merge_owner |
| forbidden | | 当前 Story 禁止修改 |

### 文件系统布局

> 预期创建/修改的文件列表（含完整路径）。

```
<root>/
├── .agents/skills/<skill-name>/
│   └── SKILL.md           ← 新建
├── .agents/agents/
│   └── <agent-name>.md    ← 新建 / 修改
└── ...
```

### 关键 Frontmatter 字段

| 文件 | 字段 | 类型 | 必填 | 说明 / 取值范围 |
|------|------|------|------|----------------|
| SKILL.md | title | string | ✅ | Skill 显示名称 |
| SKILL.md | version | string | ✅ | 语义化版本号 |
| SKILL.md | description | string | ✅ | 一句话描述 |

### AI 可执行任务清单

> 使用 TASK-ID 前缀 + 确定性动词（创建/修改/删除）的原子任务。

| TASK-ID | 动作 | 目标文件 | 描述 |
|---------|------|---------|------|
| T1 | 创建 | `.agents/skills/<name>/SKILL.md` | |
| T2 | 修改 | | |

## 验证上下文（validation_context）

- **验证入口**：
- **验证方式**：（人工检查 / platform-validator / dangerous-command-scan）
- **依赖环境**：（参见 VALIDATION-ENV.yaml）

## 量化验收标准（acceptance_criteria）

- [ ] **完整性**：产物文件数量 >= N（期望输出数：N）
- [ ] **平台适配**：至少 1 个平台安装目录符合 PLATFORM-INSTALL-SPEC.md 规范
- [ ] **验收标准覆盖**：verified_criteria == total_criteria
- [ ] **安全合规**：dangerous-command-scan 返回 0 个风险项
- [ ] **命名规范**：文件名符合 `^[a-z][a-z0-9-]+\.md$`
- [ ] **Frontmatter 完整**：title、version、description 字段均非空
- [ ] **可安装性**：目录树结构比对通过（DryRun 或结构校验）
- [ ] **文档覆盖**（OPTIONAL）：功能在 USER-MANUAL.md 中有对应说明

## 阻塞说明（如有）

（无）
