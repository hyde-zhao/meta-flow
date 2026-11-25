# Meta Flow Improvements（实施队列层）

本目录是 **meta-flow 源码/交付库的 MFP 实施队列**，不是提案真相。

## 两层目录

| 层 | 路径 | 角色 |
|---|---|---|
| 提案/登记 | 业务项目的 `<project>-contract/improvements/`（meta-flow 自身为 `meta-flow-contract/improvements/`） | MFP 提案、验收标准、`inbox_ref` |
| 实施队列 | 本目录 `meta-flow/improvements/` | maintainer 的 `inbox/open/closed/records` |

- 提案层回答“为什么提、验收什么”；本目录回答“怎么实施、对应哪个 BUG/REQ/CHG”。
- 源码 `BUG/REQ/CHG` 记录只放本目录 `records/`，不放契约库。
- 生产项目不需要、也不建议 clone `meta-flow-contract`；每个项目使用自己的 `<project>-contract`，MFP 通过全局 inbox 传递。

## 目录

```text
improvements/
├── inbox/     # 从全局 inbox 导入的原始 MFP
├── open/      # 已分类、尚未实现；meta-flow 源码会话在这里工作
├── closed/    # 已实现/已验证/关闭的 MFP
└── records/   # 对应 meta-flow 的 BUG / REQ / CHG 记录
```

## 传递流程

```text
业务项目 contract/improvements/（或 meta-flow-contract/improvements/）
  → mf improve submit → ~/.meta-flow/improvements/inbox/<project-id>/
  → maintainer: mf dev improve import <project-id>/MFP-xxxx
  → 本目录 inbox/ → 分类 → open/ 或 records/
  → 实施/测试 → closed/
```

- 跨机器：把已脱敏 MFP YAML 复制到目标机全局 inbox，再 `mf dev improve import`；不 clone 生产项目 contract。
- 团队集中收集：建独立 MFP inbox 仓/制品库，不要用 `meta-flow-contract` 承担跨项目 inbox。

## 分类建议

| 情况 | 记录 | 处理 |
|---|---|---|
| 现有行为错误 | `BUG-*` | 已实现则记录版本/commit 并关闭 MFP；未实现则修复 |
| 新增能力 | `REQ-*` | 已实现则记录对应版本；未实现则进入 open |
| 改变现有行为/模板兼容性 | `CHG-*` | 已实现则记录变更；未实现则进入 open |

## 命令

```bash
mf dev improve list --scope open
mf dev improve import <project>/MFP-0001 --kind bug
mf dev improve import <project>/MFP-0001 --kind requirement --already-implemented --version 1.0.0 --commit abc123
mf dev improve update MFP-0001 --status verified --version 1.0.1 --commit def456 --note "tests passed"
```

- 已实现的 MFP：直接记录 `BUG/REQ/CHG`，MFP 移入 `closed/`。
- 未实现的 MFP：完整包留在 `open/`，由 meta-flow 源码会话按 MFP 的上下文和验收标准实施。
- 验收标准由 MFP 提出者写定，maintainer 不得改写。

完整规则见 `meta-flow-contract/standards/IMPROVEMENTS.md`。
