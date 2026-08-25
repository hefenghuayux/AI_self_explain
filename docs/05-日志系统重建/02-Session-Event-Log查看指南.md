# Session Event Log 查看指南

## 1. 当前可以在哪里查看

Session Event Log 的权威数据保存在 SQLite 数据库的 `session_events` 表中。Surface、Trajectory、Trace 不是三份独立日志文件，而是读取同一批事件后即时生成的三种投影。

```text
data/database/ai_self_explain.db
└── session_events（唯一持久化的 Session Event Log）
    ├── SurfaceService.build_surface()       -> 模型可见内容
    ├── TrajectoryService.build_trajectory() -> 面向人的运行步骤
    └── TraceService.build_trace()           -> 单次运行的因果树
```

对应位置如下：

| 内容 | 当前查看位置 | 说明 |
| --- | --- | --- |
| 原始 Event Log | `data/database/ai_self_explain.db` 的 `session_events` 表 | 权威事实，按 `session_id + seq` 排序 |
| Surface | `backend/app/services/surface.py` | 从 `user.message`、`context.added` 折叠得到 |
| Trajectory | `backend/app/services/trajectory.py` | 按 `run_id` 分组，生成用户输入、模型调用、状态变化步骤 |
| Trace | `backend/app/services/trace.py` | 按 `parent_event_id` 建立因果树 |
| 进程诊断日志 | `.env` 中 `LOG_DIR` 指向的 `application.log` | 不是本指南所说的三种投影 |

### 1.1 当前限制

阶段四查询 API 和前端查看页面现已实现。教师登录后可在会话页点击“查看运行日志”，进入 `/sessions/{session_id}/logs`；后端 API 位于 `/api/sessions/{session_id}/...`。当前可使用以下三种方式：

1. 用 DB Browser for SQLite 等 SQLite 工具查看原始事件。
2. 在项目虚拟环境中直接调用三个投影服务查看 Surface、Trajectory、Trace。
3. 通过教师账号使用前端 Trajectory/Trace 页面；页面按 `seq` 读取原始事件详情。

当前开发数据库已升级到 Alembic revision `20260820_18`，包含 `session_events` 表。旧版本数据库需要先执行 `scripts/dev.ps1` 或 `python -m alembic -c backend/alembic.ini upgrade head`；旧业务记录不会自动回填成新的 Session Event Log。

五个查询 API 为：

```text
GET /api/sessions/{session_id}/events?afterSeq=-1&limit=100
GET /api/sessions/{session_id}/events/{seq}
GET /api/sessions/{session_id}/surface?asOfSeq={seq}
GET /api/sessions/{session_id}/trajectory
GET /api/sessions/{session_id}/trace?run_id={run_id}
```

这些 API 只允许教师账号访问。原因是原始事件可能包含完整模型 Prompt 和学生文本；没有 Session 所有权模型时，教师角色是当前最小权限边界。

## 2. 查看原始 Event Log

### 2.1 使用 SQLite 图形工具

在 DB Browser for SQLite 中打开：

```text
E:\workspacce\AI\AI_self_explain\data\database\ai_self_explain.db
```

先查看哪些 Session 已经有事件：

```sql
SELECT
    session_id,
    COUNT(*) AS event_count,
    MIN(seq) AS first_seq,
    MAX(seq) AS last_seq
FROM session_events
GROUP BY session_id
ORDER BY session_id DESC;
```

再按确定顺序查看某个 Session。将 `1` 改为实际 `session_id`：

```sql
SELECT
    seq,
    event_type,
    run_id,
    event_id,
    parent_event_id,
    occurred_at,
    data
FROM session_events
WHERE session_id = 1
ORDER BY seq;
```

查看该 Session 中有哪些运行批次：

```sql
SELECT
    run_id,
    MIN(seq) AS first_seq,
    MAX(seq) AS last_seq,
    COUNT(*) AS event_count
FROM session_events
WHERE session_id = 1 AND run_id IS NOT NULL
GROUP BY run_id
ORDER BY first_seq;
```

这里必须用 `seq` 判断 Session 内的先后顺序。`occurred_at` 用于展示发生时间，不负责解决同一 Session 内的排序。

### 2.2 使用 PowerShell

在仓库根目录执行下面的只读命令。它会打印 Session 1 的原始事件；需要查看其他 Session 时修改 `session_id = 1`。

```powershell
$env:PYTHONPATH = "backend"
$env:PYTHONUTF8 = "1"

@'
import json

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.session_event import SessionEvent

session_id = 1
engine = create_engine("sqlite:///./data/database/ai_self_explain.db")

with Session(engine) as database_session:
    events = database_session.scalars(
        select(SessionEvent)
        .where(SessionEvent.session_id == session_id)
        .order_by(SessionEvent.seq)
    ).all()
    if not events:
        raise RuntimeError(f"Session {session_id} 没有事件")

    for event in events:
        print(json.dumps({
            "seq": event.seq,
            "eventType": event.event_type,
            "runId": event.run_id,
            "eventId": event.event_id,
            "parentEventId": event.parent_event_id,
            "occurredAt": event.occurred_at.isoformat(),
            "data": event.data,
        }, ensure_ascii=False, indent=2))

engine.dispose()
'@ | & .\.venv\Scripts\python.exe -
```

## 3. 查看 Surface、Trajectory、Trace

在仓库根目录执行下列命令。先把 `session_id` 和 `run_id` 改成上一节 SQL 查到的值。

```powershell
$env:PYTHONPATH = "backend"
$env:PYTHONUTF8 = "1"

@'
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.services.surface import SurfaceService
from app.services.trace import TraceService
from app.services.trajectory import TrajectoryService

session_id = 1
run_id = "run_session_1_attempt_1"
engine = create_engine("sqlite:///./data/database/ai_self_explain.db")

with Session(engine) as database_session:
    surface = SurfaceService(database_session).build_surface(session_id)
    trajectory = TrajectoryService(database_session).build_trajectory(session_id)
    trace = TraceService(database_session).build_trace(session_id, run_id)

    print("\n=== Surface ===")
    print(surface.model_dump_json(by_alias=True, indent=2))
    print("\n=== Trajectory ===")
    print(trajectory.model_dump_json(by_alias=True, indent=2))
    print("\n=== Trace ===")
    print(trace.model_dump_json(by_alias=True, indent=2))

engine.dispose()
'@ | & .\.venv\Scripts\python.exe -
```

如果只想查看模型在某个历史时点之前可见的内容，可以传入 `as_of_seq`：

```python
surface = SurfaceService(database_session).build_surface(session_id, as_of_seq=5)
```

## 4. 真实日志样本

### 4.1 样本来源和边界

下面的样本来自 2026-08-21 实际执行：

```powershell
.\.venv\Scripts\python.exe -m pytest `
  backend\tests\integration\test_session_event_flow.py::test_text_self_explanation_writes_real_event_chain `
  -q
```

执行结果为 `1 passed`。该测试通过真实的题目创建、Session 创建、初始选择和文本自讲提交接口，最终真实写入 SQLite，再使用当前投影服务读取。为了避免调用外部服务，AI 客户端响应由测试替身返回。因此这是“真实业务链路和真实 Event Log 写入”的样本，不是“真实外部 AI 网络请求”的样本。

测试输入为：

```text
题目：计算 1 + 1。
学生确认文本：1 加 1 等于 2。
```

### 4.2 原始事件顺序

本次运行生成 Session 1、Run `run_session_1_attempt_1`，共 9 条事件：

| seq | event_type | parent seq | 关键内容 |
| ---: | --- | ---: | --- |
| 0 | `session.started` | - | Session 建立 |
| 1 | `user.message` | - | 学生提交“1 加 1 等于 2。” |
| 2 | `state.changed` | 1 | `CAPTURING_INPUT -> AI_EVALUATING` |
| 3 | `context.added` | 2 | 题目和评价输出约束 |
| 4 | `context.added` | 2 | 两个评分点 |
| 5 | `context.added` | 2 | 当前轮次、支持次数和已覆盖点 |
| 6 | `model.requested` | 5 | 实际发送给 `test-ai-model` 的完整消息，`surfaceSeq = 5` |
| 7 | `model.responded` | 6 | 校验通过，耗时 3 ms |
| 8 | `state.changed` | 7 | `AI_EVALUATING -> WAIT_STUDENT_ACTION` |

以下是本次数据库中 `model.responded` 的完整真实记录：

```json
{
  "sessionId": 1,
  "seq": 7,
  "eventId": "evt_612faad8b78449d5bf665aae78486f76",
  "runId": "run_session_1_attempt_1",
  "parentEventId": "evt_fd7d0fd079da4796a89f96d485ae199d",
  "eventType": "model.responded",
  "occurredAt": "2026-08-21T08:58:58.095745",
  "data": {
    "output": {
      "correctness": "CORRECT",
      "completeness": "COMPLETE",
      "coveredPoints": [
        "正确计算加法",
        "得出结果 2"
      ],
      "missingPoints": [],
      "errorEvidence": [],
      "confidence": 1,
      "needHumanReason": null
    },
    "validation": "valid",
    "durationMs": 3
  }
}
```

分析：

- `seq = 7` 表示它是该 Session 的第 8 条事实记录。
- `parentEventId` 指向 seq 6 的 `model.requested`，证明这是该请求的直接结果，不是靠时间邻近推断。
- `validation = valid` 表示模型返回内容通过业务 schema 校验。
- `correctness = CORRECT` 和 `completeness = COMPLETE` 是 AI 评价结果；后续业务状态仍由确定性状态机处理，而不是由日志投影决定。
- `durationMs = 3` 是测试替身返回的模拟耗时，不能代表真实外部模型延迟。

### 4.3 Surface 真实投影

本次运行的 Surface 结构如下。为便于阅读，题目上下文中的完整 `outputSchema`、常见错误、提示等内容没有在文档中重复展开；数据库和实际投影中保存的是完整值。

```json
{
  "sessionId": 1,
  "asOfSeq": 8,
  "messages": [
    {
      "seq": 1,
      "role": "user",
      "content": "1 加 1 等于 2。"
    }
  ],
  "contexts": [
    {
      "seq": 3,
      "kind": "question",
      "source": "question:1",
      "content": {
        "questionContent": "计算 1 + 1。",
        "standardAnswer": "2",
        "rubricPoints": ["正确计算加法", "得出结果 2"]
      }
    },
    {
      "seq": 4,
      "kind": "rubric",
      "source": "question:1:rubric",
      "content": {
        "rubricPoints": ["正确计算加法", "得出结果 2"]
      }
    },
    {
      "seq": 5,
      "kind": "session_state",
      "source": "session.state",
      "content": {
        "round": 1,
        "supportCountRound": 0,
        "coveredPointsCurrentRound": []
      }
    }
  ]
}
```

分析：

- Surface 回答“模型在组装请求时看到了什么”。它只收集 `user.message` 和 `context.added`。
- `model.requested`、`model.responded` 和 `state.changed` 不进入 Surface，避免把内部运行记录再次喂给模型。
- `asOfSeq = 8` 表示投影扫描到了 seq 8，不表示 seq 8 本身被加入了 Surface。
- 本次 `model.requested.data.surfaceSeq = 5`，表示真正发送请求前使用的 Surface 截止到 seq 5。调查某次请求时，应优先用该值执行 `build_surface(session_id, as_of_seq=5)`，而不是直接查看最新 Surface。

### 4.4 Trajectory 真实投影

```json
{
  "sessionId": 1,
  "runs": [
    {
      "runId": "run_session_1_attempt_1",
      "startedAt": "2026-08-21T08:58:58.030714",
      "steps": [
        {
          "kind": "user_input",
          "eventSeq": 1,
          "summary": "学生提交自讲"
        },
        {
          "kind": "state_change",
          "eventSeq": 2,
          "from": "CAPTURING_INPUT",
          "to": "AI_EVALUATING"
        },
        {
          "kind": "model_call",
          "requestSeq": 6,
          "resultSeq": 7,
          "status": "success",
          "durationMs": 3
        },
        {
          "kind": "state_change",
          "eventSeq": 8,
          "from": "AI_EVALUATING",
          "to": "WAIT_STUDENT_ACTION"
        }
      ]
    }
  ]
}
```

分析：

- Trajectory 回答“这次用户操作经历了哪些关键步骤”，适合快速判断流程停在哪一步。
- 三条 `context.added` 被隐藏，因为它们属于模型调用细节，不是面向人的主步骤。
- `status = success` 表示模型请求收到 `model.responded`，即传输链路成功。即使 `validation = invalid`，Trajectory 仍会显示 `success`；要判断内容校验是否通过，必须展开原始 `model.responded.data.validation`。
- 只有 `model.requested`、没有直接结果事件时显示 `pending`；结果为 `model.failed` 时显示 `failed`。

### 4.5 Trace 真实投影

```json
{
  "sessionId": 1,
  "runId": "run_session_1_attempt_1",
  "roots": [
    {
      "seq": 1,
      "eventType": "user.message",
      "children": [
        {
          "seq": 2,
          "eventType": "state.changed",
          "children": [
            {"seq": 3, "eventType": "context.added", "children": []},
            {"seq": 4, "eventType": "context.added", "children": []},
            {
              "seq": 5,
              "eventType": "context.added",
              "children": [
                {
                  "seq": 6,
                  "eventType": "model.requested",
                  "children": [
                    {
                      "seq": 7,
                      "eventType": "model.responded",
                      "children": [
                        {"seq": 8, "eventType": "state.changed", "children": []}
                      ]
                    }
                  ]
                }
              ]
            }
          ]
        }
      ]
    }
  ]
}
```

分析：

- Trace 回答“哪个事件直接导致了哪个事件”，适合调查一次 Run 的因果链。
- seq 3、4、5 都是 seq 2 的直接子事件，说明进入 `AI_EVALUATING` 后组装了三类上下文。
- seq 6 挂在 seq 5 下，seq 7 挂在 seq 6 下，明确表示“上下文准备完成 -> 发起模型请求 -> 收到模型结果”。
- Trace 只使用 `parent_event_id`，不会因为两个事件时间相近就推断父子关系。
- `session.started` 没有 `run_id`，因此不会出现在某个 Run 的 Trace 中。

## 5. 三种投影应该怎样配合排查

推荐按以下顺序查看：

1. 先看 Trajectory，确认故障属于用户输入、状态转换还是模型调用。
2. 再看 Trace，确认直接因果关系和缺失的子事件。例如 `model.requested` 没有结果子节点时，模型调用仍在等待或流程异常中断。
3. 涉及 Prompt 或上下文时，读取 `model.requested.data.surfaceSeq`，再查看对应 `as_of_seq` 的 Surface。
4. 最后回到原始 Event Log，检查完整 `data`、`event_id`、`parent_event_id` 和准确顺序。

常见判断规则：

| 现象 | Trajectory | 原始事件/Trace | 结论 |
| --- | --- | --- | --- |
| 模型正常返回且校验通过 | `success` | `model.responded.validation = valid` | 请求和内容校验均成功 |
| 模型正常返回但结构不合法 | `success` | `model.responded.validation = invalid` | 传输成功，内容校验失败 |
| 模型调用明确失败 | `failed` | `model.failed` 包含错误类型和消息 | 查看 `errorType`、`message` |
| 模型请求没有结果 | `pending` | `model.requested` 无结果子事件 | 可能仍在执行，也可能异常中断；需结合 `application.log` |
| 模型看到的上下文不对 | 不展示完整上下文 | 用请求的 `surfaceSeq` 重建 Surface | 对照 `model.requested.messages` 判断组装差异 |

## 6. 合理性批判与不足

1. **访问范围仍较窄**：API 和前端入口已可用，但仅教师可访问，且页面只覆盖 Trajectory/Trace 与按 seq 展开的事件详情。学生视图、分页事件浏览和权限细分仍未实现；这些能力需要明确敏感字段策略后再扩展。
2. **旧数据库不会回填历史事件**：迁移只创建新表并保留新业务写入路径，旧业务记录不会自动变成 Session Event Log。因此升级后只能查看升级后产生的事件，除非另行设计可审计的历史重建规则。
3. **样本不代表真实模型网络质量**：本指南样本验证了真实业务写入链路和投影规则，但模型客户端由测试替身代替，3 ms 延迟不能用于性能判断。
4. **时间序列化存在偏差风险**：设计要求 API 输出 UTC `Z`，但当前 SQLite 读取样本中的 `occurred_at` 仍可能没有时区后缀。排查时应以 `seq` 为顺序依据；后续应补充 API 时间格式的专门契约测试。
5. **Surface 不是模型请求快照的替代品**：Surface 只呈现结构化的消息与上下文；判断模型实际收到什么时，`model.requested.data.messages` 才是最终证据。两者不一致时应按后者调查组装逻辑。
