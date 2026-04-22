---
name: awesome-copilot-fetcher
description: >-
  从 https://github.com/github/awesome-copilot 拉取所有 agents、skills、workflows、hooks、
  instructions 和 plugins，存放到项目 .input/ 目录，并生成使用摘要。
  触发词包括：拉取 awesome-copilot、同步 copilot 资源、更新 .input、fetch awesome-copilot。
argument-hint: "可选：指定要拉取的类别（agents/skills/workflows/hooks/instructions/plugins）或 all（默认）"
user-invokable: true
called-by: meta-se, awesome-copilot-analysis
status: active
source: https://github.com/github/awesome-copilot
---

## 目标

通过 git sparse-checkout 从 `github/awesome-copilot` 拉取指定类别的资源文件，
存放到本项目 `.input/<category>/` 目录，并生成摘要说明每类资源的用途及在应用开发中的使用方式。

## 适用场景

- 初始化或更新项目的 Copilot 提示词资源库
- 为应用开发配置专属 Agent / Skill / Instruction 组合
- 探索 awesome-copilot 新增资源，同步到本地工作流

## 前置条件

- [ ] git 已安装且网络可访问 `https://github.com/github/awesome-copilot`
- [ ] 项目根目录存在（写入 `.input/`）

## 执行步骤

### 1. 创建目录结构

```bash
mkdir -p .input/{agents,skills,workflows,hooks,instructions,plugins}
```

### 2. 通过 sparse checkout 拉取

```bash
TMP=$(mktemp -d)
cd "$TMP"
git init -q
git remote add origin https://github.com/github/awesome-copilot.git
git sparse-checkout init
git sparse-checkout set agents skills workflows hooks instructions plugins
git pull --depth=1 origin main

# 复制到项目 .input/
cp -r agents/.      <PROJECT_ROOT>/.input/agents/
cp -r skills/.      <PROJECT_ROOT>/.input/skills/
cp -r workflows/.   <PROJECT_ROOT>/.input/workflows/
cp -r hooks/.       <PROJECT_ROOT>/.input/hooks/
cp -r instructions/. <PROJECT_ROOT>/.input/instructions/
cp -r plugins/.     <PROJECT_ROOT>/.input/plugins/
```

### 3. 输出摘要

执行完毕后，输出各目录文件数量统计及分类说明（见下方「资源目录」章节）。

## 资源目录

### `.input/agents/` — 204 个 Agent 文件

每个 `.agent.md` 文件是一个专用 AI 代理定义，在 VS Code / GitHub Copilot CLI 中直接加载使用。

**应用开发高价值 Agents（精选）：**

| Agent 文件 | 用途 |
|-----------|------|
| `api-architect.agent.md` | API 设计与架构评审 |
| `adr-generator.agent.md` | 自动生成架构决策记录（ADR） |
| `debug.agent.md` | 通用调试助手 |
| `code-tour.agent.md` | 代码库导览生成器 |
| `critical-thinking.agent.md` | 批判性代码评审 |
| `context-architect.agent.md` | 上下文工程架构师 |
| `devops-expert.agent.md` | DevOps 全栈专家 |
| `security-code-review.agent.md` | 安全代码审查 |
| `test-engineer.agent.md` | 测试工程专家 |
| `blueprint-mode.agent.md` | 蓝图规划模式 |
| `CSharpExpert.agent.md` | C# 专家 |
| `Thinking-Beast-Mode.agent.md` | 深度推理模式 |

**VS Code 安装链接示例：**
```
vscode-insiders://github.copilot/openFromUrl?url=https://raw.githubusercontent.com/github/awesome-copilot/main/agents/api-architect.agent.md
```

### `.input/skills/` — 308 个 Skill 目录

每个子目录包含一个可复用技能定义（通常含 `skill.md` 和模板）。

**应用开发高价值 Skills（精选）：**

| Skill 目录 | 用途 |
|-----------|------|
| `acquire-codebase-knowledge` | 快速获取代码库知识 |
| `architecture-blueprint-generator` | 架构蓝图生成器 |
| `breakdown-epic-arch` | Epic 拆分（架构视角） |
| `breakdown-feature-implementation` | 功能实现拆分 |
| `breakdown-plan` | 计划拆分 |
| `code-tour` | 代码导览 |
| `security-review` | 安全审查 |
| `unit-test-vue-pinia` | Vue/Pinia 单元测试 |
| `web-coder` | Web 开发助手 |
| `conventional-commit` | 规范化提交消息 |
| `automate-this` | 自动化任务生成 |
| `copilot-instructions-blueprint-generator` | Copilot 指令蓝图生成器 |

### `.input/workflows/` — 7 个 Workflow 文件

| 文件 | 用途 |
|------|------|
| `daily-issues-report.md` | 每日 Issues 报告工作流 |
| `ospo-contributors-report.md` | 开源贡献者报告 |
| `ospo-org-health.md` | 组织健康度检查 |
| `ospo-release-compliance-checker.md` | 发布合规检查 |
| `ospo-stale-repos.md` | 停滞仓库检测 |
| `relevance-check.md` | 内容相关性检查 |
| `relevance-summary.md` | 内容相关性摘要 |

### `.input/hooks/` — 6 个 Hook 目录

| Hook 目录 | 用途 |
|----------|------|
| `dependency-license-checker` | 依赖许可证检查 |
| `governance-audit` | 治理审计 |
| `secrets-scanner` | 密钥/凭证扫描 |
| `session-auto-commit` | 会话自动提交 |
| `session-logger` | 会话日志记录 |
| `tool-guardian` | 工具使用守卫 |

### `.input/instructions/` — 177 个 Instruction 文件

涵盖主流语言、框架和平台的编码规范，直接作为 `.github/copilot-instructions.md` 引用。

**应用开发高价值 Instructions（精选）：**

| 文件 | 适用场景 |
|------|---------|
| `a11y.instructions.md` | 无障碍开发规范 |
| `code-review-generic.instructions.md` | 通用代码审查规范 |
| `containerization-docker-best-practices.instructions.md` | Docker 最佳实践 |
| `context-engineering.instructions.md` | 上下文工程规范 |
| `csharp.instructions.md` | C# 开发规范 |
| `dart-n-flutter.instructions.md` | Flutter 开发规范 |
| `github-actions.instructions.md` | GitHub Actions 规范 |
| `javascript.instructions.md` | JavaScript 规范 |
| `python.instructions.md` | Python 规范 |
| `react.instructions.md` | React 开发规范 |
| `rust.instructions.md` | Rust 开发规范 |
| `security.instructions.md` | 安全编码规范 |
| `typescript.instructions.md` | TypeScript 规范 |

### `.input/plugins/` — 63 个 Plugin 目录

| Plugin 目录（部分） | 用途 |
|-------------------|------|
| `frontend-web-dev` | 前端 Web 开发插件包 |
| `java-development` | Java 开发插件包 |
| `csharp-dotnet-development` | C#/.NET 开发插件包 |
| `context-engineering` | 上下文工程插件包 |
| `database-data-management` | 数据库管理插件包 |
| `devops-oncall` | DevOps 值班插件包 |
| `azure-cloud-development` | Azure 云开发插件包 |
| `security-review` | 安全审查插件包（通过 `awesome-copilot` 聚合） |

## 应用开发工作流组合建议

以下工作流可由上述资源直接支持：

### 工作流 1：新功能开发
```
instructions/[language].instructions.md       → 编码规范上下文
agents/api-architect.agent.md                 → API 设计
agents/blueprint-mode.agent.md                → 功能蓝图规划
skills/breakdown-feature-implementation/      → 实现任务拆分
agents/code-tour.agent.md                     → 为新成员生成导览
```

### 工作流 2：代码审查与质量保障
```
agents/critical-thinking.agent.md             → 批判性代码审查
agents/debug.agent.md                         → 调试辅助
instructions/code-review-generic.instructions.md → 审查规范
skills/security-review/                       → 安全审查
hooks/secrets-scanner/                        → 提交前密钥扫描
```

### 工作流 3：架构决策
```
agents/adr-generator.agent.md                 → ADR 生成
agents/context-architect.agent.md             → 上下文架构设计
skills/architecture-blueprint-generator/      → 架构蓝图
agents/devils-advocate.agent.md               → 挑战性验证
```

### 工作流 4：DevOps 与发布
```
agents/devops-expert.agent.md                 → DevOps 任务
instructions/containerization-docker-best-practices.instructions.md → Docker 规范
workflows/ospo-release-compliance-checker.md  → 发布合规检查
hooks/governance-audit/                       → 治理审计
hooks/dependency-license-checker/             → 许可证检查
```

### 工作流 5：测试策略
```
skills/breakdown-test/                        → 测试计划拆分
skills/spring-boot-testing/                   → Spring Boot 测试
skills/unit-test-vue-pinia/                   → Vue 单元测试
agents/Thinking-Beast-Mode.agent.md           → 深度测试场景推理
```

## 输出说明

执行完毕后在 `.input/` 下产生以下结构：

```
.input/
├── agents/          # 204 个 .agent.md 文件
├── skills/          # 308 个 skill 目录
├── workflows/       # 7 个 workflow.md 文件
├── hooks/           # 6 个 hook 目录
├── instructions/    # 177 个 .instructions.md 文件
└── plugins/         # 63 个 plugin 目录
```

## 附加建议

1. **按技术栈筛选**：`instructions/` 下按框架命名，直接匹配项目技术栈
2. **Plugin 包优先**：`plugins/` 目录聚合了多个相关资源，适合整体引入
3. **Hook 集成**：`hooks/secrets-scanner` 和 `hooks/dependency-license-checker` 建议在所有项目中启用
4. **定期同步**：此 Skill 可定期执行以获取上游最新资源（`git pull --depth=1`）
5. **VS Code 安装**：所有 `.agent.md` 文件支持通过 `vscode-insiders://github.copilot/openFromUrl` 协议直接安装
