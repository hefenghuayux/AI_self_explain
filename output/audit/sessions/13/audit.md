# 会话审计报告：session-13

## 会话概览

- 会话 ID：13
- 当前状态：IN_PROGRESS
- 当前阶段：WAIT_INITIAL_CHOICE
- 当前轮次：1
- 事件数量：1
- 外部调用：0
- 错误数量：0

## 执行链路

| 序号 | 时间 | 事件 | 状态 | Trace ID |
| ---: | --- | --- | --- | --- |
| 1 | 2026-08-10T02:49:49 | session.created | SUCCESS | session-13 |

## 事件明细

### 1. session.created

```json
{
  "schemaVersion": "1.0",
  "eventId": "state-transition-75",
  "sequence": 1,
  "occurredAt": "2026-08-10T02:49:49",
  "eventName": "session.created",
  "severity": "INFO",
  "source": {
    "service": "ai-self-explain-backend",
    "module": "audit_trace"
  },
  "correlation": {
    "sessionId": 13,
    "requestId": null,
    "traceId": "session-13",
    "spanId": "state-transition-75",
    "parentSpanId": null
  },
  "operation": {
    "name": "CREATE_SESSION",
    "kind": "STATE_TRANSITION"
  },
  "result": {
    "status": "SUCCESS",
    "durationMs": null,
    "errorType": null,
    "errorMessage": null
  },
  "data": {
    "fromStatus": "NEW",
    "toStatus": "IN_PROGRESS",
    "fromFlowStage": null,
    "toFlowStage": "WAIT_INITIAL_CHOICE",
    "beforeSnapshot": {
      "status": "NEW",
      "flowStage": null
    },
    "afterSnapshot": {
      "status": "IN_PROGRESS",
      "flowStage": "WAIT_INITIAL_CHOICE",
      "round": 1,
      "supportCountRound": 0,
      "supportCountTotal": 0,
      "noProgressCount": 0,
      "noProgressHelpRequestCount": 0,
      "solutionExposed": false,
      "completionType": null,
      "needHumanReason": null,
      "coveredPointsCurrentRound": [],
      "coveredPointsAll": [],
      "currentDraft": "",
      "version": 0,
      "pausedFromStage": null
    }
  },
  "references": {
    "stateTransitionEventId": 75,
    "attemptId": null,
    "evaluationId": null
  },
  "privacy": {
    "redactedFields": []
  }
}
```

## 脱敏说明

学生原始输入、ASR 原始文本、完整模型原始响应和本地音频路径不直接写入本报告。
报告仅保存长度、SHA-256、必要的业务结果及数据库记录引用。
