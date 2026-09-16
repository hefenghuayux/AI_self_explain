# 阶段一：Structured Event v3 与事件精简

## 1. 阶段目标

建立 Structured Event Schema `3.0`，删除没有真实用户动作对应的事件，减少重复字段和空字段，同时保持底层业务表、状态机与现有功能不变。

本阶段不保存模型请求快照，不调整运行日志 formatter，不完成最终前端业务聚合视图；但必须完成 v3 全量导出基线和业务关联字段，避免后续阶段依赖不可重建的事件关系。

## 2. 准备修改的准确路径

- `backend/app/schemas/audit.py`
- `backend/app/services/audit_trace.py`
- `backend/app/api/audit.py`
- `backend/app/models/student_submission.py`
- `backend/app/models/support_event.py`
- `backend/app/models/state_transition_event.py`
- `backend/app/repositories/sessions.py`
- `backend/alembic/versions/<revision>_add_audit_correlation_fields.py`
- `frontend/src/types/audit.ts`
- `frontend/src/views/AuditTraceView.vue`
- `backend/tests/unit/test_audit_trace.py`
- `backend/tests/integration/test_pause_resume_audit.py`
- `docs/01-基本功能/03-全链路日志字段说明.md`

实施前重新检查这些文件是否存在用户未提交改动；如果无法区分修改来源，停止编辑并报告。

## 3. 数据契约任务

### 3.1 顶层生产者信息

在 `SessionTraceResponse` 增加顶层 `producer`：

```json
{
  "service": "ai-self-explain-backend",
  "version": "0.1.0"
}
```

从 `TraceEventResponse` 删除每条重复的 `source`。不保留固定的 `module: audit_trace`，因为它只说明投影位置，不能准确表示事件发生组件。

### 3.2 结果结构

将 `TraceResultResponse` 调整为：

- `status`：必填；
- `duration_ms`：可选，仅计时操作输出；
- `error`：可选，仅失败时输出；
- `error.type` 和 `error.message`：失败时必填。

不得在成功事件中输出空 error 对象。

### 3.3 序列化规则

- `GET /audit/trace` 设置 `response_model_exclude_none=True`，或使用项目中等价的显式序列化方式。
- JSONL 使用 `model_dump(..., exclude_none=True)`。
- `data`、`references`、`privacy` 是自由字典，Pydantic 的 `exclude_none` 不会自动清理其中的空值；各事件构造函数必须显式只加入适用键。
- 不新增递归删除空字段的通用兜底函数。

### 3.4 Schema 版本

- 顶层 `schemaVersion` 改为 `3.0`。
- API 事件不再重复单条 `schemaVersion`。
- JSONL 每行使用 `{schemaVersion, producer, sessionId, event}` 独立记录信封；版本和生产者属于导出信封，不重新放回事件体。
- JSONL 每次导出都从权威数据库记录全量重建，先写临时文件并原子替换；阶段四只负责验证历史迁移，不再保留 v2 增量追加逻辑。

## 4. 事件任务

### 4.1 合并文本 attempt 与 submission 投影

删除文本 `ExplanationAttempt` 对应的 `student.input.confirmed` 投影。

`StudentSubmission(submission_type=SELF_EXPLANATION)` 投影为：

```text
student.explanation.submitted
```

该事件从 submission context 和关联 attempt 中合并：

- `round`
- `inputMode`
- `content` 字符数和 SHA-256 指纹（不保存原文）
- `confirmedAt`
- `studentSubmissionId`
- `attemptId`
- `audioFileId`（仅语音）

底层 `ExplanationAttempt` 和 `StudentSubmission` 均保留，不修改提交事务。

### 4.2 语音事件

未提交的语音转写 attempt 继续产生独立技术事件，但名称改为：

```text
voice.transcription.completed
```

它只表达 ASR 转写和语音草稿形成。语音草稿随后提交为自讲时，再产生 `student.explanation.submitted`。

### 4.3 AI 事件

保持以下事件原子性：

- `ai.call.completed`
- `ai.call.failed`
- `ai.output.validated`
- `ai.output.validation_failed`

原因：传输成功、结构校验成功和确定性规则应用是三个不同结果。Schema 重试时必须看到“调用成功但校验失败”。

### 4.4 状态事件

`state.transitioned` 和 `session.created` 保持不变。允许前端在后续阶段折叠，但 Structured Event 必须保留 before/after 状态证据。

## 5. AuditTraceService 重构任务

1. 调整 `build_session_trace`，在构造提交事件时建立 submission、attempt 和状态事件之间的确定性索引。
2. 文本 attempt 不再由 `_attempt_events` 独立生成事件。
3. `_submission_events` 生成新的 `student.explanation.submitted`，同时包含两个记录引用。
4. `_attempt_events` 只处理尚未被 `SELF_EXPLANATION` 提交事件覆盖的语音转写事实；其他 `StudentSubmission` 类型继续使用 `student.input.submitted`。
5. `_event` 不再写固定 `source`，并接受新的条件式 result、references 和 privacy。
6. 对每种事件显式构造适用字段，不能用通用空值清理掩盖错误。
7. 更新事件排序和 eventId 规则，确保同一数据库事实每次重建产生相同 ID 和顺序。
8. 为 `StudentSubmission`、`SupportEvent` 保存 `request_id`，为状态转换保存 `related_support_event_id`；新记录必须写入，历史记录为空时不得按时间猜测。
9. `export_session` 不按 eventId 增量追加，而是每次全量重建 `trace.jsonl` 和 `audit.md` 并原子替换；`GET /audit/trace` 只读取，不触发导出。

## 6. 前端兼容任务

本阶段只完成 v3 契约兼容，不提前完成阶段三的最终视觉重构：

1. 更新 TypeScript 类型，支持顶层 producer、新 result.error 和省略的可选字段。
2. 将业务分组匹配从 `student.input.submitted/confirmed` 更新为 `student.explanation.submitted`。
3. 将 `voice.capture.completed` 更新为 `voice.transcription.completed`。
4. 删除对固定 source 和 null 字段的假设。
5. 保持现有页面可正常加载、筛选和展开 JSON。

## 7. 测试任务

### 7.1 单元测试

- 成功非计时事件序列化为 `{"status":"SUCCESS"}`。
- 计时成功事件包含 `durationMs`，不包含 error。
- 失败事件包含完整 error，不包含旧 `errorType/errorMessage`。
- 顶层只有一个 producer，单条事件没有 source。
- JSONL 每行记录信封包含 schemaVersion，内部 event 不包含 source 和 schemaVersion。
- JSONL 每次导出只包含当前数据库投影结果，不保留已被后续提交覆盖的旧事件。
- 自由字典中不出现已知不适用空字段。
- 数据库无时区时间仍转换为 UTC `Z`。

### 7.2 集成测试

- 文本提交只产生一个 `student.explanation.submitted`，不产生 `student.input.confirmed`。
- 新提交事件同时引用 `attemptId` 和 `studentSubmissionId`。
- 文本提交的 `state.transitioned` 仍存在。
- 语音转写未提交时存在 `voice.transcription.completed`。
- 语音转写提交后存在 `student.explanation.submitted`，且引用音频和 attempt。
- 非 `SELF_EXPLANATION` 提交继续产生 `student.input.submitted`，不被错误重命名。
- 新 `StudentSubmission`、`SupportEvent` 和关联状态转换保存适用的 request/support 引用。
- AI 调用成功但输出校验失败时，两类事件均存在且状态正确。
- API JSON 中不出现不适用 null 字段。
- 先导出语音草稿、再提交并重新导出后，JSONL 不保留已被合并的旧 transcription 投影。

## 8. 阶段验收标准

- Schema 版本为 `3.0`。
- 现有状态机、计数、阈值、模型调用和学生操作行为没有变化。
- Structured Event 不再输出 `student.input.confirmed`。
- 每条事件不再重复固定 source。
- 成功事件没有空错误字段。
- 前端能够读取 v3 trace，不出现类型或运行时错误。
- 后端目标测试和前端构建通过。

## 9. 明确不做

- 不增加 `request_snapshot` 数据库字段。
- 不显示完整模型请求。
- 不改变模型 messages 角色。
- 不重做最终人读业务 Trace 布局。
- 不改变 stdout 和 `application.log` 格式。
- 不接入 OpenTelemetry。

## 10. 风险与不足

1. 删除合成事件会改变现有事件数量和 eventId 集合，因此 JSONL 必须在本阶段改为每次全量重建；阶段四只验收历史文件迁移。
2. submission 和 attempt 的时间可能略有差异。合并事件应以真实学生提交时间为主，不能把 attempt 创建时间误当成最终提交时间。
3. 自由字典条件构造会增加少量重复代码，但比通用清理函数更能暴露契约错误，符合项目不写兜底封装的约束。
