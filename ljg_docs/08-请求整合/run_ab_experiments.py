# -*- coding: utf-8 -*-
"""
实验：评价(evaluate_explanation) 与 教学(generate_teaching) 请求整合对照实验
直接调用 DeepSeek API,不启动项目。

三个实验(每个实验跑 3 组学生回答):
  实验1: 两次调用。
    调用1 evel: correctness, completeness, hasProgress
    调用2 teach: main_reason, other_reasons, judge_reason, content, questions
  实验2: 两次调用。
    调用1 eval: correctness, completeness, hasProgress, main_reason, other_reasons, judge_reason
    调用2 teach: content, questions
  实验3: 一次调用,输出全部 8 个字段:
    correctness, completeness, hasProgress, main_reason, other_reasons, judge_reason, content, questions

提示词不再照搬现有 generate_teaching / evaluate_explanation,而是针对字段拆分裁剪。下游步骤
(教学)的提示词中注入上游(评价)已产出的结果,以减少大模型重复推理。
"""
import json
import os
import pathlib
import time

import httpx

ENV_PATH = pathlib.Path(r"D:\lijianguo\project\AI_self_explain\.env")
BASE_DIR = pathlib.Path(__file__).resolve().parent


def load_env():
    env = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


ENV = load_env()
BASE_URL = ENV["AI_BASE_URL"].rstrip("/") + "/chat/completions"
API_KEY = ENV["AI_API_KEY"]
# .env 里的 AI_MODEL=deepseek-v4.1-flash 在当前 API 上不可用, 探测到可用名称为
# deepseek-flash / deepseek-v4-pro。这里默认 deepseek-flash。
MODEL = os.environ.get("AB_MODEL", "deepseek-flash")


# ---------------------------------------------------------------------------
# 题干上下文(来自题库 question id=3)
# ---------------------------------------------------------------------------
QUESTION = {
    "questionContent": (
        "（高一数学·二次函数，中等）已知函数 f(x)=x²-2ax+2a-1（a∈R）。"
        "当 x∈[0,2] 时，f(x) 的最大值为 3。求实数 a 的所有可能取值，"
        "并求每种情况下 f(x) 在区间 [0,2] 上的最小值。"
    ),
    "standardAnswer": "a=0 或 a=2；两种情况下，f(x) 在 [0,2] 上的最小值都为 -1。",
    "rubricPoints": [
        "指出二次函数图像开口向上，因此区间 [0,2] 上的最大值必在端点 x=0 或 x=2 处取得",
        "正确计算 f(0)=2a-1，f(2)=3-2a，并建立 max{2a-1, 3-2a}=3",
        "分类讨论两个端点取得最大值的情形并校验另一端点不超过 3，得到 a=0 或 a=2",
        "分别代入 a=0 和 a=2，结合函数图像或配方法求出区间最小值均为 -1，并说明对应取值点",
    ],
    "commonErrors": [
        "误认为开口向上的抛物线在区间内的最大值一定在顶点处取得",
        "只令 f(0)=3 或只令 f(2)=3，遗漏另一个参数解",
        "求出端点等于 3 后未检查另一端是否不超过 3",
        "得到 a 的取值后没有分别代回函数求区间最小值及取值点",
    ],
    "fullSolution": (
        "第一步，二次项系数 1>0，开口向上，所以闭区间 [0,2] 上最大值必在两端点之一取得。"
        "第二步，f(0)=2a-1，f(2)=3-2a，因此 max{2a-1, 3-2a}=3。"
        "第三步，若 f(0)=3 则 2a-1=3 得 a=2，此时 f(2)=-1≤3 成立；"
        "若 f(2)=3 则 3-2a=3 得 a=0，此时 f(0)=-1≤3 成立。故 a=0 或 a=2。"
        "第四步，a=0 时 f(x)=x²-1，在 x=0 处取最小值 -1；a=2 时 f(x)=(x-2)²-1，"
        "在 x=2 处取最小值 -1。"
    ),
}

# ---------------------------------------------------------------------------
# 三组学生自讲回答(构造: 场景各异)
# ---------------------------------------------------------------------------
STUDENT_ANSWERS = [
    {
        "id": "A-有进展正确不完整",
        "confirmedText": (
            "这题二次函数开口向上，因为 x² 系数是 1 大于 0。闭区间 [0,2] 上的最大值"
            "应该在端点 x=0 或 x=2 取到。先算 f(0)=2a-1，f(2)=3-2a，"
            "然后令 f(0)=3 得 a=2，这时候 f(2)=-1。最大值就是 3。"
        ),
        "progressContext": {"previousExplanations": [], "previousTeaching": []},
    },
    {
        "id": "B-错误理解",
        "confirmedText": (
            "开口向上，所以最大值在顶点取得。顶点 x=a，f(a)=-a²+2a-1。"
            "令最大值等于 3，解出 a。然后最小值也是顶点那里。"
        ),
        "progressContext": {"previousExplanations": [], "previousTeaching": []},
    },
    {
        "id": "C-无进展表述不清",
        "confirmedText": "我不知道，感觉就是差不多，不知道最大值怎么算，也不会分类。",
        "progressContext": {"previousExplanations": [], "previousTeaching": []},
    },
]


# ---------------------------------------------------------------------------
# 提示词模板  (均针对字段拆分做了裁剪, 不照搬现有长提示词)
# ---------------------------------------------------------------------------

EVAL_EXP1_PROMPT = """你是 AI 自讲 Demo 的评价器。基于题目材料和学生最终确认文本，只做"评价"这一件事。你必须只输出符合下方 JSON Schema 的 JSON，不要输出 Markdown 或额外字段。

字段定义：
- correctness：CORRECT（正确）/ WRONG（有错误）/ UNCERTAIN（无法可靠判断）
- completeness：COMPLETE（完整覆盖全部评分点）/ INCOMPLETE（存在缺失）
- hasProgress：布尔值。根据题目、学生确认文本判断学生本轮是否出现有效的新推理、纠正错误、补充依据或提出了合理的替代解法。首次自讲只要提出与本题有关的有效推理就视为有进展；只表达疑问、不知道或机械复述不算进展。

## 题目材料
{question_json}

## 学生确认文本
{confirmed_text}

JSON Schema：
{schema}
"""

TEACH_EXP1_PROMPT = """你是 AI 自讲 Demo 的教学内容生成器。后端已经完成了评价,并把评价结果作为已确定事实提供给你(见下方【已确定的评价结果】),你不必重新评价正确性/完整性/进度,只根据这些事实和学生原文生成教学内容。你必须只输出符合下方 JSON Schema 的 JSON。

【已确定的评价结果】
correctness={correctness}
completeness={completeness}
hasProgress={hasProgress}

字段定义：
- main_reason：本轮卡点的主要原因，只能取：表达与输入问题 / 题意理解问题 / 知识理解与回忆问题 / 知识应用问题 / 执行错误 / 原因未明
- other_reasons：其他可能或次要原因数组，没有时返回 []
- judge_reason：用一小段话说明原因判断依据
- content：面向学生的反馈/提示/纠错正文，不得直接复述标准答案或完整解析
- questions：追问问题数组。若适合用聚焦追问引导则给恰好一个问题，否则为空数组

动作依据（结合 correctness 与 hasProgress）：
- hasProgress=false 时 content 应是"最小提示"，questions 为空
- correctness=WRONG 时 content 应先纠错，可配合一个追问
- completeness=INCOMPLETE 时 content 可给聚焦追问引导，questions 给恰好一个问题
- 终态或信息不足时不强行生成教学

## 题目材料
{question_json}

## 学生确认文本
{confirmed_text}

JSON Schema：
{schema}
"""

EVAL_EXP2_PROMPT = """你是 AI 自讲 Demo 的评价与"原因分类"生成器。基于题目材料和学生最终确认文本，输出评价字段以及错因分类字段，但不要输出教学内容。你必须只输出符合下方 JSON Schema 的 JSON。

字段定义：
- correctness：CORRECT / WRONG / UNCERTAIN
- completeness：COMPLETE / INCOMPLETE
- hasProgress：布尔值，判断学生是否出现有效新推理/纠错/补依据/合理替代解法
- main_reason：本轮卡点主要原因，取值：表达与输入问题 / 题意理解问题 / 知识理解与回忆问题 / 知识应用问题 / 执行错误 / 原因未明
- other_reasons：其他可能或次要原因数组
- judge_reason：说明原因判断依据的一小段话

## 题目材料
{question_json}

## 学生确认文本
{confirmed_text}

JSON Schema：
{schema}
"""

TEACH_EXP2_PROMPT = """你是 AI 自讲 Demo 的教学内容生成器。后端已完成评价与错因分类，评价结果作为已确定事实提供给你(见【已知信息】)，你不必重新评价或重新分类原因，只负责生成教学内容。你必须只输出符合下方 JSON Schema 的 JSON。

【已知信息】
correctness={correctness}
completeness={completeness}
hasProgress={hasProgress}
main_reason={main_reason}
other_reasons={other_reasons}
judge_reason={judge_reason}

字段定义：
- content：面向学生的反馈/提示/纠错正文，不得直接复述标准答案或完整解析
- questions：追问问题数组。聚焦追问时给恰好一个问题，否则为空数组

依据已给出的 main_reason 组织教学内容；问题只能围绕 main_reason 验证，不得向学生展示原因标签。hasProgress=false 时给最小提示且 questions 为空；correctness=WRONG 时 content 先纠错；completeness=INCOMPLETE 时 content 可给聚焦追问，questions 给恰好一个问题。

## 题目材料
{question_json}

## 学生确认文本
{confirmed_text}

JSON Schema：
{schema}
"""

MERGED_EXP3_PROMPT = """你是 AI 自讲 Demo 的评价与教学生成器。一次完成两件事：先评价学生确认文本的正确性、完整性、进展和主要错因，再根据评价生成教学内容。你必须只输出符合下方 JSON Schema 的 JSON。

字段定义：
- correctness：CORRECT / WRONG / UNCERTAIN
- completeness：COMPLETE / INCOMPLETE
- hasProgress：布尔值，判断学生是否出现有效新推理/纠错/补依据/合理替代解法
- main_reason：本轮卡点主要原因，取值：表达与输入问题 / 题意理解问题 / 知识理解与回忆问题 / 知识应用问题 / 执行错误 / 原因未明
- other_reasons：其他可能或次要原因数组
- judge_reason：说明原因判断依据的一小段话
- content：面向学生的反馈/提示/纠错正文，不得直接复述标准答案或完整解析
- questions：追问问题数组，聚焦追问时给恰好一个问题，否则为空数组

规则：
- 先确定 correctness、completeness、hasProgress、main_reason，再据此生成 content 与 questions。
- hasProgress=false 时 content 是最小提示，questions 为空。
- correctness=WRONG 时 content 先纠错，可配合一个追问。
- completeness=INCOMPLETE 时可给聚焦追问，questions 给恰好一个问题。
- 终态(CORRECT+COMPLETE)或信息不足(UNCERTAIN)时 content=null、questions=[]。

## 题目材料
{question_json}

## 学生确认文本
{confirmed_text}

JSON Schema：
{schema}
"""


def build_schema(fields):
    """构造精简 JSON Schema,字段按类型给 enum/type 提示。"""
    prop_types = {
        "correctness": {"type": "string", "enum": ["CORRECT", "WRONG", "UNCERTAIN"]},
        "completeness": {"type": "string", "enum": ["COMPLETE", "INCOMPLETE"]},
        "hasProgress": {"type": "boolean"},
        "main_reason": {
            "type": "string",
            "enum": [
                "表达与输入问题",
                "题意理解问题",
                "知识理解与回忆问题",
                "知识应用问题",
                "执行错误",
                "原因未明",
            ],
        },
        "other_reasons": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [
                    "表达与输入问题",
                    "题意理解问题",
                    "知识理解与回忆问题",
                    "知识应用问题",
                    "执行错误",
                    "原因未明",
                ],
            },
        },
        "judge_reason": {"type": "string"},
        "content": {"type": "string"},
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"question": {"type": "string"}},
                "required": ["question"],
                "additionalProperties": False,
            },
        },
    }
    props = {f: prop_types[f] for f in fields}
    schema = {
        "type": "object",
        "properties": props,
        "required": fields,
        "additionalProperties": False,
    }
    return schema


def call_model(system_prompt):
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": system_prompt}],
        "response_format": {"type": "json_object"},
        "temperature": 0.3,
        "max_tokens": int(os.environ.get("AB_MAX_TOKENS", "4000")),
    }
    started = time.perf_counter()
    with httpx.Client(timeout=120) as client:
        resp = client.post(
            BASE_URL,
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        if resp.status_code != 200:
            return {
                "ok": False,
                "http_status": resp.status_code,
                "raw": resp.text,
                "duration_ms": round((time.perf_counter() - started) * 1000),
            }
        body = resp.json()
        content = body["choices"][0]["message"]["content"]
    return {
        "ok": True,
        "content": content,
        "duration_ms": round((time.perf_counter() - started) * 1000),
        "usage": body.get("usage"),
    }


def parse_json(content):
    try:
        return json.loads(content)
    except Exception as e:
        return {"_parse_error": str(e), "_raw": content}


def run_case(experiment, student):
    """执行单个实验对单个学生回答的完整流程,返回结构化结果。"""
    question_json = json.dumps(QUESTION, ensure_ascii=False, indent=2)
    confirmed = student["confirmedText"]
    result = {
        "experiment": experiment,
        "student_id": student["id"],
        "confirmed_text": confirmed,
        "steps": [],
        "total_duration_ms": 0,
        "combined_output": None,
    }

    if experiment == 1:
        # 步骤1: 评价 -> correctness, completeness, hasProgress
        schema1 = json.dumps(
            build_schema(["correctness", "completeness", "hasProgress"]),
            ensure_ascii=False,
        )
        prompt1 = EVAL_EXP1_PROMPT.format(
            question_json=question_json, confirmed_text=confirmed, schema=schema1
        )
        r1 = call_model(prompt1)
        result["steps"].append(
            {"call": "eval", "fields": ["correctness", "completeness", "hasProgress"],
             "prompt": prompt1, "response": r1}
        )
        eval_data = parse_json(r1.get("content", "{}")) if r1.get("ok") else {}
        correctness = eval_data.get("correctness", "UNCERTAIN")
        completeness = eval_data.get("completeness", "INCOMPLETE")
        hasProgress = eval_data.get("hasProgress", False)

        # 步骤2: 教学 -> main_reason, other_reasons, judge_reason, content, questions
        schema2 = json.dumps(
            build_schema(
                ["main_reason", "other_reasons", "judge_reason", "content", "questions"]
            ),
            ensure_ascii=False,
        )
        prompt2 = TEACH_EXP1_PROMPT.format(
            question_json=question_json,
            confirmed_text=confirmed,
            schema=schema2,
            correctness=correctness,
            completeness=completeness,
            hasProgress=hasProgress,
        )
        r2 = call_model(prompt2)
        result["steps"].append(
            {"call": "teach",
             "fields": ["main_reason", "other_reasons", "judge_reason", "content", "questions"],
             "prompt": prompt2, "response": r2}
        )
        teach_data = parse_json(r2.get("content", "{}")) if r2.get("ok") else {}
        result["total_duration_ms"] = sum(
            s["response"].get("duration_ms", 0) for s in result["steps"]
        )
        result["combined_output"] = {**eval_data, **teach_data}

    elif experiment == 2:
        # 步骤1: 评价 + 错因 -> correctness, completeness, hasProgress, main_reason, other_reasons, judge_reason
        schema1 = json.dumps(
            build_schema(
                [
                    "correctness", "completeness", "hasProgress",
                    "main_reason", "other_reasons", "judge_reason",
                ]
            ),
            ensure_ascii=False,
        )
        prompt1 = EVAL_EXP2_PROMPT.format(
            question_json=question_json, confirmed_text=confirmed, schema=schema1
        )
        r1 = call_model(prompt1)
        result["steps"].append(
            {"call": "eval",
             "fields": ["correctness", "completeness", "hasProgress",
                        "main_reason", "other_reasons", "judge_reason"],
             "prompt": prompt1, "response": r1}
        )
        eval_data = parse_json(r1.get("content", "{}")) if r1.get("ok") else {}

        # 步骤2: 教学 -> content, questions
        schema2 = json.dumps(
            build_schema(["content", "questions"]), ensure_ascii=False
        )
        prompt2 = TEACH_EXP2_PROMPT.format(
            question_json=question_json,
            confirmed_text=confirmed,
            schema=schema2,
            correctness=eval_data.get("correctness", "UNCERTAIN"),
            completeness=eval_data.get("completeness", "INCOMPLETE"),
            hasProgress=eval_data.get("hasProgress", False),
            main_reason=eval_data.get("main_reason", "原因未明"),
            other_reasons=json.dumps(
                eval_data.get("other_reasons", []), ensure_ascii=False
            ),
            judge_reason=eval_data.get("judge_reason", ""),
        )
        r2 = call_model(prompt2)
        result["steps"].append(
            {"call": "teach", "fields": ["content", "questions"],
             "prompt": prompt2, "response": r2}
        )
        teach_data = parse_json(r2.get("content", "{}")) if r2.get("ok") else {}
        result["total_duration_ms"] = sum(
            s["response"].get("duration_ms", 0) for s in result["steps"]
        )
        result["combined_output"] = {**eval_data, **teach_data}

    elif experiment == 3:
        # 一次调用 -> 全部字段
        schema1 = json.dumps(
            build_schema(
                [
                    "correctness", "completeness", "hasProgress",
                    "main_reason", "other_reasons", "judge_reason",
                    "content", "questions",
                ]
            ),
            ensure_ascii=False,
        )
        prompt1 = MERGED_EXP3_PROMPT.format(
            question_json=question_json, confirmed_text=confirmed, schema=schema1
        )
        r1 = call_model(prompt1)
        result["steps"].append(
            {"call": "merged",
             "fields": ["correctness", "completeness", "hasProgress", "main_reason",
                        "other_reasons", "judge_reason", "content", "questions"],
             "prompt": prompt1, "response": r1}
        )
        merged_data = parse_json(r1.get("content", "{}")) if r1.get("ok") else {}
        result["total_duration_ms"] = r1.get("duration_ms", 0)
        result["combined_output"] = merged_data

    return result


def main():
    experiments = [1, 2, 3]
    all_results = []
    for exp in experiments:
        for stu in STUDENT_ANSWERS:
            print(f"[RUN] 实验{exp} | {stu['id']} ...", flush=True)
            res = run_case(exp, stu)
            all_results.append(res)
            print(
                f"      ok={all(s['response'].get('ok') for s in res['steps'])} "
                f"total={res['total_duration_ms']}ms", flush=True
            )

    out_path = BASE_DIR / "ab_experiment_results.json"
    out_path.write_text(
        json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nDONE -> {out_path}", flush=True)


if __name__ == "__main__":
    main()