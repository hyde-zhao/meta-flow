---
story_id: "UCD-03"
story_title: "UCD 上下游契约同步"
status: "confirmed"
tier: "S"
confirmed: true
confirmed_by: "meta-po-delegated"
confirmed_at: "2026-04-23T12:09:47+08:00"
created_at: "2026-04-23T12:09:47+08:00"
updated_at: "2026-04-23T12:09:47+08:00"
source_story: "process/stories/STORY-UCD-03.md"
source_hld:
  - "process/HLD.md"
architecture_decision: "process/ARCHITECTURE-DECISION.md"
platform_spec: "process/PLATFORM-INSTALL-SPEC.md"
---

# LLD - UCD-03 UCD 上下游契约同步

## 1. Goal

把 `use-case-discovery` 新增的治理字段和 Phase 1A / 1B 语义同步到 `meta-pm`、`requirement-extraction` 和 `skills/README`，消除上下游口径漂移。

## 2. Requirements（Functional / Non-Functional）

### 2.1 Functional

- F1：`meta-pm` 必须明确 `use-case-discovery` 的 Phase 1A / 1B 和治理字段产出。
- F2：`requirement-extraction` 必须显式消费 `target_artifact_type`、`governance_mode`、`review_policy`。
- F3：`skills/README.md` 必须刷新 Agent→Skill 描述和模板交叉引用。

### 2.2 Non-Functional

- NF1：字段名必须与 `USE-CASES-TEMPLATE.md` 完全一致。
- NF2：不改变 `meta-pm` 和 `requirement-extraction` 的主职责边界。

## 3. 模块拆分与职责

| 模块 / 文件组 | 职责 | 说明 |
|---|---|---|
| `delivery/agents/meta-pm.md` | 编排 use-case-discovery | 暴露 Phase 1A / 1B 与治理字段 |
| `delivery/skills/requirement-extraction/SKILL.md` | 需求提取 | 直接消费治理字段 |
| `delivery/skills/README.md` | 注册表与交叉引用 | 刷新正式口径 |

## 4. 代码结构与文件影响范围

| 动作 | 文件路径 | 变更内容 |
|---|---|---|
| 修改 | `delivery/agents/meta-pm.md` | 增加治理字段与 Phase 1A / 1B 编排描述 |
| 修改 | `delivery/skills/requirement-extraction/SKILL.md` | 增加治理字段消费语义 |
| 修改 | `delivery/skills/README.md` | 同步 Agent→Skill 与模板交叉引用 |

## 5. 数据模型与持久化设计

无新增持久化对象；只同步以下字段的消费契约：

| 对象 / 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `target_artifact_type` | enum | 与 USE-CASES 模板一致 | 需求提取上下文 |
| `governance_mode` | enum | 与 USE-CASES 模板一致 | 路由上下文 |
| `review_policy` | enum | 与 USE-CASES 模板一致 | 评审强度线索 |

## 6. API / Interface 设计

| 接口 / 入口 | 输入 | 输出 | 调用方 | 说明 |
|---|---|---|---|---|
| `meta-pm` -> `use-case-discovery` | 请求、输入索引、历史草稿 | `USE-CASES.md` | meta-pm | 先编排，再进入场景发现 |
| `use-case-discovery` -> `requirement-extraction` | `USE-CASES.md` + 治理字段 | 需求提取上下文 | requirement-extraction | 不依赖会话转述 |
| `skills/README.md` | 实际交付关系 | 人类可读注册信息 | 全体维护者 | 保持目录事实一致 |

## 7. 核心处理流程

1. 从 W1 已实现的 `use-case-discovery` 读取治理字段和阶段说明。
2. 在 `meta-pm.md` 中同步编排口径。
3. 在 `requirement-extraction` 中同步治理字段消费口径。
4. 在 `skills/README.md` 中刷新正式映射。

## 8. 技术设计细节

- 所有治理字段采用 exact-match 语义。
- README 只写正式交付对象，不补历史占位。
- `meta-pm` 继续只编排，不内联场景发现细节。

## 9. 安全与性能设计

| 维度 | 设计措施 | 验证方式 |
|---|---|---|
| 安全 | 不新增命令执行或外部调用 | 文本检查 |
| 性能 | 仅文档更新 | 文本检查 |

## 10. 测试设计

| 测试场景 | 前置条件 | 操作 | 预期结果 | 验证方式 |
|---|---|---|---|---|
| meta-pm 编排检查 | 已有 use-case-discovery 新版 Skill | 阅读 `meta-pm.md` | 可见 Phase 1A / 1B 与治理字段说明 | 文本检查 |
| requirement-extraction 输入检查 | 已有治理字段模板 | 阅读 `requirement-extraction` | 明确消费治理字段 | 文本检查 |
| README 映射检查 | 目录事实已变更 | 阅读 `skills/README.md` | 映射和交叉引用更新 | 文本检查 |

## 11. 实施步骤

| TASK-ID | 动作 | 目标文件 | 详细描述 |
|---|---|---|---|
| TASK-UCD-03-01 | 修改 | `delivery/agents/meta-pm.md` | 同步 Phase 1A / 1B 与治理字段产出 |
| TASK-UCD-03-02 | 修改 | `delivery/skills/requirement-extraction/SKILL.md` | 同步治理字段消费 |
| TASK-UCD-03-03 | 修改 | `delivery/skills/README.md` | 刷新正式映射与交叉引用 |

## 12. 风险、难点与预研建议

| 风险 / 难点 | 影响 | 缓解措施 / 预研建议 |
|---|---|---|
| 上下游字段名漂移 | 需求提取失真 | 坚持 exact-match |

## 13. 回滚与发布策略

- 发布方式：文档原位更新
- 回滚触发条件：上下游字段名与模板不一致
- 回滚动作：回退本 Story 修改并以模板字段为准重新同步

## 14. Definition of Done

- [x] 14 个章节全部填写完成
- [x] 文件影响范围、接口、测试与实施步骤可直接指导编码
- [x] `confirmed=false` 时不进入实现
- [x] 人工确认意见已收敛

## 人工确认区

> 已按委托方式确认并进入实现。

