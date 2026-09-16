# Session Event Log 日志系统重建方案

## 1. 文档目的

本文是日志系统重建的实现契约。开发人员应以本文的数据契约、状态规则和验收条件为准实现代码，不继续扩展旧的 Structured Event v3 方案。

本次重建的目标是建立一个最小的 Session Event Log，并从它派生三个读取视图：

```text
Session Event Log（不可变事实）
    ├── Surface（模型实际可见上下文）
    ├── Trajectory（面向人的运行步骤）
    └── Trace（一次运行的因果关系）
```

本阶段只覆盖 AI 自讲 Demo 当前已经存在的文本/语音提交、上下文组装、AI 评价、教学生成和状态变化。不提前实现子 Agent、上下文压缩、用户审批、插件热替换和跨进程恢复。

## 2. 与旧系统的关系

这是一次重建，不是兼容性改造。以下旧实现不再作为新系统的实现基础：

- `backend/app/services/audit_trace.py` 的多表拼接逻辑；
- Structured Event v3 的 `TraceEventResponse` 字段集合；
- `student.input.confirmed`、`student.input.submitted` 等旧审计事件命名；
- 依赖多个业务表后按时间猜测关联关系的投影逻辑；
- `trace.jsonl` 的旧 envelope 和 `audit.md` 导出格式。

旧业务表不要求在本阶段删除。它们仍然保存评价、教学支持和状态机所需的领域事实；新 Event Log 只保存运行事实和对领域事实的引用。日志投影不能反向决定业务状态、支持次数或阈值。

## 3. 设计边界

### 3.1 权威来源

| 内容 | 权威来源 | 说明 |
| --- | --- | --- |
| Session 运行顺序和因果关系 | `session_events` | 只追加，按 `seq` 回放 |
| 模型实际收到的请求 | `model.requested` 事件 | `data.messages` 必须是实际发送值 |
| 当前业务状态、评价和计数 | 现有领域服务/业务表 | Event Log 不参与状态计算 |
| Surface | 从 `session_events` 折叠 | 不单独写一份可修改的上下文历史 |
| Trajectory、Trace | 读取投影 | 可丢弃、可重建，不是事实 |
| 进程异常和 HTTP 诊断 | `application.log` | 不写学生全文和完整模型 Prompt |

### 3.2 最小实现原则

1. 不设计通用 `metadata`、`tags`、`attributes`、`source` 等无法验证用途的字段。
2. 不设计事件注册中心；事件类型由一个明确的 Python `Literal`/枚举和对应 schema 固定。
3. 不设计 Span 表；`run_id`、`parent_event_id`、`seq` 已足够表达当前 Trace。
4. 不为未来能力预留空字段。新增能力时新增事件类型和迁移，而不是提前扩张公共结构。
5. 事件失败必须保留明确错误类型和消息；不吞异常，也不写兜底事件掩盖失败。

## 4. 核心数据模型

### 4.1 `sessions`

使用现有 `sessions` 表作为 Session 身份表，增加或确认以下字段：

```text
id          INTEGER PRIMARY KEY
created_at  UTC datetime NOT NULL
parent_id   INTEGER NULL REFERENCES sessions(id)
status      TEXT NOT NULL
```

`status` 只表示 Session 生命周期：`active`、`completed`、`failed`。教学状态仍由现有会话状态字段和状态转换规则负责，不要将两个概念混为一个字段。

### 4.2 `session_events`

新增 SQLAlchemy 模型 `backend/app/models/session_event.py`，数据库表名固定为 `session_events`。

| 字段 | 类型 | 必填 | 约束/含义 |
| --- | --- | --- | --- |
| `id` | INTEGER | 是 | 数据库主键 |
| `session_id` | INTEGER | 是 | 外键到 `sessions.id` |
| `seq` | INTEGER | 是 | Session 内从 `0` 开始连续递增 |
| `event_id` | TEXT | 是 | 全局唯一、由应用生成 |
| `run_id` | TEXT | 否 | 一次用户操作；`session.started` 可为空 |
| `parent_event_id` | TEXT | 否 | 直接因果来源；必须引用同 Session 已存在事件 |
| `event_type` | TEXT | 是 | 七种事件类型之一 |
| `occurred_at` | UTC datetime | 是 | 事件发生时间 |
| `data` | JSON | 是 | 当前事件的严格 payload |

数据库约束：

```text
UNIQUE(session_id, seq)
UNIQUE(event_id)
CHECK(seq >= 0)
```

建议索引：

```text
INDEX(session_id, seq)
INDEX(session_id, run_id, seq)
INDEX(session_id, event_type, seq)
```

不要增加 `severity`、`producer`、`module`、`duration_ms`、`error_message` 等公共列。它们只有在具体事件的 `data` 中适用时才出现。

### 4.3 Event Log 公共结构

API 和内部对象统一使用下列结构：

```json
{
  "sessionId": 42,
  "seq": 8,
  "eventId": "evt_01J...",
  "runId": "run_001",
  "parentEventId": "evt_01H...",
  "eventType": "model.requested",
  "occurredAt": "2026-08-20T10:20:30Z",
  "data": {}
}
```

序列化规则：

- API 使用 camelCase；数据库列使用 snake_case；
- 时间统一输出 UTC `Z`；
- `runId`、`parentEventId` 不适用时省略，不输出 `null`；
- `data` 必须是 JSON object，不允许字符串、数组或任意 Python 对象；
- 事件读取后不得修改返回对象，避免投影过程意外改变事实。

## 5. 事件类型契约

事件类型固定为以下七种。第一阶段不得增加其他类型。

### 5.1 `session.started`

表示 Session 第一次建立。

```json
{
  "eventType": "session.started",
  "data": {}
}
```

规则：每个 Session 恰好一条，`seq = 0`，`runId` 省略，`parentEventId` 省略。

### 5.2 `user.message`

表示学生完成确认并提交的输入。语音模式只在 ASR 文本确认后写入一次。

```json
{
  "eventType": "user.message",
  "runId": "run_001",
  "data": {
    "text": "学生确认后的完整文本",
    "inputType": "text"
  }
}
```

`inputType` 只能是 `text` 或 `voice`。不保存 ASR partial、草稿、录音过程事件。

### 5.3 `context.added`

表示后续模型请求新增的确定性上下文。

```json
{
  "eventType": "context.added",
  "runId": "run_001",
  "data": {
    "kind": "question",
    "source": "question:12",
    "content": "题目内容"
  }
}
```

`kind` 只能是：`question`、`rubric`、`session_state`、`memory`。当前没有真正跨会话记忆注入时，不创建 `kind = memory` 的事件。

`content` 必须是模型实际会看到的文本。结构化上下文放入 JSON object 的 `content`，不要同时保存一份格式化文本和一份结构化副本。

### 5.4 `model.requested`

表示一次真实模型请求已经组装完成并准备发送。该事件必须在调用外部模型客户端之前追加。

```json
{
  "eventType": "model.requested",
  "runId": "run_001",
  "parentEventId": "evt_user_message",
  "data": {
    "provider": "deepseek",
    "model": "deepseek-chat",
    "messages": [
      {
        "role": "user",
        "content": "实际发送给模型的完整内容"
      }
    ],
    "surfaceSeq": 8
  }
}
```

字段规则：

- `provider` 和 `model` 必填；
- `messages` 必须与模型客户端实际收到的参数完全一致；
- 不允许只保存 Prompt hash 或展示用的语义分块替代 `messages`；
- `surfaceSeq` 是事件追加前折叠出的 Surface 最后序号；
- 不在普通 `application.log` 中输出 `messages`。

### 5.5 `model.responded`

表示模型传输成功且返回了内容。输出 schema 校验是否通过由 `data.validation` 表示。

```json
{
  "eventType": "model.responded",
  "runId": "run_001",
  "parentEventId": "evt_model_requested",
  "data": {
    "output": {},
    "durationMs": 1200,
    "inputTokens": 300,
    "outputTokens": 180,
    "validation": "valid"
  }
}
```

字段规则：

- `output` 保存业务需要的结构化输出；
- `durationMs`、Token 字段只在客户端实际提供时写入；
- `validation` 只能是 `valid` 或 `invalid`；
- 输出校验失败仍属于模型传输成功，不能改写成 `model.failed`。

### 5.6 `model.failed`

表示模型请求没有得到可用响应，包括超时、连接失败、HTTP 错误或客户端解析失败。

```json
{
  "eventType": "model.failed",
  "runId": "run_001",
  "parentEventId": "evt_model_requested",
  "data": {
    "errorType": "TIMEOUT",
    "message": "模型请求超时",
    "durationMs": 30000
  }
}
```

`errorType` 为有限字符串，第一阶段允许：`TIMEOUT`、`CONNECTION_ERROR`、`HTTP_ERROR`、`INVALID_RESPONSE`、`UNKNOWN`。`UNKNOWN` 只用于客户端确实无法分类的错误，不能作为普通兜底分支。

### 5.7 `state.changed`

表示确定性状态机已经完成一次状态转换。

```json
{
  "eventType": "state.changed",
  "runId": "run_001",
  "parentEventId": "evt_model_responded",
  "data": {
    "from": "EVALUATING",
    "to": "WAIT_STUDENT_ACTION",
    "reason": "evaluation_completed"
  }
}
```

规则：

- 只有状态机成功提交后才追加；
- `from`、`to` 必须来自现有状态枚举；
- `reason` 必须由调用方明确传入；
- 投影不得根据其他事件推测状态变化。

## 6. 事件追加服务

新增 `backend/app/services/event_store.py`，只提供以下操作：

```python
create_session() -> Session
append(session_id, event_type, data, run_id=None, parent_event_id=None) -> SessionEvent
list_events(session_id, after_seq=None, limit=None) -> list[SessionEvent]
get_event(session_id, seq) -> SessionEvent
```

不要增加通用 `append_raw()`、`append_any()` 或“自动清理字段”的兜底接口。事件类型和 payload schema 在 `append()` 内严格校验。

### 6.1 追加算法

一次追加必须在一个数据库事务中完成：

```text
1. 锁定或以数据库写事务保护 session_id
2. 读取该 Session 当前最后 seq
3. next_seq = last_seq + 1
4. 校验 event_type、data、parent_event_id
5. 插入 session_events
6. 提交事务
7. 返回刚插入的事件
```

并发控制要求：

- 不使用普通读操作后在事务外插入；
- SQLite 使用写事务保证同一时刻只有一个追加者；
- 唯一约束失败时原样抛出明确错误；
- 事件插入失败时，不发送“成功”事件，也不修改业务状态。

### 6.2 业务事务边界

下列动作必须在同一数据库事务内完成：

```text
写业务事实 → 追加对应 Event → 提交事务
```

例如学生提交：

```text
1. 保存 StudentSubmission
2. 保存 ExplanationAttempt
3. 追加 user.message
4. 追加 state.changed（如果状态确实改变）
5. 提交
```

如果事务回滚，业务事实和对应事件都不得存在。不要先提交业务表，再异步补写事件。

## 7. Surface 投影

新增 `backend/app/services/surface.py`。

```python
build_surface(session_id, as_of_seq=None) -> Surface
```

### 7.1 Surface 数据结构

```json
{
  "sessionId": 42,
  "asOfSeq": 8,
  "messages": [],
  "contexts": [
    {
      "seq": 3,
      "kind": "question",
      "source": "question:12",
      "content": "题目内容"
    }
  ]
}
```

### 7.2 折叠规则

按 `seq` 升序读取事件：

| 事件 | Surface 行为 |
| --- | --- |
| `session.started` | 不产生消息 |
| `user.message` | 追加一条 user message |
| `context.added` | 追加 context |
| `model.requested` | 不重复追加 messages，只记录请求边界 |
| `model.responded` | 不自动追加，除非业务下一次明确写入 `context.added` |
| `model.failed` | 不产生消息 |
| `state.changed` | 不产生消息 |

Surface 必须是纯投影：不写数据库、不修改事件、不调用模型、不读取进程缓存。

## 8. Trajectory 投影

新增 `backend/app/services/trajectory.py`。

```python
build_trajectory(session_id) -> Trajectory
```

Trajectory 以 `run_id` 分组，再按 `seq` 排序。它只做展示聚合，不创造新的事件。

### 8.1 输出结构

```json
{
  "sessionId": 42,
  "runs": [
    {
      "runId": "run_001",
      "startedAt": "2026-08-20T10:20:30Z",
      "steps": [
        {
          "kind": "user_input",
          "eventSeq": 2,
          "summary": "学生提交自讲"
        },
        {
          "kind": "model_call",
          "requestSeq": 5,
          "resultSeq": 6,
          "status": "success",
          "durationMs": 1200
        },
        {
          "kind": "state_change",
          "eventSeq": 7,
          "from": "EVALUATING",
          "to": "WAIT_STUDENT_ACTION"
        }
      ]
    }
  ]
}
```

第一阶段只允许三种 Trajectory step：`user_input`、`model_call`、`state_change`。

完整事件必须可通过 `eventSeq` 展开。Trajectory 不保存第二份模型输出或学生文本。

## 9. Trace 查询

新增 `backend/app/services/trace.py`。

```python
build_trace(session_id, run_id) -> Trace
```

查询规则：

1. 读取指定 `session_id` 和 `run_id` 的事件；
2. 按 `seq` 排序；
3. 使用 `parent_event_id` 建立父子关系；
4. 没有父事件的事件作为根节点；
5. 不根据时间近似推断父子关系。

```json
{
  "sessionId": 42,
  "runId": "run_001",
  "roots": [
    {
      "seq": 2,
      "eventType": "user.message",
      "children": [
        {
          "seq": 5,
          "eventType": "model.requested",
          "children": [
            {
              "seq": 6,
              "eventType": "model.responded",
              "children": []
            }
          ]
        }
      ]
    }
  ]
}
```

如果 `parent_event_id` 指向不存在的事件，写入时拒绝，而不是在查询时自动修复。

## 10. API 契约

新增或重建以下接口：

```text
GET /api/sessions/{session_id}/events
GET /api/sessions/{session_id}/events/{seq}
GET /api/sessions/{session_id}/surface
GET /api/sessions/{session_id}/trajectory
GET /api/sessions/{session_id}/trace?run_id={run_id}
```

### 10.1 `GET /events`

查询参数：

```text
afterSeq 可选，默认 -1
limit    可选，默认 100，最大 500
```

返回：

```json
{
  "sessionId": 42,
  "events": [],
  "nextAfterSeq": 8
}
```

不允许该接口修改或导出文件。

### 10.2 错误

统一使用明确错误：

```text
404 SESSION_NOT_FOUND
404 EVENT_NOT_FOUND
400 INVALID_EVENT_DATA
409 EVENT_SEQUENCE_CONFLICT
```

不返回空数组掩盖 Session 不存在，也不把事件校验错误转换成通用 `500`。

## 11. 前端边界

前端只消费 `events`、`surface`、`trajectory`、`trace` API：

- 不在 Vue 中合并事件；
- 不根据事件时间计算顺序；
- 不根据事件名称猜测业务状态；
- 不复制模型请求和学生原文到新的前端缓存结构；
- Trajectory 默认显示三类步骤，点击后读取对应原始事件。

前端改造属于后端 API 稳定后再进行的独立步骤，不在 Event Store 阶段提前实现。

## 12. 测试要求

### 12.1 Event Store 单元测试

必须覆盖：

1. 新 Session 第一条事件为 `session.started` 且 `seq = 0`；
2. 连续追加产生 `0, 1, 2...`；
3. `parent_event_id` 不存在时追加失败；
4. 非法 `event_type` 追加失败；
5. 非 object 的 `data` 追加失败；
6. 事务失败时业务记录和事件同时回滚；
7. 两个并发追加不会产生重复 `seq`；
8. 读取后事件顺序与数据库 `seq` 一致。

### 12.2 Surface 测试

必须覆盖：

1. `user.message` 能生成一个模型可见消息；
2. `context.added` 能生成对应上下文来源；
3. `model.requested` 不造成消息重复；
4. `as_of_seq` 能重建历史 Surface；
5. `model.responded` 和 `state.changed` 不会被错误加入下一次请求。

### 12.3 Trajectory/Trace 测试

必须覆盖：

1. 同一 `run_id` 的事件归入同一运行；
2. 不同 `run_id` 不互相合并；
3. Trace 只按 `parent_event_id` 建树；
4. 模型失败显示失败而不是成功；
5. 状态转换使用事件中的 `from`、`to`，不从其他记录推断。

### 12.4 验收场景

至少执行以下完整场景：

```text
创建 Session
→ 提交一段文本自讲
→ 注入题目和评分规则
→ 模型成功返回评价
→ 记录状态变化
→ 查询 events / surface / trajectory / trace
```

还必须执行：

```text
模型超时
模型返回但结构校验失败
语音确认后重复提交防护
进程重启后读取同一 Session
```

## 13. 实施顺序

### 阶段一：数据层和 Event Store

新增：

- `backend/app/models/session_event.py`；
- `backend/app/services/event_store.py`；
- 对应 Alembic migration；
- Event Store 单元测试。

暂不修改前端，不实现 Surface、Trajectory 和 Trace API。

完成标准：事件能够可靠追加、读取、回滚和处理并发。

### 阶段二：三个投影

新增：

- `backend/app/services/surface.py`；
- `backend/app/services/trajectory.py`；
- `backend/app/services/trace.py`；
- 对应 schema 和单元测试。

完成标准：三个投影都能只根据 Event Log 重建，投影过程不写库。

### 阶段三：接入自讲链路

按以下顺序接入现有服务：

```text
学生确认输入 → user.message
上下文组装完成 → context.added
实际调用模型前 → model.requested
模型成功 → model.responded
模型失败 → model.failed
状态机提交成功 → state.changed
```

完成标准：一次自讲不再依赖旧 `AuditTraceService` 才能生成可观测记录。

### 阶段四：API 和前端

实现五个查询接口，前端只显示后端 Trajectory 和原始事件详情。

完成标准：桌面和移动端都能查看业务步骤，并展开到具体事件。

## 14. 明确不实现的内容

本方案当前不实现：

- 子 Agent 和 Session fork；
- 上下文 compaction 和 replacement event；
- 用户审批；
- 插件热替换；
- OpenTelemetry 导出；
- Kafka、Redis 或独立日志服务；
- 事件流式推送；
- 旧 JSONL 和 Markdown 导出兼容；
- 从 Event Log 完全重建评价、计数和教学状态。

这些能力以后需要时，应先新增独立设计文档和事件契约，不得直接向当前七类事件增加可选字段。

## 15. 验收清单

- [ ] `session_events` 只有追加写入路径；
- [ ] Session 内 `seq` 连续且不可重复；
- [ ] 事件 payload 有严格 schema；
- [ ] `model.requested.data.messages` 与真实模型请求一致；
- [ ] Surface 可以只根据事件回放；
- [ ] Trajectory 不创造事实；
- [ ] Trace 不依赖时间猜测父子关系；
- [ ] 业务状态仍由确定性状态机控制；
- [ ] 模型失败和输出校验失败被区分；
- [ ] 普通运行日志不包含学生全文和模型 Prompt；
- [ ] 前端不实现事件聚合规则；
- [ ] 完整测试场景全部通过。

## 16. 合理性批判与不足

1. 两张表可以支撑当前 Demo，但还不是完整 Event Sourcing。评价和教学状态仍由业务表维护，这是降低迁移风险的有意取舍。
2. 完整保存 `model.requested.data.messages` 会增加隐私和存储压力，但没有它就无法证明模型实际看到了什么。上线多租户前必须增加授权和保留策略。
3. 当前没有为 compaction、子 Agent 和审批预留字段。未来增加这些能力需要新的事件契约和回放规则，短期会牺牲扩展便利性，但可以防止当前日志系统过早复杂化。
4. SQLite 写事务能满足本地 Demo 的单进程并发边界；如果以后运行多个后端进程或迁移到服务化数据库，需要重新验证 Session 内序号分配和单 Session 写入所有权。
