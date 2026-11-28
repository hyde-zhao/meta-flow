# WORK-PACKAGE {id}

```yaml
id: R{n}-P3-WP-{subproject}-{seq}
roadmap: R{n}
phase: P3
subproject: {subproject}
design_package: DP-{id}|null
status: planned|in_progress|waiting_decision|verifying|done|accepted|blocked
scope:
  requirements: [REQ-xxxx]
  mfps: [MFP-<project>-<seq>]
  specs: [SPEC-xxx]
context:
  design_refs: [architecture/DESIGN.md]
  interface_refs: [architecture/MODULES.md#M4]
  allowed_paths: [src/**, tests/**]
  must_read: [SPEC-xxx, DP-xx]
  budget: {files: 60, bytes: 1048576}
tasks:
  - id: T1
    type: implement|verify|decision|spike|bugfix|document
    goal: ...
    context: []
    acceptance: [{id: A1, method: automated|artifact|demonstration, expect: ...}]
    verification: none|peer|independent|designer|manager
    decision: null
  - id: T2
    type: decision
    decision:
      problem: ...
      impact: ...
      options: [{id: A, pros: ..., cons: ...}]
      recommendation: A
      level: D0|D1|D2|D3
      owner: user|manager
verification:
  final: subproject-worker
  cross_project: designer|null
  acceptance: manager
audit:
  created_by: manager
  created_at: ...
```

## 规则（CHG-0005）

1. 每子项目每设计周期一个工作包；任务只在需要人工决策/必要独立验证时拆分。
2. 默认不按任务生成 review 任务；工作包完成做子项目最终验证，再由 manager 验收。
3. 决策点暂停工作包；决策结果写回设计/规格/工作包。
4. 验证失败：reviewer 用人话写原因/风险/影响/期望；实现 worker 直接返工。
5. 命令：`mf work create/task/start/decision/verify/accept/show/list`。
