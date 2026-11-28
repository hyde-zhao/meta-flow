---
name: release
roles: [manager]
trigger: 阶段 P5/版本发布
inputs: [版本目标, REQ/BUG/MFP 状态, VR]
outputs: [发布清单/说明/手册/smoke 记录]
read: [release/, requirements/, verification/]
write: [release/, docs/]
budget: 按 manager 预算
---

# SKILL release

> 适用角色: manager
> 触发: P5 发布
> 输出: 发布证据与用户门禁

## 步骤

1. 核对 REQ/BUG/MFP 状态与证据完整；未关闭项列出风险。
2. `mf release freeze` 冻结清单；更新 RELEASE-NOTES/用户手册。
3. 安装/升级 smoke（新环境安装、`mf doctor`、hook、角色）；记录命令与结果。
4. 用户 P5 门禁：`mf phase exit --approved-by user`。
5. 发布后归档与复盘；tag/push 需用户授权。

## 门禁

- 发布门禁前不得打 tag/发布；BLOCKED 不算完成。
- 版本规则与 ARCHITECTURE 一致；MAJOR/MINOR/PATCH 按变更性质。

## 失败/升级

- 证据缺失 → 回补阶段任务；用户拒批 → 记录整改。
- 下一责任: maintainer（全局部署）/用户（门禁）。

## 证据

- RELEASE 清单、smoke 输出、阶段退出记录、ledger。

## 反模式

- 未过用户门禁就发布；跳过安装/升级 smoke；发布后补标准。
