# SCOPE-Pack USER-MANUAL

## 1. 安装前准备

- Python 入口统一使用 `uv run --python 3.11 python ...`
- 若从源码仓库根目录执行，安装器路径是 `delivery/scripts/install.py`
- 若 `delivery/` 已作为独立仓库分发，安装器路径是 `scripts/install.py`

## 2. 常用安装命令

从仓库根目录执行：

```bash
uv run --python 3.11 python delivery/scripts/install.py --platform claude-code
uv run --python 3.11 python delivery/scripts/install.py --platform codex --project-dir /path/to/project
uv run --python 3.11 python delivery/scripts/install.py --platform copilot --scope user --content skills
uv run --python 3.11 python delivery/scripts/install.py --platform openclaw --dry-run
```

从 `delivery/` 目录执行：

```bash
cd delivery
python scripts/install.py --platform claude-code
python scripts/install.py --platform codex --scope user
```

包装脚本：

```powershell
scripts\install.ps1 --platform codex --dry-run
```

```bash
bash scripts/install.sh --platform claude-code --dry-run
```

## 3. 安装内容

- `agents`：平台 Agent 定义
- `skills`：Skill 定义与 Skill 私有运行时资产
- `rules`：平台规则入口

可通过 `--content agents|skills|rules|all` 控制安装范围。

## 4. DryRun 与卸载

```bash
uv run --python 3.11 python delivery/scripts/install.py --platform claude-code --dry-run
uv run --python 3.11 python delivery/scripts/install.py --platform codex --scope user --uninstall
```

## 5. 工作模式查看与切换

### 5.1 默认规则

- 工作流默认是 `production`
- 只有当你**明确说明**当前是在做“meta 工作流优化 / 自我开发”时，才会切换到 `meta-self-dev`
- 在 `production` 模式下，场景主体默认是目标产物，而不是当前仓库本身

### 5.2 如何查看当前工作模式

方法一：直接询问当前会话中的主编排器，例如：

```text
你当前在哪个工作模式？
```

方法二：查看过程文件中的 frontmatter 字段：

- `process/REQUEST.md`：查看 `engagement_mode`、`scenario_subject_type`、`scenario_subject_id`
- `process/USE-CASES.md`：查看 `engagement_mode`、`scenario_subject_type`、`scenario_subject_id`

字段含义：

- `engagement_mode=production`：当前是在生产模式下为目标 Agent / Skill / Workflow 产出方案
- `engagement_mode=meta-self-dev`：当前是在优化 meta 工作流自身
- `scenario_subject_type=target-artifact`：当前场景主体是目标产物
- `scenario_subject_type=implementation-carrier`：当前场景主体是当前实现载体 / 当前仓库

### 5.3 如何切换到 meta-self-dev

在需求开始时明确说明当前目标是优化 meta 工作流本身，例如：

```text
当前是在做 meta 工作流优化，请进入 meta-self-dev 模式。
```

或：

```text
这次不是生产项目交付，而是 meta 工作流自我开发。
```

### 5.4 如何切回 production

明确说明当前回到生产模式，并指出真正服务的目标产物，例如：

```text
当前回到 production 模式，目标是为 ptm-tde 这个 agent 梳理用户场景。
```

或：

```text
这次不是优化 meta 工作流本身，而是为目标 workflow 产出正式方案。
```

### 5.5 使用建议

- 若你不特别声明，系统会继续按 `production` 处理
- 如果请求同时提到“整改当前仓库”和“目标 Agent / Skill / Workflow”，又**没有**明确声明 meta 优化，系统会优先把目标产物当作场景主体
- 想避免歧义时，建议在第一轮消息里同时写明：`engagement_mode` 意图 + 目标产物名称

## 6. 排障

1. **提示找不到 `scripts/install.py`**：你在仓库根目录执行了 delivery-root 命令；改用 `delivery/scripts/install.py`
2. **Skill 运行时脚本未找到**：检查目标 Skill 的私有脚本是否位于 `delivery/skills/<skill>/scripts/`
3. **需要确认交付结构是否合规**：运行 `uv run --python 3.11 python scripts/check_delivery_guardrails.py`
