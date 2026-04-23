---
name: awesome-copilot-analysis
description: >-
  在 HLD 设计前，扫描 .input/ 中的 awesome-copilot 资源，
  对照当前项目 REQUIREMENTS.md 与 USE-CASES.md，识别可借鉴的 agent、skill、workflow、
  hooks、instructions 和 plugins，输出优缺点分析报告供 meta-se 在 HLD 和后续
  meta-dev / meta-qa 阶段直接引用。
  触发词包括：分析 awesome-copilot、copilot 资源分析、借鉴分析、HLD 前分析。
argument-hint: "可选：指定分析类别（agents/skills/workflows/hooks/instructions/plugins）或 all（默认）"
user-invokable: false
status: active
called-by: meta-se
output: process/ANALYSIS-<project_id>-<analysis_topic>.md
---

## 目标

在 HLD 输出前，基于项目已确认的 REQUIREMENTS.md 与 USE-CASES.md，
扫描 `.input/` 目录下由 `awesome-copilot-fetcher` 获取的所有资源，
识别与当前项目**技术栈、领域、质量目标**相关的资源，
对每条资源分析优缺点，并给出**可直接借鉴 / 需要适配 / 不适用**的明确判断，
最终输出结构化分析报告 `ANALYSIS-<project_id>-<analysis_topic>.md`，供 HLD、meta-dev 和 meta-qa 引用。

## 适用场景

- `meta-se` 进入 `hld-design` 前的资源调研阶段
- 项目需要复用社区最佳实践时
- 需要为 meta-dev / meta-qa 提供可直接落地的参考资源时

## 前置条件

- [ ] `process/REQUIREMENTS.md` 已确认（`confirmed=true`）
- [ ] `process/USE-CASES.md` 已确认（`confirmed=true`）
- [ ] `.input/` 目录已由 `awesome-copilot-fetcher` 填充；若不存在，先触发 `awesome-copilot-fetcher`

## 必须读取的输入

| 文件 | 用途 |
|------|------|
| `process/REQUIREMENTS.md` | 提取技术栈、质量目标、关键约束 |
| `process/USE-CASES.md` | 提取使用场景与用户角色 |
| `process/REQUEST.md` | 提取原始请求意图 |
| `.input/agents/*.agent.md` | 扫描可用 Agent |
| `.input/skills/*/` | 扫描可用 Skill（读各目录 README 或 skill.md）|
| `.input/workflows/*.md` | 扫描可用 Workflow |
| `.input/hooks/*/` | 扫描可用 Hook |
| `.input/instructions/*.instructions.md` | 扫描编码规范 |
| `.input/plugins/*/` | 扫描插件包 |

## 执行步骤

### 步骤 0：检查 .input/ 是否已就绪

```
IF .input/ 不存在 OR .input/ 为空:
    触发 awesome-copilot-fetcher → 等待完成
ELSE:
    继续步骤 1
```

### 步骤 1：提取项目特征向量

从 REQUIREMENTS.md 和 USE-CASES.md 中提取：

| 特征维度 | 提取内容 |
|---------|---------|
| 技术栈 | 语言、框架、平台、云服务 |
| 领域关键词 | 业务领域（如 AI、DevOps、Web、数据处理等）|
| 质量目标 | 安全、性能、可观测性、可维护性等 |
| 集成需求 | 第三方服务、API、数据源 |
| 开发规范 | 代码风格、测试要求、提交规范 |
| Agent/Skill 需求 | 需要什么类型的 AI 辅助能力 |

### 步骤 2：分类扫描与相关性筛选

对每个类别按**相关性**从高到低排序，只保留相关性 ≥ 中 的资源：

**相关性判断标准：**
- **高**：名称/描述与项目特征词直接匹配，功能与项目需求高度重叠
- **中**：名称/描述与项目特征词部分匹配，功能可经适配后使用
- **低/不适用**：与项目无关，跳过，不写入报告

### 步骤 3：逐资源优缺点分析

对每条相关资源填写分析条目（格式见「输出格式」章节）：

| 分析维度 | 说明 |
|---------|------|
| 核心功能 | 该资源做什么 |
| 优点 | 对本项目的直接价值 |
| 缺点/局限 | 不适用之处或需要适配的部分 |
| 借鉴判断 | 直接使用 / 需适配 / 仅参考 / 不适用 |
| 借鉴内容 | 若借鉴，明确说明借鉴哪些具体规则、流程、模板 |
| 引用路径 | 本地 `.input/` 路径 + GitHub 原始链接 |

### 步骤 4：综合借鉴建议

- 列出推荐引入的**完整资源清单**（供 meta-dev/meta-qa 直接引用）
- 列出推荐**适配后引入**的清单（附适配说明）
- 列出可在 HLD 中直接引用的**架构模式、安全规则、工作流模板**
- 指出哪些资源直接影响 `ARCHITECTURE-DECISION.md` 的决策点

### 步骤 5：输出文件

将分析结果写入 `process/ANALYSIS-<project_id>-<analysis_topic>.md`。

## 输出格式：`ANALYSIS-<project_id>-<analysis_topic>.md`

```markdown
---
generated_by: meta-se / awesome-copilot-analysis
generated_at: <ISO-8601>
project: <project_id>
source_repo: https://github.com/github/awesome-copilot
requirements_version: <版本或 confirmed_at>
status: ready  # ready | partial（.input/ 不完整时）
---

# Awesome-Copilot 资源借鉴分析报告

## 项目特征摘要

- **技术栈**：<提取结果>
- **领域关键词**：<提取结果>
- **质量目标**：<提取结果>
- **集成需求**：<提取结果>

---

## 一、Agents 分析

### 可直接借鉴

| Agent | 本地路径 | GitHub 链接 | 核心功能 | 优点 | 缺点/局限 | 借鉴内容 |
|-------|---------|-----------|---------|------|----------|---------|
| `xxx.agent.md` | `.input/agents/xxx.agent.md` | [链接](https://raw.githubusercontent.com/github/awesome-copilot/main/agents/xxx.agent.md) | ... | ... | ... | ... |

### 需适配后借鉴

| Agent | 本地路径 | GitHub 链接 | 核心功能 | 适配说明 |
|-------|---------|-----------|---------|---------|

### 不适用（跳过原因）

> 跳过的 agents 统一在此简述原因，不展开分析。

---

## 二、Skills 分析

### 可直接借鉴

| Skill 目录 | 本地路径 | GitHub 链接 | 核心功能 | 优点 | 缺点/局限 | 借鉴内容 |
|-----------|---------|-----------|---------|------|----------|---------|

### 需适配后借鉴

| Skill 目录 | 本地路径 | GitHub 链接 | 适配说明 |
|-----------|---------|-----------|---------|

---

## 三、Workflows 分析

| Workflow | 本地路径 | GitHub 链接 | 核心功能 | 借鉴判断 | 借鉴内容/适配说明 |
|---------|---------|-----------|---------|---------|----------------|

---

## 四、Hooks 分析

| Hook | 本地路径 | GitHub 链接 | 核心功能 | 借鉴判断 | 借鉴内容/适配说明 |
|------|---------|-----------|---------|---------|----------------|

---

## 五、Instructions 分析

| Instruction 文件 | 本地路径 | GitHub 链接 | 适用技术栈 | 借鉴判断 | 借鉴内容 |
|----------------|---------|-----------|---------|---------|---------|

---

## 六、Plugins 分析

| Plugin 目录 | 本地路径 | GitHub 链接 | 包含资源 | 借鉴判断 | 借鉴内容/适配说明 |
|-----------|---------|-----------|---------|---------|----------------|

---

## 七、综合借鉴建议

### 7.1 直接引入清单（meta-dev / meta-qa 可直接使用）

| 资源路径 | 类型 | 引入方式 | 目标消费方 |
|---------|------|---------|---------|
| `.input/instructions/xxx.instructions.md` | instruction | 复制到 `.github/copilot-instructions.md` 或在 Story 卡片中引用 | meta-dev |
| `.input/hooks/secrets-scanner/` | hook | 集成到 pre-commit / CI | meta-qa |

### 7.2 适配引入清单

| 资源路径 | 类型 | 适配要点 | 目标消费方 |
|---------|------|---------|---------|

### 7.3 HLD 直接引用的架构模式 / 安全规则

> 列出可在 HLD.md 「技术选型」「非功能需求」「主要风险与应对」中直接引用的具体内容。

- **架构模式**：<来源资源> → <借鉴的具体模式>
- **安全规则**：<来源资源> → <具体规则条目>
- **工作流模板**：<来源资源> → <具体流程步骤>

### 7.4 对 ARCHITECTURE-DECISION.md 的影响

> 指出哪些资源影响架构决策，供 meta-se 在 HLD 确认后写 ARCHITECTURE-DECISION.md 时引用。

| 决策点 | 来源资源 | 推荐决策 | 理由 |
|-------|---------|---------|------|

---

## 八、遗留问题

> 若 .input/ 不完整，或某些资源内容无法读取，在此记录。

| 问题 | 影响 | 建议操作 |
|------|------|---------|
```

## 与 HLD.md 的集成约定

`meta-se` 输出 `HLD.md` 时，必须：

1. 在 `## 技术选型与理由` 中，对来自 `ANALYSIS-<project_id>-<analysis_topic>.md` 的借鉴内容加注来源引用：
   ```
   > 参考：[awesome-copilot/<资源路径>](<GitHub 链接>) — <一句话说明借鉴内容>
   ```
2. 在 `## 非功能需求设计` 中，引用借鉴的安全规范、测试规范等
3. 在 `## ADR 候选决策点` 中，引用来自分析报告 7.4 节的影响项
4. 在 HLD 末尾追加：
   ```markdown
   ## 附录：Awesome-Copilot 资源借鉴清单
   > 完整分析见 `process/ANALYSIS-<project_id>-<analysis_topic>.md`

   | 资源 | 类型 | 借鉴内容 | 消费方 |
   |------|------|---------|-------|
   ```

## 与 meta-dev / meta-qa 的集成约定

- `meta-dev` 在实现 Story 前，**必须读取** `ANALYSIS-<project_id>-<analysis_topic>.md` 的第 7.1 节，
  直接使用其中标注的 `instructions` 和 `agents`
- `meta-qa` 在执行验证前，**必须读取** 第 7.1 节中 hooks 部分，
  将 `secrets-scanner`、`dependency-license-checker`、`governance-audit` 等纳入验证流程

## 输出隔离

| 产出文件 | 路径 |
|---------|------|
| 分析报告 | `process/ANALYSIS-<project_id>-<analysis_topic>.md` |
| 无检查点文件（分析报告不需要人工确认） | — |

> 分析报告是 HLD 的**前置输入**，不是人工确认对象；但 HLD 检查点中需要引用分析结论。
