---
name: run-feedback-parser
description: >-
  当用户提交了测试执行反馈，需要固化为标准 RUN-EXEC 记录时使用。
  触发词包括：执行反馈、提交反馈、记录执行结果、执行记录。
  适用场景：执行反馈阶段。
argument-hint: "执行反馈的自然语言描述或结构化数据"
user-invokable: true
status: draft
---

## 目标

将用户提交的执行反馈（自然语言或结构化数据）解析并固化为标准的 `RUN-EXEC-*.md` 记录文件。

## 适用范围

- 适用阶段：交付后的执行反馈阶段
- 输入：用户的执行反馈
- 输出：`runs/RUN-EXEC-[timestamp].md`

## 前置条件

- [ ] 已有交付文档（执行反馈需对应某个已交付的工作流）
- [ ] `.fw-meta/templates/RUN-EXEC-TEMPLATE.md` 可用

## 执行约束

- RUN-EXEC 编号格式：`RUN-EXEC-YYYYMMDD-NNN`
- 必须填写环境快照、任务执行结果、证据引用
- 失败任务必须填写 error_message 和 actual_result
- 异常与偏差部分不能为空——至少填"无异常"

## Gotchas

- 用户的反馈可能是非结构化的自然语言（如"ACL 测试通过了但日志没出来"），需要解析为结构化字段
- 用户可能只报告失败，忽略成功的任务——需主动询问全部任务的结果

## 验收标准

- 输出的 RUN-EXEC 文件 frontmatter 完整
- 每个任务都有执行结果记录
- 失败任务有详细的错误信息
- 异常与偏差部分已填写
