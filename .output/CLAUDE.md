# ptm-tde — MFQ&PPDCS 测试用例设计工具

本项目使用 **ptm-tde**（MFQ&PPDCS 测试用例设计工具），一个基于《海盗派测试分析》方法论的测试用例设计 Agent。

## Agent

主 Agent 定义位于 `agents/ptm-tde.md`，启动时请首先读取该文件获取完整指令和 12 步状态机。

## Skills

所有 Skill 定义位于 `skills/<skill-name>/SKILL.md`，共 16 个：

| 阶段 | Skills |
|------|--------|
| 输入与场景 | feature-parser, scenario-discovery |
| MFQ 分析 | m-analyzer, f-analyzer, q-analyzer |
| 整合与计划 | test-point-integrator, design-planner |
| PPDCS 用例设计 | process-design, parameter-design, data-design, combination-design, state-design |
| 验证与交付 | coverage-verifier, deliverable-renderer |
| 扩展 | change-impact-analyzer, bug-gap-analyzer |

## 工具脚本

| 脚本 | 用途 |
|------|------|
| `scripts/excel_coupling_tool.py` | Excel 耦合矩阵读写（含批注解析） |
| `scripts/mcp_query_client.py` | MCP 知识库查询客户端 |

## 工作目录约定

| 目录 | 用途 | Git 跟踪 |
|------|------|----------|
| `.input/` | 用户放置特性需求文件、耦合矩阵 Excel 等输入材料 | ❌ gitignored |
| `.output/` | 工具生成的分析中间产物和最终交付物 | ❌ gitignored |

## 权限

- **Shell**：允许（执行 Python 脚本、文件转换）
- **文件读取**：允许（`.input/` 中的需求文件、Skills、Agent 定义）
- **文件写入**：允许（`.output/` 中的分析产物和交付物）
- **Web 搜索**：允许（场景分析阶段搜索产品文档）

## 快速启动

1. 将特性需求文件放入 `.input/` 目录
2. 对话中输入"开始 MFQ 分析"或"解析特性"
3. Agent 自动按 12 步流程推进，关键节点会请求用户确认
