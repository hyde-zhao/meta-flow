# 高层设计（HLD）：跨平台用户级统一指令 / Skill / 工具方案（Codex / Claude Code）

> 迁移说明：本文已从 `docs/` 迁移到 `process/`，作为过程实施分析文档保留。

> **评审记录**
>
> - 2026-04-18 初稿：提出共享 template / shared runtime。
> - 2026-04-20 二次评审：废止共享 template，改用平台原生渲染；把运行输出从 meta 仓库 `.output/` 迁移到目标工作区 `process/`、`checkpoints/`、`delivery/`；补充运行时优先级与覆盖链。
> - **2026-04-21 三次评审**：
>   1. 统一 **B-xx / L-xx 双问题体系**为单一 `Q-xx` 问题跟踪表 + 问题详细描述章节；
>   2. 对 **Codex 独立 TOML subagent 文件**补充风险标注与版本下限要求；
>   3. 放宽 **WORKSPACE_ROOT 来源合同**：主选从 cwd 向上查找 git repo root，`--project-dir` 为覆盖项，两者都缺失才报错；
>   4. 补充 **canonical agent 过渡期 permissive 模式**作为严格失败的热备选；
>   5. **调整 Phase 顺序**：`delivery/scripts/install.py` 平台渲染面修正前置到 Phase 2；
>   6. 新增：卸载 / 清理、版本审计线、跨平台事务性回滚、`.gitignore` 噪音控制、managed block 边界；
>   7. 所有"待决策"问题均给出主选候选。
>
> - **2026-04-21 四次评审（本轮）· 用户决策回写**：
>   1. **Q-20 更正**：`~/.agents/skills/` **是** Codex 官方 USER scope 路径（依据：<https://developers.openai.com/codex/skills>），上一轮评审误判为 myflow 自家约定，本轮修正。继续沿用，两平台共用 canonical source 的前提成立。
>   2. **Q-21 敲定**：仅支持 **Codex 最新版本**（独立 TOML 文件载体），不保留 `config.toml [agents.<name>]` fallback。新增第 **7.9 节「Codex Subagent 写作规范」**，依据 <https://developers.openai.com/codex/subagents>。
>   3. **Q-26 敲定**：全局命名规范 —— Skill 名、Subagent 名在各自命名空间内必须全局唯一；跨命名空间强烈建议不重复（`/skills` 与 `$agent` 触发面不同但视觉相似会造成误用）。新增第 **4.5 节「全局命名与冲突检测」**，含第三方 Skill / Subagent 引入时的冲突检测机制。
>   4. **Q-27 敲定**：当前主要运行环境是 **WSL**（Linux 语义），Codex Hooks 的 Windows 禁用问题在 WSL 下不触发；方案中保留备注即可，不做 Windows 原生路径特殊处理。
>
> - **2026-04-28 五次评审 · CR-001 回写**：
>   1. 新增 `delivery/doc/PLATFORM-CONTRACTS.yaml` 作为平台安装路径单一真相源；
>   2. `delivery/scripts/install.py` 已改为从契约矩阵读取 rules / agents / skills 路径；
>   3. guardrail 已覆盖 Codex Skill 项目级 `.agents/skills`、用户级 `~/.agents/skills` 正向断言，以及 `.codex/skills` / `~/.codex/skills` 负向断言。

---

## 1. 问题定义

一套 canonical source，经渲染后同时服务 **Codex** 与 **Claude Code**，并把元工作流运行结果写到 **被服务工作区**（不是 meta 仓库自身）。

核心难点不是"复制文件"，而是：

1. 两平台的**发现面**不同（Claude Markdown+frontmatter，Codex TOML）；
2. 旧方案错误引入共享 template / shared runtime；
3. 元工作流默认把 `.output/` 写到 meta 仓库自己目录，与"服务当前工作区"不一致；
4. 只列目标路径，未固化运行时优先级 / 覆盖链；
5. Agent 在两平台并非只差目标目录，存在 schema 差异（Codex `developer_instructions` vs Claude `body`、Codex 无 `tools` 字段等）；
6. `.output -> .meta-workflow` 迁移缺兼容策略；
7. 仓库 `delivery/scripts/install.py`、README、USER-MANUAL、`platform-validator` 已通过 CR-001 收敛到平台契约矩阵；
8. Skill / Subagent 全局命名未规范，第三方引入缺冲突检测。

---

## 2. 问题跟踪表（统一编号）

> 本表合并并替代旧 `B-01~B-16` / `L-01~L-19` 双体系。  
> 每条问题在 **第 8 节「问题详细描述」** 中有完整背景、影响范围、主选 / 备选与决策人。  
> 状态语义：`closed`（已解决并固化）、`decided`（已给出主选，实施待落地）、`open`（仍需用户最终决策）、`in-progress`（实施中）。

| 编号 | 状态 | 主题 | 简述 |
|------|------|------|------|
| Q-01 | in-progress | 相对路径依赖 | `delivery/scripts/`、硬编码仓库路径需改为面向目标项目根目录的路径合同 |
| Q-02 | closed | 工具共享运行时 | 本轮不把共享 runtime 作为目标，只收敛指令 / Skill / 产物渲染 |
| Q-03 | closed | 两平台差异 | Codex 与 Claude Code 发现面不同，必须分别渲染 |
| Q-04 | decided | 工作区根目录合同 | 主选：cwd → 向上查找 git repo root → `--project-dir` 覆盖 → 都缺失则报错；备选：显式强制输入 |
| Q-05 | closed | Codex subagent 文件载体 | 独立 TOML 文件（`~/.codex/agents/*.toml` / `.codex/agents/*.toml`）；无 fallback；与 Q-21 合并 |
| Q-06 | closed | 目标平台范围 | 本轮仅 Codex / Claude Code |
| Q-07 | closed | 用户状态分离 | `~/.claude.json`、Codex `auth.json` / `history.jsonl` / memories 不托管 |
| Q-08 | in-progress | Python 入口 | 统一为 `uv run --python 3.11 python delivery/scripts/install.py ...`（交付安装器）或 `uv run --with pyyaml --python 3.11 python scripts/package_builder.py ...`（仓库级辅助脚本） |
| Q-09 | in-progress | `/skill` 与 `$skill` 调用语法 | 需统一渲染规则，两端命中均不降级到自由文本 |
| Q-10 | closed | 托管配置所有权 | `model`、`provider`、`mcp` 不托管 |
| Q-11 | in-progress | Skill 注册表闭环 | 影响 Agent/Skill 关系变更时必须回写 `delivery/skills/README.md` |
| Q-12 | in-progress | Skill 辅助脚本占位 | 需清点真实可用 / 规划项，不得留死引用 |
| Q-13 | decided | 运行时优先级 / 覆盖链 | 主选：见第 3 节；写入目标路径仅表示"安装成功"，doctor 负责"运行时是否生效"判断 |
| Q-14 | decided | canonical agent 字段合同 | 主选：共享核心字段 `name/description/instructions` + 严格失败；过渡期 `--permissive` 允许仅丢弃平台专属字段并落审计记录 |
| Q-15 | decided | `.output -> .meta-workflow` 迁移 | 主选：新写入只落新路径；旧路径只读兜底；兜底期 doctor 强制提示；切换完成条件见第 6.3 节 |
| Q-16 | closed | 仓库实现漂移 | CR-001 已将安装器、README、USER-MANUAL、platform-validator 与 guardrail 收敛到 `delivery/doc/PLATFORM-CONTRACTS.yaml` |
| Q-17 | decided | Override / Local 层处理 | 主选：只提示不阻断；备选：阻断渲染 / 仅记录不提示 |
| Q-18 | decided | canonical agent 共享字段白名单 | 主选：共享 `{name, description, instructions}`；可映射 `{model, tools}` 经映射矩阵；其它严格失败 |
| Q-19 | decided | 用户已有 `AGENTS.md` / `CLAUDE.md` 的 merge 策略 | 主选：**managed block 夹带**（以 HTML 注释哨兵为边界，仅替换块内，不触碰人工内容）；备选：整体托管 / 外部 `@import` 导入 |
| Q-20 | closed | `~/.agents/skills/` 路径归属 | 经查证为 Codex 官方 USER scope 路径，继续沿用；两平台共用 canonical Skill source 成立 |
| Q-21 | closed | Codex 独立 TOML subagent 文件支持下限 | 仅支持 Codex 最新版本（独立文件载体），无 fallback；写作规范见 §7.9 |
| Q-22 | decided | `process/checkpoints/delivery/` 噪音控制 | 主选：安装器自动建议把 `process/` 与 `checkpoints/` 加入 `.gitignore`，仅 `delivery/` 默认入库 |
| Q-23 | decided | 卸载 / 清理策略 | 主选：`install.py --uninstall --platform <name>` 按 `INSTALL-MANIFEST.yaml` 清单精确移除；managed block 仅清空块内容保留文件 |
| Q-24 | decided | 版本审计线 | 主选：渲染时在每个产物头部注入哨兵注释（含 canonical commit + 版本 + 生成时间），doctor 比对 canonical 与 installed 版本漂移 |
| Q-25 | decided | 跨平台事务性回滚 | 主选：按平台分事务独立提交；单平台失败只回滚该平台，其它平台保留已装内容并在 manifest 中记录 partial 状态 |
| Q-26 | closed | Skill / Subagent 全局命名 | 各命名空间内全局唯一；引入第三方时走 §4.5 冲突检测机制 |
| Q-27 | closed | Codex Hooks Windows 禁用 | 主要运行环境是 WSL（Linux 语义），Windows 原生禁用问题不触发；文档中备注即可 |

**全部问题均已 `closed` / `decided` / `in-progress`，无 `open` 阻塞项，Phase 1 可以开工。**

---

## 3. 平台事实基线（修订后）

### 3.1 Codex

| 类别 | 位置 | 说明 |
|------|------|------|
| 主配置 | `~/.codex/config.toml` | 全局配置入口；全局 subagent 并发 / 深度在 `[agents]` 顶层 |
| 持久指令 | `~/.codex/AGENTS.md` | 用户级全局指令 |
| Skills（USER scope） | `~/.agents/skills/<name>/SKILL.md` | **Codex 官方 USER scope 路径**（见 [skills 文档](https://developers.openai.com/codex/skills)） |
| Skills（REPO scope） | `$CWD/.agents/skills/`、`$CWD/../.agents/skills/`、`$REPO_ROOT/.agents/skills/` | 从 cwd 向上扫描到 repo root |
| Skills（ADMIN scope） | `/etc/codex/skills/` | 系统管理员全局配置位置（不托管） |
| 用户级 subagent | `~/.codex/agents/<name>.toml` | 独立 TOML 文件，必填 `name` / `description` / `developer_instructions` |
| 项目级 subagent | `<repo>/.codex/agents/<name>.toml` | 同上 |
| Hooks | `~/.codex/hooks.json` | experimental；Windows 原生禁用（WSL 下不受影响，见 Q-27） |
| 用户状态 | `auth.json` / `history.jsonl` / `memories/` | 不托管 |

#### 3.1.1 Codex 运行时优先级 / 覆盖链

| 对象 | 优先级（近者 / 高者胜出） |
|------|---------------------------|
| `config.toml` | CLI flags / `--config` → profile → trusted project `.codex/config.toml`（root→cwd 逐级） → user `~/.codex/config.toml` → system → built-in defaults |
| `AGENTS.md` | `CODEX_HOME` 下 `AGENTS.override.md` 或 `AGENTS.md` → project root 到 cwd 各级 `AGENTS.override.md` / `AGENTS.md`；**按从根到近处拼接**（不是覆盖） |
| Skills | cwd 向上扫 `.agents/skills/`；user skills 在 `~/.agents/skills/`；**同名 skill 不自动合并**；高优先级位置直接胜出 |
| 自定义 agents | user `~/.codex/agents/*.toml` + project `.codex/agents/*.toml`；**Codex 运行时事实**：与 built-in 重名时自定义胜出；**myflow 安装器规则**（见 §4.5）：与 built-in 重名 **阻断渲染**，避免静默覆盖内置行为 |
| Hooks | 读取自活动 config layer 同级；**多个 hooks 并行运行而非相互覆盖** |

**设计含义**：写入 `~/.codex/` 只是"安装成功"；doctor 必须检查 `AGENTS.override.md`、project config、project-scoped agents 是否覆盖受管内容（Q-17 主选：提示不阻断）。

### 3.2 Claude Code

| 类别 | 位置 | 说明 |
|------|------|------|
| 主配置 | `~/.claude/settings.json` | 用户级 |
| 持久指令 | `~/.claude/CLAUDE.md` | 用户级全局指令 |
| Skills | `~/.claude/skills/<name>/SKILL.md` | 原生路径 |
| Subagents | `~/.claude/agents/<name>.md` | Markdown + YAML frontmatter |
| 用户状态 | `~/.claude.json` | 不托管 |

#### 3.2.1 Claude Code 运行时优先级 / 覆盖链

| 对象 | 优先级 |
|------|--------|
| `settings.json` | managed → CLI → local `.claude/settings.local.json` → project `.claude/settings.json` → user `~/.claude/settings.json` |
| `CLAUDE.md` | `~/.claude/CLAUDE.md` + 项目 `CLAUDE.md` / `.claude/CLAUDE.md` / `CLAUDE.local.md` 参与；目录链上方文件启动加载，子目录按需加载；`CLAUDE.local.md` 追加在 `CLAUDE.md` 之后 |
| Skills | enterprise / managed > **personal** `~/.claude/skills/` > project `.claude/skills/` > plugin |
| Subagents | managed > CLI `--agents` > **project** `.claude/agents/` > user `~/.claude/agents/` > plugin |
| Rules / Hooks | `.claude/rules/*.md` 属上下文规则层；hooks 在 `settings.json`、skill / agent frontmatter 定义 |

**⚠️ 不对称提示**（Q-26）：Claude Code 的 Skills 是 **user 高于 project**，但 Subagents 是 **project 高于 user**。安装到用户级后：user-level skill 会胜过项目级 skill，但 user-level subagent 会被项目级 subagent 覆盖。doctor 必须针对两类产物分别判断。

### 3.3 本轮必须遵守的结论

1. Skill 保持原生 `SKILL.md`；
2. 两平台共用同一 canonical Skill source；
3. 两平台 subagent 不共用发现入口文件；
4. 共享 template 方案废止，默认内联；
5. 不建设 shared runtime 根目录；
6. 文档必须同时描述**安装目标路径**和**运行时生效优先级**；
7. **写入目标路径 ≠ 运行时一定生效**，doctor 负责后者。

---

## 4. 核心设计原则

### 4.1 单一来源 + 平台原生渲染

Canonical source：`delivery/agents/`、`delivery/skills/`、`delivery/rules/`、`delivery/scripts/`。

渲染目标：

- Codex：`~/.codex/AGENTS.md`（Q-19 managed block） + `~/.agents/skills/<name>/SKILL.md`（Codex 官方 USER scope） + `~/.codex/agents/<name>.toml`（§7.9 写作规范）
- Claude Code：`~/.claude/CLAUDE.md`（Q-19 managed block） + `~/.claude/skills/<name>/SKILL.md` + `~/.claude/agents/<name>.md`

### 4.2 不再保留共享 template

- 默认内联
- 保留已有且有 owner 的 Skill 私有 `templates/`
- 不引入新的共享模板域

### 4.3 元工作流输出写入目标工作区根目录

统一改为：`{{WORKSPACE_ROOT}}/process/`、`{{WORKSPACE_ROOT}}/checkpoints/`、`{{WORKSPACE_ROOT}}/delivery/`。

**WORKSPACE_ROOT 来源合同**（Q-04 主选）：

1. `--project-dir <path>` 显式覆盖（最高）；
2. 否则从进程 cwd 向上查找最近的 git repo root；
3. 两者都缺失（既没传参也不在任何 git repo 内）才报错，不回退 meta 仓库目录或 cwd。

**`TARGET_PROJECT_ROOT`** 为文档展示别名，语义等同 `WORKSPACE_ROOT`。  
**`PROJECT_META_ROOT = {{WORKSPACE_ROOT}}/.meta-workflow`**。

### 4.4 canonical agent 字段合同（Q-14 / Q-18）

1. **共享核心字段**（严格必填）：`name`、`description`、`instructions`
2. **可映射字段**（双端精确映射矩阵）：`model`
3. **平台专属字段**：仅允许在各自平台分支中出现；常见例：Claude `tools`、Codex `sandbox_mode` / `mcp_servers` / `skills.config` / `model_reasoning_effort` / `nickname_candidates`

**主选失败模式：严格失败** —— canonical 中出现无法无损映射的字段时直接报错，不静默。

**过渡期热备选：`--permissive` 开关** —— 允许渲染时丢弃未识别的字段并写入 `INSTALL-MANIFEST.yaml` 的 `warnings[]`，用于字段白名单尚未收敛的初期。**默认关闭**。

**禁止**：平台分支字段块未进入白名单即静默采用；`--permissive` 下不产生 warnings。

### 4.5 全局命名与冲突检测（Q-26）

**命名规范**（写入全局开发标准，适用于所有 Skill 与 Subagent 作者）：

1. **Skill 名在全部 Skill 命名空间内必须唯一**（涵盖 SYSTEM / ADMIN / USER / REPO 全部 scope）。
2. **Subagent 名在全部 Subagent 命名空间内必须唯一**（涵盖 built-in / USER / REPO）。
3. **强烈建议 Skill 与 Subagent 跨命名空间不重名**：`/skills` 与 `$agent` 触发面不同但视觉相似，重名会造成误用。
4. 格式：小写 kebab-case，`^[a-z][a-z0-9-]{2,39}$`（3–40 字符，首字符字母）。
5. **禁止与 Codex built-in subagent 重名**：`default`、`worker`、`explorer`（重名会覆盖内置行为）。
6. 命名前缀建议：第一方 Skill / Subagent 无前缀；第三方 / 组织托管建议 `<org>-<name>` 或在 `description` 中注明来源。

**冲突检测机制**（安装器 / doctor 实现）：

1. **注册表**：`delivery/skills/README.md` 维护 Skill 注册表；新增 `delivery/agents/README.md` 维护 Subagent 注册表；两者都纳入 canonical source。
2. **安装时预检**：`install.py` 在写入前执行：
   - 扫描目标平台所有 scope 下已存在的 Skill / Subagent 名；
   - 与本次渲染清单（canonical source）比对；
   - 若发生同 scope 同名冲突：按 Q-17 主选**提示不阻断**，冲突项写入 `INSTALL-MANIFEST.yaml` 的 `conflicts[]` 并标注受影响 scope 与解决建议（rename / 指定 scope / 放弃安装）。
3. **第三方引入时强制走 `install.py --import <source>`**：
   - 下载 / 拷贝前扫描来源目录的 `SKILL.md` / `*.toml` 的 `name` 字段；
   - 与本地注册表比对，命中冲突时**默认阻断**（不同于第一方的"提示不阻断"），提示用户选择：
     - 跳过导入；
     - 重命名后导入（在 `description` 中记录原名称）；
     - 指定低优先级 scope 导入并承担覆盖风险。
4. **doctor 定期扫描**：列出当前生效的 Skill / Subagent 清单 + 来源 + scope，当检测到跨 scope 同名（高优先级胜出导致低优先级被隐藏）时发出提示。
5. **built-in 名称保护**：安装器对 `default` / `worker` / `explorer` 检测到的用户级同名 subagent **阻断渲染**并报错，需用户先改名。

**注册表格式示例**（`delivery/agents/README.md` 片段）：

```markdown
| 名称 | 类型 | 来源 | 描述 |
|------|------|------|------|
| meta-po | subagent | first-party | ... |
| meta-pm | subagent | first-party | ... |
```

---

## 5. 目标项目根目录结构

### 5.1 总体结构

```text
<WORKSPACE_ROOT>/
  process/
  checkpoints/
  delivery/
    process/               # 过程文档（默认建议加入 .gitignore，Q-22）
      STATE.md
      REQUEST.md
      INPUT-INDEX.md
      CLARIFICATION-LOG.md
      USE-CASES.md
      REQUIREMENTS.md
      HLD.md
      ARCHITECTURE-DECISION.md
      STORY-BACKLOG.md
      DEVELOPMENT-PLAN.yaml
      TEST-STRATEGY.md
      changes/CR-*.md
      run/RUN-EXEC-*.md
      stories/STORY-*.md
      stories/STORY-*-LLD.md

    checkpoints/           # 人工确认版（默认建议加入 .gitignore，Q-22）
      CHECKPOINT-REQUIREMENTS.md
      CHECKPOINT-HLD.md
      CHECKPOINT-STORY-PLAN.md
      CHECKPOINT-STORY-LLD-<story-id>.md
      CHECKPOINT-FINAL-REVIEW.md

    delivery/              # 最终交付物（默认入库）
      README.md
      doc/
        USER-MANUAL.md
        HLD.md
        ARCHITECTURE-DECISION.md
        VERIFICATION-REPORT.md
        INSTALL-MANIFEST.yaml  # Q-23 / Q-24 的真相源
        CONTEXT-MANIFEST.yaml
      stories/
      agents/
      skills/
      rules/
      scripts/
```

### 5.2 三类文档职责

| 区域 | 用途 | 入库默认 |
|------|------|----------|
| `process/` | 过程文档 | **不入库**（Q-22 建议 `.gitignore`） |
| `checkpoints/` | 人工确认 | **不入库** |
| `delivery/` | 交付物 | **入库** |

安装器在初始化工作目录时默认提示用户把 `process/`、`checkpoints/` 加入 `.gitignore`，用户可关闭此建议。

### 5.3 输出规则

1. 过程文档只进 `process/`；
2. 正式 check 文档只进 `checkpoints/`；
3. 验证通过的可交付物只进 `delivery/`；
4. 不在项目根散落过程文件；
5. 顶层 `AGENTS.md` / `CLAUDE.md` 由最终渲染步骤从 `delivery/` 提升，且**不绕过 Q-19 managed block 合同**。

---

## 6. meta Skill / Agent 路径整改

基于 `PROJECT_META_ROOT = {{WORKSPACE_ROOT}}/.meta-workflow`。

### 6.1 Skill 整改

| Skill | 新位置 | 备注 |
|-------|--------|------|
| `state-router` | `process/STATE.md` | |
| `requirement-clarifier` | `process/CLARIFICATION-LOG.md` | |
| `requirement-extraction` | `process/REQUIREMENTS.md` | |
| `scenario-expansion` | `process/USE-CASES.md` | |
| `scope-normalization` | `process/REQUIREMENTS.md` | |
| `hld-designer` | `process/HLD.md` → `checkpoints/CHECKPOINT-HLD.md` → `delivery/doc/HLD.md` | 三段式 |
| `story-manager` | `process/STORY-BACKLOG.md`、`process/stories/*` | |
| `lld-designer` | `process/stories/STORY-*-LLD.md` → `checkpoints/CHECKPOINT-STORY-LLD-*.md` | |
| `change-impact-analysis` | `process/changes/CR-*.md` | |
| `run-feedback-parser` | `process/run/RUN-EXEC-*.md` | |
| `workflow-renderer` | `delivery/` | 只从 `process/` / `checkpoints/` 读 |
| `context-manifest-builder` | `delivery/doc/CONTEXT-MANIFEST.yaml` | |
| `package-builder` / `platform-validator` | `delivery/scripts/`、`delivery/doc/INSTALL-MANIFEST.yaml` | |

### 6.2 Agent 连带影响

| Agent | 调整点 |
|-------|--------|
| `meta-po` | 不再初始化仓库根 `.output/`；初始化 `{{PROJECT_META_ROOT}}/process/`、`checkpoints/` |
| `meta-pm` | 需求 / 澄清文档进 `process/` |
| `meta-se` | HLD / Story / Plan 走三段式 |
| `meta-dev` | LLD 与实现物走新结构；影响 Skill 关系时同步 `delivery/skills/README.md` |
| `meta-qa` | TEST-STRATEGY、验证报告、安装清单进新位置 |
| `meta-doc` | 只从已确认 / 已验证对象生成 `delivery/` |

### 6.3 `.output → .meta-workflow` 迁移策略（Q-15）

1. **新写入只落 `{{PROJECT_META_ROOT}}`**；
2. 兜底期允许**只读** `.output/`（明显迁移提示）；
3. 所有 meta Agent / Skill / 安装器 / 校验器完成切换后，移除兜底；
4. 兜底期 doctor / validator 必须识别"仍依赖旧 `.output/`"并提示未完成迁移。

**禁止**：长期双写、静默兜底、未完成治理就宣称 `.output/` 已废止。

**退场条件**：(a) 所有 Skill 的默认写路径都已指向新路径；(b) `delivery/scripts/install.py`、`platform-validator`、`README.md` 不再引用 `.output/`；(c) 连续一个迭代周期 doctor 未触发"旧路径依赖"提示。

---

## 7. 平台渲染策略

### 7.1 Codex

正式目标面：

1. `~/.codex/AGENTS.md`（Q-19 managed block）
2. `~/.agents/skills/<name>/SKILL.md`（Codex 官方 USER scope）
3. `~/.codex/agents/<name>.toml`（仅支持 Codex 最新版本，独立 TOML 文件）
4. 必要时 `~/.codex/config.toml` 的 `[agents]` 全局设置（`max_threads` / `max_depth` / `job_max_runtime_seconds`）

**不再采用**：内联 prompt 作为唯一路径、`config.toml [agents.<name>]` 作为独立 subagent 文件的 fallback、伪 `.codex/agents/*.yaml`、假设两平台都走 Markdown agent 文件。

### 7.2 Claude Code

正式目标面：

1. `~/.claude/CLAUDE.md`（Q-19 managed block）
2. `~/.claude/skills/<name>/SKILL.md`
3. `~/.claude/agents/<name>.md`

### 7.3 managed block 合同（Q-19）

> **适用范围：仅 Markdown 类文件**（`~/.codex/AGENTS.md` / `~/.claude/CLAUDE.md`），这类文件可能已存在用户手工内容。  
> **与 §7.5 版本审计哨兵的区别**：§7.3 是**文件级边界**（保护文件内人工区），§7.5 是**产物级审计行**（每个受管产物头部一行版本信息）。两者独立存在，可同时使用。

对 `AGENTS.md` / `CLAUDE.md`：

```
<!-- myflow:managed:begin v=1 commit=<sha> generated=<ISO-8601> -->
... canonical 渲染内容 ...
<!-- myflow:managed:end -->
```

规则：

1. 只替换两个哨兵之间的内容；哨兵外的用户内容**严禁触碰**；
2. 哨兵缺失时首次写入；哨兵损坏时报错并提示用户手工修复；
3. `--uninstall` 时仅清空块内内容，保留哨兵（用户可手动移除文件）。

### 7.4 不托管的范围

- **Claude Code**：
  - `~/.claude.json`（用户状态）
  - `~/.claude/settings.json` 的 **`permissions` / `hooks` / `model` / MCP 配置片段**（安装器不写入 `settings.json`）
- **Codex**：
  - 认证 / 历史 / memories（`auth.json` / `history.jsonl` / `memories/`）
  - `~/.codex/config.toml` 中的 `model` / `provider` / `mcp` / 用户个人 profile 段；**仅允许写入** `[agents]` 下的 `max_threads` / `max_depth` / `job_max_runtime_seconds`（且仅在用户明确开启时）
  - `~/.codex/hooks.json`（experimental，且 Windows 原生禁用；WSL 下虽可运行，本轮仍**不托管**）
- **跨平台**：project-local override / local 文档（`AGENTS.override.md` / `CLAUDE.local.md` / `.claude/settings.local.json` / project-scoped agents / skills）

### 7.5 版本审计（Q-24）

每个受管产物头部注入哨兵行（或 frontmatter / toml 注释）：

```
# myflow-managed: version=<semver> canonical-commit=<sha> generated=<ISO-8601>
```

doctor 通过该哨兵比对 canonical 与 installed 版本漂移；哨兵缺失视为"未受管"（用户手工改过），doctor 提示是否重新渲染。

### 7.6 卸载策略（Q-23）

`install.py --uninstall --platform <name>`：

1. 读取 `INSTALL-MANIFEST.yaml` 精确清单；
2. 对独立产物文件（`.toml` / Skill 目录 / agent `.md`）直接删除；
3. 对 managed block 文件仅清空块内内容并保留文件；
4. 清理后重写 manifest，标记 `uninstalled_at`。

### 7.7 跨平台事务性回滚（Q-25）

按平台独立事务：单平台渲染失败只回滚该平台（删除已写但未完成的产物），其它平台保留已装内容并在 manifest 标 `status: partial`。不尝试全局原子化。

### 7.8 当前仓库实现漂移（Q-16）

CR-001 已关闭本项：

1. `delivery/scripts/install.py` 已从 `delivery/doc/PLATFORM-CONTRACTS.yaml` 读取 rules / agents / skills 路径矩阵；
2. Codex agent 已渲染为 `.codex/agents/*.toml` / `~/.codex/agents/*.toml`，遵循 §7.9 写作规范；
3. Codex Skill 已渲染为 `.agents/skills/<name>/SKILL.md` / `~/.agents/skills/<name>/SKILL.md`，并将 `.codex/skills` / `~/.codex/skills` 作为禁止路径；
4. README、USER-MANUAL、`package-builder`、`platform-validator` 已同步为派生说明，不再作为平台路径事实来源；
5. `scripts/check_delivery_guardrails.py` 已新增 Codex Skill dry-run 正向 / 负向断言。

### 7.9 Codex Subagent 写作规范（Q-21）

> 依据：<https://developers.openai.com/codex/subagents>。仅支持 Codex 最新版本，独立 TOML 文件载体，无 fallback。

#### 7.9.1 文件位置

- 用户级：`~/.codex/agents/<name>.toml`
- 项目级：`<repo>/.codex/agents/<name>.toml`
- 每个文件定义**一个** subagent，文件名（去掉 `.toml`）必须与 `name` 字段一致。

#### 7.9.2 必填字段

| 字段 | 类型 | 约束 |
|------|------|------|
| `name` | string | 小写 kebab-case，`^[a-z][a-z0-9-]{2,39}$`；遵循 §4.5 全局命名规范；禁止与 built-in（`default` / `worker` / `explorer`）或已注册 Skill 重名 |
| `description` | string | implicit 匹配依据，**必须明确"何时触发、何时不触发"边界**（与 Skill 描述同标准） |
| `developer_instructions` | string | 作为 subagent system prompt 层级的指令；使用多行 TOML 字符串 `"""..."""` |

#### 7.9.3 可选字段（省略时继承父会话）

| 字段 | 用途 |
|------|------|
| `nickname_candidates` | 候选别名数组，供 `/agent` 切换时匹配 |
| `model` | OpenAI 模型标识（与父会话 `model` 策略对齐） |
| `model_reasoning_effort` | `low` / `medium` / `high` |
| `sandbox_mode` | `read-only` / `workspace-write` / `danger-full-access`；父会话运行时覆盖（`/approvals`、`--yolo`）会重新应用，自定义默认值会被盖 |
| `mcp_servers` | 数组；**Q-10 已明确 mcp 不托管，本字段安装器永远不写入**；若 canonical source 中出现该字段，严格失败模式下报错 |
| `skills.config` | 允许该 subagent 加载的 Skills 过滤清单 |

#### 7.9.4 模板

```toml
name = "<kebab-case-name>"
description = """
<一句话说明适用场景>。
何时触发：<具体条件>。
何时不触发：<具体反例>。
"""
developer_instructions = """
<subagent 的 system prompt 内容>

## 职责
...

## 禁止
...
"""

# 可选
# nickname_candidates = ["alt-name-1", "alt-name-2"]
# model = "gpt-5.2-codex"
# model_reasoning_effort = "medium"
# sandbox_mode = "read-only"
```

#### 7.9.5 全局调度（`~/.codex/config.toml` 的 `[agents]`）

| 字段 | 默认 | 说明 |
|------|------|------|
| `agents.max_threads` | `6` | 并发打开的 agent 线程上限 |
| `agents.max_depth` | `1` | spawned agent 嵌套深度（root=0）；**保持默认，除非明确需要递归委派** |
| `agents.job_max_runtime_seconds` | `1800` | `spawn_agents_on_csv` 单 worker 默认超时 |

**渲染约束**：

1. 安装器生成 `.toml` 时必须校验三个必填字段非空；
2. `name` 冲突走 §4.5 冲突检测；
3. 与 built-in 重名时**阻断渲染**（§4.5 规则 5）；
4. `developer_instructions` 中不得内联其它 subagent 的定义；
5. 渲染头部注入第 7.5 节版本审计哨兵（TOML 注释形式 `# myflow-managed: ...`）。

---

## 8. 问题详细描述

### Q-04 工作区根目录来源合同 · decided

- **背景**：元工作流必须知道"当前被服务的项目根"，以决定 `process/`、`checkpoints/`、`delivery/` 写到哪里。二次评审要求显式输入，但这对 CLI / IDE / worktree 场景不友好。
- **影响**：若每次强制 `--project-dir`，用户侧几乎无法接受；若完全依赖 cwd，又容易误写到错误位置。
- **主选**：`--project-dir` > git repo root（从 cwd 向上找）> 报错。
- **备选**：严格显式输入（无自动推断）。
- **决策人**：用户确认 / QA 默认实施。

### Q-05 / Q-21 Codex 独立 TOML subagent 文件载体 · closed

- **四次评审敲定**：仅支持 Codex 最新版本，独立 TOML 文件；**取消** `config.toml [agents.<name>]` fallback。
- **写作规范**：见第 7.9 节。
- 三次评审中对 Q-21 提出的"最低版本号 / fallback 自动探测"已不再适用。

### Q-13 / Q-17 运行时优先级与 override 层处理 · decided

- **主选**：doctor 发现 `AGENTS.override.md` / `CLAUDE.local.md` / project-scoped 覆盖层时，仅提示不阻断。
- **备选**：阻断渲染 / 仅记录不提示。

### Q-14 / Q-18 canonical agent 字段合同 · decided

- **背景**：Codex 是 TOML（`developer_instructions` 承载指令体），Claude Code 是 MD+frontmatter（body 承载指令体），不存在"任意 agent markdown 都能双端渲染"。
- **主选**：白名单 + 严格失败，同时提供 `--permissive` 过渡期开关（默认关）。
- **映射矩阵**：

| canonical 字段 | Codex TOML 字段 | Claude Code frontmatter / body | 备注 |
|---------------|----------------|-------------------------------|------|
| `name` | `name` | frontmatter `name` | 共享核心 |
| `description` | `description` | frontmatter `description` | 共享核心 |
| `instructions` | `developer_instructions`（多行字符串） | body（frontmatter 之后的 Markdown 正文） | 共享核心 |
| `model` | `model` | frontmatter `model` | 可映射，但**两端取值域几乎不交集**（Codex: `gpt-5.x` / `gpt-5.x-codex`；Claude: `sonnet` / `opus` / `haiku`）；canonical 需以字符串直通，不由 myflow 做别名转换；无匹配时严格失败 |

**平台专属字段**（不进入共享合同，仅各平台分支使用）：

- Codex only：`sandbox_mode`、`mcp_servers`（强制不托管）、`skills.config`、`model_reasoning_effort`、`nickname_candidates`
- Claude only：`tools`（Codex subagent 无此字段）、其它 frontmatter 字段

其它字段需单独评审后才能加入。

### Q-15 `.output → .meta-workflow` 迁移 · decided

- **主选**：单写新路径 + 兜底只读旧路径 + doctor 强提示，退场条件见第 6.3 节。
- **禁止**：长期双写、静默兜底、预先宣布废止。

### Q-19 用户已有 `AGENTS.md` / `CLAUDE.md` 的 merge 策略 · decided

- **背景**：用户可能已手工编辑这些文件，整体覆盖会破坏用户资产。
- **主选**：**managed block 夹带**（HTML 注释哨兵，见 7.3）。
- **备选 A**：整体托管（强制覆盖，用户先备份）。
- **备选 B**：`@import` / `@include` 外部导入（需平台原生支持，现阶段两端都不保证）。

### Q-20 `~/.agents/skills/` 路径归属 · closed

- **三次评审曾误判**：将 `~/.agents/skills/` 标注为 myflow 自家约定。
- **本轮更正**：依据 <https://developers.openai.com/codex/skills>，Codex 官方定义了四类 scope：
  - `REPO`：`$CWD/.agents/skills` → `$CWD/../.agents/skills` → `$REPO_ROOT/.agents/skills`
  - `USER`：`$HOME/.agents/skills`
  - `ADMIN`：`/etc/codex/skills`
  - `SYSTEM`：Codex 内置
- `~/.agents/skills/` 即 Codex 官方 USER scope 路径。Claude Code 使用 `~/.claude/skills/`。两平台共用同一 canonical Skill source，在渲染时分别写入各自 USER scope 路径。
- **结论**：继续沿用，**并非 myflow 自家约定**。

### Q-21 Codex 独立 TOML subagent 支持 · closed

- **决策**：仅支持 Codex **最新版本**（独立 TOML 文件载体）；取消 `config.toml [agents.<name>]` fallback。
- **写作规范**：见第 7.9 节。
- **built-in agent 保护**：`default` / `worker` / `explorer` 重名阻断渲染。
- **全局调度**：`[agents]` 下 `max_threads` / `max_depth` / `job_max_runtime_seconds` 保持 Codex 默认值，除非有明确需求。

### Q-22 `process/checkpoints/delivery/` 噪音控制 · decided

- **主选**：安装器默认建议把 `process/`、`checkpoints/` 加入 `.gitignore`；`delivery/` 保留入库。
- **用户可选项**：关闭 `.gitignore` 建议（全部入库）或全部忽略。

### Q-23 卸载 / 清理 · decided

见 7.6。

### Q-24 版本审计线 · decided

见 7.5。

### Q-25 跨平台事务性回滚 · decided

见 7.7。

### Q-26 Skill / Subagent 命名与冲突检测 · closed

- **决策**：
  1. 写入**全局开发标准**：Skill 名在全部 Skill 命名空间内全局唯一；Subagent 名在全部 Subagent 命名空间内全局唯一；两者强烈建议跨命名空间不重名。
  2. 第一方冲突：提示不阻断。
  3. 第三方引入：走 `install.py --import <source>`，同名默认**阻断**，用户选 skip / rename / 指定 scope。
  4. built-in 名称保护：`default` / `worker` / `explorer` 重名阻断渲染。
- **实施位置**：§4.5 全局命名与冲突检测；安装器实现、`delivery/skills/README.md` 注册表、新增 `delivery/agents/README.md` 注册表。
- **关于 Claude Skills vs Subagents 的优先级不对称**（`Skills` 是 user>project，`Subagents` 是 project>user）：由 doctor 对两类产物分别判断 + README 固定优先级矩阵表，两者结合。不单独列为决策项。

### Q-27 Codex Hooks Windows 禁用 · closed

- **运行环境事实**：当前方案主要运行环境是 **WSL**（Linux 语义），Codex Hooks 的 Windows 原生禁用问题在 WSL 下不触发。
- **决策**：保留事实备注（§3.1 的 Hooks 行），不做 Windows 原生路径特殊处理。
- **若未来需要原生 Windows 支持**：再按需恢复"跳过 + 提示"策略，当前不纳入实施。

---

## 9. 修订后的实施步骤

### Phase 0：前置决策（已全部关闭）

Q-20 / Q-21 / Q-26 / Q-27 已在 2026-04-21 四次评审中由用户决策关闭，可直接进入 Phase 1。

### Phase 1：工作区根目录与运行时优先级收敛

1. 废除默认 `.output/` 根路径；
2. 引入 `{{WORKSPACE_ROOT}}/process/`、`checkpoints/`、`delivery/`；
3. 明确 `process/` / `checkpoints/` / `delivery/` 三层；
4. 把两平台运行时优先级 / 覆盖链写入正式合同；
5. 实现 WORKSPACE_ROOT 来源合同（Q-04 主选）。

### Phase 2：Skill / Agent 路径整改 ＋ 安装器同步整改（并行）

> **本 Phase 前 `delivery/scripts/install.py` 必须同轮次整改**，否则新路径无法验证。

1. 扫描所有 `.output/...` 引用；
2. 按第 6 节整改 meta Skill；
3. 同步修订 meta Agent 路径合同；
4. 定义 canonical agent 共享字段白名单与 renderer 映射矩阵（Q-14 / Q-18）；
5. **同步修 `delivery/scripts/install.py`**：Codex agent → `.toml`（§7.9 规范）、Codex skills → `~/.agents/skills/<name>/SKILL.md`、`README.md` 与 `platform-validator` 表述同步；
6. **新增 `delivery/agents/README.md` Subagent 注册表**，与 `delivery/skills/README.md` 协同构成 §4.5 冲突检测的数据源。

### Phase 3：迁移兼容

1. 按 6.3 执行 `.output → .meta-workflow`；
2. 新路径单写、旧路径只读兜底；
3. 补充 doctor / validator 对覆盖层与旧路径依赖的提示。

### Phase 4：平台渲染面落地

1. Codex Skills 渲染生效（`~/.agents/skills/<name>/SKILL.md`）；
2. Codex Subagents 渲染生效（`~/.codex/agents/*.toml`，遵循 §7.9 规范，无 fallback）；
3. Claude Code Skills / Subagents 渲染生效；
4. managed block 合同（Q-19 §7.3）落地；
5. 版本审计哨兵（Q-24 §7.5）注入；
6. 事务性回滚（Q-25）与卸载（Q-23）联调；
7. §4.5 冲突检测在安装器中实装。

### Phase 5：治理规则回写

1. 影响 Agent / Skill 关系时同步更新 `delivery/skills/README.md`；
2. 固化用户自己执行的边界；
3. 固化权限按需加载与渲染后提示规则；
4. 把 Q-14 / Q-17 的主选与切换条件写入实施文档。

### Phase 6：漂移收尾

1. 校验 `.output/` 不再作为新设计入口；
2. 校验共享 template 章节与路径已移除；
3. 校验 Codex subagent 路径表述正确；
4. 校验安装器 / README / platform-validator 与方案一致；
5. 校验问题跟踪表状态与当前决议一致。

---

## 10. 验收标准

1. 不再保留共享 `templates/` 章节；
2. Codex 用户级 subagent 表述统一为 `~/.codex/agents/*.toml`（独立 TOML 文件），**不再出现 `config.toml [agents.<name>]` fallback 字样**；
3. 两平台运行时优先级 / 覆盖链已写入正式方案，并区分"运行时事实"与"安装器规则"（如 built-in 重名）；
4. meta 输出根改为 `{{WORKSPACE_ROOT}}/process/`、`checkpoints/`、`delivery/`，`WORKSPACE_ROOT` 有明确来源合同（Q-04）；
5. 过程 / 检查点 / 交付三类目录结构清晰且 `.gitignore` 建议明确（Q-22）；
6. canonical agent 共享字段合同、严格失败边界与 `--permissive` 过渡期开关已明示（Q-14 / Q-18）；canonical `instructions` → Codex `developer_instructions` 映射已固化；
7. `.output → .meta-workflow` 迁移策略、兜底期、退场条件已写入（Q-15）；
8. 仓库实现漂移项逐条列明，不把设计稿误当现状（Q-16）；
9. 问题跟踪表中已无 `open`；`closed` / `decided` 均有主选并可实施；`in-progress` 有明确收尾条件（第 2 节 + 第 8 节）；
10. 非托管边界清晰：**Claude `settings.json` 的 `permissions/hooks/model/MCP` 不托管**，Codex `model/provider/mcp/hooks.json` 不托管，用户手工动作不越权代做；
11. 新增：卸载（Q-23）、版本审计（Q-24）、事务性回滚（Q-25）、managed block（Q-19）、全局命名与冲突检测（Q-26 §4.5）、Codex Subagent 写作规范（Q-21 §7.9）均可在实施阶段直接落地。

---

## 11. 最终结论

1. **不建设 shared template / shared runtime**；
2. **仓库内 canonical source + 平台原生渲染**；
3. **元工作流结果写入显式 `WORKSPACE_ROOT` 下 `process/`、`checkpoints/`、`delivery/`**；
4. **Codex / Claude Code 使用各自原生 subagent 发现面**；两平台共用同一 canonical Skill source（`~/.agents/skills/` 是 Codex 官方 USER scope，`~/.claude/skills/` 是 Claude 官方）；
5. **同时描述安装目标路径与运行时优先级**；
6. **Agent 共源以共享字段合同 + 严格失败（过渡期可 permissive）为前提**；
7. **Codex Subagent 写作遵循 §7.9 规范**；全局命名与冲突检测遵循 §4.5；
8. **先完成 meta Skill 路径整改、迁移兼容、`delivery/scripts/install.py` 同步整改**，再做渲染闭环；
9. **所有 open 问题已关闭**，Phase 1 可以开工。
