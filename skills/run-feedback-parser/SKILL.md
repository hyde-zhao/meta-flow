---
name: run-feedback-parser
description: >-
  当用户提交了测试执行反馈，需要固化为标准 RUN-EXEC 记录时使用。
  触发词包括：执行反馈、提交反馈、记录执行结果、执行记录。
  适用场景：执行反馈阶段。
argument-hint: "执行反馈的自然语言描述或结构化数据"
user-invokable: true
status: active
---

## 目标

将用户提交的执行反馈解析并固化为标准 `RUN-EXEC-*.md` 记录。

## 适用场景

- 用户提交测试执行结果、失败现象或验证回执
- 需要把自然语言反馈转成结构化运行记录

## 前置条件

- [ ] 已有对应的执行上下文或交付对象

## 必须读取的输入

- 用户执行反馈
- 相关命令、日志、截图或结构化结果
- 对应工作流 / Story / 交付对象标识（若已知）

## 知识来源

- `skills/run-feedback-parser/templates/RUN-EXEC-TEMPLATE.md`
- 用户提供的事实性执行证据

## 执行步骤

1. 提取执行环境、操作步骤、结果与证据。
2. 将每个任务结果归一为 `pass / fail / blocked / skipped`。
3. 对失败项补写 `actual_result` 与 `error_message`。
4. 按模板输出 RUN-EXEC 记录。

## 输出文件 / 输出模板

| 文件 | 路径 | 模板 |
|---|---|---|
| 执行记录 | `runs/RUN-EXEC-YYYYMMDD-NNN.md` | `skills/run-feedback-parser/templates/RUN-EXEC-TEMPLATE.md` |

## 约束

- RUN-EXEC 编号必须唯一
- 环境快照、任务结果、证据引用必填
- RUN-EXEC 记录必须复用当前私有模板

## 验收标准

- [ ] RUN-EXEC frontmatter 完整
- [ ] 每个任务有结构化结果
- [ ] 失败项含错误信息与实际结果
- [ ] 异常与偏差部分不为空

## 不适用边界

- 当前请求只要求口头总结，不需要固化为记录文件
- 没有任何可提炼的执行事实

## Gotchas

- 用户常只描述失败项，遗漏成功项；应尽量把执行全貌补齐
- 非结构化自然语言要先规范化再落表，不能原样堆进模板
