# SCOPE-Pack 元工作流

> 通用 Agent/Skill 工作流产物工厂 — 从需求到交付的全流程编排。

## 目录结构

| 目录 | 用途 |
|------|------|
| `.agents/agents/` | 元工作流 Agent 定义（meta-po/pm/se/dev/qa/doc） |
| `.agents/skills/` | 元工作流 Skill 定义（SCOPE-Pack 内置） |
| `.github/agents/` | Copilot CLI 入口（元工作流 Agent） |
| `.input/` | 只读输入目录（用户提供的原始材料） |
| `.output/` | **统一输出目录** — 工作流状态 + 产物文件 |
| `docs/` | 参考文档和源材料 |
| `scripts/` | 元工作流工具脚本 |
| `packages/` | 元工作流自身的平台安装包 |

## 输出隔离原则

所有由元工作流产生的产物（Agent、Skill、Tool、文档、安装包）统一输出到 `.output/` 目录：

```
.output/
├── agents/              # 产物 Agent 文件
├── skills/              # 产物 Skill 文件
├── scripts/             # 产物工具脚本
├── .github/agents/      # 产物 Copilot CLI 入口
├── packages/            # 产物平台安装包
├── README.md            # 产物 README
├── USER-MANUAL.md       # 产物用户手册
├── STATE.md             # 工作流运行时状态
├── HLD.md               # 高层设计（经人工确认后进入 Story 拆解）
├── stories/             # Story 卡片与 Story 级 LLD
└── ...                  # 其他工作流中间文件
```

测试时可在 `.output/` 目录中独立启动 Agent 加载产物文件：

```bash
cd .output && copilot @ptm-tde
```

## 开发节奏

1. `meta-pm` 输出需求与场景
2. `meta-se` 输出并提交 `HLD.md`
3. 用户确认 HLD 后，`meta-se` 拆解 Story 与开发计划
4. `meta-dev` 对每个 Story 先输出 `STORY-{id}-LLD.md`，确认后再实现
5. `meta-qa` 验证并打包，`meta-doc` 输出交付文档

## 快速开始

```
@meta-po 开始
```

详细使用说明见 `.output/README.md`（产物文档）和 `.output/USER-MANUAL.md`。
