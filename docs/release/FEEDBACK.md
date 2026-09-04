---
status: release_candidate
version: "0.6.5"
---

# Meta Flow 0.6.5 Feedback

## 发布后观察

| ID | 信号 | 阈值 | 处理 |
|---|---|---:|---|
| OBS-065-01 | 高风险在无用户选择时进入 G3 | 任意一次 | HIGH，停止新 G3 route |
| OBS-065-02 | V1 G2 被解释为新轻量 G2 | 任意一次 | BLOCKER，回滚评估 |
| OBS-065-03 | config/API 自报选择绕过 G3 binding | 任意一次 | security blocker |
| OBS-065-04 | 架构 delta 被自动升级 G3 或无复核放行 | 任意一次 | route defect |
| OBS-065-05 | consent trigger 自动代表用户同意 | 任意一次 | authorization blocker |
| OBS-065-06 | 旧 approval 批准新 result head | 任意一次 | state projection blocker |
| OBS-065-07 | CP6/CP7 缺失时前沿直接进入 CP8 | 任意一次 | lifecycle blocker |
| OBS-065-08 | publication RiskGrade 出现 G3 | 任意一次 | namespace regression |
| OBS-065-09 | provider activation receipt 非 CURRENT | 任意一次 | 停止安装/发布 |
| OBS-065-10 | GitHub 四项资产摘要与本地 canary 资产不一致 | 任意一次 | publication failure |

问题反馈应包含版本、安装资产 SHA-256、命令、最小复现和是否从 checkout import；不得包含 token、凭据或未脱敏生产数据。
