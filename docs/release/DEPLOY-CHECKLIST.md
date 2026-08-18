---
status: in_progress
version: "0.6.0-candidate"
release_artifact_profile: full
release_decision: NOT_READY
---

# 0.6.0 Deploy Checklist

## 发布前输入

| 输入 | 状态 | 证据 |
|---|---|---|
| Release Context Capsule | PASS | `process/release/RELEASE-CONTEXT.yaml` |
| Work objective/scope | PASS | `process/works/STAB-055-001/WORK.yaml`、R3/R4 receipt |
| Test Report | PASS | `docs/quality/TEST-REPORT.md`；qualification 后完整回归 0 failed |
| Review | NOT_READY | `docs/quality/REVIEW.md` |
| BLOCKER / HIGH | 0 open product HIGH；1 release blocker | clean provider/artifact evidence |

## 候选与资格化

| 检查 | 当前状态 | 放行条件 |
|---|---|---|
| 版本三真相 | PASS | pyproject、runtime version、uv.lock 均为 0.6.0 |
| 双仓 source freeze preflight | PASS | 前置提交已成对推送且 clean/synced；最终 product OID 在本次 evidence commit 后捕获并用于 artifact qualification |
| canonical quality/release docs tracking | PASS | 六个 canonical 文件不再被 `.gitignore` 吞掉；未使用 `git add -f` |
| detector full/incremental gate | PASS | full 407/407 classified、0 ambiguous；incremental dynamic 45/45 allowlisted、0 unresolved、findings=[] |
| provider qualification | PENDING | clean checkout，receipt + digest sidecar 原子生成 |
| 完整回归 | PASS | 2635 passed、716 subtests passed、0 failed、20 warnings |
| source/cache hygiene | PENDING | source digest 明确排除 cache/build/generated，tracked-generated 阻断 |
| wheel/sdist | PENDING | 隔离临时输出，版本/内容/digest 全匹配 |
| isolated canary | PENDING | checkout import=false、installed payload/receipt/policy 全匹配 |

## 平台与安装验证

| 平台 | 场景 | 状态 | 说明 |
|---|---|---|---|
| Codex / Claude | project install dry-run | PENDING | 不执行真实安装；只验证 canonical platform paths 与 payload |
| Linux Python 3.11+ | clean wheel install / lifecycle canary | PENDING | 临时 venv，不写外部 consumer |
| 0.5.3 → 0.6.0 | 整体升级 | PASS（设计）/ PENDING（artifact） | writer/inspector/detector 必须同版本，不支持混用 |
| rollback | pre/post V2 correction | PASS（设计）/ PENDING（artifact） | 见 `docs/release/ROLLBACK.md` |

## 不授权项

双仓前置 commit/push 已执行；本轮允许完成发布事实 evidence commit/push、隔离 artifact build、provider qualification 与 canary。仍不授权 tag、GitHub Release、PyPI、真实安装、外部 consumer mutation、凭据读取或生产写；CP8 readiness 也不等于 `RELEASED`。
