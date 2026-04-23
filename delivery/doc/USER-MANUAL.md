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

## 5. 排障

1. **提示找不到 `scripts/install.py`**：你在仓库根目录执行了 delivery-root 命令；改用 `delivery/scripts/install.py`
2. **Skill 运行时脚本未找到**：检查目标 Skill 的私有脚本是否位于 `delivery/skills/<skill>/scripts/`
3. **需要确认交付结构是否合规**：运行 `uv run --python 3.11 python scripts/check_delivery_guardrails.py`
