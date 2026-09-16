# 阶段三：人读 Trace Log 与审计视图

## 1. 阶段目标

将运行日志和会话审计的人读表现从“完整 JSON 优先”调整为“业务摘要优先、技术证据按需展开”，同时保持 Structured Event v3 为机器契约和事实来源。

本阶段不改变状态机、事件持久化和模型消息角色。

## 2. 准备修改的准确路径

- `backend/app/core/logging.py`
- `backend/app/main.py`
- `backend/app/services/ai_evaluation.py`
- `backend/app/services/ai_support.py`
- `backend/app/services/audit_trace.py`
- `backend/app/api/audit.py`
- `backend/app/schemas/audit.py`
- `frontend/src/views/AuditTraceView.vue`
- `frontend/src/types/audit.ts`
- `backend/tests/unit/test_logging.py`
- `backend/tests/unit/test_audit_trace.py`
- 前端现有测试文件；如当前没有对应测试，则新增与 `AuditTraceView` 同目录约定一致的测试文件
- `docs/01-基本功能/03-全链路日志字段说明.md`

## 3. 运行 Trace Log 任务

### 3.1 输出格式

stdout 和 `data/logs/application.log` 改为相同的紧凑单行文本：

```text
2026-08-10 10:20:30 INFO  request.completed POST /api/sessions/42/text-attempts 200 184ms sid=42 rid=8af21c
2026-08-10 10:20:31 INFO  ai.call.completed AI_EVALUATION deepseek-chat 1320ms sid=42 rid=8af21c
2026-08-10 10:20:31 ERROR ai.output.validation_failed AI_SCHEMA_ERROR sid=42 rid=8af21c
```

格式规则：

- 一条记录只占一行；
- 固定顺序为时间、级别、事件、核心结果、关联短 ID；
- requestId 在人读日志中可以显示前 8 至 12 位，Structured Event 保留完整值；
- 异常堆栈可换行，但必须紧跟 ERROR 主行；
- 每个业务日志必须显式提供 `eventName`；formatter 不根据自由文本猜测事件名。
- 不输出学生原文、提示词、标准答案、完整解析、记忆和模型请求快照。

### 3.2 日志级别

- 应用启动、停止和关键业务完成：INFO；
- 普通 HTTP 成功请求：INFO，但健康检查和高频无状态查询可降为 DEBUG；
- `httpx` 成功请求：DEBUG；
- 重试、校验失败但流程仍可继续：WARNING；
- 最终失败和未处理异常：ERROR。

不得通过静默吞掉异常来减少日志。失败仍保留明确错误和堆栈。

### 3.3 application.log 定位

`application.log` 作为人读运行 Trace Log，不再承担机器 Structured Event 职责。本阶段不额外创建 `application.jsonl`，避免增加第三份机器日志；机器会话事实由 `/audit/trace` 和 `trace.jsonl` 提供。

首次切换 formatter 时，不覆盖或删除已有 JSON `application.log`；将其原子重命名为带时间戳的历史 JSON 日志，再创建新的文本 `application.log`。轮转文件保留原有内容。

AI 评价和教学支持服务在每次真实外部调用、输出校验和最终失败时写入紧凑业务运行日志。日志只包含事件、purpose、模型、耗时、状态、错误类型和关联 ID，不包含 prompt、学生文本、答案材料或请求快照。

## 4. 前端业务 Trace 任务

### 4.1 默认视图

默认按业务动作显示，而不是逐条平铺机器事件：

1. 会话开始与输入方式；
2. 学生提交自讲；
3. AI 评价；
4. 确定性规则应用结果；
5. 教学反馈；
6. 后续学生动作。

一次正常文本自讲默认显示 2 至 3 个主要条目。推荐将“AI 评价”和“确定性规则应用”合并为一个主要条目；技术事件数量可以作为摘要显示，但默认折叠。

业务步骤由后端新增的 `GET /api/sessions/{session_id}/audit/business-trace` 统一生成。前端和 `audit.md` 都消费该投影，不各自复制聚合规则；`/audit/trace` 仍只提供机器 Structured Event v3。

### 4.2 聚合规则

后端业务步骤投影只能依据 Structured Event 中的确定性字段：

- requestId；
- attemptId；
- evaluationId；
- externalCallRecordId；
- eventName；
- operation.name；
- sequence。

不得根据展示文本模糊匹配事件，也不得让前端重新推断业务状态。

建议聚合：

- `student.explanation.submitted` + `SUBMIT_TEXT/SUBMIT_VOICE_TRANSCRIPT` 状态转换 -> “学生提交自讲”；
- 同一 evaluation/request 下的 `ai.call.*` + `ai.output.*` + 评价后状态转换 -> “AI 评价”；
- `support.generated` + 对应状态转换 -> “教学反馈”；
- ASR 调用 + transcription + audio persisted -> “语音转写”。

`BusinessTraceResponse` 至少包含 `sessionId`、`generatedAt` 和 `steps`。每个 step 固定包含：

- `stepId`：由主事件 ID 和步骤类型确定性生成；
- `kind`、`title`、`status`、`occurredAt`；
- `summary`：面向人阅读的简短结果；
- `eventIds`：该步骤包含的 Structured Event ID；
- 有关联时才输出 `requestId`、`durationMs` 和 `error`。

业务步骤响应不是新的权威记录，也不写入数据库；每次都由当前 Structured Event v3 确定性构造。

### 4.3 展开策略

- 错误和 WARNING 默认展开；
- 成功业务条目默认展开摘要、收起原始 JSON；
- 连续成功技术事件默认收起；
- 重试发生时显示“共 N 次调用”，并允许逐次展开；
- requestId、数据库引用和 before/after snapshot 放入“技术详情”；
- 完整 Structured Event JSON 放在最深一层。

### 4.4 不适用字段

前端不能为缺失字段显示 `null`、空横线或空标签：

- 有 duration 才显示耗时；
- 有 error 才显示错误区域；
- 有 requestId 才显示 requestId；
- 有 privacy 才显示内容限制说明；
- 有 memoryContext 才展示记忆内容，否则在模型请求块显示“本次未注入记忆”。

## 5. 模型请求分块任务

AI 条目展开后显示：

```text
模型请求
  评价规则（当前实际以 user message 传输）
  题目与评分材料
  当前会话上下文
  教学记忆：本次未注入
  用户输入
  上轮校验错误
  实际 transport messages
  响应格式
```

展示要求：

- “用户输入”默认展开；
- “评价规则”“题目与评分材料”“实际 transport”默认收起；
- 标准答案和完整解析明确标记为教师审计内容；
- 每次重试单独展示快照，不能只显示最后一次；
- systemInstructions 的标题必须提示当前实际传输角色，避免语义分块与 HTTP payload 不一致；
- 长文本可复制和滚动，但不能撑破桌面或移动布局。

## 6. Markdown 导出任务

`audit.md` 与前端都消费后端 `business-trace` 投影，不能在 Markdown 和 TypeScript 中分别复制聚合规则。输出顺序：

1. 会话概览；
2. 业务执行链路表；
3. 业务步骤详情；
4. 模型请求分块；
5. 技术事件和引用；
6. 隐私说明。

Markdown 不再为每条成功事件机械打印全部 JSON。完整机器事件保留在 `trace.jsonl`，Markdown 只在技术附录中按需提供关键字段。

## 7. 测试与视觉验证

### 7.1 后端日志测试

- stdout 和 application.log 为紧凑文本，不再按 JSON 解析。
- 一条成功请求只占一行。
- requestId、sessionId、duration 和 status 存在时顺序稳定。
- 学生文本、API key、标准答案和模型请求不进入运行日志。
- ERROR 保留错误类型、消息和堆栈。
- 文件轮转仍正常工作。
- AI 传输与输出校验分别产生 `ai.call.*` 和 `ai.output.*` 运行日志，且不包含受限正文。
- 首次格式切换后旧 JSON 日志被保留为历史文件，新 `application.log` 只包含紧凑文本。

### 7.2 前端测试

- 正常文本自讲默认不超过 2 至 3 个主要业务条目。
- AI 调用和输出校验在业务视图合并，在完整审计视图仍独立存在。
- 错误自动展开，成功技术事件默认收起。
- 缺失可选字段不显示空标签。
- 模型请求各块内容和 transport messages 正确。
- 多次重试不会互相覆盖。

### 7.3 视觉验证

必须使用真实浏览器验证：

- 桌面宽度；
- 390px 移动宽度；
- 长提示词、长学生输入和长错误信息；
- 多次 AI 重试；
- 没有 memoryContext；
- ERROR 和 WARNING 展开状态。

确保文本不重叠、按钮不溢出、代码块可滚动且业务摘要仍易扫描。

## 8. 阶段验收标准

- 运行日志可以直接在终端阅读，不需要 JSON 格式化工具。
- 普通运行日志不泄露模型请求和学生原文。
- 前端默认业务视图显著少于 Structured Event 数量。
- 完整审计视图仍可逐条查看所有机器事件。
- 模型请求按照约定分块显示。
- `audit.md` 面向人阅读，`trace.jsonl` 面向机器消费，两者职责明确。
- `business-trace` 是前端和 Markdown 共用的业务步骤来源，Structured Event v3 仍是机器事实来源。
- 桌面和移动截图验证通过。

## 9. 明确不做

- 不增加 OpenTelemetry、Perfetto 或外部观测平台。
- 不增加运行日志 JSONL 副本。
- 不改变实际 system/user message 结构。
- 不删除状态转换或外部调用权威记录。
- 不在前端执行状态机判断。

## 10. 风险与不足

1. application.log 从 JSON 改为文本会影响依赖旧格式的脚本；当前未发现正式消费者，但实施前仍需搜索一次仓库引用，并保留旧 JSON 文件供回溯。
2. 前端聚合规则本质上是展示投影。如果引用 ID 不完整，错误聚合会降低可读性，因此阶段一和阶段二的关联字段测试是前置条件。
3. 后端 `business-trace` 消除了 Python 与 TypeScript 复制聚合规则的问题，但新增了一个人读投影 API；必须保持它只负责展示，不成为状态机或机器审计事实来源。
