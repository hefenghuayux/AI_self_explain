# DeepSeek 缓存基线统计结果

> 本文件由 `02-DeepSeek缓存基线统计.py` 生成，记录改造前的缓存基线数据。
>
> 改造完成后各阶段结果追加在下方，不覆盖历史记录。

---

## 统计概览

| 项目 | 值 |
| --- | --- |
| 统计时间范围 | `{{START_TIME}}` ~ `{{END_TIME}}` |
| 记录总数 | `{{TOTAL_RECORDS}}` |
| 可分析记录（含 usage） | `{{USABLE_RECORDS}}` |
| 无法解析的记录 | `{{UNPARSABLE_RECORDS}}` |
| 数据库类型 | `{{DB_TYPE}}` |
| 模型 | `{{MODEL}}` |
| 提示词版本 | `{{PROMPT_VERSION}}` |

---

## 分组统计结果

### 1. 按 taskType 汇总

| taskType | 样本量 | 输入 token 合计 | 缓存命中 token | 缓存未命中 token | 缓存 token 命中率 | 有命中请求占比 | 输出 token 合计 | Schema 重试率 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `{{TASK_TYPE_1}}` | {{N1}} | {{IN1}} | {{HIT1}} | {{MISS1}} | {{RATE1}}% | {{REQ_RATE1}}% | {{OUT1}} | {{RETRY_RATE1}}% |
| ... | ... | ... | ... | ... | ... | ... | ... | ... |

### 2. 按 (taskType, model, promptVersion) 明细

| taskType | model | promptVersion | 样本量 | 平均输入 | 平均命中 | 平均未命中 | 命中率 | 命中请求率 | 平均输出 | 重试率 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `{{TYPE}}` | `{{MODEL}}` | `{{VER}}` | {{N}} | {{AVG_IN}} | {{AVG_HIT}} | {{AVG_MISS}} | {{RATE}}% | {{REQ_RATE}}% | {{AVG_OUT}} | {{RETRY}}% |

### 3. 全局汇总

| 指标 | 值 |
| --- | ---: |
| 总输入 token | `{{TOTAL_INPUT}}` |
| 缓存命中 token 合计 | `{{TOTAL_HIT}}` |
| 缓存未命中 token 合计 | `{{TOTAL_MISS}}` |
| **缓存 token 命中率** | **`{{CACHE_HIT_RATE}}`%** |
| 有缓存命中的请求数 | `{{HIT_REQ_COUNT}}` / `{{USABLE_RECORDS}}` |
| **有缓存命中的请求占比** | **`{{HIT_REQ_RATE}}`%** |
| 命中时平均命中 token | `{{AVG_HIT_WHEN_HIT}}` |
| 总输出 token | `{{TOTAL_OUTPUT}}` |
| 平均输出 token/请求 | `{{AVG_OUTPUT}}` |
| Schema 校验失败数 | `{{INVALID_COUNT}}` |
| **Schema 重试率** | **`{{SCHEMA_RETRY_RATE}}`%** |

---

## 一次性例子 token 估算

仅针对 `AI_TEACHING` / `generate_teaching` 请求：

| taskType | 平均输入 token | 估算例子 token/请求（~10%） |
| --- | ---: | ---: |
| `AI_TEACHING` | `{{TEACHING_AVG_INPUT}}` | ~`{{TEACHING_EXAMPLE_COST}}` |

> 说明：例子 token 按平均输入 token 的 10% 粗略估算，实际需根据模板去重后的例子内容长度精确计量。

---

## 费用估算

> 按 DeepSeek V4.1-Flash 官方价格（2026-09-17）计算。

| 项目 | 单价（高峰） | Token 量 | 估算费用 |
| --- | ---: | ---: | ---: |
| 缓存命中输入 | ¥0.04/百万 | `{{TOTAL_HIT}}` | ¥`{{HIT_COST}}` |
| 缓存未命中输入 | ¥2.00/百万 | `{{TOTAL_MISS}}` | ¥`{{MISS_COST}}` |
| 输出 | ¥8.00/百万 | `{{TOTAL_OUTPUT}}` | ¥`{{OUTPUT_COST}}` |
| **总计** | | | **¥`{{TOTAL_COST}}`** |

> 费用以实际账单为准，此处仅作参考。空閒时段价格减半。

---

## 无法解析的记录

| 记录 ID | 原因 |
| --- | --- |
| `{{ID_1}}` | JSON 格式错误 / 缺少 usage 字段 |
| ... | ... |

---

## 抽样核对记录

| 记录 ID | taskType | model | hit_tokens | miss_tokens | completion_tokens | 手工核对 |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| `{{ID_1}}` | `{{TYPE}}` | `{{MODEL}}` | {{HIT}} | {{MISS}} | {{COMP}} | 待核对 |
| ... | ... | ... | ... | ... | ... | ... |

---

## 改造后追加记录

### 阶段一：先改 `evaluate_explanation + generate_teaching` 后

> 记录时间、样本量、与基线的对比。

### 阶段二：四个任务全部切换后

> 记录时间、样本量、与基线的对比。

---

*生成时间：{{GENERATED_AT}}*