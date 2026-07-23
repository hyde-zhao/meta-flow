# Meta Flow USER-MANUAL

## 0. vNext 默认治理：独立双仓、轻量 Work、按风险加流程

新项目默认使用两个相互独立的 Git 仓库：

```text
<project>/                  # 发布库：代码和发布文档
└── .meta-flow/
    └── workspace.yaml      # tracked；指向 sibling 过程库

<project>-process/          # 过程库：只服务当前项目
├── .meta-flow-process.yaml # 反向绑定发布库
├── PROJECT.yaml
├── ROADMAP.yaml            # 可选
├── phases/                 # 可选
├── works/
├── retrospectives/
└── evolution/
```

先预览，再显式应用本地初始化：

`--project-root` 已是 Git 根时复用为发布库；路径不存在或为空目录时本地初始化 `main` 发布库。非空且不是 Git 根的目录会被阻断，不会接管其中的用户文件。

```bash
meta-flow project init --project-root . --project-id demo \
  --decision-ref decisions/DQ-PROJECT-INIT.json
meta-flow project init --project-root . --project-id demo \
  --decision-ref decisions/DQ-PROJECT-INIT.json \
  --apply --authorization /tmp/project-init-authorization.json
meta-flow project check --project-root .
meta-flow project query --project-root .
meta-flow project resolve-ref --project-root . --logical-ref process/PROJECT.yaml --format json
```

默认且当前唯一可由 `project init` 接受的模式是 `--process-link-mode none`，即 `route_mode=sibling-binding`：不会创建 `process` 入口，也不会修改 `.gitignore`。`relative-symlink` 仅保留为 legacy 顶层操作的兼容概念，不属于 GOV-004 init 验收路径。Agent/Skill 中的 `process/...` 是逻辑引用，文件 I/O 前统一调用 `project resolve-ref`；成功结果的绝对 `resolved_path` 只瞬时使用，退出码 2 必须阻断，不得自行拼 sibling、去前缀、恢复软链接或回退 legacy。需要过程仓的 vNext `project/work/retrospective/evolution` Python 命令统一从 binding 解析；`repository` 命令继续要求调用方显式提供单仓 `--repo-root`。

### 0.1 统一计划与 typed authorization

`project init`、`project adopt`、`project recover` 共用 schema v2 的 12 字段 envelope：`schema_version`、`operation`、`decision`、`decision_ref`、`project_id`、`release_repo`、`process_repo`、`base_oids`、`actions`、`conflicts`、`rollback_plan`、`plan_digest`。不得添加第 13 个顶层字段。`plan_digest` 是排除自身后的 canonical JSON SHA-256；release/process 在 dry-run、authorization-consume、apply-final 各核验一次，共 6 个检查点。adopt source 与 init snapshot seed source 在同三阶段另行只读核验，不计入这 6 个 mutation 检查点；init seed 还把 `source/PROJECT.yaml` 原始字节 SHA-256 纳入 action 与 plan digest，并在 apply-final 重算。

非 `NOOP` apply 必须提供严格 JSON typed authorization：

```json
{
  "schema_version": 1,
  "authorization_id": "auth-init-001",
  "authorization_source": "typed-user-confirmation",
  "authorization_kind": "project-onboarding",
  "operation": "project.init",
  "decision_ref": "decisions/DQ-PROJECT-INIT.json",
  "project_id": "demo",
  "plan_digest": "<64-character-plan-digest>",
  "expected_oids": {
    "release": {"state": "commit", "oid": "<40-character-oid>"},
    "process": {"state": "absent", "oid": ""}
  },
  "expires_at": "<future-RFC3339-time-with-timezone>",
  "single_use": true
}
```

`expected_oids` 必须逐字来自同一计划的 `base_oids`；repo observation 只允许 `absent`、`unborn`、`commit`，其中 `commit` 必须带 40 位小写 OID，另两态 OID 必须为空。授权输入不会被修改；排他 claim 与 transaction manifest 写入 release Git common dir 的 Meta Flow 私有区，不进入 tracked tree，也不记录绝对 process 路径。`READY/PASS/NOOP` 返回 0，`PARTIAL` 或未知内部错误返回 1，契约型 `BLOCKED` 返回 2。

### 0.2 snapshot-only 接入与恢复

已有项目的 source 必须是独立、clean、已提交的当前新格式过程快照 Git 根。先用 init snapshot seed 将 source 根级 `PROJECT.yaml` 的原始字节 create-only 写入新过程仓并建立 binding；source exact OID、PROJECT digest、plan digest 和 typed authorization 必须一致。source 的绝对路径不进入 binding、manifest 或 receipt：

```bash
meta-flow project init --project-root . --project-id demo --project-name Demo \
  --source-process-root ../snapshot-process \
  --decision-ref decisions/DQ-PROJECT-INIT-SNAPSHOT.json

# 审核计划后，authorization.expected_oids 必须包含计划中的 source_snapshot
meta-flow project init --project-root . --project-id demo --project-name Demo \
  --source-process-root ../snapshot-process \
  --decision-ref decisions/DQ-PROJECT-INIT-SNAPSHOT.json \
  --apply --authorization /tmp/project-init-snapshot-authorization.json
```

init route healthy 后再运行 adopt。公共 CLI 不接受任意 `--target-process-root`，目标 process 只能从 `--project-root` 的 healthy binding 解析；相同 PROJECT 为 NOOP，不同 PROJECT 保持冲突，受控替换尚未实施。adopt 只复制明确列出的其余 allowlist ref，source tree 和 source Git 始终零写入：

```bash
meta-flow project adopt --project-root . --project-id demo \
  --source-id current-snapshot --source-process-root ../snapshot-process \
  --include-ref PROJECT.yaml --include-ref ROADMAP.yaml \
  --decision-ref decisions/DQ-PROJECT-ADOPT.json

# 审核计划后，用与该 adopt 计划完全绑定的新授权执行
meta-flow project adopt --project-root . --project-id demo \
  --source-id current-snapshot --source-process-root ../snapshot-process \
  --include-ref PROJECT.yaml --include-ref ROADMAP.yaml \
  --decision-ref decisions/DQ-PROJECT-ADOPT.json \
  --apply --authorization /tmp/project-adopt-authorization.json
```

init/adopt 部分成功不会触发跨仓自动回滚。adopt 的 PASS terminal receipt 只在所有 ref/index action 和后置 route health 成功后写入；失败只记录真实 PARTIAL，receipt 自身写入失败时 transaction manifest 标记 `receipt_missing`，不得把上一时点的 PASS 当作终态。

先只读 inspect，再选择 resume、cleanup 或 abandon；后三者若产生 mutation，必须基于新计划提供新的 `operation=project.recover` typed authorization。inspect 保持 12 个顶层字段，并在 `actions` 内逐侧报告 state、target、ownership、outcome、before/after digest、`digest_matches`、allowed next actions 和 blocked reason。manifest 缺失、损坏或摘要漂移会 fail closed，不猜 ownership、不消费授权。cleanup 只删除该事务创建且当前摘要仍等于 `after_digest` 的文件；`.git`、仓库目录、用户修改文件和无法证明 ownership 的对象不自动删除。snapshot-seeded init 的 resume 必须再次显式提供同一 `--source-process-root`，并匹配原事务的 source exact OID 与 PROJECT digest。

```bash
meta-flow project recover --project-root . \
  --authorization-id auth-init-001 --action inspect
meta-flow project recover --project-root . \
  --authorization-id auth-init-001 --action resume \
  --apply --authorization /tmp/project-recover-authorization.json
```

成功后的第二次同意图 dry-run 必须返回 `NOOP`、mutation=0，且无需授权。Linux/Python 3.11 是本阶段原生验收平台；Windows 保持 deferred/out-of-scope，不得据此声明 Windows 原生 PASS。

两份 binding 必须在 `schema_version`、`layout_version`、`project_id`、`route_mode` 和 reciprocal sibling 路由上相互一致；任一不一致都会 BLOCKED。`workspace_parent` 当前只支持同一父目录的两个仓，绝对路径、`..`、sibling discovery 和非同父目录布局都不会被接受。缺少 `PROJECT.yaml` 时，`project status/check/query` 会报告过程仓尚未初始化；旧或缺失 layout metadata 不会静默降级为 vNext。

版本控制策略是：`.meta-flow/workspace.yaml` 属于发布仓机器真相源，必须提交；`.meta-flow/INSTALL-MANIFEST.yaml` 只记录本机项目级安装状态，必须 gitignore。工作区根 README 只作人类导航，不参与路由判定。

旧 shared artifact 子目录采用只读来源索引，不调用 `project adopt`，也不复制旧 CR/CP/Story/ledger。成功执行 `project init --apply` 后、过程仓首次提交前，人工创建 `legacy/LEGACY-SOURCE.yaml`：

```yaml
schema_version: 1
project_id: meta-flow
migration_mode: fresh-vnext-bootstrap
source_repo_url: git@github.com:hyde-zhao/meta-flow-artifacts.git
source_ref: refs/heads/main
source_oid: <exact-oid-from-git-ls-remote>
source_subpath: process/meta-flow
source_mode: read-only
copied_history: false
deletion_authorized: false
history_rewrite_authorized: false
snapshot_date: <YYYY-MM-DD>
note: 旧 CR/CP/Story/docs/ledger 保留在 legacy 仓；新工作从独立过程仓开始
```

`source_oid` 必须来自本次 preflight 的 `git ls-remote`，不得依赖本地缓存；文件不得记录本机绝对路径、用户名或凭据。`project adopt` 只适用于其 source 契约明确支持的 Git 根和新格式快照，不能用于 legacy shared artifacts 子目录。

日常工作以用户确认过的最小 `REQUEST.md` 和一个 `WORK.yaml` 为中心。系统解释 Work/CR 和 G0/G1/G2 判定；用户可主动升级，但高风险不得静默降级：

```bash
meta-flow work classify --change-kind documentation --touched-path-count 1
meta-flow work status --project-root . --work-id W-001
meta-flow work review-plan --project-root . --work-id W-001
meta-flow work validation-plan --project-root . --work-id W-001 --check-risk target-tests=覆盖当前功能风险
meta-flow work pause --project-root . --work-id W-001
meta-flow work resume-check --project-root . --work-id W-001
meta-flow work resume --project-root . --work-id W-001
```

| 档位 | 资源硬上限 | 默认流程 |
|---|---|---|
| G0 | `8 reads / 8 writes / 3 check groups / 32k token` | 无独立设计评审；目标检查 + diff/status |
| G1 | `20 / 24 / 8 / 96k` | 最多一次 Work 范围轻量评审；目标测试 + 必要构建/检查 |
| G2 | 每项人工批准 | HLD/ADR、人工设计门、独立 QA、经批准的全量验证 |

读取、写入和检查都必须同时满足 risk、`WORK.yaml.scope` 与 budget。token 只能标为 `measured`、`proxy` 或 `unavailable`；unavailable 不等于 0。默认项目查询最多读取 5 个直接引用对象，不扫描 sibling 项目或全历史。

### 0.1 Native CR 状态与可重建索引

vNext 正式 CR 的真相是 `PROJECT.yaml`、当前 `WORK.yaml` 和 `process/changes/CR-*.md`。`process/changes/CR-INDEX.json` 是可删除重建的派生索引，只扫描 native formal CR、按数值 CR ID 排序，并用 `semantic_digest` 覆盖 `schema_version + items`；它不会读取旧 index items、summary 正文、ledger 或 legacy 仓来补字段。旧仓和 `CR-INDEX.yaml` 只读，不复制、不修改、不重新生成。

```bash
# index 默认 dry-run；apply 必须绑定当前 process HEAD
meta-flow cr index --project-root .
meta-flow cr index --project-root . --apply --expected-process-oid <oid>
# 只有损坏 index 的显式恢复才增加 --rebuild
meta-flow cr index --project-root . --rebuild --apply --expected-process-oid <oid>

# 状态更新先生成计划，再使用完全相同的目标与 expected OID apply
meta-flow cr status-sync --id CR-101 --status closed --readiness READY_WITH_RISK \
  --gate-status cp8_closed --work-id CR-101 --project-root .
meta-flow cr status-sync --id CR-101 --status closed --readiness READY_WITH_RISK \
  --gate-status cp8_closed --work-id CR-101 --project-root . \
  --apply --expected-process-oid <oid>
```

`status-sync` 会在 process Git common dir 的私有 Meta Flow 区准备 transaction manifest、全部目标的 before/after digest、不可变恢复载荷和逐步 receipt；确认目标未漂移后逐文件原子替换，并最后写 CR-INDEX。发现未解决事务时新 sync 必须 BLOCKED：先运行 `meta-flow cr status-sync-inspect --project-root .`，再对明确 transaction ID 执行 `status-sync-resume` 或 `status-sync-rollback`。`RECOVERED` 表示发生过替换但已恢复，`PARTIAL` 表示恢复不完整；二者都不是 PASS。

### 0.2 合并确认与 exact Git scope

连续的本地实现、验证、交付子门可以冻结为一个 Decision Bundle revision，从而只向用户请求一次确认。确认只覆盖该 revision 中列出的 exact subgate、OID/branch/dirty facts、scope digest、授权与不授权项；每个 subgate 仍须分别检查、分别写 evidence/result，任一 `failed|blocked` 后不得启动后续门。facts、scope 或授权变化时必须建立新 revision 并重新确认。

冻结 changed paths 前运行 `meta-flow work git-inventory`，将候选路径唯一归入八类：`tracked_regular`、`tracked_symlink`、`prospective_untracked`、`ignored_generated`、`missing`、`submodule`、`outside_repo`、`duplicate`。只有 regular/prospective 是 mutation；symlink/missing/ignored 只验证，submodule/outside/duplicate 阻断。提交前 release/process 两仓分别检查 staged symmetric difference=0，不能用聚合结果代替，也不能用 `git add -f` 强行暂存 ignored 或 symlink alias。

两仓提交/推送彼此独立：

```bash
# 默认都是 dry-run
meta-flow repository commit ...
meta-flow repository push ...
```

`--apply` 必须额外提供与单仓计划、operation 和 exact OID 匹配的 typed authorization。两仓不使用双 leg/aggregate，也不声称原子性；一侧失败时保留另一侧真实成功结果，不自动回滚。

项目、关键 Phase 或发布切片完成后，使用 `meta-flow retrospective build|check|confirm-facts` 生成六维复盘：价值、规范/证据、质量/恢复、流动效率、token/context、Meta Flow 适配性。随后 `meta-flow evolution decision|package|check|start|result` 逐项审议并验证改进。事实确认、建议 accepted、实现启动、commit/push/production 授权是四种独立语义；复盘报告和进化结果都不能自动触发代码修改、publication 或下一代递归自进化。

本手册后续关于 `workspace bootstrap/push`、共享 artifacts、project integration、双 leg、aggregate 和完整 CP0-CP8 的章节保留给 legacy 项目与明确选择的 G2/正式 CR，不再是 G0/G1 默认路径。


## 1. 安装前准备

- Python 入口统一使用 `uv run --python 3.11 python ...`
- 若从源码仓库根目录执行，安装器路径是 `delivery/scripts/install.py`
- 若 `delivery/` 已作为独立仓库分发，安装器路径是 `scripts/install.py`
- 平台安装路径以 `doc/PLATFORM-CONTRACTS.yaml` 为真相源，README 与本手册只是派生说明

## 2. 常用安装命令

全局命令方式（推荐本地开发使用 editable，以便命令读取当前 checkout 的 `delivery/` 资产）：

```bash
uv tool install --editable .
meta-flow install codex --scope user
meta-flow install codex --scope project --project-dir /path/to/project
meta-flow install qoder --scope project --project-dir /path/to/project
```

项目级安装未提供 `--project-dir` 时，交互式终端会提示确认当前目录或输入其他目录；非交互环境必须显式传入 `--project-dir`。

安装状态按 scope 隔离：project scope 使用目标项目内 gitignored 的 `.meta-flow/INSTALL-MANIFEST.yaml`，user scope 使用 `~/.meta-flow/delivery/doc/INSTALL-MANIFEST.yaml`。project scope 的 install、uninstall 与 reinstall 不读写用户级 manifest。

CI / Agent 等非交互环境请使用三平台等价 dry-run；三条命令都只计算安装计划，不写目标项目：

```bash
uv run --python 3.11 meta-flow install codex --scope project --component full --project-dir . --dry-run
uv run --python 3.11 meta-flow install claude --scope project --component full --project-dir . --dry-run
uv run --python 3.11 meta-flow install qoder --scope project --component full --project-dir . --dry-run
```

meta-flow 源码仓的发布前 preflight：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' uv run --python 3.11 pytest -q
uv run --python 3.11 ruff check .
PYTHONDONTWRITEBYTECODE=1 uv run --python 3.11 python scripts/check_delivery_guardrails.py
PYTHONDONTWRITEBYTECODE=1 uv run --python 3.11 meta-flow doctor all --project-root .
PYTHONDONTWRITEBYTECODE=1 uv run --python 3.11 meta-flow check cr-tracking --project-root .
```

必须逐门读取原始退出码和 warning。`OK_WITH_WARNINGS` 仍是带风险结论；任一 blocker 或非零退出码都会阻断发布准备。

多层级帮助：

```bash
meta-flow --help
meta-flow install --help
meta-flow install codex --help
meta-flow install qoder --help
meta-flow uninstall --help
meta-flow uninstall codex --help
```

从仓库根目录执行：

```bash
uv run --python 3.11 python delivery/scripts/install.py claude
uv run --python 3.11 python delivery/scripts/install.py codex --project-dir /path/to/project
uv run --python 3.11 python delivery/scripts/install.py openclaw --dry-run
uv run --python 3.11 python delivery/scripts/install.py qoder --dry-run
```

从 `delivery/` 目录执行：

```bash
cd delivery
uv run --python 3.11 python scripts/install.py claude
uv run --python 3.11 python scripts/install.py codex --scope user
```

包装脚本：

```powershell
scripts\install.ps1 codex --dry-run
```

```bash
bash scripts/install.sh claude --dry-run
```

## 3. 安装内容

- `rules`：平台规则入口（AGENTS.md 为唯一 canonical 源；claude 平台安装时从 AGENTS.md 生成 CLAUDE.md）
- `agent`：平台 Agent 定义 + Skill 定义与 Skill 私有运行时资产
- `full`：同时安装 rules 与 agent

可通过 `--component rules|agent|full` 控制安装范围。默认值：

- `--scope user` 默认只安装 `rules`
- `--scope project` 默认安装 `full`
- `meta-flow uninstall <platform>` 未指定 `--component` 时默认卸载 `full`

legacy `--content agents|skills|rules|all` 保留兼容，但新文档优先使用 `--component`。

## 3.1 Agent 命令与显示区分

canonical role 只覆盖功能子 agent，用于状态机、handoff、检查点和审计。Host Orchestrator 是当前会话主进程职责，不安装为 Codex / Claude Code agent 文件。平台展示按下表安装：

| canonical role | Codex 命令 / nickname_candidates | Codex 模型 | Codex `model_reasoning_effort` | Claude Code color |
|---|---|---|---|---|
| `meta-pm` | `pm-wu`、`pm-zheng`、`pm-wang`、`pm-feng`、`pm-chen` | `gpt-5.6-terra` | `medium` | `orange` |
| `meta-se` | `se-chu`、`se-wei`、`se-jiang`、`se-shen`、`se-han` | `gpt-5.6-terra` | `high` | `yellow` |
| `meta-dev` | `dev-yang`、`dev-zhu`、`dev-qin`、`dev-you`、`dev-xu`、`dev-he`、`dev-lv`、`dev-shi`、`dev-zhang`、`dev-kong` | `gpt-5.6-terra` | `medium` | `green` |
| `meta-qa` | `qa-he`、`qa-lv`、`qa-shi`、`qa-zhang`、`qa-kong`、`qa-cao`、`qa-yan`、`qa-hua`、`qa-jin`、`qa-wei` | `gpt-5.6-terra` | `high` | `cyan` |
| `meta-doc` | `doc-cao`、`doc-yan`、`doc-hua`、`doc-jin`、`doc-wei` | `gpt-5.6-luna` | `low` | `purple` |

Codex 安装器把命令别名、Codex-only 模型路由和推理等级写入 `.codex/agents/*.toml`。Claude Code 文件型 subagent 不使用 nickname，安装器写入 `color` 字段，通过颜色区分不同子 agent；OpenAI 模型名不会写入 Claude Code 或 Qoder Agent。主进程建议父会话在标准 / 复杂工作流中使用 `model_reasoning_effort="high"`，fast-lane 或小范围机械修改可使用 `medium`。

Codex 还会安装动态思考 profile，但 canonical role 不变：

| Codex profile agent | canonical role | Codex 模型 | `model_reasoning_effort` | 典型触发 |
|---|---|---|---|---|
| `meta-dev-debugger` | `meta-dev` | `gpt-5.6-sol` | `high` | 重复失败、复杂追因、跨模块 bug、状态机 / 数据一致性问题 |
| `meta-se-critical` | `meta-se` | `gpt-5.6-sol` | `xhigh` | 架构冻结、公共 contract、重大 ADR、长期边界风险 |
| `meta-qa-critical` | `meta-qa` | `gpt-5.6-sol` | `xhigh` | CP5 / CP7 / CP8、发布前、高风险验证和证据链裁决 |

Host Orchestrator 调度时必须在 `AGENT-DISPATCH-LEDGER.ndjson` 或 handoff `dispatch` 记录 `canonical_role`、`codex_agent_name`、`reasoning_profile` 和 `dispatch_trigger`。Codex 工具面有 `spawn_agent` / `resume_agent` / `send_input` 时，创建 `mode=subagent` handoff 后必须调用对应工具；只创建 handoff 不算子 agent 已执行。

Qoder 安装器复用 canonical Agent 定义和 reasoning profile（含 `meta-dev-debugger` / `meta-se-critical` / `meta-qa-critical`），但不复用 Codex-only GPT-5.6 模型路由；输出为 Markdown + YAML frontmatter 格式（`.qoder/agents/*.md`）。Qoder 不使用 `nickname_candidates`，改用 `effort` 字段映射 Codex 的 `model_reasoning_effort`（`minimal` → `low`，其余 1:1），并复用 Claude Code 的 `color` 字段区分角色。

## 4. DryRun 与卸载

全局命令方式：

```bash
meta-flow uninstall codex --scope user
meta-flow uninstall codex --scope project --project-dir /path/to/project
meta-flow uninstall claude --scope user --component rules --dry-run
meta-flow uninstall qoder --scope project --project-dir /path/to/project
```

脚本入口方式：

```bash
uv run --python 3.11 python delivery/scripts/install.py claude --dry-run
uv run --python 3.11 python delivery/scripts/install.py uninstall codex --scope user
```

`meta-flow uninstall <platform>` 依赖当前 scope 的安装 manifest 精确移除已安装文件：project scope 读取目标项目 `.meta-flow/INSTALL-MANIFEST.yaml`，user scope 读取 `~/.meta-flow/delivery/doc/INSTALL-MANIFEST.yaml`。默认 `--component full`，也可以使用 `--component rules|agent|full` 卸载对应组件；项目级卸载必须传入和安装时一致的 `--project-dir`。

如果要移除 `meta-flow` 这个全局命令本身，而不是卸载已写入 Claude Code / Codex / OpenClaw 的规则、Agent 或 Skill，使用：

```bash
uv tool uninstall meta-flow
```

## 5. 默认安装位置

| 平台 | 项目级 Agent | 项目级 Skill | 用户级 Agent | 用户级 Skill |
|------|---------------|---------------|--------------|--------------|
| Claude Code | `<project>/.claude/agents/` | `<project>/.claude/skills/` | `~/.claude/agents/` | `~/.claude/skills/` |
| Codex | `<project>/.codex/agents/` | `<project>/.agents/skills/` | `~/.codex/agents/` | `~/.agents/skills/` |
| OpenClaw | `<project>/.openclaw/agents/` | `<project>/.openclaw/skills/` | `~/.openclaw/agents/` | `~/.openclaw/skills/` |
| Qoder | `<project>/.qoder/agents/` | `<project>/.qoder/skills/` | `~/.qoder/agents/` | `~/.qoder/skills/` |

Codex Skill 不安装到 `.codex/skills` 或 `~/.codex/skills`；安装器 dry-run 和 guardrail 会检查这个负向断言。

Qoder 与 Codex 在 project scope 共享 `AGENTS.md`。安装器使用 platform-tagged managed block（`<!-- myflow:managed:begin platform=qoder -->` / `<!-- myflow:managed:end platform=qoder -->`）隔离各平台内容；卸载 Qoder 只清除 Qoder 的 block，不影响 Codex 已安装的内容。旧的无 platform 标签 managed block 在下次安装时自动迁移为带标签格式。

如果安装失败并提示 `安装路径被非目录占用: <path>`，说明目标安装目录的某一级已被普通文件占用。请删除、移动或重命名该文件后重试。

## 6. 快速使用 meta-flow

主编排器是当前会话的 Host Orchestrator。首次启动一个正式交付工作流时，建议直接给出目标、平台和约束：

```text
开始
目标：为 <agent / skill / workflow 名称> 产出正式方案
平台：Claude Code、Codex、Qoder
要求：先澄清需求，再给我 HLD，确认后再拆 Story
```

常用控制语句：

```text
当前状态
下一步
继续
快速修改
回退到 CP3 蓝图 / HLD 架构评审前
```

### 6.0.1 目标项目 Adoption Readiness

在目标项目安装 Meta Flow 后，先完成 workspace/state/ledger bootstrap、identity scan、adoption doctor，再创建首个 bootstrap CR：

```bash
meta-flow workspace bootstrap --artifact-root <relative-artifact-root> --project-name <project-name> --project-root .
meta-flow identity scan --project-root .
meta-flow quality init --project-root .
meta-flow doctor adoption --project-root .
meta-flow cr bootstrap --id CR-001 --title "<project> adoption bootstrap" --scope "Initialize Meta Flow adoption readiness." --project-root .
meta-flow context check --context process/context/CP0-CR001.context.json --project-root .
meta-flow check cp-result --result process/checks/CP0-CR-001-BOOTSTRAP.result.json --project-root .
```

`workspace bootstrap` 会建立外置 `process` 路由、`STATE.current.json`、`STATE.md` 人类摘要、`process/current/CURRENT.json` 当前入口发现层和基础 ledgers。`identity scan` 只读扫描 `PACKAGE-IDENTITY.yaml`、`pyproject.toml`、README 和 docs 交付约定，不自动写 production 交付路由。`doctor adoption` 只聚合 readiness，不写文件；`cr bootstrap` 只写 `process/` 内的 active CR、summary/index/ledger、CP0 result/summary 和 CP0 context。

`STATE.current.json` 是轻量机器状态，不是历史数据库；关闭 CR 的长字段、历史 checkpoint、human gate 决策、source refs、last actions 和 workflow health 详情应进入 ledger、summary、checkpoint 或 `process/archive/state/<timestamp>/`。如果旧项目的 `STATE.current.json` 已经膨胀，可先审计再应用 slim：

```bash
meta-flow state slim --project-root . --dry-run
meta-flow state slim --project-root . --apply
meta-flow state render --project-root . --force
meta-flow state current-refresh --project-root .
meta-flow state check --project-root . --mode enforce
```

`process/current/CURRENT.json` 会表达 `idle`、`active`、`awaiting_gate` 或 `blocked`，并指向当前 `state_ref`、`cr_index_ref`、`context_ref`、`checkpoint_ref`、`story_packet_ref`、`release_context_ref` 和 `handoff_ref`。空闲期会显示 `status: "idle"`；这表示当前没有活跃 CR，Agent 应优先读取最新 release context、handoff 和 CR index，而不是误把已关闭 CR 的上下文当成活跃工作。

上述流程不授权 credentials、runtime、SaaS、production write、trading、publish 或 CR-033 runtime follow-up。正式编号使用 `CR-xxx`；`MF-xxx` 仅作为历史别名。

#### 源码仓库与共享 artifacts 仓库的 Git 周期

外置 `process` 路由只建立文件路由关系，不会把源码 / 交付仓库和共享 artifacts 仓库变成同一个 Git 仓库。两边使用同一个 CR ID 关联证据，但分支起点和完成目标不同：

| leg | CR 开始前必须确认 | 短期 CR 分支 | CR 完成目标 |
|---|---|---|---|
| source | 源码仓库的 default branch（`main` 或 `master`）是本次采用的最新基线 | `refs/heads/cr/<cr-id>-<slug>` | 推送并按源码仓库流程合并回 default branch |
| artifact | 当前项目 integration 是本次采用的最新项目基线 | `refs/heads/projects/<project>/cr/<cr-id>-<slug>` | 只回合到 `refs/heads/projects/<project>/integration` |

共享 artifacts 仓库保留 shared `main`，但它只是共享集成基线，不是项目 worktree 的日常驻留分支，也不是单个 artifact CR 的目标分支：

```text
main（共享集成基线）
  ├── projects/<project-a>/integration（项目 A 常驻）
  │     └── projects/<project-a>/cr/<cr-id>-<slug>（短期）
  └── projects/<project-b>/integration（项目 B 常驻）
        └── projects/<project-b>/cr/<cr-id>-<slug>（短期）
```

每次创建 artifact CR 时，只要求从**最新的项目 integration** 派生短期分支。`main` → integration 和 integration → `main` 都是 CR 外的人工同步操作；单个 CR 不自动拉入 shared `main`，也不自动把项目累计产物回灌到 `main`。

#### artifact worktree 驻留与切换

- 空闲时：worktree 驻留 `projects/<project>/integration`。
- CR 活动时：worktree 切到该项目的 `projects/<project>/cr/<cr-id>-<slug>`。
- CR leg 完成后：目标是回合到项目 integration，再恢复空闲驻留状态；不触碰 shared `main`。
- 切换前：要求 clean worktree、无进行中的 Git 操作，并完成容量、权限和 durable intent 预检。
- 切换异常：fail-closed；通过 fresh observation 判断继续、恢复到 integration，或保留现场交给人工处理。分支切换不被宣称为底层原子事务。

上述 project-first routing、worktree 恢复与 lifecycle 契约已实现，但当前仅由离线 fixture 验证；没有面向用户的 project-worktree 切换 CLI。只读迁移 preflight 也只提供 Python library / API，当前不存在 migration CLI。不要自行拼接未记录的命令。

#### 双 leg 完成聚合

source leg 与 artifact leg 各自独立完成，并把结果写入同一个 CR 的证据链。整体状态按以下优先级取最差值：

```text
BLOCKED > FAIL > IN_PROGRESS > PASS
```

只有两个 leg 都是 terminal `PASS` 时，CR 才能声明整体完成；任一 leg 未完成、失败或阻断时，整体不得宣称完成。一个 leg 已产生效果而另一个未成功时，聚合会保留 `PARTIAL` 事实，供恢复或人工裁决，不会把已发生的结果回写成“未发生”。已有聚合入口是：

```bash
meta-flow cr aggregate --id CR-051 --operation-id operation-001 --attempt 1 --source-handle source.json --artifact-handle artifact.json --dry-run --project-root .
```

`--dry-run` 只检查并展示聚合计划；聚合不创建、切换、合并或推送分支，也不执行 `main` ↔ integration 同步。

#### 现有 workspace 命令的边界

只读检查可以使用当前真实存在的命令：

```bash
meta-flow workspace check --project-root .
meta-flow workspace git-status --project-root .
```

`workspace git-status` 会分别展示两个仓库当前的 branch、upstream、dirty、ahead、behind，但不证明当前分支符合 source / artifact leg 契约，也不证明 integration 已与 shared `main` 同步。

`meta-flow workspace push` 仍是通用的顺序推送辅助命令：它默认拒绝 dirty working tree，并分别推送两个仓库当前分支；它不是项目优先生命周期执行器，不会创建 integration / CR 分支，不会完成 CR → integration 或 `main` ↔ integration 合并，不会切换 worktree，也不会聚合双 leg。因两个仓库的目标分支不同，不应把该命令当成日常 CR 自动完成入口；任何真实推送仍需独立授权并先核对各仓库分支、upstream 和目标 ref。

#### 能力与授权状态

| 能力 | 当前状态 |
|---|---|
| 项目优先 routing、可恢复 worktree switch、异构双 leg lifecycle、多项目 selector | 已实现；仅通过离线 fixture 验证 |
| 只读 migration preflight manifest | 已实现为 Python library / API；仅通过离线 fixture 验证，无用户 CLI |
| 真实托管 remote / branch protection / Windows native pilot | `not-authorized`；未执行、未验证 |
| 真实 worktree / ref mutation、迁移、复制、移动、软链接、同步与 publish | `not-authorized`；未执行 |

CP7 的 `PASS_WITH_RISK` 与 CP8 的 `READY` / `READY_WITH_RISK` 只表示验证或交付就绪，不表示真实 Git、worktree、ref、remote、迁移、软链接、凭据、网络或 publish 已获授权。

### 6.0.2 初始化质量治理 Policy

新项目需要启用轻量质量治理时，先初始化默认 policy：

```bash
meta-flow quality init --project-root .
meta-flow quality model-check --project-root .
meta-flow quality eval-check --project-root .
meta-flow doctor quality --project-root .
meta-flow doctor workflow --project-root .
```

`quality init` 会写入：

- `process/policies/QUALITY-MODEL.yaml`
- `process/policies/EVAL-MATRIX.yaml`

这两个 policy 用于定义质量维度、eval 映射和最小 workflow metrics 的派生来源。`doctor workflow` 只从 CP result、event ledger 和 read-expansion ledger 汇总指标，不会创建独立的手工 metrics 真相源。若某个项目暂时没有 ledger，doctor 会以 warning 说明缺失，而不是静默创建统计文件。

### 6.0 输出目录

Meta Flow 生成的文档默认分为三类：

| 类型 | 默认目录 | 典型文件 |
|---|---|---|
| 长期可交付文档 | `docs/` | `docs/product/USE-CASES.md`、`docs/design/HLD.md`、`docs/features/<feature>/DESIGN.md`、`docs/quality/TEST-REPORT.md`、`docs/release/DEPLOY-CHECKLIST.md` |
| 运行过程文档 | `process/` | `process/STATE.md`、`process/REQUEST.md`、`process/DEVELOPMENT-PLAN.yaml`（Story / Wave / status / task 机器真相源）、`process/STORY-BACKLOG.md` / `process/STORY-STATUS.md`（可选 legacy / generated view）、`process/stories/STORY-*.md`、`process/stories/STORY-*-IMPLEMENTATION.md`、`process/changes/CR-*.md` |
| 人工确认态 | `process/checkpoints/` | `process/checkpoints/CP2-REQUIREMENTS-BASELINE.md`、`process/checkpoints/CP3-HLD-REVIEW.md`、`process/checkpoints/CP5-ALL-STORIES-LLD-BATCH.md`、`process/checkpoints/CP8-DELIVERY-READINESS.md` |

旧项目中已经存在的 `process/USE-CASES.md`、`process/HLD.md`、根目录 `checkpoints/CP*.md` 等路径只作为 legacy fallback 读取；新工作流在无目标项目约定时默认写入 `docs/...` 和 `process/checkpoints/...`。production 项目如果已有交付目录或 README/docs 约定，优先按目标项目约定输出。

`process/` 下的目录按热 / 温 / 冷分区读取，完整 contract 见 `delivery/rules/DIRECTORY-CONTRACT.md` / `.yaml`：

- 热区：`process/state/STATE.current.json`、`process/current/CURRENT.json`、当前 context capsule 或 Story packet。只有被 context / packet 列入 `must_read` 或 `allowed_reads` 时才默认读取。
- 温区：`process/checks/*.result.json`、`process/checkpoints/CP*.md`、`process/changes/summaries/*.summary.json`、`process/evidence/*.index.json`、当前 release context。默认通过 context / packet 列表读取，避免扫全量目录。
- 冷区：`process/archive/**`、历史 discussion log、legacy 长状态和历史长计划。默认进入 `do_not_read_by_default`；确需读取时必须有 `full_doc_read_reason`，并通过 `process/state/READ-EXPANSION-LEDGER.ndjson` 记录。

### 6.1 标准推进顺序

1. `host-orchestrator` 初始化请求并写入 CP0 自动检查结果。
2. `host-orchestrator` 将需求澄清阶段委托给 `meta-pm`。你可以直接与 `meta-pm` 多轮讨论 Scenario Gray Areas：先识别 3-4 个会影响交付的灰区，让你选择 1-3 个重点讨论；标准模式下至少会出现 1 个 `SGQ-*` 用户可见场景确认问题，并记录你的回答和复述确认；未选但有价值的想法进入 Deferred Ideas。随后沉淀 `USE-CASES.md` 和 `REQUIREMENTS.md`，写入 CP1 / CP2 自动检查结果，并在你确认“可提交给 host-orchestrator 汇总”后交还。
3. CP2 Decision Brief 人工确认通过后，`host-orchestrator` 将 HLD 设计阶段委托给 `meta-se`。你可以直接与 `meta-se` 讨论 Architecture Gray Areas 和 advisor table；advisor lane 使用 `Option | Pros | Cons | Impact Surface | Recommendation | Assumptions / When to switch` 表格形成候选方案输入。随后 `meta-se` 输出 `BLUEPRINT.md`、`DOMAIN-MAP.md`、`DEPENDENCY-MAP.md`，并生成包含适用性矩阵、Use Case → Architecture Traceability 和关键场景模拟的 `HLD.md` 与 CP3 自动预检；当你确认“HLD 草案可提交给 host-orchestrator 发起 CP3”后交还。
4. CP3 人工确认通过后，`meta-se` 先输出 `docs/design/FEATURE-DESIGN-MATRIX.md`，判断哪些 Feature 需要 `docs/features/<feature>/DESIGN.md` / `TEST-PLAN.md` / `TASKS.md`，并为每个 Story 标记 `feature_design_refs` 与 `lld_policy=full-lld|technical-note|waived`；随后输出 `process/DEVELOPMENT-PLAN.yaml`（Story / Wave / status / task 机器真相源）、Story 卡片和 CP4 自动预检。`STORY-BACKLOG.md` / `STORY-STATUS.md` 只作为 optional legacy / generated views，并用 `meta-flow story plan-check --project-root .` 检查 drift。CP4 不再单独人工确认，其摘要汇入 CP5。
5. `host-orchestrator` 仍处于 story-planning，按 Story DAG 确定覆盖全部目标 Story 的设计证据批次，组织 `meta-dev` 并行输出设计证据：高风险 Story 生成完整 `STORY-{id}-{story_slug}-LLD.md`，`standard-lite` / `allows_batch_lld=true` 下低风险、同质且共享实现面的 Story 可写入 `BATCH-{cr_id-or-batch_id}-{slug}-LLD.md#story-story-{id}`，低风险 Story 可在 Story 卡片内补 `## 技术说明`，明确豁免的 Story 写 waived 证据，并全部生成 CP5 自动预检。`full-lld` 必须覆盖工程依据、目标、需求、模块拆分、代码结构、数据模型、API、流程、技术细节、安全、测试、实施、风险和 DoD 等 14 段语义要点；`batch-lld` 必须标注 batch scope、homogeneous story pattern、risk level 和 shared contract，且不得用于 runtime / security / credential / production-write 等高风险 Story。多个 `meta-dev` 遇到实现灰区时只写 clarification queue，由 `host-orchestrator` 合并后一次性问你，再把答案分发回对应 `meta-dev`。队列收敛后，host-orchestrator 先执行 CP5 capsule-first 和 LLD 结构检查，再发起一次全量人工确认。
6. 全量 CP5 确认后进入 story-execution；当前 Wave Story 的 `dev_gate` 满足后，`host-orchestrator` 自动按 Wave 调度 `meta-dev`，并在 `process/state/AGENT-DISPATCH-LEDGER.ndjson` 与 handoff `dispatch` 中记录证据。`meta-dev` 先用 `implementation-execution` 形成实现对象清单、设计契约映射、测试 / Fixture 计划、最小实现切片、平台差异和交接摘要；复杂 / 高风险 / Prompt-Skill / Workflow / 安装器 / 护栏 / 平台适配 / 发布相关 Story 写完整 `IMPLEMENTATION.md`，低风险 Story 可写 Story 摘要或 DEV-LOG。实现完成后写入 CP6 编码完成检查结果。
7. 每个 Story 开发完成且 CP6 通过后，`host-orchestrator` 自动调度 `meta-qa` 执行验证，并记录调度证据。验证时 `meta-qa` 会使用 `verification-execution` 消费 CP6 实现执行证据、设计证据和 `TEST-MATRIX.md`，输出验证对象清单、验证追踪矩阵、设计契约验证、分层验证计划、fixture / dry-run / 人工审查、问题和剩余风险，再使用 `quality-review` 固化 TEST-REPORT / REVIEW / FIXES 并写入 CP7。CP7 结论为 `PASS` / `WAIVED` 时进入 verified，`PASS_WITH_RISK` 时可推进但风险进入 CP8，`NEEDS_REWORK` 回 meta-dev，`NEEDS_DESIGN_CLARIFICATION` 回 meta-se / host-orchestrator，`BLOCKED` 阻断。
8. `meta-doc` 最后输出 README 和 USER-MANUAL。随后 `meta-qa` 使用 `release-readiness` 先生成 `process/release/RELEASE-CONTEXT.yaml` 和 `process/context/CP8-DELIVERY-CONTEXT.yaml`，再按 `release_artifact_profile=minimal|compact|full` 裁剪发布文档。CP8 的 `release_decision=READY|READY_WITH_RISK` 才可发起人工终验，`NOT_READY` 阻断，`RELEASED|FAILED` 必须有独立真实发布授权；CP8 Decision Brief 和人工终验通过后进入 delivered。

人工门禁 approve 或自动 CP `PASS` / `WAIVED` 后，回填审批结果不是本轮终点。host-orchestrator 必须继续消费 active CR 的 route plan，自动执行所有 `human_gate=none` 的 CP / 阶段准备，直到下一个 required human gate、delivered、失败路由、授权边界或 workflow health 阈值才停。典型例子是 CP3 approve 后应穿过 CP4 自动预检并打开 CP5，而不是等待用户再说“继续推进 CP5”。该行为可用以下命令回归检查：

route plan 的 CP applicability 来自 CR type、route traits 和 gate profile。`applies=false` 的 checkpoint 使用 `N/A`，表示该门不属于本次路径；`WAIVED` 只表示本来适用但经显式审批豁免，两者不得互换。状态推进还会校验 decision 与 stop reason 的兼容性：rework / design clarification 必须保留精确失败原因，授权边界和 workflow-health 阈值可安全停止 pass-like 路径，任何 required human gate 都不得被自动越过。

```bash
meta-flow check state-transition --route-plan process/checks/CP0-CR158.route-plan.json --result process/checks/CP4-CR158.result.json --project-root .
meta-flow check state-transition --route-plan process/checks/CP0-CR158.route-plan.json --approved-gate CP3 --project-root .
```

### 6.2 检查点文件

所有检查点都包含 Entry Criteria、Checklist、Exit Criteria、Deliverables。自动检查点必须写入逐项检查结果；CP2 / CP3 / CP5 / CP8 人工检查点必须有可审查的 Decision Brief、审批者摘要、决策分层、待人工决策清单和 checklist 文件。审批者摘要先说明本次确认服务的整体目标、推荐动作、`approve` 后会发生什么、`approve` 不授权什么、不确认会阻塞什么；决策分层再区分必须用户决策、高风险策略确认、agent 默认处理和仅审计记录。待人工决策清单会汇总本轮所有需要你确认的问题，状态机对象是 `process/checkpoints/CP*.md` Decision Brief 与 `process/state/GATE-LEDGER.ndjson`；每项包含决策 ID、决策类型、推荐方案、至少 1 个备选方案（优先 2 个）、优劣分析、影响 / 风险和回退 / 切换条件。

CP2 / CP3 / CP5 / CP6 / CP7 / CP8 前后会生成 `process/context/*-CONTEXT.yaml` 阶段上下文胶囊。它不替代正式文档，也不需要用户手工维护；作用是让下游 Agent 先读取摘要、证据路径、决策项、风险和不授权项，只有缺失、冲突、字段不足、人工审计或深度评审时才展开读取完整正式文档，从而减少 token 消耗。

同一 CR 的 CP 不以内联章节作为真相源。`process/changes/CR-*.md` 只维护 `Checkpoint Index`、状态摘要和 ref；自动 CP 真相源是 `process/checks/CP*.result.json`，人工门禁真相源是 `process/checkpoints/CP*.md`，事件真相源是 `CHECKPOINT-LEDGER.ndjson` / `GATE-LEDGER.ndjson`。如果需要看完整 CP 详情，应打开 index 中的 ref，而不是要求 CR 正文复制 CP result、Decision Brief 或 review 全文。

CP result 和事件台账应使用机器可读命令闭环：

```bash
meta-flow cp result-check --result process/checks/CP4-CR158.result.json --check-consistency --project-root .
meta-flow cp ledger-append --result process/checks/CP4-CR158.result.json --project-root .
meta-flow event check --ledger process/state/CHECKPOINT-LEDGER.ndjson --type checkpoint
```

`--check-consistency` 会在存在 `STATE.current.json` 和 route plan 时同步执行 state-transition 检查，防止自动 CP 通过后状态停在等待用户继续。

| CP | 名称 | 类型 | 文件 |
|----|------|------|------|
| CP0 | 原始请求受理门 | 自动 | `process/checks/CP0-REQUEST-INTAKE.md` |
| CP1 | 用户场景完备门 | 自动 | `process/checks/CP1-USE-CASE-COMPLETENESS.md` |
| CP2 | 需求基线门 | 自动预检 + 人工 | `process/checks/CP2-REQUIREMENTS-BASELINE.md`；`process/checkpoints/CP2-REQUIREMENTS-BASELINE.md` |
| CP3 | 蓝图 / HLD 架构评审门 | 自动预检 + 人工 | `process/checks/CP3-HLD-CONSISTENCY.md`；`process/checkpoints/CP3-HLD-REVIEW.md` |
| CP4 | Story 拆解与并行安全门 | 自动预检（汇入 CP5） | `process/checks/CP4-STORY-DAG-PARALLEL-SAFETY.md` |
| CP5 | Story 设计证据可实现性门 | 全量自动预检 + 人工 | `process/checks/CP5-{story_id}-{story_slug}-LLD-IMPLEMENTABILITY.md`；`process/checkpoints/CP5-ALL-STORIES-LLD-BATCH.md` |
| CP6 | Story 编码完成门 | 滚动自动 | `process/checks/CP6-{story_id}-{story_slug}-CODING-DONE.md`，并引用 `IMPLEMENTATION.md` 或低风险实现摘要 |
| CP7 | Story 验证完成门 | 滚动自动 | `process/checks/CP7-{story_id}-{story_slug}-VERIFICATION-DONE.md`，并引用 `VERIFICATION-REPORT.md`、`TEST-REPORT.md`、`REVIEW.md` 或低风险验证摘要 |
| CP8 | 交付就绪门 | 自动预检 + 人工 | `process/checks/CP8-DELIVERY-READINESS.md`；`process/checkpoints/CP8-DELIVERY-READINESS.md` |

CP6 / CP7 自动检查结果必须包含 `Agent Dispatch Evidence` 小节，用来证明 `meta-dev` / `meta-qa` 是真实子 agent 执行，而不是只有 handoff 文档。CP6 还必须记录实现执行证据路径、证据类型和 N/A 理由。CP7 还必须记录验证对象清单、验证追踪矩阵、设计契约验证、分层验证计划、fixture / dry-run / 人工审查、问题和剩余风险、阶段决策。

软件开发工作流会在这些检查点周围生成额外工程产物：

| 阶段 | 关键产物 | 用途 |
|---|---|---|
| CP2 前 | `docs/product/SCENARIOS.yaml`、`docs/product/TEST-MATRIX.md`、`docs/product/STORY-MAP.md`、`docs/product/MVP-SCOPE.md`、`docs/product/RELEASE-SLICES.md` | 把用户场景转为工程验证覆盖、产品范围、发布切片和 backlog 输入 |
| CP3 前 | `docs/design/BLUEPRINT.md`、`docs/design/DOMAIN-MAP.md`、`docs/design/DEPENDENCY-MAP.md`、`docs/design/HLD.md` | 先定义 Feature / Epic 边界、领域对象、数据归属和依赖方向，再形成系统架构 |
| CP7 | `docs/quality/VERIFICATION-REPORT.md`、`docs/quality/TEST-REPORT.md`、`docs/quality/REVIEW.md`、`docs/quality/FIXES.md` | 汇总验证对象清单、追踪矩阵、设计契约、分层验证、验证命令、覆盖缺口、review findings、回修 / 设计澄清输入和剩余风险 |
| CP8 | `process/release/RELEASE-CONTEXT.yaml`、`docs/release/RELEASE-NOTES.md`、`docs/release/DEPLOY-CHECKLIST.md`、`docs/release/ROLLBACK.md`、`docs/release/MIGRATION.md`、`docs/release/FEEDBACK.md` | 先用 capsule 摘要控制发布上下文，再按 `release_artifact_profile=minimal|compact|full` 输出发布产物；`release_decision=READY|READY_WITH_RISK` 可进入终验，`NOT_READY` 阻断，`RELEASED|FAILED` 需要独立真实发布授权；`FEEDBACK.md` 不替代 follow-up tracking 台账 |

阶段上下文胶囊默认路径：

| 门禁 | 路径 | 说明 |
|---|---|---|
| CP2 | `process/context/CP2-REQUIREMENT-CONTEXT.yaml` | 需求、场景、范围和待决策摘要 |
| CP3 | `process/context/CP3-DESIGN-CONTEXT.yaml` | 蓝图、HLD、ADR 和架构灰区摘要 |
| CP5 | `process/context/CP5-LLD-CONTEXT.yaml` | Story 设计证据、LLD policy、clarification 队列和文件 owner 摘要 |
| CP6 | `process/context/CP6-IMPLEMENTATION-CONTEXT.yaml` | 当前 Wave / Story 的实现输入和设计契约摘要 |
| CP7 | `process/context/CP7-VERIFICATION-CONTEXT.yaml` | 验证范围、实现证据、测试矩阵和风险摘要 |
| CP8 | `process/context/CP8-DELIVERY-CONTEXT.yaml` | 发布准备、文档缺口、风险接受、不授权项和 follow-up 摘要 |

CP5 发起前必须额外通过 capsule-first 与 LLD 结构检查：

```bash
meta-flow story cp5-context-check --context process/context/CP5-LLD-CONTEXT.yaml --project-root .
meta-flow story lld-check --lld process/stories/STORY-S01-example-LLD.md --evidence-type full-lld --project-root .
meta-flow story lld-check --lld process/stories/BATCH-CR123-adapters-LLD.md --evidence-type batch-lld --project-root .
```

`cp5-context-check` 会阻止 CP5 默认读取完整 HLD / ADR / TEST-MATRIX / TEST-REPORT / REVIEW，除非 context capsule 写明 `full_doc_read_reason` 或 `read_expansion_log`。`lld-check` 负责机械结构和分级约束；内容一致性仍由 CP5 审查判断。

CP2 / CP3 还会生成讨论追溯文件：

| 阶段 | Discussion Log | Discussion Checkpoint | 记录内容 |
|---|---|---|---|
| CP2 | `process/discussions/CP2-SCENARIO-DISCUSSION-LOG.md` | `process/checks/CP2-DISCUSSION-CHECKPOINT.json` | Scenario Gray Areas、用户选择、freeform 确认、Deferred Ideas、canonical refs |
| CP3 | `process/discussions/CP3-HLD-DISCUSSION-LOG.md` | `process/checks/CP3-DISCUSSION-CHECKPOINT.json` | Architecture Gray Areas、advisor table、方案形成输入、HLD 后审查意见、切换条件 |

这些 Discussion Log 用于审计和中断恢复，不替代正式产物。后续 Agent 默认先以 `process/context/*-CONTEXT.yaml` 为读取入口；必要时再展开读取 `docs/product/USE-CASES.md`、`docs/product/REQUIREMENTS.md`、`docs/product/SCENARIOS.yaml`、`docs/product/TEST-MATRIX.md`、`docs/design/HLD.md`、`docs/design/ARCHITECTURE-DECISION.md`、`docs/design/FEATURE-DESIGN-MATRIX.md` 或 Decision Brief。

复杂项目未来可扩展为异步 power mode，例如生成 `process/discussions/CP2-QUESTIONS.json/html` 或 `CP3-QUESTIONS.json/html` 让用户批量回答问题。本版本不默认生成这些文件，也不把它们作为检查点前置条件。

### 6.3 阶段委托与 LLD 问题队列

阶段委托让 `meta-pm` / `meta-se` 在本阶段直接与你沟通，减少 host-orchestrator 传话：

- `handoff/context delegated_interaction ref or STATE.current.json.active_delegation_ref` 会记录当前委托的 `phase`、`agent_role`、`agent_id/thread_id`、`handoff_path`、`status`、`started_at`、`returned_at` 和 `return_summary_path`。
- 委托期间，如果你在 host-orchestrator 线程补充需求或 HLD 意见，host-orchestrator 应把内容转给被委托 Agent，而不是自己改写需求或 HLD。
- 被委托 Agent 只能完成本阶段草案和交还摘要；CP2 / CP3 正式人工确认仍由 host-orchestrator 发起。

LLD clarification queue 用来避免多个 `meta-dev` 同时打断你：

- 队列位置是 `process/state/QUESTION-LEDGER.ndjson` 或 CP5 context queue ref。
- 每个 item 至少包含 `id`、`story_id`、`owner_agent`、`question`、`options`、`recommendation`、`pros_cons`、`impact_surface`、`blocks_lld`、`answer`、`status`；其中 `options` 必须表达 1 个推荐方案和至少 1 个备选方案。
- `blocks_lld=true` 的未回答项会阻止 CP5；非阻断 OPEN / Spike 可以进入 CP5，但必须在 Decision Brief、完整 LLD、Batch LLD Story 锚点或 Story 技术说明、DEV-LOG 中说明影响、owner 和重访条件。

合格证据包括：

- Codex `spawn_agent` / `resume_agent` / `send_input` 的返回标识
- Claude Code / OpenClaw 的 Task/Subagent 标识
- `process/state/AGENT-DISPATCH-LEDGER.ndjson` dispatch events 中非空的 `agent_id` 或 `thread_id`
- handoff `dispatch` 中的 `tool_name`、`spawned_at` / `resumed_at`、`completed_at`

只有 `to_agent: meta-dev`、`to_agent: meta-qa` 或 handoff `status=completed`，不能作为子 agent 执行证据。

如果当前运行模式无法拉起子 agent，host-orchestrator 必须阻断并说明原因。用户明确批准后，才允许 `dispatch.mode=inline-fallback`，并必须写明 `fallback_reason`、`approved_by`、`approved_at`。这种结果应表述为 host-orchestrator 代执行，不能表述为 meta-dev / meta-qa 独立完成。

用户启动正式工作流后，同工作流内默认允许 `host-orchestrator` 自动拉起所需功能 Agent。该授权只覆盖真实子 agent 调度，不覆盖 inline fallback。

### 6.4 fast-lane 快速模式

`fast-lane` 适用于低风险轻量实现、小型规则 / Skill / Agent 修改和文档更新。它可以减少需求、HLD、LLD、IMPLEMENTATION、VERIFICATION 和 release 文档厚度，发布阶段默认使用 `release_artifact_profile=minimal`，但不能跳过 CP6 / CP7、Agent Dispatch Evidence、实现执行证据摘要、验证执行证据摘要、`RELEASE-CONTEXT.yaml` 或 CP8 终验摘要。

命中架构、权限、安全、平台安装、外部接口、文件所有权冲突或多 Story 依赖时，必须升级为 `standard`。

Scenario / Architecture Gray Areas 不会把所有小修改强制升级成长流程。fast-lane 下如果 discussion log / checkpoint 不适用，自动检查会写明 N/A 原因；验证、调度证据和 CP8 终验摘要仍然保留。

### 6.5 人工确认操作

host-orchestrator 发起人工检查时会提示 checklist 文件路径，例如：

```text
请审查：process/checkpoints/CP3-HLD-REVIEW.md
自动预检结论：PASS
本轮待人工决策项：1
如果你回复 approve，表示你接受以下 1 项推荐方案，不表示授权以下 0 项禁止操作。
待人工决策清单：
| 决策 ID | 决策类型 | 待确认问题 | 推荐方案 | 备选方案 | 优劣摘要 | 影响 / 风险 |
|---|---|---|---|---|---|---|
| CP3-DQ-01 | architecture | ... | ... | ... | ... | ... |

不授权项：
- 无

该文件包含本检查点的 Entry Criteria、Checklist、Exit Criteria、Deliverables、自动预检摘要、Decision Brief、待人工决策清单和人工审查结果区。
```

审查后可以在对应 `process/checkpoints/CP*.md` 的“人工审查结果”中填写结论，也可以直接在对话中回复。Claude Code 可继续使用结构化选择，但允许 direct ask 的 subagent 必须在 frontmatter `tools:` 中显式包含 `AskUserQuestion`。Codex 只有在当前工具面明确提供可用的 `request_user_input` / 选择 UI 时才使用结构化选择；否则默认使用 exact 文本确认。系统对用户只展示三个推荐回复：`approve`、`修改: <具体修改点>`、`reject`；历史别名 `1/通过`、`2/修改: ...`、`3/不通过` 仅作为兼容解析，不作为主要提示文案。`approve` 表示接受待人工决策清单内全部推荐方案；需要调整单项时，用 `修改: <决策 ID>=<具体修改点>`。

```text
approve                  # 确认通过
修改: <具体修改点>        # 需要修改
reject                   # 不通过并回退
```

不匹配上述 exact 输入时，host-orchestrator 不得推进状态。

用户直接在对话中确认时，host-orchestrator 仍必须把结论回填到对应 `process/checkpoints/CP*.md`。

人工门禁消息本身也会被校验：必须包含 checklist 路径、自动预检结论、Context Capsule 摘要、审批者摘要、决策分层、决策收集覆盖摘要、待决策项数量、待决策表格或压缩后的 blocking / high-risk 决策摘要和三个 exact 回复。对应 checklist 的 Decision Brief 必须完整，并包含 `Decision Collection Coverage`，列出已扫描来源、候选问题数、纳入待决策数和 N/A / 缺失原因；这样你不需要再打开长文档自行查找是否还有遗漏问题。对话消息可按 `decision_brief_profile=full|compact|summary` 压缩，但不能省略整体目标、`approve` 后果、高风险 / 阻断决策、不授权项、阻塞影响和完整 checklist 路径。低风险、可回退、实现细节类事项默认归入 agent 默认处理或仅审计记录，不进入你的主确认表。真实运行、凭据、安全、外部接口、数据写入、publish、live / 交易类事项必须列为不授权项；`approve` 只接受表内推荐方案，不代表授权这些操作。

发起人工门禁前，建议先用命令生成并自检 launch message，再用 human-gate checker 强制校验 checkpoint 与发起消息：

```bash
meta-flow ask-user human-gate --checkpoint process/checkpoints/CP5-ALL-STORIES-LLD-BATCH.md --output process/checkpoints/CP5-ALL-STORIES-LLD-BATCH.launch.md --check-output
meta-flow check human-gate --checkpoint process/checkpoints/CP5-ALL-STORIES-LLD-BATCH.md --launch-message-file process/checkpoints/CP5-ALL-STORIES-LLD-BATCH.launch.md --require-launch-message
```

如果 `--require-launch-message` 未提供发起消息文件，或发起消息缺少 checklist 路径、待决策项数量、决策表或 exact 回复，检查会失败；不得先发起人工门再事后补格式。

### 6.5.1 CP8 follow-up tracking

CP8 终验会把遗留事项分流到 follow-up tracking 台账，而不是一次性预创建多个正式 CR 文件：

| 分类 | 含义 | 用户可调整内容 |
|---|---|---|
| 关闭范围 | 本轮已完成并关闭 | 关闭证据或范围描述 |
| 不授权范围 | 设计 / 文档通过不代表授权执行 | 未来授权条件、是否转正式 CR |
| 风险接受项 | 用户接受风险后放行 | 接受条件、回退条件、owner |
| 后续 CR 候选项 | 只进入台账，未启动正式 CR | 标题、owner、重访条件、是否转 Spike |
| 取消 / deferred 项 | 明确不做或延后 | 取消理由、可重启条件 |

台账路径形如 `process/changes/CR-*-FOLLOW-UP-TRACKING-YYYY-MM-DD.md`。状态取值包括 `candidate`、`active`、`blocked`、`spike_candidate`、`converted-to-spike`、`closed`、`cancelled`、`superseded`。当你决定推进某一候选项时，host-orchestrator 才创建正式 CR，并把台账状态改为 `active`。

启动候选项时，在对话中给出“启动后续 CR”、台账路径、候选编号和目标摘要：

```text
启动后续 CR
台账：process/changes/CR-019-FOLLOW-UP-TRACKING-2026-05-31.md
候选编号：CR-020
目标：推进 Windows gateway 实机部署准入
```

host-orchestrator 会执行以下动作：

| 步骤 | 动作 | 输出 |
|---|---|---|
| 1 | 读取台账候选项、`STATE.current.json.active_change`、`process/changes/CR-INDEX.json`、`process/state/CR-LEDGER.ndjson` 和活跃 CR；`CR-INDEX.yaml` 仅作 legacy read-only fallback | 判断是否已有未完成 CR |
| 2 | 执行 CR 冲突预检 | 输出影响面、重叠对象和推荐处理 |
| 3 | 无冲突或用户确认处理方式后创建正式 CR | `process/changes/CR-0xx-<slug>-YYYY-MM-DD.md` |
| 4 | 回写台账 | 状态改为 `active`，填写正式 CR 路径、当前门控、阻塞原因和下一步 |
| 5 | 进入普通 CR 流程 | 五维度影响分析、门禁、实现和验证 |

候选项没有启动时只是 backlog，不会和新的 CR 冲突。已启动但未完成的 CR 会占用执行语义：如果新 CR 与它影响同一正式文档、Story、文件 owner、外部接口、安全 / 运行授权或风险接受项，host-orchestrator 不得静默并行推进，必须发起冲突决策。可选处理包括：合并到现有 CR、保持候选等待、标记为 `blocked`、拆分无冲突子集先做、或标记为 `superseded` 并链接替代 CR。

### 6.5.2 CR lifecycle 与影响面迁移

正式 CR 的完整记录写在 `process/changes/CR-*.md`，但默认机器入口是 summary、index 和 ledger：

```bash
meta-flow cr summary --id CR-101 --project-root .
meta-flow cr index --project-root .
meta-flow cr brief --id CR-101 --project-root .
meta-flow cr brief --id CR-101 --mode enforce --project-root .
meta-flow cr check --project-root .
meta-flow cr conflicts --id CR-101 --project-root .
```

`cr brief --mode enforce` 会用 enforce 模式解析 capability refs；默认 `audit` 模式适合盘点，`enforce` 模式适合发起人工确认或阻断 deprecated / unresolved capability refs。

新 CR 应优先写结构化影响面字段：

| 字段 | 用途 |
|---|---|
| `impact_capability_refs` | capability registry refs |
| `impact_feature_refs` | Feature / bounded context refs |
| `impact_module_paths` | 源码、测试或模块路径 |
| `impact_policy_refs` | 授权、门禁或治理 policy refs |
| `impact_process_refs` | process artifact / ledger / checkpoint refs |
| `impact_runtime_refs` | runtime surface refs；只记录影响，不授权执行 |
| `impact_data_refs` | data surface refs；只记录影响，不授权写入 |

旧 `impact_surface` 仍兼容读取。迁移时运行：

```bash
meta-flow cr impact-report --project-root .
meta-flow cr impact-report --mode enforce --project-root .
```

报告会合并显式 split fields 和 legacy 推导字段，解析 capability refs，并输出 `uncategorized_legacy`。`uncategorized_legacy` 非空表示旧 `impact_surface` 中存在无法自动分类的值，应创建人工分类 follow-up candidate 或在 CR 风险中说明。项目级 legacy 分类规则可写入 `process/project/IMPACT-SURFACE-RULES.yaml`，用于补充本项目命名约定；规则修改后应重新运行 impact report、`cr check` 和相关测试。

CR036 / CR037 的当前参考状态：

| CR | 状态 | 说明 |
|---|---|---|
| `CR-036` | `closed / READY_WITH_RISK / cp8_recovery_closed` | approval-oriented human gate protocol 已完成 recovery closure；原始 planning / handoff / formal decision artifact 缺失风险保留 |
| `CR-037` | `closed / READY / cp8_closed` | impact surface split、migration report、uncategorized legacy reporting 和 configurable legacy impact classification rules 已完成 |

查看当前 CR 时，使用：

```text
当前状态
检查还有哪些 CR 需要推进，建议如何推进
```

host-orchestrator 必须输出五类清单：`active formal CR`、`blocked formal CR`、`follow-up candidate`、`spike_candidate`、`stale_status_conflicts`。`candidate` 和 `spike_candidate` 不是执行锁，但必须作为 backlog 展示；如果 `STATE.current.json.active_change` 指向已关闭 CR，或正式 active CR 没有回写台账 / `CR-INDEX.json`，必须先列为状态冲突。存在 `meta-flow check cr-tracking` 时，可用以下命令独立检查：

```bash
meta-flow check cr-tracking --project-root .
```

CP approval、CP result 通过、CR close 或状态修复后，应使用 status-sync 自动刷新 CR frontmatter、summary、CR-INDEX、`STATE.current.json` 和 lifecycle ledger，避免手工更新遗漏：

```bash
meta-flow cr status-sync --id CR-158 --status closed --readiness READY_WITH_RISK --gate-status cp8_closed --project-root .
meta-flow cr summary --id CR-158 --project-root .
meta-flow cr index --project-root .
meta-flow cr check --project-root .
```

`status-sync` 不复制 CP result 或 Decision Brief 正文到 CR；CR 正文仍只保留 checkpoint refs 和状态摘要。

### 6.6 何时显式声明 meta-self-dev

如果这次目标是优化当前元工作流本身，而不是为某个目标产物交付方案，请在第一轮明确说明：

```text
当前是在做 meta 工作流优化，请进入 meta-self-dev 模式。
```

## 7. 工作模式查看与切换

### 7.1 默认规则

- 工作流默认是 `production`
- 只有当你**明确说明**当前是在做“meta 工作流优化 / 自我开发”时，才会切换到 `meta-self-dev`
- 在 `production` 模式下，场景主体默认是目标产物，而不是当前仓库本身
- 在 `production` 模式下，不默认把交付物写入当前仓库 `delivery/`

### 7.2 如何查看当前工作模式

方法一：直接询问当前会话中的主编排器，例如：

```text
你当前在哪个工作模式？
```

方法二：查看过程文件中的 frontmatter 字段：

- `process/REQUEST.md`：查看 `engagement_mode`、`scenario_subject_type`、`scenario_subject_id`
- `docs/product/USE-CASES.md`：查看 `engagement_mode`、`scenario_subject_type`、`scenario_subject_id`

字段含义：

- `engagement_mode=production`：当前是在生产模式下为目标 Agent / Skill / Workflow 产出方案
- `engagement_mode=meta-self-dev`：当前是在优化 meta 工作流自身
- `scenario_subject_type=target-artifact`：当前场景主体是目标产物
- `scenario_subject_type=implementation-carrier`：当前场景主体是当前实现载体 / 当前仓库

### 7.3 如何切换到 meta-self-dev

在需求开始时明确说明当前目标是优化 meta 工作流本身，例如：

```text
当前是在做 meta 工作流优化，请进入 meta-self-dev 模式。
```

或：

```text
这次不是生产项目交付，而是 meta 工作流自我开发。
```

### 7.4 如何切回 production

明确说明当前回到生产模式，并指出真正服务的目标产物，例如：

```text
当前回到 production 模式，目标是为 ptm-tde 这个 agent 梳理用户场景。
```

或：

```text
这次不是优化 meta 工作流本身，而是为目标 workflow 产出正式方案。
```

### 7.5 使用建议

- 若你不特别声明，系统会继续按 `production` 处理
- 如果请求同时提到“整改当前仓库”和“目标 Agent / Skill / Workflow”，又**没有**明确声明 meta 优化，系统会优先把目标产物当作场景主体
- 想避免歧义时，建议在第一轮消息里同时写明：`engagement_mode` 意图 + 目标产物名称

## 8. 交付出口路由

meta-flow 会先判断当前任务是否为自身改进：

- `meta-self-dev` 或用户明确说明“优化 meta-flow / 当前元工作流”：交付件写当前仓库 `delivery/`
- `production` 外部项目：先扫描目标项目已有交付目录、`README.md`、`README.*` 与 `docs/` 是否有交付物、发布、构建或包结构说明
- 已有交付目录或 README/docs 存在交付约定：按目标项目约定输出，并在 HLD / Story 中引用依据
- 目标项目没有已有交付目录且 README/docs 没有交付约定：host-orchestrator / meta-se 先提出建议目录，等待用户确认后才写入

用户确认前，production 项目不得默认创建当前仓库 `delivery/` 交付件。

## 9. 验证环境准备

### 9.1 项目类型与 workflow eval

Meta Flow 不把“纯代码开发”和“工作流开发”拆成两条主流程。它通过两个字段分流：

- `engagement_mode`：只判断当前是 meta-flow 自改进还是 production 交付。
- `target_project_profile.project_kind`：判断目标项目是 `code-project`、`workflow-product`、`agentic-code-product`、`mixed` 或 `unknown`。
- `validation_target.sut_type`：判断当前 Story / 交付对象需要 `code-project`、`generated-workflow`、`prompt-skill-workflow`、`meta-flow-core-code`、`agentic-code-product` 或 `mixed` 验证。

纯代码项目默认继续跑目标项目自己的测试、构建、静态检查和质量评审。只有 generated workflow、prompt-skill、meta-flow-core-code、agentic-code-product 或 mixed 对象才默认要求 workflow eval / prompt bundle 证据。

本地 workflow eval 示例：

```bash
meta-flow eval validate --eval evals/fixtures/generated-workflow-basic/WORKFLOW-EVAL.yaml
meta-flow eval run --eval evals/fixtures/generated-workflow-basic/WORKFLOW-EVAL.yaml --out process/evals/runs/generated-workflow-basic
meta-flow eval suite-health --runs process/evals/runs --out docs/quality/EVAL-SUITE-HEALTH.md
meta-flow eval run --eval evals/fixtures/runtime-workflow-basic/WORKFLOW-EVAL.yaml --out process/evals/runs/runtime-workflow-basic
meta-flow eval runtime-run --eval evals/fixtures/runtime-workflow-basic/WORKFLOW-EVAL.yaml --sample RT-GENERIC-FULL-20260617 --platform codex --workspace evals/fixtures/runtime-workflow-basic/runtime/workspace-basic --mode collect --out process/evals/runtime-run
meta-flow eval feedback sync --eval evals/fixtures/runtime-workflow-basic/WORKFLOW-EVAL.yaml --out process/evals/feedback/raw
meta-flow eval feedback normalize --in process/evals/feedback/raw --out process/evals/feedback/run-exec
meta-flow eval feedback triage --runs process/evals/feedback/run-exec --out process/evals/feedback/triage
meta-flow eval release-check --eval evals/fixtures/runtime-workflow-basic/WORKFLOW-EVAL.yaml --runs process/evals/runs --profile release --triage process/evals/feedback/triage --format json --json-out process/evals/release-check.json
```

`runtime_artifact` grader 只读取已有运行工作区，用于检查运行态目录、STATE phase、Skill 调用链、Gate、阶段顺序、内容密度、空文件 / 模板残留、delivery、trace chain、coverage 和表格；release-grade 运行证据建议通过 `RUNTIME-SAMPLE-REGISTRY.yaml` 和 `sample_ids` 声明，支持 `partial`、`full`、`regression` profile 和 expected BLOCKED 样本。`runtime-run` 是独立 runner 入口，只生成 RUN-EXEC 和 runtime artifact manifest，支持 `dry-run`、`manual-handoff`、`collect`，不负责启动 Agent，也不替代 runtime_artifact grader 判分。现场反馈流程是 `feedback source -> normalized RUN-EXEC -> triage -> ISSUE_DRAFT / GAP / BACKLOG / ENVIRONMENT / USAGE / DUPLICATE / NO_ACTION`，不会把所有 feedback 自动升级为 ISSUE；每条 triage 结果都保留 `run_exec_id`。mutation 使用 `meta-flow eval mutate` 生成确定性负例，并为每个 mutation 声明 `expected_failing_grader`；安装映射使用 `meta-flow eval install-check` 检查 manifest、installed root 或 `PLATFORM-CONTRACTS.yaml` 下的平台发现路径。`suite-health` 输出质量趋势，`release-check` 独立输出 `PASS|PASS_WITH_RISK|BLOCKED`，可用 `--format json` 生成机器可读门禁结果。

外部 adapter（Promptfoo / DeepEval / Langfuse / Garak）默认关闭。它们可以做 case / result / trace 映射，但真实网络调用、凭据使用、trace 上传、外部模型评估、publish、live 或 production 写入必须单独授权。

进入验证阶段前，建议由人工提供或确认类似如下的环境配置：

```yaml
environment_id: local-dev
provided_by: human
targets:
  - claude
  - openclaw
approval:
  confirmed: true
notes:
  - "本轮验证只检查安装目录、文件引用和提示词加载"
```

### 9.1 治理恢复、预算与发布边界

当检查失败时，Meta Flow 先分类再决定是否恢复：仅 `CHECK_HARNESS_ERROR` 和
`DETERMINISTIC_SCHEMA_REPAIR` 可能自动恢复；`REAL_CONTENT_FAILURE`、
`PARTIAL_MUTATION`、未知失败或 facts / scope / OID / authz / profile 漂移会立即停止。
G0 / G1 / G2 的单检查恢复上限分别为 1 / 2 / 2。G2 同一 finding 最多独立 re-QA
2 次；G0 / G1 不启动独立 QA，只重跑受影响检查。

Work usage 在每个阶段写入 `process/works/<work-id>/USAGE.json`。达到任一预算的 80%
会警告；达到或超过 100%，或 token 无法测量时，当前事实仍会落账，但下一次 mutation
会被拒绝。路径统计必须看 `changed_leaf_path_count` 和 `changed_leaf_paths`；终端中折叠
显示的一条未跟踪目录只用于 UI，不能代表一个实际文件。

CP6 / CP8 前的 cost closure 必须同时满足：阶段 coverage=100%、当前 token proxy 未超过
批准上限、去重后的 gate interaction 未超过批准上限、unknown leaf paths=0。历史
CR-057 的 1,752,000 是授权 proxy ceiling，不是可直接比较的 actual token；因此迁移期
正常结论是 `PASS_WITH_BASELINE_LIMITATION`，任一硬条件失败则为 `FAIL` 并停止推进。

人工门修改后会创建新的 Decision Bundle revision，只展示 facts / scope / authz delta 和
capsule 引用。一次交互可以合并确认 CP3 + CP5，但两道门仍各有 result、evidence 与 receipt。
native CR 关闭时，status-sync 会在同一事务更新 formal CR、正文状态表、Checkpoint Index、
summary、ledger 和 formal-only index；follow-up candidate 不会伪装成正式 CR。

最后要区分“就绪”和“发布授权”：CP8 approve、native close、测试通过或 cost closure
通过都不允许自动执行 `git commit`、`git push`、publish、live、production write 或读取
凭据。每一种真实外部动作都需要单独、目标明确并绑定当前 OID/facts 的授权。

## 10. 排障

1. **提示找不到 `scripts/install.py`**：你在仓库根目录执行了 delivery-root 命令；改用 `delivery/scripts/install.py`
2. **Skill 运行时脚本未找到**：检查目标 Skill 的私有脚本是否位于 `delivery/skills/<skill>/scripts/`
3. **需要确认交付结构是否合规**：仅当当前仓库存在 `scripts/check_delivery_guardrails.py` 时，运行 `uv run --python 3.11 python scripts/check_delivery_guardrails.py`；如果是外部 production 项目且没有该脚本，外部 production 项目不得硬引用 meta-flow 源仓库路径，改按目标 README/docs 的测试、构建、安装 dry-run 或用户确认的验证命令执行。
