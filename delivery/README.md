# SCOPE-Pack Delivery Package

本目录是可独立交付的 SCOPE-Pack 产物包，包含：

- `agents/`：交付 Agent 定义
- `skills/`：交付 Skill 定义及其私有运行时资产
- `rules/`：平台规则文件
- `scripts/`：安装器入口
- `doc/PLATFORM-CONTRACTS.yaml`：平台安装路径契约；安装器和校验脚本以此为路径真相源

## 安装

从仓库根目录运行：

```bash
uv run --python 3.11 python delivery/scripts/install.py --platform claude-code
```

或把 `delivery/` 作为独立仓库根目录运行：

```bash
cd delivery
python scripts/install.py --platform claude-code
```

支持的平台：

- `claude-code`
- `codex`
- `openclaw`

常用示例：

```bash
uv run --python 3.11 python delivery/scripts/install.py --platform codex --scope user
uv run --python 3.11 python delivery/scripts/install.py --platform claude-code --dry-run
```

## 目录约束

1. `scripts/` 只放安装器入口：`install.py`、`install.sh`、`install.ps1`
2. Skill 私有模板、脚本、示例必须放在 `skills/<skill>/` 目录内
3. Python 缓存文件（`__pycache__/`、`*.pyc`）不得进入交付包
4. Codex Agent 与 Skill 路径分开治理：Agent 在 `.codex/agents` / `~/.codex/agents`，Skill 在 `.agents/skills` / `~/.agents/skills`
5. 安装器写入前会检查路径组件冲突；目标目录任一级被普通文件占用时会 fail fast 并提示修复

更多使用方式见 `doc/USER-MANUAL.md`。
