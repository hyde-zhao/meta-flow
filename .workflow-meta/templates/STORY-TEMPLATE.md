---
story_id: "STORY-{id}"
title: ""
status: "draft"
priority: "P0"
wave: "W1"
depends_on: []
created_at: ""
updated_at: ""
---

## 目标

[一句话描述本 Story 要实现什么]

## 开发上下文（dev_context）

- **输入文件**：
- **输出文件**：
- **设计约束**：
- **命名规范**：kebab-case，文件名符合 `^[a-z][a-z0-9-]+\.md$`，必须包含 title/version/description Frontmatter
- **平台目标**：

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
