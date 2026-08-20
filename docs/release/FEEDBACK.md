---
status: release_candidate
version: "0.6.3"
base_version: "0.6.2"
release_artifact_profile: full
release_decision: NOT_READY
---

# Meta Flow 0.6.3 Feedback

## 发布后观察信号

| ID | 信号 | 阈值 | 分流 |
|---|---|---|---|
| OBS-074-01 | native 与 registered legacy consumer 得到不同 partition digest，legacy bytes 被改写，或 unregistered contamination 未阻断 | 任意复现 | formal truth blocker |
| OBS-074-02 | same-tuple `cr status-sync` 发生 mutation，或 registry/OID/preimage drift 后仍写入 | 任意复现 | status-sync atomicity blocker |
| OBS-074-03 | State/CURRENT 五字段继续漂移，或 projection-correct 接受 partial/corrupt/ambiguous lineage | 任意复现 | state lineage HIGH / rollback assessment |
| OBS-074-04 | Work status-transition 的 plan 非零写、target set 漂移、authorization replay 再次写入，或非零 mutation 被报告为 `BLOCKED/0` | 任意复现 | lifecycle transaction blocker |
| OBS-074-05 | `PARTIAL` / child failure 无法 inspect/recover，或 committed parent 被 child rollback | 任意复现 | recovery blocker |
| OBS-074-06 | routine direct G0/G1 被错误要求 HANDOFF，或 G2 functional-agent / legacy CP pause/block 漏掉 HANDOFF | 任意复现 | route-policy HIGH |
| OBS-074-07 | direct HANDOFF writer 绕过 status-transition，或 caller boolean override 改写 canonical policy | 任意复现 | authorization/ownership blocker |
| OBS-074-08 | post-close 缺 authoritative child report 仍 PASS，未知 capability alias 被本地推断为 resolved，或 release context 扩大空批准范围 | 任意复现 | post-close/capability blocker |
| OBS-074-09 | `scope_authz_consistency=NEEDS_REVIEW` 被消音、并入 post-close finding 或误写为已全绿 | 任意复现 | `R-074-SCOPE-AUTHZ-EVIDENCE-KIND` |
| OBS-074-10 | 72 条 legacy callable mutation routes 被宣传成 V3 合同已完成，或 provider admission 与 inventory 不一致 | 任意复现 | `R-074-LEGACY-PUBLIC-ROUTES` |
| OBS-074-11 | 在 shared primitive 收敛前出现第五个 transaction kernel，或继续复制 manifest/rollback/recovery 语义 | 任意新增 | `R-074-WB-STRUCTURE` / P6 hard follow-up |
| OBS-074-12 | 0.6.3 候选或发布过程中运行 full suite，或用 full 替代失效层的有界重验 | 任意发生 | no-full policy violation |
| OBS-074-13 | qualification/build/canary/CP8 重复、乱序或被 source fixture 冒充 | 任意发生 | release-order blocker |
| OBS-074-14 | quant-lab replay 在 0.6.3 发布前被恢复为硬门，或在无独立授权时被读取、运行、安装或写入 | 任意发生 | external authorization blocker |

## 观察窗口

| 窗口 | 观察内容 | 退出条件 |
|---|---|---|
| 发布候选阶段 | risk review、版本一致性、qualification/build/canary/CP8 顺序与 no-full policy | 所有发布门有 current receipt；当前尚未达到 |
| 发布后首个 lifecycle | formal partition、same-tuple NO_CHANGE、State/CURRENT、status-transition 与 HANDOFF policy | 无 OBS-074-01..13；无 unresolved transaction |
| 发布后首个 legacy consumer | registered legacy immutable、unregistered contamination fail closed、legacy route 分类可见 | partition/inventory digest 一致，legacy bytes mutation=0 |
| 发布后 quant-lab acceptance | installed 0.6.3 在独立授权下执行 victim journeys | 形成独立 result 与 evidence；结果不回填为发布前证据 |

## Quant-lab 发布后 acceptance

quant-lab CR-175 replay 已明确调整为 `DEFERRED_AFTER_RELEASE_INDEPENDENT_FOLLOW_UP`。它不是 0.6.3 qualification、canary、CP8 或 publication 的前置条件，也不能由本发布文档授权。

启动该 acceptance 前必须同时满足：

- 0.6.3 已真实发布，并可取得 exact installed artifact、receipt、sidecar 与远端 digest；release candidate 或 source checkout 不满足条件。
- quant-lab 的 exact project root、读取范围、运行范围、安装范围和任何写入分别获得独立 typed authorization；默认不读取、不运行、不安装、不写入。
- 使用独立 Work/CR 或 follow-up tracking 记录目标、禁止项、source/artifact identity、consumer environment 与证据路径。
- J1 formal partition、J2 repairable successor lineage、J3 route-aware HANDOFF 必须逐项映射到 quant-lab 的真实受害者旅程；Meta Flow fixture PASS 不能冒充 victim PASS。
- 结果只使用 `PASS`、`PASS_WITH_RISK`、`BLOCKED`、`NEEDS_REWORK` 或适用的 typed decision；失败先分流，不自动回滚 Meta Flow 0.6.3。

该 follow-up 的成功可以补充 installed consumer adoption evidence；失败是否影响 0.6.3，需要根据是否复现通用 provider defect 单独判断，不能预设为发布失败或无影响。

## 反馈分类与路由

| 类别 | 示例 | 下一步 |
|---|---|---|
| 产品缺陷 | partition、lineage、transaction、HANDOFF 或 post-close 违约 | 起草 ISSUE，按严重度决定修复版或回滚 |
| 安全/权限缺陷 | scope/authz 被消音、未授权外部访问、authorization replay | 立即停止相关 mutation，保留证据并升级安全审查 |
| 兼容性缺陷 | 0.6.2 项目升级后合法历史记录被阻断 | 记录 exact project/artifact/route，构建最小回归集 |
| 结构性技术债 | 第五个 kernel、重复 recovery/rollback 语义 | 路由到 P6 Transaction Primitive Convergence |
| Legacy contract backlog | legacy route 缺 owner/path/auth/L3 contract | 路由到 public operation convergence，不改写为 CR-074 blocker |
| 外部 adoption | quant-lab installed acceptance | 进入独立 follow-up tracking；不回写为 0.6.3 发布前门禁 |
| 新需求 | 新 route、runtime、trading、生产或外部集成 | 新建需求/CR 候选，重新做 scope 与 authorization |

## 记录格式

反馈至少记录版本与 artifact digest、命令 identity、project/process route mode、source/environment fingerprint、transaction/authorization ID、mutation count、expected/actual typed decision、最小复现和脱敏证据路径。不得记录 token、凭据、secret、cookie、客户数据或未脱敏生产日志。

本文件只定义反馈入口，不自动创建 ISSUE、Work 或 CR，也不授权 Git、发布、外部项目、runtime、生产、交易或凭据操作。需要正式跟踪的项目必须由 Host Orchestrator 写入独立 follow-up tracking 台账。
