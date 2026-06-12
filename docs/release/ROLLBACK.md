---
project_id: "meta-flow"
release_scope: "workflow-eval-governance"
created_at: "2026-06-11T19:50:20+08:00"
---

# Rollback

## 修订记录

| 版本 | 日期 | 修订人 | 变更要点 |
|---|---|---|---|
| 1.0 | 2026-06-11 | host-orchestrator | 新增 workflow eval governance 回滚方案 |

## 回滚范围

如需回滚，撤销以下对象：

- `meta_flow/evals/*`
- `meta_flow/cli.py` 中 `eval` 子命令
- `evals/contracts/*`
- `evals/fixtures/generated-workflow-basic/*`
- `evals/adapters/ADAPTERS.md`
- `evals/ci/CI-POLICY.md`
- workflow eval governance 相关 docs / rules / template 修改

## 回滚验证

- `meta-flow --help` 不再展示 eval 子命令。
- `meta-flow check cr-tracking --project-root .` 仍 PASS。
- guardrail 无新增错误。
