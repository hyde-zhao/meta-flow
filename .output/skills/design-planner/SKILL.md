---
name: design-planner
description: >-
  基于 PPDCS 五特征匹配为每个逻辑用例推荐测试设计方法，生成设计计划表并与用户确认。
  触发词包括：设计计划、PPDCS匹配、方法推荐、测试设计计划。
  适用场景：MFQ 分析的第七步（plan 阶段）。
argument-hint: "无需参数，自动读取 integration 目录"
user-invokable: true
status: active
---

## 目标

读取整合后的逻辑用例列表和 PPDCS 特征标注，根据 PPDCS 五特征匹配规则
为每个逻辑用例推荐最适合的测试设计方法，生成设计计划表并与用户确认。

## 理论基础

基于《海盗派测试分析: MFQ&PPDCS》的 PPDCS 框架：
- M 分析阶段已为每个子模块标注了 PPDCS 主特征
- 设计方法选择直接由 PPDCS 特征驱动：

| PPDCS 特征 | 对应设计方法 | 对应设计 Skill | 核心建模工具 |
|-----------|-------------|---------------|-------------|
| **P-Process** | 流程图法 | `process-design` | 流程图/活动图 |
| **P-Parameter** | 判定表法 | `parameter-design` | 判定表/因果图/决策树 |
| **D-Data** | 等价类+边界值法 | `data-design` | 等价类划分表 |
| **C-Combination** | 组合法 | `combination-design` | Pairwise/正交阵列 |
| **S-State** | 状态图法 | `state-design` | 状态图/转换表 |

## 适用范围

- 适用阶段：MFQ 分析的 plan 阶段
- 输入：`.output/integration/logic-cases.md` + `.output/m-analysis/ppdcs-annotation.md`
- 输出：`.output/integration/design-plan.md`

## 前置条件

- [ ] 测试点整合完成（`.output/integration/logic-cases.md` 存在）
- [ ] 测试数据已分配（`.output/integration/test-data.md` 存在）
- [ ] PPDCS 特征标注已完成（`.output/m-analysis/ppdcs-annotation.md` 存在）

## PPDCS 匹配规则

### 主规则：特征驱动匹配

```
逻辑用例 LC → 所属子模块 → 查 .output/m-analysis/ppdcs-annotation.md 获取 PPDCS 主特征
  │
  ├── P-Process   → process-design（流程图法）
  ├── P-Parameter → parameter-design（判定表法）
  ├── D-Data      → data-design（等价类+边界值法）
  ├── C-Combination → combination-design（组合法）
  └── S-State     → state-design（状态图法）
```

### 辅助规则：混合特征处理

当子模块标注了辅特征时：
1. **主特征决定主方法**
2. **辅特征生成补充验证**：在主方法用例中追加辅特征的关键数据
3. 不为辅特征单独设计用例，避免冗余

### 区分判定（当存在疑惑时）

| 疑似 | 区分问题 | 判定 |
|------|---------|------|
| Process vs State | 流程能否回退到之前步骤？ | 不能=Process，可以=State |
| Parameter vs Data | 参数间有业务规则关系？ | 有=Parameter，没有=Data |
| Data vs Combination | 因子独立验证够？ | 够=Data，不够=Combination |
| Parameter vs Combination | 规则是确定的判定逻辑？ | 确定=Parameter，需组合探索=Combination |

### 直接设计法回退

仅在以下**全部**条件满足时允许直接设计：
1. 步骤 ≤ 3 步
2. 数据项 ≤ 2 个
3. 无分支/无状态/无规则
4. **必须标注回退理由**
5. 直接设计法占比上限 < 5%

## 执行流程

### 步骤 1：加载输入

1. 读取 `.output/integration/logic-cases.md` 获取逻辑用例列表
2. 读取 `.output/m-analysis/ppdcs-annotation.md` 获取 PPDCS 特征标注
3. 建立 LC → 子模块 → PPDCS 特征的映射

### 步骤 2：逐条匹配

对每个逻辑用例：
1. 查找所属子模块的 PPDCS 主特征
2. 按主规则匹配设计方法
3. 检查辅特征，记录补充验证需求
4. 如特征标注为"混合"，分析 LC 的具体逻辑特征做二次判定

### 步骤 3：生成设计计划表

```markdown
## 设计计划表

| LC-ID | 逻辑用例标题 | PPDCS特征 | 推荐方法 | 设计Skill | 推荐理由 | 辅特征补充 |
|-------|------------|-----------|---------|-----------|---------|-----------|
| LC-001 | 日志服务器参数规则 | P-Parameter | 判定表法 | parameter-design | 多参数间存在规则（IP+端口+协议组合约束） | D-Data:端口边界值 |
| LC-002 | 日志过滤流程 | P-Process | 流程图法 | process-design | 过滤有多步骤和分支（校验→查重→保存） | — |
| LC-003 | 日志导出状态管理 | S-State | 状态图法 | state-design | 导出任务有4状态互转 | — |
| LC-004 | 日志查询条件 | D-Data | 等价类+边界值法 | data-design | 查询条件有独立取值范围 | C-Combination:多条件组合 |
| LC-005 | 日志告警级别组合 | C-Combination | 组合法 | combination-design | 5因子各4级别，需Pairwise压缩 | — |
```

### 步骤 4：统计与自检

```markdown
## 设计方法分布

| PPDCS 特征 | 设计方法 | 逻辑用例数 | 占比 |
|-----------|---------|-----------|------|
| P-Process | 流程图法 | N | X% |
| P-Parameter | 判定表法 | M | Y% |
| D-Data | 等价类+边界值法 | K | Z% |
| C-Combination | 组合法 | J | W% |
| S-State | 状态图法 | L | V% |
| — | 直接设计法 | H | U%（应<5%） |

## 自检项
- [ ] 每个 LC 都有推荐方法
- [ ] 直接设计法占比 < 5%
- [ ] PPDCS 特征与 `.output/m-analysis/ppdcs-annotation.md` 一致
```

### 步骤 5：用户确认

将设计计划表展示给用户，用户可以：
1. 全部确认
2. 修改某个 LC 的设计方法
3. 合并/拆分逻辑用例

确认后标记 `confirmed: true`。

### 步骤 6：输出

写入 `.output/integration/design-plan.md`（含 PPDCS 特征列）。

## Gotchas

- PPDCS 特征是"子模块级"标注，同一子模块的不同 LC 通常共享主特征
- 如果某 LC 的逻辑与子模块主特征不一致，以 LC 实际逻辑为准做二次判定
- 直接设计法应尽量避免，v2 有 5 种方法足以覆盖大部分场景
- 用户修改方法时需更新推荐理由

## 验收标准

- [ ] 每个逻辑用例都有 PPDCS 特征和推荐方法
- [ ] 推荐理由清晰且符合 PPDCS 匹配规则
- [ ] 直接设计法占比 < 5%
- [ ] 设计计划表包含 PPDCS 特征列
- [ ] 用户已确认设计计划
- [ ] 输出文件写入 `.output/integration/design-plan.md`
- [ ] `.output/STATE.yaml` 更新
