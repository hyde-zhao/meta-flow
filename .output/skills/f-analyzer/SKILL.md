---
name: f-analyzer
description: >-
  F 分析（功能交互/耦合分析）：三源合并耦合关系（Excel 矩阵 + 场景耦合 + 代码依赖），
  构建内存图模型，生成耦合测试点。
  触发词包括：F分析、耦合分析、耦合矩阵、特性交互、功能耦合。
  适用场景：MFQ 分析的第四步（f-analysis 阶段）。
argument-hint: "可选：耦合矩阵 Excel 路径"
user-invokable: true
status: active
---

## 目标

从三个数据源收集耦合关系，构建内存图模型，分析当前特性与其他特性/模块的交互点，
生成耦合测试点。新发现的耦合点经用户确认后可回写到耦合矩阵。

## 适用范围

- 适用阶段：MFQ 分析的 f-analysis 阶段
- 输入：`.output/m-analysis/` + 耦合矩阵 Excel + 场景文档
- 输出：`.output/f-analysis/` 目录下多个文件

## 前置条件

- [ ] M 分析已完成（`.output/m-analysis/test-points.md` 存在）
- [ ] `scripts/excel_coupling_tool.py` 可用

## 三源数据模型

### 源 1：Excel 矩阵基线（最低基线）

调用 Excel 工具读取耦合矩阵：

```bash
python scripts/excel_coupling_tool.py read "<excel_path>" --output ".output/f-analysis/coupling-graph.json"
```

从中提取当前特性相关的耦合关系：

```bash
python scripts/excel_coupling_tool.py query ".output/f-analysis/coupling-graph.json" --feature "<特性名>"
```

### 源 2：场景耦合推理

从已确认的应用场景中推理功能交互：

1. 读取 `.output/scenarios/confirmed-scenarios.md`
2. 分析每个场景涉及的功能点组合
3. 如果一个场景跨越多个模块/特性，则这些模块/特性之间存在场景耦合

推理规则：
- 场景处理逻辑中依次经过的功能模块 → 顺序耦合
- 场景异常路径涉及的故障隔离 → 容错耦合
- 场景数据在模块间的传递 → 数据耦合

### 源 3：代码依赖（首版简化）

首版通过手动输入接口，由用户或开发人员提供代码级别的依赖关系：

```
请提供当前特性代码中依赖的其他特性/模块的接口列表（可选，首版非必填）：
```

## 执行流程

### 步骤 1：矩阵基线读取

1. 查找耦合矩阵 Excel 文件（用户提供或从配置获取）
2. 调用 `excel_coupling_tool.py read` 生成图模型
3. 调用 `excel_coupling_tool.py query` 提取当前特性耦合点
4. 记录基线耦合点数量

### 步骤 2：场景耦合推理

1. 读取已确认场景
2. 按推理规则生成候选耦合边
3. 标注来源为 `scenario-coupling`

### 步骤 3：代码依赖收集（可选）

1. 提示用户输入代码依赖（如有）
2. 将输入转换为耦合边
3. 标注来源为 `code-dependency`

### 步骤 4：三源合并

合并规则：
1. 以 `(source_feature, target_feature)` 为 key 去重
2. 相同功能点对的多源耦合合并，保留所有来源标注
3. 耦合强度取最高值（strong > normal > weak）

输出合并后的图模型到 `.output/f-analysis/coupling-graph.yaml`

### 步骤 5：候选耦合点确认

将新发现的耦合点（不在矩阵基线中的）呈现给用户，使用 `ask_user` 工具发起结构化确认：

```
## 新发现的耦合关系

| # | 当前特性模块 | 耦合目标 | 耦合类型 | 来源 | 描述 |
|---|------------|---------|---------|------|------|
| 1 | ... | ... | 场景耦合 | SCN-001 | ... |
| 2 | ... | ... | 代码依赖 | 用户输入 | ... |
```

**ask_user 选项**：
1. ✅ 全部确认成立 — 所有新耦合关系有效，继续生成耦合测试点，并询问是否回写矩阵
2. ✏️ 部分确认 — 请指出不成立的耦合关系编号，其余确认成立
3. ❌ 全部不成立 — 新发现的耦合关系均不成立，跳过回写，仅使用基线矩阵

### 步骤 6：耦合测试点生成

对每个已确认的耦合关系，生成 CAE 格式的耦合测试点：

| 字段 | 说明 |
|------|------|
| TP-ID | `TP-F-<源模块缩写>-<目标缩写>-NNN` |
| 所属模块 | 四级目录（归属当前特性的模块） |
| 所属子模块 | 五级目录 |
| C 条件 | 触发耦合交互的前置状态和环境条件（多个用"；"分隔） |
| A 动作 | 施加的操作（操作当前特性，触发耦合效果） |
| E 预期 | 可观测的耦合行为预期（包含对耦合目标的影响） |
| 来源 | matrix-baseline / scenario-coupling / code-dependency |
| 耦合强度 | strong / normal / weak |

### 步骤 7：可选回写

若步骤 5 中用户选择了"全部确认成立"或"部分确认"，使用 `ask_user` 询问是否回写矩阵：

**ask_user 选项**：
1. ✅ 同意回写 — 将已确认的新耦合点写入 Excel 耦合矩阵
2. ❌ 暂不回写 — 本次仅用于测试点生成，不更新矩阵基线

若用户同意回写，执行：

```bash
python scripts/excel_coupling_tool.py write "<excel_path>" --source ".output/f-analysis/new-coupling-points.json"
```

## 输出文件

| 文件 | 说明 |
|------|------|
| `.output/f-analysis/coupling-graph.json` | 完整图模型（所有源合并后） |
| `.output/f-analysis/matrix-baseline.yaml` | Excel 矩阵基线摘要 |
| `.output/f-analysis/coupling-test-points.md` | F 分析产出的耦合测试点（CAE格式，按四/五级目录分节） |
| `.output/f-analysis/new-coupling-points.json` | 新发现的耦合点（用于回写） |

**`coupling-test-points.md` 输出格式**：

```markdown
# <特性名> — F 分析耦合测试点

## <四级目录>

### <五级目录>

| TP-ID | C 条件 | A 动作 | E 预期 | 来源 | 耦合强度 |
|-------|--------|--------|--------|------|---------|
| TP-F-CFG-BCK-001 | 日志归并功能已开启；日志服务器已配置 | 删除已配置的日志服务器 | 日志归并功能不受影响；归并日志继续正常记录 | matrix-baseline | strong |
```

## 耦合分析维度

### 特性内耦合

同一特性内不同模块/子模块之间的交互：
- 配置变更传播：模块 A 的配置变更是否影响模块 B
- 数据共享：模块间共享的数据结构/缓存/数据库
- 状态依赖：模块 A 的状态变化是否影响模块 B 的行为

### 特性间耦合

当前特性与其他特性之间的交互：
- 功能依赖：当前特性依赖其他特性的功能
- 资源竞争：与其他特性共享系统资源
- 事件触发：当前特性的事件可能触发其他特性的行为

## Gotchas

- Excel 批注中混有审阅批注和格式说明，需要语义过滤
- 耦合矩阵的行列可能使用不同粒度的名称，需做名称规范化
- 场景耦合推理可能产生误报，需用户确认
- 不要漏掉"反向耦合"：A→B 存在时检查 B→A

## 验收标准

- [ ] Excel 矩阵基线已成功读取
- [ ] 场景耦合推理已执行
- [ ] 三源合并后无重复耦合边
- [ ] 新耦合点已呈现给用户并获得确认
- [ ] 耦合测试点包含完整 CAE 三字段（C/A/E 均不为空）
- [ ] 输出文件按四/五级目录分节，格式符合规范
- [ ] 输出文件写入 `.output/f-analysis/`
