# Meta Flow

> AI 项目操作系统：三个角色、契约库与交付库、规格驱动交付。

## 状态

v1 设计阶段。当前仓库是 Meta Flow v1 的新仓，旧的 v0.x 工作流实现将打 tag 归档。

- 设计文档：[DESIGN.md](DESIGN.md)
- CLI 名称：`mf`
- 三个角色：`meta-maintainer`、`meta-manager`、`meta-worker`

## 核心模型

```text
workspace/
├── contracts/     # 契约库：规范、需求、路标、计划、状态、验证、架构与端到端契约
└── deliveries/    # 交付库集合：源码、发布件、发布说明、用户手册
```

- 契约库是唯一公共真相源和跨库集成点。
- 交付库是完整交付单元，交付库之间不直接引用。
- manager 在契约库管理项目；worker 在交付库执行任务卡；maintainer 维护工作区和工具。
- 版本双轨：路标 `R{n}` ↔ 项目版本 `n.x.y`，交付物使用 SemVer。

## 下一步

R0 骨架：CLI 骨架、三角色定义、两仓初始化、角色路由、玩具项目端到端闭环。
