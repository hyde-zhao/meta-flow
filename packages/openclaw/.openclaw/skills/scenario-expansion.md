---
name: scenario-expansion
description: >-
  当结构化需求已就绪，需要为每条需求展开为具体测试场景时使用。
  触发词包括：展开场景、生成场景、测试场景、场景扩展。
  适用场景：元工作流需求分析阶段，需求提取之后。
argument-hint: "REQUIREMENTS.md 路径"
user-invokable: true
status: draft
---

## 目标

为 `REQUIREMENTS.md` 中的每条需求生成对应的测试场景（正向、负向、边界），输出为 `SCENARIOS.yaml` 和 `TEST-MATRIX.md`。

## 适用范围

- 适用阶段：需求分析阶段，在 requirement-extraction 之后
- 输入：`REQUIREMENTS.md`
- 输出：`SCENARIOS.yaml`、`TEST-MATRIX.md`

## 前置条件

- [ ] `REQUIREMENTS.md` 已生成且 `status` 不为空
- [ ] 需求条目均有 REQ-ID 和优先级

## 执行约束

- 场景编号使用 `TC-NNN`，三位数字递增
- 每个场景必须 `linked_requirements` 回链到至少一条 REQ
- 场景类型（type）只允许：`positive`、`negative`、`edge-case`、`precheck`
- 高优先级需求展开规则：

  | 需求优先级 | 最低场景要求 |
  |-----------|------------|
  | HIGH | ≥ 1 positive + ≥ 1 negative |
  | MEDIUM | ≥ 1 positive |
  | LOW | ≥ 1 positive |

- 每个场景必须填写 `preconditions`、`test_action`、`expected_result`、`evidence_type`
- `expected_result` 必须是可用自动化或人工判定的明确结果（如返回码、日志关键字、状态值）

## 场景种类指导

| 类型 | 目标 | 示例 |
|------|------|------|
| positive | 验证功能正常放行/生效 | ACL 规则允许的流量可正常通过 |
| negative | 验证功能正确拒绝/阻断 | ACL 规则拒绝的流量被阻断且日志记录 |
| edge-case | 验证边界条件处理 | 同时多条 ACL 匹配时优先级是否正确 |
| precheck | 验证执行前置条件 | 设备 SSH 可达、管理权限可用 |

## 测试矩阵生成规则

- 行 = REQ-ID，列 = TC-ID
- 交叉点标记覆盖关系（✅ 或空）
- 统计覆盖率 = 已覆盖需求数 / 总需求数
- 列出未覆盖需求清单

## Gotchas

- 不要只生成"能通过"的正向场景而忽略负向场景——防火墙测试中，验证阻断是否生效往往比验证放行更重要
- 边界场景容易被遗漏，如：规则匹配优先级冲突、会话超时后的行为、并发连接场景
- precheck 类场景虽然不是核心测试，但缺少它会导致执行阶段出现大量 env-issue

## 验收标准

- 每条 HIGH 级 REQ 至少有 1 positive + 1 negative 场景
- 全部场景都有 `linked_requirements` 回链
- `TEST-MATRIX.md` 的覆盖率统计正确
- 未覆盖需求清单无遗漏
- `SCENARIOS.yaml` 格式符合模板规范
