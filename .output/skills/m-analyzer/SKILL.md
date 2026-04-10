---
name: m-analyzer
description: >-
  M 分析（MD: Model-based Discrete Function）：按四/五级目录拆分单功能，
  为每个单功能标注 PPDCS 特征（Process/Parameter/Data/Combination/State），
  生成覆盖需求和场景的测试点。
  触发词包括：M分析、功能分析、模块分析、测试点分析、PPDCS标注。
  适用场景：MFQ 分析的第三步（m-analysis 阶段）。
argument-hint: "无需参数，自动读取 feature-input 目录"
user-invokable: true
status: active
---

## 目标

基于 feature-parser 输出的结构化需求和已确认的三~五级目录，
逐模块/子模块分析功能点，**为每个单功能标注 PPDCS 主特征**，
生成测试点，确保所有需求和用户场景的功能被完整覆盖。

## 理论基础

M 分析即 MFQ 框架中的 **MD（Model-based Discrete Function）**：
> 将被测对象细分为可独立测试的单功能，使用 PPDCS 模型分析每个单功能的内在逻辑特征。

**PPDCS 五特征**（来源：《海盗派测试分析》P183-199）：

| 特征 | 识别条件 | 对应建模技术 |
|------|---------|-------------|
| **P-Process** | 需求有业务流程含义，多步骤有序约束 | 流程图/活动图 |
| **P-Parameter** | 参数参与业务规则判定，输入组合影响输出 | 判定表/因果图 |
| **D-Data** | 数据有明确取值范围，各数据项相对独立 | 等价类 + 边界值 |
| **C-Combination** | 多因子多状态，全组合不可枚举 | Pairwise/正交 |
| **S-State** | 对象有多状态可互转，存在状态生命周期 | 状态图/转换表 |

**区分规则**：
- Process vs State → 流程能否回退？不能 = Process，可以 = State
- Parameter vs Data → 参数间有业务规则？有 = Parameter，无/独立 = Data
- Data vs Combination → 因子独立验证够？够 = Data，需组合 = Combination

## 适用范围

- 适用阶段：MFQ 分析的 m-analysis 阶段
- 输入：`.output/feature-input/` + `.output/scenarios/`
- 输出：`.output/m-analysis/test-points.md` + `.output/m-analysis/ppdcs-annotation.md`

## 前置条件

- [ ] `.output/feature-input/raw-requirements.md` 存在
- [ ] `.output/feature-input/directory-structure.md` 存在（用户已确认）
- [ ] `.output/scenarios/confirmed-scenarios.md` 存在（用户已确认）

## 执行流程

### 步骤 1：加载输入

1. 读取 `.output/feature-input/raw-requirements.md` 获取需求条目列表
2. 读取 `.output/feature-input/directory-structure.md` 获取目录层级
3. 读取 `.output/scenarios/confirmed-scenarios.md` 获取应用场景

### 步骤 2：逐模块功能分析

按四级目录（模块）→五级目录（子模块）的顺序，依次分析：

对每个子模块：
1. 提取该子模块关联的需求条目
2. 提取该子模块关联的应用场景
3. 分析功能点：该子模块需要实现哪些功能
4. 对每个功能点，考虑以下维度生成测试点：
   - **正常功能**：功能按预期工作
   - **参数边界**：输入参数的有效/无效边界
   - **异常处理**：错误输入、异常条件下的行为
   - **默认值**：默认配置下的行为
   - **交互影响**：与同模块内其他功能的交互

### 步骤 3：PPDCS 特征标注（v2 新增）

**对每个五级目录节点（单功能），分析其内在逻辑特征并标注 PPDCS 主特征**：

```
对每个单功能：
  1. 分析需求描述中的逻辑结构
  2. 按以下优先级逐条判断：
     ├── 是否涉及多状态互转（可回退）？   → 标注 S-State
     ├── 是否有多步骤有序业务流程？         → 标注 P-Process
     ├── 参数间是否存在规则依赖？           → 标注 P-Parameter
     ├── 因子是否过多需组合压缩？           → 标注 C-Combination
     └── 数据是否独立可单独验证？           → 标注 D-Data
  3. 如有混合特征，标注主特征 + 辅特征
  4. 记录判定依据
```

### 步骤 4：测试点标注

每个测试点必须标注以下信息：

| 字段 | 说明 | 示例 |
|------|------|------|
| TP-ID | 测试点编号 | `TP-M-<模块缩写>-<子模块缩写>-NNN` |
| 所属模块 | 四级目录名称 | 配置管理 |
| 所属子模块 | 五级目录名称 | 日志服务器配置 |
| 测试点描述 | 具体的测试验证内容 | 验证配置最大日志服务器数量时系统行为 |
| 关联需求 | 需求编号列表 | SR-001, SR-003 |
| 关联场景 | 场景编号列表 | SCN-XXX-001 |
| 来源 | M 分析 | M-analysis |
| 测试类型建议 | 功能/边界/异常/默认 | 边界 |

### 步骤 5：覆盖初检

1. **需求覆盖**：检查每条 SR 至少关联 1 个测试点
2. **场景覆盖**：检查每个场景的关键功能点至少关联 1 个测试点
3. **输出未覆盖项**：标记为 `⚠️ 待补充`

### 步骤 6：输出

写入两个文件：

**`.output/m-analysis/test-points.md`**（与 v1 格式一致）

**`.output/m-analysis/ppdcs-annotation.md`**（v2 新增）：

```markdown
# <特性名> — PPDCS 特征标注表

## 统计

| PPDCS 特征 | 子模块数 | 占比 |
|-----------|---------|------|
| P-Process | N | X% |
| P-Parameter | M | Y% |
| D-Data | K | Z% |
| C-Combination | J | W% |
| S-State | L | V% |
| 混合特征 | H | U% |

## 标注详表

| 子模块 | PPDCS 主特征 | 辅特征 | 判定依据 |
|--------|-------------|--------|---------|
| 日志服务器配置 | P-Parameter | D-Data | 多参数规则判定（IP/端口/协议组合影响结果） |
| 日志过滤流程 | P-Process | — | 过滤有明确步骤和分支（格式校验→名称检查→保存） |
| 日志导出状态 | S-State | — | 导出任务有状态变迁（未启动→导出中→完成/失败） |
| 日志查询 | D-Data | C-Combination | 查询条件有取值范围，多条件需组合 |
```

## 测试点生成原则

1. **一个功能点至少一个测试点**
2. **正面优先**：先覆盖正常功能，再覆盖异常和边界
3. **粒度适中**：测试点应可独立验证
4. **可追溯**：每个测试点必须关联至少一条需求
5. **不预设设计方法**：M 分析只关注"测什么"和"什么特征"，不关注"怎么测"

## Gotchas

- 需求描述中隐含的功能也需要提取测试点
- 同一需求可能跨多个子模块
- 不要在 M 分析阶段引入耦合测试点（F 分析职责）
- PPDCS 标注时注意区分 Process 和 State 的双向性差异
- 一个子模块可能有混合特征，此时标注主特征+辅特征

## 验收标准

- [ ] 每个五级目录（子模块）至少有 1 个测试点
- [ ] 每个测试点包含完整的 8 字段标注
- [ ] **每个五级目录节点均有 PPDCS 主特征标注和判定依据**
- [ ] 需求覆盖初检已执行，未覆盖项已标记
- [ ] 输出 `test-points.md` 和 `ppdcs-annotation.md`
- [ ] `.output/STATE.yaml` 更新为 m-analysis 完成
