---
status: candidate
version: "0.6.0"
release_artifact_profile: full
release_decision: NOT_READY
---

# 0.6.0 Feedback

## 反馈与观察

| ID | 信号 | 阈值 | 分流 |
|---|---|---|---|
| OBS-060-01 | detector 新增 unresolved/stale allowlist | 任意 1 条 | defect；阻断发布或后续 source change |
| OBS-060-02 | scope/objective amendment 出现 REPLAN/PARTIAL | 任意非 PASS terminal | 同版本 inspect/recover；禁止继续切片 |
| OBS-060-03 | 旧工具接受 V2 correction | 任意复现 | HIGH compatibility defect |
| OBS-060-04 | source/wheel/install digest 不一致 | 任意复现 | release blocker |
| OBS-060-05 | route 错误暴露 traceback | 任意复现 | defect，附结构化输入类别而非敏感路径日志 |
| OBS-060-06 | 过程/产品文件比再次超过 2 | 下一变更包 ratio > 2 | B 包 cost convergence 输入 |

## 回流边界

本文件只保存反馈入口，不启动 CR。需要后续治理的项必须在人工发布门后进入正式 follow-up tracking；B 包 0.6.1 只是用户指定候选，仍需自身 CP2 和 SemVer 门，不由本文件预授权。
