---
name: lld-designer
description: >-
  当某个已批准 Story 在开发前需要落地为 Low-Level Design（LLD）时使用。
  输出模块拆分、文件影响范围、数据模型、接口、流程、异常处理、测试设计、实施步骤、
  风险、发布与回滚策略，并交由人工确认后再进入实现。触发词包括：LLD、详细设计、实现设计、Story 设计。
argument-hint: "必填：Story ID；可选：功能名、目标平台或技术栈"
user-invokable: true
status: active
---

## 目标

基于已批准的 Story、已确认的 HLD 和架构约束，输出一份**可直接指导编码与评审**的 `.output/stories/STORY-{id}-LLD.md`。该文档必须在人工确认后，才能作为实现入口。

## 核心原则

1. **实现导向**：聚焦“如何实现”，不重复 HLD 的宏观论证
2. **确定性**：对模块、接口、文件影响、测试和步骤给出可执行描述
3. **边界完整**：显式说明异常路径、安全、性能、幂等性、一致性和回滚策略
4. **与 Story 对齐**：不得超出当前 Story 的范围，不得擅自扩容需求
5. **人工门控**：LLD 输出后必须停下，等待 meta-po 发起确认

## 前置条件

- [ ] `.output/stories/STORY-{id}.md` 存在且 `status=approved`
- [ ] `.output/HLD.md` 存在且 `confirmed=true`
- [ ] `.output/ARCHITECTURE-DECISION.md` 存在且 `confirmed=true`

## 必须读取的输入

- 当前 Story 卡片 `.output/stories/STORY-{id}.md`
- `.output/HLD.md`
- `.output/ARCHITECTURE-DECISION.md`
- Story `depends_on` 指向的前置产物（若存在）
- `.output/PLATFORM-INSTALL-SPEC.md`（当 Story 涉及平台目录或安装结构时）

## 执行步骤

### 步骤 1：范围澄清

从 Story 中提炼：

- 本次交付目标
- 验收标准
- 输出文件
- 平台目标
- 设计约束
- 与前置 Story 的接口边界

若发现 Story 缺少实现所需关键信息，停止并报告阻塞。

### 步骤 2：LLD 主体设计

`STORY-{id}-LLD.md` 必须严格包含以下章节：

1. Goal
2. Requirements（Functional / Non-Functional）
3. 模块拆分与职责
4. 代码结构与文件影响范围
5. 数据模型与持久化设计（若无则显式说明）
6. API / Interface 设计
7. 核心处理流程
8. 技术设计细节
9. 安全与性能设计
10. 测试设计
11. 实施步骤
12. 风险、难点与预研建议
13. 回滚与发布策略
14. Definition of Done

### 步骤 3：评审门控

完成 `.output/stories/STORY-{id}-LLD.md` 后：

- 在 Frontmatter 中设置 `story_id: STORY-{id}`
- 在 Frontmatter 中设置 `status: ready-for-review`
- 在 Frontmatter 中设置 `confirmed: false`
- 说明“需要 meta-po 发起人工确认”
- **立即停止**，不得开始实现产物文件

## 输出文件

| 文件 | 路径 | 说明 |
|------|------|------|
| Story LLD | `.output/stories/STORY-{id}-LLD.md` | 当前 Story 的详细设计文档 |

## 验收标准

- [ ] LLD 文档覆盖 14 个规定章节
- [ ] 文件影响范围、接口、测试、实施步骤和 DoD 可直接指导编码
- [ ] 明确异常路径、安全、性能、回滚和发布策略
- [ ] 不超出当前 Story 范围
- [ ] `confirmed=false` 时不进入实现

## 不适用边界

- 当前任务仍处于需求澄清或 HLD 设计阶段
- Story 尚未批准，或 HLD / 架构决策尚未确认
- 当前请求只需要高层方案评审，不需要实现级设计
