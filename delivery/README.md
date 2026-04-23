# SCOPE-Pack Delivery Package

本目录是可独立交付的 SCOPE-Pack 产物包，包含：

- `agents/`：交付 Agent 定义
- `skills/`：交付 Skill 定义及其私有运行时资产
- `rules/`：平台规则文件
- `scripts/`：安装器入口

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

- `copilot`
- `claude-code`
- `codex`
- `openclaw`

常用示例：

```bash
uv run --python 3.11 python delivery/scripts/install.py --platform codex --scope user
uv run --python 3.11 python delivery/scripts/install.py --platform copilot --content skills
uv run --python 3.11 python delivery/scripts/install.py --platform claude-code --dry-run
```

## 目录约束

1. `scripts/` 只放安装器入口：`install.py`、`install.sh`、`install.ps1`
2. Skill 私有模板、脚本、示例必须放在 `skills/<skill>/` 目录内
3. Python 缓存文件（`__pycache__/`、`*.pyc`）不得进入交付包

更多使用方式见 `doc/USER-MANUAL.md`。
