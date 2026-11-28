# Meta Flow 用户手册

> 适用版本：meta-flow **1.1.0**（V1/R1 1.1.x）。R0 1.0.x 为历史版本，仅作迁移参考。
> 本手册描述 R1 的角色、信息流、工作包/任务流程与命令；具体参数以 `mf <命令> --help` 为准。

## 目录

- [0. 版本、范围与阅读指南](#0-版本范围与阅读指南)
- [1. 框架总览](#1-框架总览)
- [2. 安装、升级与角色](#2-安装升级与角色)
- [3. 快速开始](#3-快速开始)
- [4. 操作手册](#4-操作手册)
- [5. 故障排查](#5-故障排查)
- [6. 附录：命令速查](#6-附录命令速查)

## 0. 版本、范围与阅读指南

### 0.1 版本规则

- 版本公式：`x.y.z = V.R.patch`。当前 **V1/R1 = 1.1.x（工具版本 1.1.0）**；
  V1/R0 = 1.0.x（已关闭，历史）。
- 版本单一来源：`pyproject.toml`、源码 `__version__`、`delivery.yaml`、
  `RELEASE-NOTES.md` 与发布清单 `release/RELEASE-<version>.yaml` 必须一致；
  发布前用 `mf release check` 校验，`--force` 不可绕过版本一致性。
- 路标版本范围在 contract 的 `roadmap/ROADMAP.yaml` 声明
  （`version_major`/`version_range`）；未声明的 MAJOR 不一致默认拒绝。

### 0.2 1.1.0 变化摘要

1.1.0 不是 1.0.x 的补丁，而是 R1 流程与工具的整体换代：

- **信息流闭环**：REQ/MFP/BUG 分层流转，MFP 不再由生产项目直接实施或归档。
- **工作包与设计包**：manager 每子项目每设计周期建工作包；designer 产出设计包/SPEC；
  任务只在人工决策或必要独立验证处拆分，默认不做逐任务评审（CHG-0005）。
- **角色与责任**：manager/designer/worker/maintainer 职责分离；责任主体与执行者分离；
  角色切换只在用户终端进行。
- **文档与证据**：继承文档/过程文档分层；SPEC 放 P2；验证 E0–E3、VR `items[]`、
  `mf verify index`；安全卡 v2。
- **R1 流程工具**：`flow_profile`/`mf roadmap classify`、`mf phase show`、
  `mf task withdraw`、`mf task review dispatch`、`mf archive authorize/show/export`、
  `mf doctor docs|process` 等。
- **安全修复**：T010/BUG-0001（N14）修复 MFP 内容 id/ref 路径穿越；完整链路
  submit→inbox→import 有负例回归。
- **范围调整**：DSH/试点验证移出 R1，不随 1.1.0 交付。

### 0.3 阅读路径

| 角色 | 建议顺序 |
|---|---|
| manager | §1 框架 → §2 安装 → §3.1 快速开始 → §4 操作 → §5 故障排查 |
| designer | §1.1–§1.6 → §3.1 → §4.3 设计/工作包 → §4.7 文档/技能 |
| worker | §1.1–§1.6 → §4.4 任务/评审 → §4.5 上下文/guard → §5 故障排查 |
| maintainer | §2 → §4.9 维护者 → §5 故障排查 |

## 1. 框架总览

### 1.1 角色、责任主体与执行者

| 角色 | 责任 | 工作区与边界 |
|---|---|---|
| **manager** | 需求/MFP/BUG 接收与评估、路标/版本/阶段计划、任务卡与 wave、工作包、设计派发与验收、验收、发布、上下文授权 | 项目根；只读 `mf` 固化证据、`delivery.yaml`、发布文档与交付元数据；**不读子项目源码、不写子项目源码** |
| **designer** | 设计责任主体：信息流/架构/子项目/模块/接口/规格/映射/跨项目验证 | contract 设计区；可写 `architecture/`、`specs/`、P2 设计包/规格与任务 bundle；**不写生产源码** |
| **worker** | 子项目实现、自验、独立验证、BUG 修复、文档 | 所属子项目 cwd；只写任务 `allowed_paths` 与任务 bundle 流程文件 |
| **maintainer** | meta-flow 工具、全局模板、MFP 归档与同步 | meta-flow 源码与全局；外部动作仍需用户授权 |
| **生产项目 maintainer** | 维护生产项目 | 不维护 meta-flow，不归档 MFP |

关键原则：

- **责任主体与执行者分离**：任务卡有 `owner_role`/`executor_role`。`kind: design`
  默认 designer；implement/fix/document/verify 默认 worker；review 由**未参与实现**的
  独立评审者执行。非默认主责需 manager `--owner-confirmed-by` 显式确认并写 ledger。
- **实现者不自验收**；评审者不得是作者/实现者；manager 验收不等于评审。
- **角色切换只在用户终端**：`mf role --as <role> --reason <原因>`；AI 会话不能
  通过 `MF_ROLE` 或锚点 API 自升级。
- **一个 worker 会话只服务一个子项目**；需要多组件时注册兄弟子项目，分别派任务卡。

### 1.2 信息流：REQ / MFP / BUG / CHG

#### REQ（需求）

1. 用户提出需求 → manager `mf req add` 记录（标题、来源、优先级、可验收标准、非目标）。
2. manager 评估：`mf req update <REQ> --status accepted|deferred|rejected`；
   accept 后按需选择 design（设计包/SPEC）或 direct（直接工作包/任务）。
3. 需要设计 → designer 设计包/SPEC → manager 设计验收；可直接开发 → 工作包/任务。
4. 工作包或批次完成 → 子项目最终验证 → manager 验收；必要场景追加独立评审。
5. 发布 → 用户门禁；需求状态按流程更新（`mf req update`）。

#### MFP（meta-flow 工具缺口）

MFP 分两层，生产项目**不 clone meta-flow-contract**：

1. **提案/登记层**：生产项目中的 manager/designer/worker 只记录到
   `.meta-flow/improvements/`（`mf improve new` 或 `mf improve new --local`），
   补齐复现、期望、实际、证据、影响面；不直接改 contract 或全局 inbox。
2. **实施队列**：manager 评估（`mf improve triage`）并提交；maintainer 唯一执行
   归档（`mf dev improve archive`）与同步（`mf improve sync`）；meta-flow manager
   评估后，由 maintainer 把 resolution 同步回生产项目。
3. 已实现的 MFP 记录为 `BUG/REQ/CHG` 并关闭；未实现的完整包进入源码
   `improvements/open/`，由 meta-flow 源码会话实施。

#### BUG（两层）

- **external（试运行/用户可见）**：manager 登记/分派 → worker 查 open → 修复/独立
  验证 → `pending_user_close` → 用户显式确认关闭
  （`mf bug close <id> --verification <VR-id> --confirmed-by <用户> --note <意见>`）。
  `--verification` 为必填；closed 默认不可见，
  查询需用户授权并写 READ-LOG。
- **verification（实施内）**：同子项目 worker 提出/修复 → **非修复者** viewer 复验关闭
  （`--by`）；`fix_owner` 必填，同一宿主会话不能自验自关；manager/用户不参与。
- **升级**：跨子项目/接口/外部可见/安全/需求级用
  `mf bug escalate <id> --reason <原因>` 升级为 external。

#### CHG（变更）

范围、基线或验收变化走 `CHG-*`，由 manager 记录/评审；不直接改已 accepted 的任务卡。
返工只在原任务范围内整改；范围外事项由 reviewer 标注 `needs: acceptance|bug|mfp|chg`，
manager 另开单，不阻塞范围内返工。

### 1.3 规划与执行：Roadmap → Phase → 工作包 → 任务

- **路标**：`mf roadmap show/plan/close/sizing/classify`。R 的版本范围在 ROADMAP 声明。
- **五阶段**：P1 需求/目标、P2 设计/规格、P3 实施、P4 验证/收口、P5 发布；
  `mf phase show/enter/review/exit`。阶段退出生成 `HANDOFF-TO-P{n}.md`；
  merged/skipped 阶段不单独进入、不建任务/空报告。
- **设计周期**：designer 产出设计包与 SPEC（P2 `design/`、`specs/`），
  manager `mf design accept` 验收；设计文档/规格评审由 manager 担任。
- **工作包**：manager 每子项目每设计周期创建一个（`mf work create`）；工作包内用
  `mf work task` 拆任务。只在**人工决策/独立验证**处拆卡，不按文件或命令机械拆分。
- **任务粒度**：按“可独立验证的增量”定义；跨模块规格由独立 verify 任务验证，
  不在单模块任务内假装覆盖。
- **批处理**：决策完成后，不需要人工参与的实施合并为批次任务；一个批处理只提交一次，
  避免并行快照污染；批次必须写清决策结论、范围、验收、BLOCKED/返工规则与预算。

### 1.4 决策、评审与人工节点

**决策分级**：

| 级别 | 内容 | 谁能决定 |
|---|---|---|
| D0 | 需求语义、用户可见、重大影响、安全合规 | 用户确认，manager 记录 |
| D1 | 跨模块接口、数据模型、发布范围 | 用户确认，manager 记录 |
| D2 | 技术细节 | 执行者可自主决策并记录结论；工作包 decision 记录仅 manager |
| D3 | 自动化操作 | 执行者留审计 |

D0/D1 不得由执行者在实施中自行决定；缺失时写 BLOCKED/交接升级。
`mf work decision` 记录问题/影响/选项/建议/级别/owner；D0/D1 只能由 manager
`--confirmed-by`+`--note` 记录用户确认。

**评审门（CHG-0005）**：

- 默认流程：worker 自验 L1 → 工作包/批次完成做**子项目最终验证** → manager 验收。
- 只有必要场景追加独立 review 任务：安全/角色/guard/权限、跨子项目接口/E2E、
  用户可见/UAT、高风险不可逆、manager/designer 判定必要。
- 评审结论仅 `PASS` / `PASS_WITH_RISK` / `NEEDS_REWORK` / `BLOCKED`；
  `PASS_WITH_RISK` 必须写风险与接受人；评审结论不代替 manager 验收。
- `NEEDS_REWORK` **即返工**：实现 worker 直接 `mf task rework <id>`，不经 manager
  范围裁决；评审者用“人话”写清原因/风险/影响/期望与必须整改项。
- 第 3 次 `NEEDS_REWORK` 停止自动评审并升级 manager/user。

**人工节点**（默认只保留）：

1. 需求提出/确认；
2. 批处理启动与批量验收/试用；
3. 阶段/发布门禁；
4. D0/D1 高风险决策；
5. 试运行期 BUG/MFP/REQ 关闭确认。

异常汇总为一次问题清单，不逐个打断用户。

### 1.5 文档模型

- **继承文档（长期）**：`architecture/`、`standards/`、`knowledge/`、`PROJECT-PLAN`、
  `ROADMAP` 等。
- **过程文档**：SPEC、设计包、工作包、TASK、验证/VR、BUG、RELEASE；SPEC 目标
  `roadmap/R{n}/phases/P2/specs/`，legacy `specs/` 兼容只读。
- **交付文档**：`delivery.yaml`、`RELEASE-NOTES.md`、`USER-MANUAL.md`、`DESIGN.md`、
  `README.md` 入交付仓；contract 只放项目/跨库契约。
- **版本隔离**：worker 只读当前 R；跨 R/历史需 archive grant。
- **检查**：`mf docs check/summary` 查看文档模型；
  `mf doctor docs|process` 检查 front matter、入口行数、重复 ID、篇幅、孤儿、
  rounds、open findings 与过程字段。

### 1.6 验证与证据

- **分层**：L1 任务自验（单元/CLI/静态检查）→ L2 契约/兼容/集成测试 →
  L3 用户/发布验收。worker 只声称 L1；任务卡要求时跑 L2；**不得声称 L3/用户验收**。
- **顺序**：targeted → compatibility → full。PASS receipt 必须绑定 source/profile
  fingerprint、check layer、command identity、环境摘要与 result digest；
  fingerprint 变化、FAIL、命令漂移或 partial mutation 不得复用。
- **证据 E0–E3**：任务证据 → 验证项 → 阶段 VR → 版本报告；证据单元=验收条件/测试/E2E，
  不是任务/规格。VR `items[]` 含 command/environment/result_digest/reuse_of/retention；
  `mf verify index` 列出 evidence debt。
- **安全类任务**：必须写威胁模型、负面不变量、负向矩阵（每条含
  id/category/command/expected/evidence）与 `fail_closed` 可证明范围；
  缺项时 create/start/validate/doctor 拒绝（历史任务 warning）。
- **失败结论**只使用 `PASS`、`PASS_WITH_RISK`、`BLOCKED`、`NEEDS_REWORK`、
  `NEEDS_DESIGN_CLARIFICATION`、`WAIVED`；`CHECK_HARNESS_ERROR` 单独标记，
  不能伪装真实内容失败。

### 1.7 版本与发布

```bash
mf roadmap sizing R1                 # VU/effort/confidence 建议（不自动分类）
mf roadmap classify R1 --flow program --decided-by user --reason "..."  # 用户终端
mf phase show                        # required/merged_into/skipped
mf release freeze                    # 按阶段策略冻结
mf release check                     # 版本单源/清单/tag 一致性
mf release show
mf roadmap close R1                  # P5 退出 + 用户批准 + 已冻结
```

- `flow_profile` 由用户终端 `mf roadmap classify` 显式决定，写 `VERSION.yaml`/
  `SIZING.yaml`/ledger；工具只给 sizing 建议，不替用户分类。
- `mf release freeze` 阶段策略：P1/P2 禁止冻结/发布；P3 active 仅 alpha/预发布；
  P3 结束（exited/done）后可正式发布；P4/P5 修复可随时冻结。阶段门是用户门禁，
  `--force` 不能绕过。
- `mf roadmap close` 生成关闭报告、下一版本交接、`LESSONS-R{n}.md`，并把任务、
  阶段计划/报告、VR、BUG、release 清单迁入 `archive/R{n}/`。

## 2. 安装、升级与角色

### 2.1 安装工具与全局模板

```bash
git clone git@github.com:hyde-zhao/meta-flow.git
cd meta-flow
UV_NO_CACHE=1 uv tool install --force .
mf --version        # 应为 1.1.0
mf bootstrap
mf doctor --global
```

- 同版本号源码迭代时，uv 可能复用缓存构建（MFP-0029），必须带 `UV_NO_CACHE=1`
  或 `uv tool install --force --reinstall .`；安装后确认 `mf --version` 输出源码版本。
- 1.1.0 为 R1 发布候选；发布后可用 `@v1.1.0` 源码 tag 安装。
- `mf bootstrap` 生成 `~/.meta-flow/`：manifest、agents（manager/designer/worker/
  maintainer）与 templates（规范、制品模板、技能）。

### 2.2 项目、contract 与子项目安装

```bash
cd <项目根>
mf install claude                       # 只装 manager
mf install claude --agent maintainer    # 装 maintainer + manager
mf install designer --project-dir <项目根>/<项目名>-contract   # 设计区
mf install worker --project-dir <项目根>/<子项目>
```

若子项目 `install.yaml` 丢失 `workspace_root`，用
`mf install worker --workspace-root <项目根> --contract-dir <项目根>/<项目名>-contract`
修复。

生成内容：

```text
<项目根>/
├── CLAUDE.md                  # @<项目名>-contract/workspace/CLAUDE.md
├── README.md
├── .claude/agents/{manager,maintainer}.md
├── .claude/settings.json      # agent + hooks
└── .meta-flow/install.yaml

<项目名>-contract/
├── .claude/agents/designer.md
├── CLAUDE.md                  # designer 受管块
├── .meta-flow/install.yaml    # role: designer
└── workspace/{CLAUDE.md,README.md,mf.workspace.yaml}

<子项目>/
├── CLAUDE.md
├── .claude/agents/worker.md
├── .meta-flow/install.yaml
├── delivery.yaml
└── src/ tests/ release/
```

安装镜像（CLAUDE.md/.claude/.meta-flow）不入库；`delivery.yaml`、`RELEASE-NOTES.md`、
`USER-MANUAL.md`、`DESIGN.md`、`README.md` 入交付仓。不创建 `contracts/`/`deliveries/`。

### 2.3 升级、回滚与卸载

```bash
mf bootstrap --force                         # 只刷新 ~/.meta-flow 全局模板
mf upgrade --project-dir <项目根> --force
mf upgrade --project-dir <contract> --force
mf upgrade --project-dir <子项目> --force
mf doctor --path <项目根>
mf workspace sync --check
```

- `--force` 只覆盖安装镜像（`.claude/agents`、`CLAUDE.md` 受管块、
  `.claude/settings.json` hook），旧文件保留 `.bak`；contract 的 standards/templates/
  policies/improvements README 与 phase plans 只补缺失文件，**不覆盖项目自定义内容**
  （BUG-0015）。
- 回滚：恢复全局 `mf` 到上一版本源码/工具快照，项目侧恢复 `.meta-flow/install.yaml`
  与全局模板，contract 按 git 历史回退。
- 卸载：`mf uninstall claude --project-dir <path>`；`--purge` 额外移除 workspace 元数据；
  默认保留 contract 与子项目源码。

### 2.4 角色锚点与切换

- 会话锚点：`<workspace>/.meta-flow/session-roles/<session_id>.yaml`。SessionStart hook
  按宿主会话写本会话锚点；`/clear` 只重写本会话；不同会话互不覆盖。
- 用户终端 `mf role --as <role> --reason <原因>` 写 `session-roles/user-tty.yaml`
  （人工切换，按更新时间优先，本会话下一次 SessionStart 覆盖）。
- 无 `session_id` 时不回退共享会话锚点（fail-closed）；user-tty 锚点仅用户终端可写
  （`write_anchor(source="user-tty")` 非 TTY 一律拒绝）；guard/CLI 优先使用锚点，
  cwd 漂移不改变角色。
- 角色短名：manager/designer/worker/maintainer；别名 `mgr/dsg/wkr/mnt` 与 `meta-*` 命名空间。
- maintainer 复位：`mf role --reset` 只清理 user-tty/当前会话/遗留锚点，写
  `role.reset` ledger；维护批次结束必须 reset，不得把临时 maintainer 锚点遗留给
  manager 验收会话。

```bash
mf role                                    # 显示 effective role/来源/复位建议
mf role --as designer --reason "设计工作包"   # 仅用户终端
mf role --as mgr --reason "回到 manager"
```

### 2.5 安全边界与读写规则

- **worker**：只写任务 `allowed_paths`；流程文件（handoff/dev-record/evidence）写任务
  bundle；本地副本 `.meta-flow/handoffs|dev-records/<task>.md` 仅当前任务可写；
  本地 MFP `.meta-flow/improvements/MFP-*.yaml` 受控可写。其他 `.meta-flow/**` 拒绝。
- **designer**：只写 contract 设计区与任务 bundle；子项目源码只读；禁止写需求/验收/发布。
- **manager**：不读子项目源码、不写子项目源码；跨项目写通过受控命令或 worker 任务。
- **guard 覆盖 Bash**：`$HOME`/环境变量展开、`sh -c`/`bash -c` 递归解析；
  `eval`/`source`/`.`/进程替换/转义变量同样受策略约束；无法安全解析且涉及路径时保守拒绝。
  allow/deny 写 READ-LOG，可用 `mf context log` 查询。
- **archive 默认 deny**：只有用户 TTY grant 或 maintainer root 可读/导出；
  archive 读取必须带 reason。
- **外部动作**（git push/merge/tag、发布/部署、网络、真实安装）需用户
  `mf maintainer authorize-external` 短时授权；`git commit`/push 不属于默认授权。
- **不直接问用户**：执行者的问题写进交接，由 manager 汇总升级。

## 3. 快速开始

### 3.1 全新项目：从需求到发布

目标：从空目录完成安装、工作区、设计、工作包、worker 实施、验收与发布准备。

#### 1. 初始化工作区（manager）

```bash
cd <项目根>
mf workspace init --name "示例项目" --contract-dir 示例项目-contract \
  --roadmap R1 --phase P1 --version 1.1.0
mf workspace add-project --name backend --path backend
mf workspace link
mf doctor --path .
```

检查点：`mf role` 为 manager；`mf status` 显示当前 R/阶段与子项目；
`<项目根>/CLAUDE.md` 只含 `@示例项目-contract/workspace/CLAUDE.md` 导入行；
contract 的 `roadmap/ROADMAP.yaml` 含 `version_major`/`version_range`；
`mf doctor` 输出 OK。

#### 2. 需求、路标与阶段（manager）

```bash
mf req add --title "用户可登录" --priority must --acceptance "登录成功"
mf req update REQ-0001 --status accepted   # design/direct 由后续设计包/工作包决定
mf roadmap sizing R1
mf phase show
mf phase enter P1
```

`mf roadmap classify` 只能由用户在终端执行，用于固化 `flow_profile`；
manager 不以工具建议替代用户决策。

#### 3. 设计周期（designer）

```bash
# manager 创建 design 任务（designer 主责）
mf task create --kind design --title "登录设计"
mf task prompt <design-task>
# designer 在 contract（设计区）会话中执行
mf design create --title "登录设计" --requirement REQ-0001 --spec SPEC-001 \
  --subproject backend
# manager 验收设计
mf design accept DP-R1-01 --verdict PASS --note "设计通过"
```

设计任务只由 designer 执行；worker 不得 start/submit design 任务。设计文档/规格评审
由 manager 担任；实现/verify 评审才由未参与实现的独立 worker 担任。

#### 4. 工作包与任务（manager → worker）

```bash
# manager：每子项目每设计周期一个工作包
mf work create --subproject backend --requirement REQ-0001 --spec SPEC-001 \
  --allowed-path "src/**" --acceptance "接口返回 200"
mf work task WP-01 --type implement --goal "实现登录接口" --acceptance "测试通过"
mf work decision WP-01 --problem "接口 A/B" --impact "M4" --option A \
  --recommendation A --level D1 --decision-owner user
# 用户确认后
mf work decision WP-01 --decision-id T2 --decision A --decided-by <用户> \
  --confirmed-by <用户> --note "用户确认意见"
```

工作包/设计包按**子项目 + 当前 R** 隔离；跨子项目/其他 R 读写拒绝（rc=3）。
工作包引用 design_package 时必须存在、已验收且同 R。

#### 5. worker 实施与自验

```bash
cd backend
mf task prompt R1-P1-T001
mf task show R1-P1-T001 --packet
mf task start R1-P1-T001
```

任务包给出 `delivery`、`project_dir`、`allowed_paths` 基准、验收、预算、代码入口、
process paths（handoff/dev-record/evidence）。worker 只改本子项目 `allowed_paths`
内文件；完成后写 dev-record/handoff（或交付库本地副本），自验 L1：

```bash
pytest -q && ruff check .
mf task submit R1-P1-T001 \
  --handoff ../示例项目-contract/roadmap/R1/phases/P1/tasks/T001/handoff.md
mf task prompt R1-P1-T001
```

超过读预算的单文件不要用 `cat` 硬读：用 `mf context show` 查看活动任务 bundle，
或 `mf context expand <path> --reason packet_missing` 分段补读（写 READ-LOG）。

#### 6. 验收与必要评审

```bash
# 默认：工作包/批次完成 → 子项目最终验证
mf work verify WP-01 --result PASS --evidence evidence/l1.txt

# 必要场景才派独立 review（安全/跨项目/用户可见/高风险等）
mf task review dispatch R1-P1-T002 --host claude-code --owner reviewer-2 \
  --session-id <uuid>
mf task accept R1-P1-T002 --verdict PASS   # review 任务验收
mf task accept R1-P1-T001 --verdict PASS   # 实现任务验收

# manager 工作包验收
mf work accept WP-01 --verdict PASS
```

评审者只写 `review.md` + `review-handoff.md`，结论
`PASS|PASS_WITH_RISK|NEEDS_REWORK|BLOCKED`；`NEEDS_REWORK` 后实现 worker 直接
`mf task rework <id>` 返工。实现者不自验收。

#### 7. 发布准备

```bash
mf release freeze
mf release check
mf release show
# P5 退出 + 用户批准后
mf roadmap close R1
```

版本元数据（`pyproject.toml`/源码 `__version__`/`delivery.yaml`/`RELEASE-NOTES.md`/
发布清单）必须一致；阶段门和用户门禁不能 `--force` 绕过。

### 3.2 迁移已有项目

目标：把已有项目接入 meta-flow，保留原项目内容与历史，不丢源码/文档/任务。

#### 1. 盘点与环境

```text
- 原项目源码、测试、构建脚本、发布文档；
- 已有需求/设计/任务/缺陷记录（Markdown、Excel、issue 列表均需导出摘要）；
- 已有 contract 仓（若存在）及其远程地址；
- 交付库清单、分支、版本号（旧版本标注 V0 cold）。
```

```bash
cd <原项目根>
mf bootstrap
mf install claude --project-dir .
```

#### 2. 重建或接入 contract

```bash
# 新 contract
mf workspace init --name "迁移项目" --contract-dir 迁移项目-contract \
  --roadmap R1 --phase P1 --version 1.1.0

# 已有 contract：clone 后接入，保留原内容
git clone <contract-remote> 迁移项目-contract
mf workspace attach --name "迁移项目" --contract-dir 迁移项目-contract \
  --contract-remote <contract-remote>
mf workspace link
mf doctor --path .
```

`workspace attach` 只导入 roadmap/phase/version/workspace 注册与子项目登记，
不覆盖已有 contract；已注册项目 id/名称冲突时直接报错；不导入源码或实现。

#### 3. 迁移文档与任务

1. 需求：按原需求逐条 `mf req add`，保留原编号到 `source`/描述，补验收标准；
   用 `mf req update --status accepted|deferred|rejected` 评估；design/direct 由后续
   设计包/工作包决定。
2. 路标/阶段：在 ROADMAP.yaml 声明 `version_major`（旧 0.x 记为 V0 cold）；
   当前工作放到对应 R/阶段。
3. 设计/规范：跨库真相放 contract；交付库文档（delivery.yaml、RELEASE-NOTES、
   USER-MANUAL、DESIGN、README）留在交付库并入库。
4. 任务：历史任务不伪造完成证据；未完成工作用工作包/任务重建，`inputs` 引用原需求，
   `allowed_paths` 只列本次要改的路径。
5. 子项目：`mf workspace add-project --name backend --path backend` 并 `mf workspace link`。

检查点：`mf doctor` OK、`mf workspace sync --check` OK；交付仓 `git status` 只含
交付文档与源码，不出现 CLAUDE.md/.claude/.meta-flow；contract 原内容未被覆盖；
`mf role` 在根为 manager、在子项目为 worker。

#### 4. 首个工作包与验收

```bash
mf task plan
mf work create --subproject backend --requirement REQ-0001 --spec SPEC-001 \
  --allowed-path "tests/**" --acceptance "全量测试通过"
mf work task WP-01 --type implement --goal "迁移后回归基线" --acceptance "全量测试通过"
mf task prompt <task-id>
cd backend
mf task show <task-id> --packet
mf task start <task-id>
# 实现 + 测试 + dev-record + handoff
mf task submit <task-id>
cd ..
mf work verify WP-01 --result PASS --evidence evidence/l1.txt
mf work accept WP-01 --verdict PASS
```

### 3.3 R0 → R1 迁移（1.0.x → 1.1.x）

1. **升级工具**：`UV_NO_CACHE=1 uv tool install --force .`（或 `mf dev install --yes`），
   确认 `mf --version` 输出 1.1.0；再对项目根、contract、子项目执行
   `mf upgrade --project-dir <p> --force`，最后 `mf doctor --path <根>` 与
   `mf workspace sync --check`。
2. **路标与 flow_profile**：ROADMAP 声明 `version_major`/`version_range`（1.1.x）；
   `mf roadmap sizing R1` 查看 VU/effort 建议后，由用户在终端执行
   `mf roadmap classify R1 --flow ... --decided-by user --reason ...` 固化
   flow_profile；`mf phase show` 确认 required/merged/skipped 阶段。
3. **流程切换**：R1 默认“工作包 + 子项目最终验证 + manager 验收”，不再逐任务生成
   review；只在安全/跨项目/用户可见/高风险等必要场景派独立 review。设计责任主体是
   designer；worker 不自验收。
4. **任务与证据**：新任务补 `estimate/slice/verify`；旧任务缺字段只 warning。
   R0 任务/阶段/VR/BUG/release 留在 `archive/R0/`，worker 只读当前 R；需要审计时由
   用户授权 `mf archive authorize ...`，再执行
   `mf archive show R0 --reason human_audit --grant <id>`。
5. **文档与验证**：`mf doctor docs`/`mf doctor process` 检查 front matter、入口行数、
   重复 ID、篇幅、孤儿与 rounds/open findings；安全类任务按安全卡 v2
   （`security.schema: 2`/`compat: v2`/可执行 evidence）补齐；`mf verify index`
   查看 evidence debt。
6. **MFP/BUG 流程**：MFP 先在本地登记（`mf improve new`/`--local`），由 manager
   评估/提交、maintainer 导入/归档；BUG 区分 external 与 verification，
   external 关闭需用户显式确认。
7. **回滚**：恢复全局 `mf` 到 1.0.x 源码/工具快照，项目侧恢复 `.meta-flow/install.yaml`，
   contract 按 git 历史回退；R1 新增字段/文件对旧工具为增量。

## 4. 操作手册

### 4.1 工作区

| 命令 | 说明 |
|---|---|
| `mf workspace init` | 新建 contract 与工作区注册，可声明 roadmap/phase/version |
| `mf workspace attach` | 接入已有 contract；不覆盖 contract，不导入源码 |
| `mf workspace add-project` | 安装 worker 子项目并登记 |
| `mf workspace link` | 重建根 CLAUDE/README 链接并刷新安装 digest |
| `mf workspace sync [--check]` | 校验/刷新根生成文件 |
| `mf workspace status` | 查看 contract/子项目 git 与版本 |
| `mf doctor --path <p>` / `--global` | 校验安装、工作区、契约、规划数据 |

规则：子项目必须绑定已注册 delivery；任务、guard、packet 都按 `delivery` +
`project_dir` + `allowed_paths_base` 解析；跨子项目任务仅 manager 可创建，
`cross_subproject` 只读/测试、写入一律拒绝。

### 4.2 需求、路标与版本

```bash
mf req add --title "用户登录" --priority must --acceptance "登录成功" \
  --non-goal "不做第三方登录"
mf req list
mf req show REQ-0001
mf req update REQ-0001 --status accepted   # 评估：accepted|deferred|rejected
mf req update REQ-0001 --status verified
mf req trace REQ-0001
mf req trace --check          # 孤儿/未闭环检查，有孤儿返回 1
mf req trace --archive        # 审计历史
```

- `mf req trace` 默认只追踪当前路标，排除 archive；BUG 按 id 去重；SPEC 只匹配
  `SPEC-*.md`；`--check` 输出 REQ→SPEC→TASK→证据→VR→BUG/MFP/CHG→RELEASE 链路。
- `mf roadmap sizing <R>` 汇总 VU/effort/confidence/风险并给 large/small/split 建议
  （仅建议）；`mf roadmap classify` 由用户终端显式决定 flow_profile。
- `mf phase show` 显示 P1–P5 的 required/merged_into/skipped；`mf phase enter/review/exit`
  推进阶段；阶段退出生成 HANDOFF。
- `mf state show/rebuild`：TASK.yaml + ledger 是任务真相，`state/current.json` 是
  派生快照；`mf doctor` 做状态对账，漂移用 `mf state rebuild` 重建（禁止手工编辑）。
- `mf release freeze/check/show`：阶段策略与版本单源校验见 §4.8。

### 4.3 设计与工作包

```bash
# 设计包（designer 产出，manager 验收；P2 design/）
mf design create --title "登录设计" --requirement REQ-0001 --spec SPEC-001 \
  --subproject backend
mf design accept DP-R1-01 --verdict PASS --note "设计通过"

# 工作包（manager；每子项目每设计周期一个）
mf work create --subproject backend --requirement REQ-0001 --spec SPEC-001 \
  --allowed-path "src/**" --acceptance "命令成功"
mf work task WP-01 --type implement --goal "实现登录" --acceptance "测试通过"
mf work start WP-01
mf work decision WP-01 --problem "接口 A/B" --impact "M4" --option A \
  --recommendation A --level D1 --decision-owner user
mf work decision WP-01 --decision-id T2 --decision A --decided-by <用户> \
  --confirmed-by <用户> --note "用户确认意见"
mf work verify WP-01 --result PASS --evidence evidence/l1.txt
mf work accept WP-01 --verdict PASS
mf work list
mf work show WP-01
```

- **任务拆分**：只在需要人工决策/独立验证时拆任务；否则一个工作包内连续实施，
  完成后统一子项目最终验证与 manager 验收。
- **决策点**：D0/D1 只能由 manager 记录用户确认（`--confirmed-by` + `--note`）；
  D2 技术细节可由执行者自主决策并在交接记录，工作包 decision 记录仅 manager；
  worker/designer 不得代记 D0/D1。决策记录后恢复工作包。
- **隔离**：工作包/设计包按子项目 + 当前 R 隔离；跨子项目/其他 R 读写拒绝（rc=3）。
- **设计包引用**：工作包引用 `design_package` 时必须存在、已验收且同 R。
- **默认评审**：不按任务机械生成 review；仅 CHG-0005 必要场景追加独立评审。

### 4.4 任务、评审与返工

```bash
# manager 创建任务（必须绑定子项目；中高风险会自动生成 review 任务）
mf task create --title "实现 X" --risk high --delivery backend \
  --allowed-path "src/**" --acceptance "命令 mf X 成功" \
  --estimate "{vu: 2, effort_hours: 3, confidence: medium}" \
  --verify "pytest tests/x.py::test_y" --slice S1
mf task validate R1-P1-T001
mf task prompt R1-P1-T001

# worker
mf task show R1-P1-T001 --packet
mf task start R1-P1-T001 --owner worker-1
mf task submit R1-P1-T001 --handoff <bundle>/handoff.md
mf task prompt R1-P1-T001

# 独立评审（review 任务，未参与实现）
mf task show R1-P1-T002 --review-packet
mf task start R1-P1-T002 --owner reviewer-2
mf task submit R1-P1-T002        # 只需 review.md + review-handoff.md

# manager 验收
mf task accept R1-P1-T002 --verdict PASS
mf task accept R1-P1-T001 --verdict PASS
# critical 任务必须记录用户验收：
# mf task accept <task> --verdict PASS --user-approved-by <用户/记录>
```

**任务包与上下文**：

- 任务包按 effort（XS/S/M/L/XL）分配预算，并预置 allowed_paths 前缀的代码入口清单；
  超预算用 `mf context expand <path> --reason packet_missing` 分段读取或拆分任务。
- worker 可受控 `mf context show/expand` 活动任务 bundle、评审目标、allowed_paths 与
  任务包 must_read 契约基线（TASK.yaml/REQ/SPEC/标准/BUG/MFP，写 READ-LOG）；
  非 must_read 仍拒绝。
- review 任务可读 `review_scope` 内任意大小文件；`review_scope` 外仍拒绝。
- 评审包按 `reviews` 目标嵌入被评审任务的 dev-record/handoff/diff；证据缺失显式报错。

**状态与流转**：

- 每个任务状态都有 `next_owner`；`mf task prompt` 明确下一责任 agent。
- `mf task list` 默认只列活跃任务；`--all` 含 accepted/cancelled。
- `mf task withdraw <id> --reason ...`：仅 submitted 且下游未处理（review 仍
  draft/ready、依赖未开始、父任务未验收）可自撤回；review 取消/挂起；已处理拒绝。
- `mf task submit --blocked`（或 handoff 结论写 `BLOCKED`）转 manager 裁决：
  任务状态 `blocked`、next_owner=manager，关联 review 保持 draft/ready；
  manager 改卡/扩 allowed_paths 后 worker 用 `mf task start/rework` 重新开始。
- 提交后不可直接编辑；review `NEEDS_REWORK` 后实现 worker 直接
  `mf task rework <id>` 返工；范围外事项用 `needs: acceptance|bug|mfp|chg` 标注。
- `mf task submit` 只校验本任务变更：并行任务按活动窗口隔离；单任务越界仍拒绝；
  diff.patch 包含未跟踪新增文件；task start 前的未跟踪文件与 gitignored 构建产物
  不阻塞提交（MFP-0030）。
- 任务 bundle 匹配使用完整任务 ID；跨 roadmap/phase 的同尾号任务不会互相放行。

**自动评审（REQ-0026）**：

```bash
mf task review dispatch R1-P1-T002 --host claude-code --owner reviewer-2 \
  --session-id <uuid> [--fallback ...]
```

- 只记录 `spawn-requested`，不伪装已执行；宿主不可用时用 `--fallback` 记录
  `orchestration.fallback`，由 manager 人工派单。
- 设计评审=manager；实现/verify 评审=独立 worker（不同 owner/session）；
  同 session/owner/实现者拒绝。
- `rework_count` 第 3 次 `NEEDS_REWORK` 停止自动并升级 manager/user；
  3 次尝试未果必须查官方文档/GitHub/论坛并留证，否则 BLOCKED 提交被拒绝。

**安全卡 v2**：

- 安全类任务（guard/权限/白名单/路径策略/hook/发布门禁或 `security.applies: true`）
  必须含威胁模型、负面不变量、负向矩阵（`id/category/command/expected/evidence`）
  与 `fail_closed` 可证明范围；缺项 create/start/validate/doctor 拒绝。
- 用 `mf task create --security <security.yaml>` 写入安全字段；活跃任务按
  `security.schema: 2`/`compat: v2`/可执行 evidence，历史任务 warning。
- 安全类任务先写负例再实现；L1 证据必须含正/负例表与攻击面矩阵，不用高层条目替代。

### 4.5 上下文、guard 与归档

```bash
mf context show                      # 热区文件大小/总量/预算
mf context expand src/app.py --reason packet_missing --start 0 --end 65536
mf context log                       # READ-LOG / allow/deny 查询
mf archive list
mf archive show R1 --reason human_audit --grant <id>
mf archive authorize --role manager --roadmap R0 --scope 'phases/P4/tasks/T048/**' \
  --purpose human_audit --ttl-minutes 30
mf archive revoke <id>
mf archive export --grant <id> --to roadmap/R1/inputs/archive-r0
mf maintainer authorize-external --action 'git push' --reason '发布前推送'
```

- `mf context expand` 分段读取并写 READ-LOG；`2>&1`/`2>/dev/null` 不再误判写入；
  超段/非法区间/超 `--max-bytes` 拒绝。
- guard 覆盖 Read/Write/Edit/Grep/Glob/Bash；拒绝信息含角色/当前任务/lease/
  allowed_paths 与合法通道；allow/deny 持久化，可用 `mf context log` 查询。
- **archive 默认 deny**：用户 TTY `mf archive authorize` 生成短时 grant
  （role/roadmap/scope/purpose/TTL/bytes/files/one-shot）；`archive show` 必须带
  reason；`archive export` 到 `inputs/` 并带 digest/SOURCES；maintainer root 免 grant。
- **maintainer root**：meta-flow 内读写执行、非阻断审计、防自升级；外部动作仍需用户
  短时授权。

### 4.6 MFP 与 BUG

**MFP**：

```bash
# 生产项目（manager/designer/worker）
mf improve new --title "补充 task 命令"
mf improve new --local --title "worker 被工具缺口阻塞"
mf improve validate MFP-0001
mf improve submit MFP-0001
mf improve triage MFP-0001 --decision accepted --next-step design
mf improve sync --project-dir <生产项目根> --source <源码目录>

# meta-flow maintainer
mf improve list --inbox
mf dev improve import <project>/MFP-0001 --kind requirement
mf dev improve import <project>/MFP-0001 --kind bug --already-implemented \
  --version 1.0.3 --commit <sha>
mf dev improve archive <project>/<MFP> --source <源码目录>
mf dev improve update MFP-0001 --status verified --version 1.1.0 --commit <sha>
```

- 本地 ID：`MFP-<project>-<seq>`；只有 meta-flow maintainer 可归档/同步；
  非 maintainer 归档/同步拒绝（rc=3）。
- **T010/BUG-0001（N14）**：`mf dev improve import`/`update` 对 MFP 内容 id 与
  `source_record` ref 做白名单校验，拒绝 `../`、绝对路径、路径分隔符、空/保留名与
  symlink 目录/目标；inbox/open/closed/records 写入限定在 `improvements/` 内；
  合法旧 MFP 不受影响。

**BUG**：

```bash
# external（试运行/用户可见）
mf bug add --title "登录报错" --severity major --requirement REQ-0001
mf bug fix BUG-0001
mf bug verify BUG-0001
mf bug close BUG-0001 --verification <VR-id> --confirmed-by <用户> --note "用户确认关闭"

# verification（实施内）
mf bug add --flow verification --subproject backend --title "回归失败"
mf bug fix BUG-0002          # fix_owner 必填（按命令提示填写）
mf bug verify BUG-0002 --by worker-2
mf bug close BUG-0002 --verification <VR-id> --by worker-2

# 升级与审计
mf bug escalate BUG-0002 --reason "跨子项目接口"
mf bug show BUG-0001 --packet      # 最小修复上下文
mf bug audit                       # 检测绕过 CLI 的状态篡改
```

- external 新 schema 仅 `pending_user_close` 可关，必须用户确认；`fixed/verifying`
  直关仅限 T038 前无 flow 历史 BUG。
- verification `open→in_fix→fixed→verified→closed`；fix_owner 必填；非修复者 viewer
  关闭（`closure_type=viewer`）；同一宿主会话不能自验自关。
- closed 默认不可见；查询需 `--include-closed --authorized-by <用户> --reason <理由>`
  并写 READ-LOG；同子项目当前 R 的 closed verification 对 worker 只读可见。

### 4.7 文档、技能与验证

```bash
mf docs check
mf docs summary
mf skill list --role worker
mf skill show verification
mf skill validate
mf verify record --layer implementation --scope "登录" --result PASS \
  --task R1-P1-T001 --requirement REQ-0001 --command "pytest ..." \
  --result-digest <sha256> [--reuse-of <VR>] [--artifact <path>]
mf verify list --layer implementation
mf verify index                      # 证据索引与 evidence debt
mf bug show BUG-0001 --packet
```

- **文档模型**：继承文档（architecture/standards/knowledge/ROADMAP）与过程文档
  （SPEC/DP/WP/TASK/VR/BUG/RELEASE）分层；SPEC 目标 P2 `specs/`，legacy `specs/`
  兼容读取；worker 只读当前 R。
- **技能**：角色提示词只定义身份/权限/工作区；活动步骤见 `mf skill`；
  `mf bootstrap` 部署 `~/.meta-flow/templates/skills/`，`mf skill validate` 校验。
- **验证记录**：VR `items[]` 含 command/environment/result_digest/reuse_of/retention；
  `PASS` 摘要+digest，FAIL/BLOCKED/高风险保留原始；fingerprint 不变才可复用。
- **安全卡**：`mf verify security-card --path <SECURITY-CARD.md>` 校验信任边界/
  攻击者能力/可证明 fail_closed/不可防残余/风险接受人；活跃任务 fail-closed，
  历史任务 warning，design 豁免。

### 4.8 发布与归档

```bash
mf release freeze
mf release check --source-dir ../meta-flow [--require-tag] [--json]
mf release show
mf phase exit --approved-by user
mf roadmap close R1
```

- `mf release freeze`：P1/P2 禁止；P3 active 仅 alpha/预发布；P3 结束可正式；
  P4/P5 修复可随时冻结；阶段门属用户门禁，`--force` 不能绕过。
- 版本一致性（MFP-0028）：发布清单、`pyproject.toml`、源码 `__version__`、
  `delivery.yaml`、`RELEASE-NOTES.md` 与 git tag 必须与目标版本一致；
  `--require-tag` 要求 `v<version>` tag 存在且指向的版本文件一致；技术校验不可绕过。
- `mf roadmap close` 需要 P5 退出 + 用户批准 + 已冻结；生成关闭报告、下一版本交接、
  `LESSONS-R{n}.md`，并把任务/阶段计划/报告/VR/BUG/release 清单迁入 `archive/R{n}/`。

### 4.9 维护者

```bash
mf dev status
mf dev clone
mf dev update
mf dev install --yes
mf install claude --project-dir <根> --force
mf install worker --project-dir <子项目> --force
mf uninstall claude --project-dir <path>
mf dev improve import/list/update
mf dev improve archive <project>/<MFP> --source <源码目录>
mf improve sync --project-dir <生产项目根> --source <源码目录>
mf maintainer authorize-external --action '<动作>' --reason '<原因>'
```

- `mf dev status` 在 `source_dir` 缺失/不是 git 仓库时显式报错，提示 `mf dev clone`
  或 `--source`。
- MFP-0029：`mf dev install` 已默认注入 `UV_NO_CACHE=1`；安装后务必用 `mf --version`
  与关键命令（如 `mf task --help`）确认全局工具与源码 HEAD 一致。
- `mf bootstrap --force` 只刷新 `~/.meta-flow`，不触碰 contract；contract 内容变更走
  manager 的评审/变更流程。
- Git：`mf task submit` 不创建 commit；push/merge/tag、发布/部署、网络与真实安装
  必须用户显式授权。
- MFP 归档/同步是 maintainer 唯一职责；生产项目 maintainer 不归档 MFP。

## 5. 故障排查

| 现象 | 处理 |
|---|---|
| `角色: unbound` | 在 workspace 根/contract/子项目运行，或显式 `MF_ROLE`；首次 init/attach 由安装角色 bootstrap |
| cwd 在子项目但角色显示 manager/worker 不符 | 查看 `mf role` 来源；会话锚点由 SessionStart 写入。用户终端 `mf role --as <role> --reason <原因>` 重置，`/clear` 会按会话目录重写 |
| `mf role --as` 报非 TTY | 只允许用户在终端执行；AI Bash 工具不能切换角色（防自升级） |
| designer 写文件被拒 | designer 只能写 `architecture/`、`specs/`、P2 设计包与任务 bundle；子项目源码/需求/发布禁止写入 |
| design 任务 worker start 被拒 | design 责任主体是 designer；worker 不得冒充；manager 派 designer 任务并等待 designer 会话 |
| `mf install designer` 被拒 | 目标目录必须是 contract（含 `.meta-flow/role.yaml` 或 `workspace/`）；设计区安装不写交付库 |
| worker 任务命令 rc=3 | 无交付根绑定：加 `--project-dir <交付库>` 或进入交付库目录 |
| 根 CLAUDE.md 被判 modified | 运行 `mf workspace link` 刷新 install digest；再 `mf doctor` |
| `mf dev status` 报源码不存在 | 运行 `mf dev clone` 或 `--source <有效源码目录>` |
| `mf roadmap classify` 被拒/要求用户终端 | flow_profile 是用户决策：必须由用户在终端带 `--decided-by user --reason ...` 执行；AI 会话不能代选（防自升级） |
| `mf task withdraw` 被拒 | 仅 submitted 且下游未处理（review 仍 draft/ready、依赖未开始、父任务未验收）可撤回；已处理改用 rework/CHG/BUG/新任务 |
| review dispatch 显示 spawn-requested 但未执行 | dispatch 只记录调度请求，不伪装执行；宿主不可用时用 `--fallback` 记录 `orchestration.fallback`，由 manager 人工派单 |
| review 任务提交提示缺少 handoff | review 只需 `review.md` + `review-handoff.md`；implement/fix 才要求 handoff/dev-record |
| review `NEEDS_REWORK` 后如何返工 | 实现 worker 直接 `mf task rework <id>`；范围外事项由 reviewer 标注 `needs`，manager 另开单 |
| `mf work` 命令被拒/跨项目 | 工作包/设计包按子项目 + 当前 R 隔离；确认 cwd/子项目/路标一致 |
| `mf work decision` 记录 D0/D1 被拒 | D0/D1 只能由 manager 记录用户确认（`--confirmed-by`+`--note`）；worker/designer 不得代记 |
| `mf design accept` 失败 | 设计包必须存在、已提交且同 R/子项目；designer 产出后由 manager 验收 |
| archive show/export 被拒 | archive 默认 deny；用户终端 `mf archive authorize --role ... --roadmap ... --scope ... --purpose human_audit` 生成 grant，再带 `--grant <id>`；maintainer root 免 grant |
| `mf doctor docs` 报 legacy 文档问题 | 1.1.0 对 legacy 文档输出 F3 docs debt（当前 27 条）；新/活跃文档按 front matter/篇幅/孤儿检查整改，迁移/R2 收尾 |
| MFP import/update 报非法 id/ref | 1.1.0 起校验内容 id 与 `source_record` ref（拒绝 `../`、绝对路径、分隔符、空/保留名、symlink）；修正 MFP 内容后重试 |
| 安全卡提示 schema/compat 不符合 | 活跃任务按 v2：`security.schema: 2`、`compat: v2`、可执行 evidence；历史任务 warning 不阻断 |
| release freeze 拒绝 MAJOR | 在 ROADMAP 声明 `version_major`/`version_range`；例外用 `--force --reason --approved-by` |
| release freeze 阶段被拒 | P1/P2 禁止发布；P3 active 仅 alpha/预发布，先 `mf phase exit` 再正式冻结；P4/P5 修复可直接冻结（阶段门不可 `--force` 绕过） |
| release freeze/check 报版本不一致 | 同步 `pyproject.toml`、源码 `__version__`、`delivery.yaml`、`RELEASE-NOTES.md` 与发布清单；tag 指向旧版本时重打 `v<version>`（MFP-0028） |
| `mf --version` 仍是旧版本 | 源码 `__version__` 未更新，或全局工具未重装：`UV_NO_CACHE=1 mf dev install --yes`（MFP-0028/0029） |
| 追踪矩阵出现旧任务/重复 BUG | 使用默认当前路标追踪；仅在审计时 `--archive` |
| `mf req trace --check` 返回 1 | 按输出逐项补 SPEC/TASK/证据/VR，关闭 BUG/MFP/CHG 或登记原因；仅审计历史时用 `--archive` |
| 工作区内 pytest 角色门失败 | 0.1.1 起测试已隔离 cwd/MF_ROLE；仍失败时检查是否自定义 fixture 设置了角色 |
| worker 读到 >64KB 文件被拒 | 用 `mf context expand <path> --reason packet_missing`；常规 Read/cat 受预算限制 |
| 评审包显示证据缺失 | 目标任务未提交或未固化 dev-record/handoff/diff；先完成目标任务 submit 再生成 |
| Bash 被 guard 拒绝 | 检查路径是否在契约基线/其他交付库/allowed_paths 之外；worker 用任务 bundle 与合法 CLI；变量/嵌套 shell/eval/source/进程替换无法安全解析时会被保守拒绝 |
| 提交后需要修改文件 | 不能直接编辑；review NEEDS_REWORK 后 `mf task rework <id>`；本地 MFP 例外（`.meta-flow/improvements/MFP-*.yaml`） |
| 看不到 guard 拦截原因/审计 | deny 信息含角色/任务/lease/allowed_paths；manager 用 `mf context log` 查询 allow/deny |
| 任务提交提示越界但文件属于并行任务 | 确认两个任务都处于重叠活动窗口且 allowed_paths 不相交；非活动改动仍会被拒绝 |
| 提交仍报 egg-info/构建产物越界 | 1.0.2 起提交快照排除 gitignored 与 start 前未跟踪文件；若仍报错，确认 `.gitignore` 规则并运行 `git status --ignored` 核对 |
| `mf doctor` 报“状态对账” | state 派生快照过期：运行 `mf state rebuild`；不要手工编辑 `state/current.json` |
| worker `mf bug show` 被拒 | 1.0.2 起只允许读取活动任务 `fixes`/`inputs.bugs` 关联的 BUG；非关联 BUG 由 manager 读取 |
| 写 `.meta-flow/handoffs|dev-records/<task>.md` 被拒 | 1.0.2 起仅当前 in_progress 任务的本地副本可写；提交后需 manager 重开 |
| 安装镜像被 git 跟踪 | 确认 `.gitignore` 含 `# >>> meta-flow install mirror >>>` 块；运行 `mf install/upgrade` 修复 |

## 6. 附录：命令速查

| 领域 | 命令 |
|---|---|
| 安装/工作区 | `mf bootstrap`、`mf install`、`mf uninstall`、`mf upgrade`、`mf workspace init/attach/add-project/link/sync/status` |
| 角色/上下文 | `mf role`、`mf context show/expand/log/policy`、`mf hook pretool/session-start` |
| 规划 | `mf req add/list/show/update/trace/validate`、`mf roadmap show/plan/close/sizing/classify`、`mf phase show/enter/review/exit` |
| 设计/工作包 | `mf design create/accept`、`mf work create/task/start/decision/verify/accept/list/show` |
| 任务/评审 | `mf task create/list/show/validate/start/submit/accept/reject/prompt/rework/withdraw`、`mf task graph/plan/next/release/summary`、`mf task review dispatch` |
| 文档/技能 | `mf docs check/summary`、`mf skill list/show/validate`、`mf doctor [docs|process]` |
| 验证/发布 | `mf verify record/list/show/index`、`mf release freeze/check/show` |
| MFP/BUG | `mf improve new/triage/validate/submit/sync`、`mf dev improve import/list/update/archive`、`mf bug add/list/show --packet/update/fix/verify/close/escalate/audit` |
| 归档/维护 | `mf archive list/show/authorize/revoke/export`、`mf maintainer authorize-external`、`mf dev clone/update/install/status` |
| 状态/审计 | `mf status`、`mf log`、`mf doctor`、`mf state show/rebuild` |
