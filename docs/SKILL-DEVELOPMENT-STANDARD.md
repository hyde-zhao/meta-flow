# Meta Flow Skill 开发规范

> 本规范用于约束 Meta Flow 项目中 Skill 的设计、编写、评审和演进方式。
> 目标是让 Skill 成为可复用、可组合、可审查、可交接的工程制品，而不是一次性对话 Prompt。

---

## 1. 适用范围

本规范适用于：

- 根目录 `delivery/skills/` 下的所有交付 Skill
- `delivery/skills/` 下由元工作流生成的产物 Skill
- 后续新增的跨平台共享 Skill（Copilot / Claude Code / Codex）

本规范不适用于：

- Agent 提示词文件
- Story 级 LLD 或实现设计文档
- 工具脚本本身的编码规范

---

## 2. 核心原则

### 2.1 单一职责

每个 Skill 只解决**一类稳定问题**，必须满足：

- 职责单一
- 可复用
- 可组合
- 可独立审查

禁止把多个异质任务塞进同一个 Skill，例如：

- 需求澄清 + 架构设计
- 设计 + 实现
- 实现 + 验证
- 文档输出 + 安装脚本生成

### 2.2 文档完整

`SKILL.md` 必须完整描述：

- 触发场景
- 输入格式
- 执行步骤
- 输出模板或输出对象
- 适用范围
- 不适用范围

`SKILL.md` 的本质是：**角色目标 + 触发条件 + 执行流 + 约束边界**。

### 2.3 不越界到实现层

Skill 允许定义：

- 方法论
- 流程
- 检查清单
- 输出模板
- 失败处理
- 评审标准

Skill 不应展开：

- 函数实现
- API 细节
- 数据库结构
- 代码级类/模块设计
- 技术选型细节

如果任务已经进入实现级设计，应转交 LLD 或代码实现层，而不是继续扩张 Skill。

### 2.4 防幻觉优先

每个 Skill 必须显式约束知识来源、允许生成的内容和信息不足时的行为。

规则：

1. 所有关键输出项必须可追溯到用户输入、上游文件、模板或 references
2. 信息不足时必须标记 `[待确认]`
3. 必要时标记 `BLOCKING` / `NON-BLOCKING`
4. 禁止脑补文件路径、环境状态、字段定义或用户意图

### 2.5 Prompt as Code

Skill 必须作为工程制品维护，而不是聊天上下文中的临时描述。

Skill 应满足：

- 可审查
- 可 diff
- 可版本化
- 可回溯
- 可 handoff

---

## 3. 目录规范

### 3.1 基础结构

每个 Skill 至少使用如下目录结构：

```text
skills/<skill-name>/
  SKILL.md
```

### 3.2 复杂 Skill 推荐结构

复杂 Skill 推荐使用目录化结构：

```text
skills/<skill-name>/
  SKILL.md
  references/
  examples/
  templates/
  scripts/
  tests/
```

各子目录职责如下：

| 目录 | 用途 |
|------|------|
| `references/` | 补充知识、规范摘录、来源材料 |
| `examples/` | 典型输入输出、好/坏案例 |
| `templates/` | 当前 Skill 私有模板，必须随 Skill 同树安装 |
| `scripts/` | 当前 Skill 私有运行时脚本，必须随 Skill 同树安装 |
| `tests/` | smoke test、回归样例或评审用例 |

### 3.3 Template 放置规范

Template 按归属范围分层放置：

| 类型 | 位置 |
|------|------|
| 单个 Skill 私有模板 | `delivery/skills/<skill-name>/templates/` |
| 多个 Skill / Agent 需要共享的模板 | 优先沉淀为专门 Skill 或显式复制到消费方 Skill，避免新增无 owner 的公共模板根 |

安装到项目或用户级运行时时：

- Skill 私有模板随 `delivery/skills/<skill-name>/` 同树安装。
- Skill 私有脚本随 `delivery/skills/<skill-name>/scripts/` 同树安装。
- `delivery/scripts/` 只允许放安装器入口，例如 `install.py`、`install.sh`、`install.ps1`。

不得依赖仓库根 `templates/`、`agents/templates/` 或 `delivery/scripts/` 作为 Skill 私有资产位置。

---

## 4. Frontmatter 规范

每个 `SKILL.md` 必须包含 frontmatter。

### 4.1 必填字段

```yaml
---
name: skill-name
description: >-
  当……时触发。触发词包括：……
argument-hint: "可选参数提示"
user-invokable: true
status: active
---
```

### 4.2 字段要求

#### `name`

- 使用 kebab-case
- 与目录名一致

#### `description`

- 主要写给模型判断触发时机，不是写给人的 marketing 描述
- 必须描述“何时触发”
- 推荐包含触发词
- 应避免空泛描述

#### `argument-hint`

- 用于提示可选参数
- 不写实现细节，只写调用层关注的信息

#### `user-invokable`

- `true`：允许用户直接触发
- `false`：仅供 Agent preload 或内部调用

#### `status`

- `active`：可用
- `deprecated`：保留兼容但不建议新增使用

### 4.3 推荐扩展字段

对高价值或高副作用 Skill，建议后续统一支持：

```yaml
applies_to: [copilot, claude, codex]
side_effect_level: low | medium | high
requires_confirmation: true | false
output_mode: advisory | file-generation | validation
```

---

## 5. SKILL.md 正文结构规范

每个 Skill 至少包含以下章节：

1. `## 目标`
2. `## 适用范围` 或 `## 适用场景`
3. `## 前置条件`
4. `## 必须读取的输入`
5. `## 知识来源`
6. `## 执行步骤`
7. `## 输出文件` 或 `## 输出模板`
8. `## 约束`
9. `## 验收标准`
10. `## 不适用边界`
11. `## Gotchas`

推荐骨架如下：

```markdown
## 目标
## 适用场景
## 前置条件
## 必须读取的输入
## 知识来源
## 执行步骤
## 输出文件 / 输出模板
## 约束
## 验收标准
## 不适用边界
## Gotchas
```

---

## 6. 文档内容规范

### 6.1 必须明确的内容

每个 Skill 必须清楚回答以下问题：

| 问题 | 必须回答的内容 |
|------|----------------|
| 何时触发 | 触发场景、触发词、适用阶段 |
| 读什么 | 输入文件、用户输入、参考资料 |
| 怎么做 | 明确执行步骤 |
| 产出什么 | 输出对象、输出路径、输出格式 |
| 何时停止 | 门控条件、阻断条件、人工确认要求 |
| 何时不该用 | 不适用边界 |

### 6.2 输出定义必须结构化

输出不能只写“给出结果”或“生成建议”，而应明确：

- 输出对象名称
- 输出路径
- 输出格式
- 必填章节或字段
- 哪些内容允许写为 `[待确认]`

---

## 7. 知识来源与防幻觉规范

### 7.1 知识来源章节必填

每个 Skill 必须明确知识来源优先级，推荐顺序如下：

1. 用户输入
2. 当前项目文件
3. 已确认的上游文档
4. 当前 Skill 附带的 `templates/`、`references/`、`examples/`
5. 明确标记为 `[待确认]` 的缺失信息

### 7.2 信息不足处理

如果缺少必要信息：

- 必须标记 `[待确认]`
- 必须区分 `BLOCKING` 与 `NON-BLOCKING`
- 对依赖该信息的下游结论应停止生成

禁止在信息不足时脑补：

- 路径
- 配置
- 平台能力
- 字段含义
- 外部系统行为

### 7.3 可追溯性要求

每个关键输出项都应能追溯到：

- 用户输入
- 项目文件
- 模板
- references

无法追溯的结论不得写成确定性表述。

---

## 8. Skill 类型规范

### 8.1 默认优先 Tool Skill

优先设计为：

- 独立调用
- 低耦合
- 可被多个 Agent 或用户复用
- 对主上下文污染小

### 8.2 Agent 专属 Skill 的使用边界

仅在以下条件同时满足时，才适合作为 Agent preload skill：

- 高频使用
- 仅服务特定 Agent
- 低副作用
- 内容短小稳定

---

## 9. Gotchas 规范

每个 Skill 必须维护 `## Gotchas` 章节，用来记录模型常见跑偏点、误用场景和禁止行为。

示例：

```markdown
## Gotchas

- 不要在 REQUIREMENTS 未确认时输出正式设计对象
- 不要把建议写成已确认结论
- 不要补全用户未提供的环境变量
- 不要把 `process/` 中间文件当成交付件安装
```

Gotchas 的作用：

- 约束模型默认行为
- 沉淀历史失败经验
- 降低 Skill 回归风险

---

## 10. 安全与副作用规范

对会写文件、执行脚本、生成安装器、修改状态文件的 Skill，必须额外说明：

- 会修改哪些路径
- 不会修改哪些路径
- 是否需要人工确认
- 是否应禁止自动触发

高副作用 Skill 建议满足：

- 明确输出路径
- 最小权限
- 不静默写入用户目录
- 不自动跨边界修改未声明对象

---

## 11. 测试与评审规范

### 11.1 复杂 Skill 必须具备可验证材料

复杂 Skill 建议至少具备：

- `examples/`：示例输入输出
- `tests/`：smoke test 或 review case

### 11.2 修改 Skill 时必须同步检查

修改 Skill 后，应同步检查：

- frontmatter 是否仍准确
- 触发条件是否变化
- 输出模板是否变化
- 不适用边界是否变化
- `references/`、`templates/`、`examples/`、`tests/` 是否需同步更新

### 11.3 评审关注点

评审 Skill 时至少检查：

- 是否只解决一类问题
- 是否写清触发时机
- 是否定义输入、步骤、输出
- 是否避免实现层越界
- 是否定义知识来源
- 是否处理信息不足
- 是否包含 Gotchas
- 是否具备可追溯输出

---

## 12. 与当前仓库的落地要求

结合当前 Meta Flow 仓库，新增或升级 Skill 时应优先执行以下规则：

1. 所有新 Skill 默认按目录化结构设计
2. 所有 Skill 逐步补齐 `## Gotchas`
3. Skill 私有模板和脚本必须保留在对应 `delivery/skills/<skill-name>/` 同树目录下
4. 复杂 Skill 逐步补齐 `references/`、`templates/`、`examples/`、`tests/`
5. 所有高副作用 Skill 明确知识来源与确认门控

---

## 13. 提交前检查清单

- [ ] Skill 只解决一类稳定问题
- [ ] 目录名与 `name` 均为 kebab-case
- [ ] `description` 已写清触发场景
- [ ] 正文已覆盖输入、步骤、输出、边界
- [ ] 未展开实现层细节
- [ ] 已定义知识来源
- [ ] 已定义信息不足处理
- [ ] 已包含 `Gotchas`
- [ ] 模板位置符合共享 / 私有分层规则
- [ ] Skill 私有脚本没有放入 `delivery/scripts/`
- [ ] 复杂 Skill 已补齐必要的 examples / tests / references
