# Meta Flow Improvements

本目录接收来自业务项目的 MFP 改进包（`MFP-*.yaml`），并由 maintainer 导入/分类/实施。

```text
improvements/
├── inbox/     # 从全局 inbox 导入的原始 MFP
├── open/      # 已分类、尚未实现；meta-flow 源码会话在这里工作
├── closed/    # 已实现/已验证/关闭的 MFP
└── records/   # 对应 meta-flow 的 BUG / REQ / CHG 记录
```

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
mf dev improve import <project>/MFP-0001 --kind requirement --already-implemented --version 0.1.1 --commit abc123
mf dev improve update MFP-0001 --status verified --version 0.1.2 --commit def456 --note "tests passed"
```

- 已实现的 MFP：直接记录 `BUG/REQ/CHG`，MFP 移入 `closed/`。
- 未实现的 MFP：完整包留在 `open/`，由 meta-flow 源码会话按 MFP 的上下文和验收标准实施。
- 验收标准由 MFP 提出者写定，maintainer 不得改写。
