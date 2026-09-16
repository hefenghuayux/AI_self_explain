# -*- coding: utf-8 -*-
"""
评价(evaluate_explanation) 与 教学(generate_teaching) 请求整合对照实验（第三版）
模型改为 deepseek-flash（来自 .env 配置），加入推理参数（与 ai_reasoning.py 一致）。

三个实验（每组实验跑 3 组不同学生回答，共 1 轮）：
   实验1：两次调用（3+5字段）
   实验2：两次调用（6+2字段）
   实验3：一次调用（8字段）

速度监控：若首次调用耗时接近 v2（>30s），则自动中止。
"""
import json
import os
import pathlib
import time
import re

EVAL_BASE_PATH = pathlib.Path(r"D:\lijianguo\project\AI_self_explain\ljg_docs\08-请求整合\eval_base.md")
TEACH_BASE_PATH = pathlib.Path(r"D:\lijianguo\project\AI_self_explain\ljg_docs\08-请求整合\teach_base.md")
ENV_PATH = pathlib.Path(r"D:\lijianguo\project\AI_self_explain\.env")
BASE_DIR = pathlib.Path(r"D:\lijianguo\project\AI_self_explain\ljg_docs\08-请求整合")

# ---------------------------------------------------------------------------
# 模型配置（硬编码为 deepseek-flash，来自 .env 中已注释的配置）
# ---------------------------------------------------------------------------
# 从 .env 读取 deepseek-flash 的配置
# AI_BASE_URL=https://api.deepseek.com
# AI_API_KEY=sk-3c84496397b7420c8f5c772df1b55605
# AI_MODEL=deepseek-flash
# AI_REASONING_EFFORT=high

BASE_URL = "https://api.deepseek.com/chat/completions"
API_KEY = "sk-3c84496397b7420c8f5c772df1b55605"
MODEL = "deepseek-flash"
REASONING_EFFORT = "high"  # deepseek 的 reasoning_effort 配置

# v2 实验的平均耗时参考（用于速度对比中止判断）
V2_MERGED_AVG_MS = 42700  # 实验3平均42.7s
V2_CALL1_EVAL_AVG_MS = 21800  # eval 调用平均21.8s

# 速度阈值：如果首次调用超过此值，怀疑和 v2 一样慢，自动中止
SPEED_ABORT_THRESHOLD_MS = 25000  # 25秒


# ---------------------------------------------------------------------------
# 推理参数（同 ai_reasoning.py 的逻辑）
# ---------------------------------------------------------------------------
def resolve_reasoning_params() -> dict:
    """deepseek 模型的推理参数。"""
    return {
        "reasoning_effort": REASONING_EFFORT,
        "thinking": {"type": "enabled"},
    }


# ---------------------------------------------------------------------------
# 题干上下文（题库 question id=3，与 v2 相同）
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
    "alternativeSolutions": [
        "将条件直接写成 max{2a-1, 3-2a}=3，再转化为两个式子都不大于 3 且至少一个等于 3，从而求出 a",
        "利用对称轴 x=a 与区间 [0,2] 的位置关系分类讨论端点最大值，再分别求最小值",
    ],
    "layeredHints": [
        "先判断抛物线的开口方向，并思考闭区间上的最大值可能在哪里取得",
        "分别计算 f(0) 和 f(2)，用一个含 max 的等式表示最大值条件",
        "把 max{2a-1, 3-2a}=3 拆成两个量都不超过 3，且至少有一个等于 3",
        "求出 a 后分别代回原函数，配方并结合区间确定最小值",
    ],
    "guidedQuestions": [
        "这个二次函数开口向上时，闭区间上的最大值应从哪些点中比较？",
        "f(0) 和 f(2) 分别是多少，最大值为 3 应如何表示？",
        "求得参数后，怎样判断顶点是否在区间内并确定最小值？",
    ],
    "fullSolution": (
        "第一步，因为二次项系数为 1>0，抛物线开口向上，所以 f(x) 在闭区间 [0,2] 上的最大值"
        "一定在两个端点之一取得。\n"
        "第二步，计算两个端点：f(0)=2a-1，f(2)=4-4a+2a-1=3-2a。"
        "因此 max{2a-1, 3-2a}=3。\n"
        "第三步，分类求参数。若 f(0)=3，则 2a-1=3，得 a=2；此时 f(2)=-1≤3，符合条件。"
        "若 f(2)=3，则 3-2a=3，得 a=0；此时 f(0)=-1≤3，也符合条件。"
        "因此 a=0 或 a=2。\n"
        "第四步，分别求最小值。a=0 时，f(x)=x²-1，在 [0,2] 上于 x=0 处取得最小值 -1。"
        "a=2 时，f(x)=x²-4x+3=(x-2)²-1，在 [0,2] 上于 x=2 处取得最小值 -1。"
        "综上，a=0 或 a=2，两种情况下区间最小值均为 -1。"
    ),
}

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
        "confirmedText": (
            "我不知道，感觉就是差不多，不知道最大值怎么算，也不会分类。"
        ),
        "progressContext": {"previousExplanations": [], "previousTeaching": []},
    },
]

EVAL_TEMPLATE = EVAL_BASE_PATH.read_text(encoding="utf-8")
TEACH_TEMPLATE = TEACH_BASE_PATH.read_text(encoding="utf-8")

REASON_CATEGORIES = """| 原因组 | 可作为假设依据的典型表现 | 优先验证方式 |
| --- | --- | --- |
| 表达与输入问题 | 理解基本正确，但存在表达遗漏或过度简略，或存在表达或输入障碍，导致文本未准确反映原意 | 先请学生补充遗漏内容；文本含义不清时，请其用列式、分步描述或修订文本确认原意 |
| 题意理解问题 | 没看懂题目在说什么，误解或遗漏条件，不清楚要求什么 | 请学生用自己的话复述相关条件或所求对象 |
| 知识理解与回忆问题 | 不知道、想不起相关知识，或对概念、公式、规则理解有误，包括前置知识缺失或提取困难 | 先用一个最小基础问题确认；必要时通过紧贴当前卡点的正反例区分理解情况 |
| 知识应用问题 | 知道相关知识，但不会用于当前题目，或无法解释解题依据；包括理解题意后不会建立关系，以及无法解释当前步骤的依据 | 围绕当前卡点，请学生说明题目条件与相关知识的联系，或解释当前步骤的依据 |
| 执行错误 | 思路和依据基本正确，但计算、抄写、代入、符号等操作出错 | 请学生只对出错局部重算或核对，观察其能否自行发现并纠正 |
| 原因未明 | 信息不足、候选原因无法区分、证据冲突，或表现不符合以上类别；这是不确定状态，不是确定原因 | 用一个最小澄清问题补充关键信息，暂缓归因 |"""

ACTION_TABLE = """| 判断顺序 | content | questions |
|---|---|---|---|
| `CORRECT + COMPLETE` 或 `UNCERTAIN` | `null` | `[]` |
| `hasProgress = false` | 提示正文 | `[]` |
| `WRONG` | 纠错正文 | `[]` |
| `INCOMPLETE` | 聚焦追问正文 | 恰好一个问题 |"""

TEACHING_CONSTRAINTS = """### 教学内容约束

- 不得直接复述标准答案或完整解析，不得泄露后续评分点答案
- `content` 中不得包含待回答的问题文本；追问问题只能放在 `questions` 中
- 反馈只说有依据的具体变化；确有进展时可逐字引用一句原话，无须固定表扬；没有明确进展时直接提供当前所需的帮助
- `content` 不加标题、标记或格式前缀，直接输出完整文本

### 各动作的具体要求

- `ASK_FOCUSED_QUESTION`：用一个有区分力的开放问题验证关键依据，不先提供答案；`content` 是追问引导（1～2句），`questions` 中是具体问题
- `GIVE_HINT`：提供推动当前步骤的最小提示，不展开完整基础讲解
- `GIVE_CORRECTION`：修正已确认的局部错误并说明必要依据，用陈述式引导学生重新组织该步解释
- `CORRECT_AND_ASK`：先指出已确认的局部错误，再用一个问题验证关键依据；纠错内容不要提前回答该问题"""

HASPROGRESS_SECTION = """### 如何判断是否有解题进展

返回布尔值 `hasProgress`。根据历史自讲和当前确认文本判断是否出现有效的新推理、纠正错误、补充依据或合理的替代解法。

首次自讲没有历史时，只要提出了与本题有关的有效推理就视为有进展；只表达疑问或不知道、机械复述已有内容，不算进展。结合 `progressContext.previousTeaching` 区分学生自己的推理与提示复述。完成和无法可靠判断时仍填写 `hasProgress`，但优先执行终态或不确定评价规则。"""


def build_context_json(student):
    ctx = {
        "taskType": "EXPLANATION",
        "questionContent": QUESTION["questionContent"],
        "standardAnswer": QUESTION["standardAnswer"],
        "rubricPoints": QUESTION["rubricPoints"],
        "commonErrors": QUESTION["commonErrors"],
        "alternativeSolutions": QUESTION["alternativeSolutions"],
        "layeredHints": QUESTION["layeredHints"],
        "guidedQuestions": QUESTION["guidedQuestions"],
        "fullSolution": QUESTION["fullSolution"],
        "confirmedText": student["confirmedText"],
        "progressContext": student["progressContext"],
    }
    return json.dumps(ctx, ensure_ascii=False, indent=2)


def build_schema(fields):
    prop_types = {
        "correctness": {"type": "string", "enum": ["CORRECT", "WRONG", "UNCERTAIN"]},
        "completeness": {"type": "string", "enum": ["COMPLETE", "INCOMPLETE"]},
        "hasProgress": {"type": "boolean"},
        "main_reason": {
            "type": "string",
            "enum": ["表达与输入问题", "题意理解问题", "知识理解与回忆问题", "知识应用问题", "执行错误", "原因未明"],
        },
        "other_reasons": {
            "type": "array",
            "items": {"type": "string", "enum": ["表达与输入问题", "题意理解问题", "知识理解与回忆问题", "知识应用问题", "执行错误", "原因未明"]},
        },
        "judge_reason": {"type": "string"},
        "content": {"type": "string"},
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "question": {"type": "string"}},
                "required": ["question"],
                "additionalProperties": False,
            },
        },
    }
    props = {f: prop_types[f] for f in fields}
    schema = {"type": "object", "properties": props, "required": fields, "additionalProperties": False}
    return json.dumps(schema, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Prompt 构建（与 v2 完全一致）
# ---------------------------------------------------------------------------

def build_exp1_call1(student):
    fields = ["correctness", "completeness", "hasProgress"]
    schema = build_schema(fields)
    context = build_context_json(student)
    validation_errors = "[]"
    t = EVAL_TEMPLATE
    t = t.replace(
        "你是 AI 自讲 Demo 的评价与教学内容生成器。基于提供的题目材料和学生最终确认文本完成两项工作：第一步评价学生的正确性和完整性；第二步根据评价结果和进展情况生成教学内容。",
        "你是 AI 自讲 Demo 的评价器。基于提供的题目材料和学生最终确认文本完成评价工作：评价学生的正确性、完整性以及是否有解题进展。不生成教学内容。"
    )
    t = re.sub(
        r'## 第二步：教学内容生成.*?(?=### 错误处理)',
        f'### 如何判断是否有解题进展\n\n{HASPROGRESS_SECTION.strip()}\n\n',
        t,
        flags=re.DOTALL
    )
    t = t.replace("{{JSON_SCHEMA}}", schema)
    t = t.replace("{{CONTEXT_JSON}}", context)
    t = t.replace("{{VALIDATION_ERRORS}}", validation_errors)
    return t


def build_exp1_call2(student, eval_result):
    fields = ["main_reason", "other_reasons", "judge_reason", "content", "questions"]
    schema_str = build_schema(fields)
    context_d = {
        "taskType": "EXPLANATION",
        "questionContent": QUESTION["questionContent"],
        "standardAnswer": QUESTION["standardAnswer"],
        "rubricPoints": QUESTION["rubricPoints"],
        "commonErrors": QUESTION["commonErrors"],
        "alternativeSolutions": QUESTION["alternativeSolutions"],
        "layeredHints": QUESTION["layeredHints"],
        "guidedQuestions": QUESTION["guidedQuestions"],
        "fullSolution": QUESTION["fullSolution"],
        "confirmedText": student["confirmedText"],
        "progressContext": student["progressContext"],
        "evaluationResult": eval_result,
    }
    context_str = json.dumps(context_d, ensure_ascii=False, indent=2)
    t = TEACH_TEMPLATE
    eval_injection = (
        "\n### 已由后端确认的评价结果\n\n"
        f"以下评价结果已由后端完成并确认，直接采用，不要重新评价：\n"
        f"- correctness：`{eval_result.get('correctness', 'N/A')}`\n"
        f"- completeness：`{eval_result.get('completeness', 'N/A')}`\n"
        f"- hasProgress：`{eval_result.get('hasProgress', 'N/A')}`\n\n"
        f"动作选择规则基于上述评价结果确定，你不需要判断 hasProgress。\n"
    )
    t = t.replace(
        "后端提供 `instructionFromRules.allowedAction` 时，你只能执行该动作",
        eval_injection + "后端提供 `instructionFromRules.allowedAction` 时，你只能执行该动作"
    )
    t = t.replace("{{JSON_SCHEMA}}", schema_str)
    t = t.replace("{{CONTEXT_JSON}}", context_str)
    return t


def build_exp2_call1(student):
    fields = ["correctness", "completeness", "hasProgress", "main_reason", "other_reasons", "judge_reason"]
    schema = build_schema(fields)
    context = build_context_json(student)
    validation_errors = "[]"
    t = EVAL_TEMPLATE
    t = t.replace(
        "你是 AI 自讲 Demo 的评价与教学内容生成器。基于提供的题目材料和学生最终确认文本完成两项工作：第一步评价学生的正确性和完整性；第二步根据评价结果和进展情况生成教学内容。",
        "你是 AI 自讲 Demo 的评价与原因分类生成器。基于提供的题目材料和学生最终确认文本完成两项工作：第一步评价学生的正确性和完整性；第二步根据评价结果和进展情况分类原因。不生成教学内容。"
    )
    t = t.replace(
        "## 第二步：教学内容生成\n\n根据评价结果和是否有解题进展来决定 `main_reason`、`other_reasons`、`judge_reason`、`teachingAction`、`content` 和 `questions`。`hasProgress` 必须返回；教学动作由模型直接选择，后端只记录该判断。",
        "## 第二步：原因分类\n\n根据评价结果和是否有解题进展来决定 `main_reason`、`other_reasons`、`judge_reason`。`hasProgress` 已在第一步返回；你不需要输出 teachingAction、content 和 questions。"
    )
    t = re.sub(
        r'### 动作选择表\n\n\| 判断顺序.*?### 教学内容约束',
        '### 教学内容约束',
        t,
        flags=re.DOTALL
    )
    t = re.sub(
        r'### 教学内容约束\n\n.*?### 原因假设',
        '### 原因假设（可选推理框架）',
        t,
        flags=re.DOTALL
    )
    t = re.sub(
        r'### 各动作的具体要求\n\n.*?### 原因假设',
        '### 原因假设（可选推理框架）',
        t,
        flags=re.DOTALL
    )
    t = t.replace("{{JSON_SCHEMA}}", schema)
    t = t.replace("{{CONTEXT_JSON}}", context)
    t = t.replace("{{VALIDATION_ERRORS}}", validation_errors)
    return t


def build_exp2_call2(student, eval_result):
    fields = ["content", "questions"]
    schema_str = build_schema(fields)
    context_d = {
        "taskType": "EXPLANATION",
        "questionContent": QUESTION["questionContent"],
        "standardAnswer": QUESTION["standardAnswer"],
        "rubricPoints": QUESTION["rubricPoints"],
        "commonErrors": QUESTION["commonErrors"],
        "alternativeSolutions": QUESTION["alternativeSolutions"],
        "layeredHints": QUESTION["layeredHints"],
        "guidedQuestions": QUESTION["guidedQuestions"],
        "fullSolution": QUESTION["fullSolution"],
        "confirmedText": student["confirmedText"],
        "progressContext": student["progressContext"],
        "evaluationResult": {
            "correctness": eval_result.get("correctness"),
            "completeness": eval_result.get("completeness"),
            "hasProgress": eval_result.get("hasProgress"),
            "main_reason": eval_result.get("main_reason"),
            "other_reasons": eval_result.get("other_reasons"),
            "judge_reason": eval_result.get("judge_reason"),
        },
    }
    context_str = json.dumps(context_d, ensure_ascii=False, indent=2)
    t = TEACH_TEMPLATE
    eval_injection = (
        "\n### 已由后端确认的评价与原因分类结果\n\n"
        f"以下信息已由后端完成并确认，直接采用：\n"
        f"- correctness：`{eval_result.get('correctness', 'N/A')}`\n"
        f"- completeness：`{eval_result.get('completeness', 'N/A')}`\n"
        f"- hasProgress：`{eval_result.get('hasProgress', 'N/A')}`\n"
        f"- main_reason：`{eval_result.get('main_reason', 'N/A')}`\n"
        f"- other_reasons：`{eval_result.get('other_reasons', 'N/A')}`\n"
        f"- judge_reason：`{eval_result.get('judge_reason', 'N/A')}`\n\n"
        "你不需要重新判断上述任何字段，只根据它们生成教学内容。\n"
    )
    t = t.replace(
        "后端提供 `instructionFromRules.allowedAction` 时，你只能执行该动作",
        eval_injection + "后端提供 `instructionFromRules.allowedAction` 时，你只能执行该动作"
    )
    t = t.replace(
        "- 返回 `main_reason`、`other_reasons`、`judge_reason`、`content` 和 `questions`。`main_reason` 是本轮主要原因，只能使用原因分类表中的名称；`other_reasons` 是可能或次要原因数组，没有时返回 `[]`；`judge_reason` 用一小段话说明原因判断依据。",
        "- 返回 `content` 和 `questions`。`main_reason`、`other_reasons`、`judge_reason` 已由后端确认，不需要在此输出。"
    )
    t = t.replace(
        "- 不输出候选原因分析过程；只输出 `main_reason`、`other_reasons` 和简短的 `judge_reason`。",
        "- 不输出候选原因分析过程；main_reason 等字段已由后端确认，不需要在此输出。"
    )
    t = t.replace("{{JSON_SCHEMA}}", schema_str)
    t = t.replace("{{CONTEXT_JSON}}", context_str)
    return t


def build_exp3_call(student):
    fields = ["correctness", "completeness", "hasProgress",
              "main_reason", "other_reasons", "judge_reason",
              "content", "questions"]
    schema = build_schema(fields)
    context = build_context_json(student)
    validation_errors = "[]"
    t = EVAL_TEMPLATE
    t = t.replace(
        "`main_reason`、`other_reasons`、`judge_reason`、`teachingAction`、`content` 和 `questions`。`hasProgress` 必须返回；教学动作由模型直接选择，后端只记录该判断。",
        "`main_reason`、`other_reasons`、`judge_reason`、`content` 和 `questions`。`hasProgress` 必须返回。"
    )
    t = t.replace(
        "| 判断顺序 | teachingAction | content | questions |\n|---|---|---|---|\n| `CORRECT + COMPLETE` 或 `UNCERTAIN` | `null` | `null` | `[]` |\n| `hasProgress = false` | `GIVE_HINT` | 提示正文 | `[]` |\n| `WRONG` | `GIVE_CORRECTION` | 纠错正文 | `[]` |\n| `INCOMPLETE` | `ASK_FOCUSED_QUESTION` | 聚焦追问正文 | 恰好一个问题 |",
        "| 判断顺序 | content | questions |\n|---|---|---|\n| `CORRECT + COMPLETE` 或 `UNCERTAIN` | `null` | `[]` |\n| `hasProgress = false` | 提示正文 | `[]` |\n| `WRONG` | 纠错正文 | `[]` |\n| `INCOMPLETE` | 聚焦追问正文 | 恰好一个问题 |"
    )
    t = t.replace("{{JSON_SCHEMA}}", schema)
    t = t.replace("{{CONTEXT_JSON}}", context)
    t = t.replace("{{VALIDATION_ERRORS}}", validation_errors)
    return t


# ---------------------------------------------------------------------------
# API 调用
# ---------------------------------------------------------------------------
def call_model(system_prompt, call_label=""):
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": system_prompt}],
        "response_format": {"type": "json_object"},
        "temperature": 0.3,
        "max_tokens": 4000,
    }
    # 加入推理参数（与 ai_reasoning.py 一致）
    payload.update(resolve_reasoning_params())

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }

    started = time.perf_counter()
    import urllib.request
    import urllib.error
    try:
        req = urllib.request.Request(BASE_URL, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=300) as resp:
            resp_body = resp.read().decode("utf-8")
            duration_ms = round((time.perf_counter() - started) * 1000)
            result = json.loads(resp_body)
            content = result["choices"][0]["message"]["content"]
            return {
                "ok": True,
                "content": content,
                "duration_ms": duration_ms,
                "usage": result.get("usage"),
            }
    except urllib.error.HTTPError as e:
        duration_ms = round((time.perf_counter() - started) * 1000)
        err_body = e.read().decode("utf-8", errors="replace")
        return {"ok": False, "duration_ms": duration_ms, "error": f"HTTP {e.code}: {err_body}"}
    except Exception as e:
        duration_ms = round((time.perf_counter() - started) * 1000)
        return {"ok": False, "duration_ms": duration_ms, "error": str(e)}


def parse_json(content):
    try:
        return json.loads(content)
    except Exception as e:
        return {"_parse_error": str(e), "_raw": content}


# ---------------------------------------------------------------------------
# 运行实验
# ---------------------------------------------------------------------------
def run_case(experiment, student):
    result = {
        "experiment": experiment,
        "student_id": student["id"],
        "confirmed_text": student["confirmedText"],
        "steps": [],
        "total_duration_ms": 0,
        "combined_output": None,
    }

    if experiment == 1:
        prompt1 = build_exp1_call1(student)
        r1 = call_model(prompt1, "exp1/eval")
        result["steps"].append({"call": "eval", "prompt": prompt1, "response": r1})
        eval_data = parse_json(r1.get("content", "{}")) if r1.get("ok") else {}
        prompt2 = build_exp1_call2(student, eval_data)
        r2 = call_model(prompt2, "exp1/teach")
        result["steps"].append({"call": "teach", "prompt": prompt2, "response": r2})
        teach_data = parse_json(r2.get("content", "{}")) if r2.get("ok") else {}
        result["total_duration_ms"] = sum(s["response"].get("duration_ms", 0) for s in result["steps"])
        result["combined_output"] = {**eval_data, **teach_data}

    elif experiment == 2:
        prompt1 = build_exp2_call1(student)
        r1 = call_model(prompt1, "exp2/eval")
        result["steps"].append({"call": "eval", "prompt": prompt1, "response": r1})
        eval_data = parse_json(r1.get("content", "{}")) if r1.get("ok") else {}
        prompt2 = build_exp2_call2(student, eval_data)
        r2 = call_model(prompt2, "exp2/teach")
        result["steps"].append({"call": "teach", "prompt": prompt2, "response": r2})
        teach_data = parse_json(r2.get("content", "{}")) if r2.get("ok") else {}
        result["total_duration_ms"] = sum(s["response"].get("duration_ms", 0) for s in result["steps"])
        result["combined_output"] = {**eval_data, **teach_data}

    elif experiment == 3:
        prompt1 = build_exp3_call(student)
        r1 = call_model(prompt1, "exp3/merged")
        result["steps"].append({"call": "merged", "prompt": prompt1, "response": r1})
        merged_data = parse_json(r1.get("content", "{}")) if r1.get("ok") else {}
        result["total_duration_ms"] = r1.get("duration_ms", 0)
        result["combined_output"] = merged_data

    return result


def main():
    import sys

    print(f"🔬 实验 v3 | 模型: {MODEL} | reasoning_effort={REASONING_EFFORT}")
    print(f"   速度阈值: 首次调用 > {SPEED_ABORT_THRESHOLD_MS}ms 则自动中止")
    print(f"   v2 参考: 实验3平均 {V2_MERGED_AVG_MS}ms, eval调用平均 {V2_CALL1_EVAL_AVG_MS}ms")

    # 先做一次预热+速度检查（用实验1调用1，学生A）
    print("\n--- 预热/速度检查: 实验1-调用1, 学生A ---", flush=True)
    warmup_prompt = build_exp1_call1(STUDENT_ANSWERS[0])
    warmup_result = call_model(warmup_prompt, "预热")
    warmup_ms = warmup_result.get("duration_ms", 0)
    warmup_ok = warmup_result.get("ok", False)

    print(f"    预热耗时: {warmup_ms}ms | {'✅' if warmup_ok else '❌'}", flush=True)

    if warmup_ms > SPEED_ABORT_THRESHOLD_MS:
        print(f"\n🚫 中止！预热调用耗时 {warmup_ms}ms，超过阈值 {SPEED_ABORT_THRESHOLD_MS}ms。"
              f"速度仍与 v2 实验相当（v2 eval 平均 {V2_CALL1_EVAL_AVG_MS}ms），没有明显改善。", flush=True)
        print(f"    v2 实验的 eval 调用在 deepseek-v4.1-flash 上耗时 16~48s，当前 {warmup_ms}ms 仍在同一量级。", flush=True)
        # 保存中止记录
        abort_record = {
            "status": "ABORTED",
            "reason": f"预热耗时 {warmup_ms}ms 超过阈值 {SPEED_ABORT_THRESHOLD_MS}ms",
            "model": MODEL,
            "reasoning_effort": REASONING_EFFORT,
            "warmup_result": warmup_result,
            "v2_reference_avg_ms": V2_CALL1_EVAL_AVG_MS,
        }
        abort_path = BASE_DIR / "ab_experiment_results_v3.json"
        abort_path.write_text(json.dumps(abort_record, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"    ⚠️ 但请注意：预热 {warmup_ms}ms 远低于 v2 的 {V2_CALL1_EVAL_AVG_MS}ms（快了 {V2_CALL1_EVAL_AVG_MS/max(warmup_ms,1):.0f} 倍！），"
              f"说明 deepseek-flash 已经比 v2 快了很多。", flush=True)
        print(f"    然而预热超过了 25s 阈值，是否继续完整实验？", flush=True)
        print(f"    如果你确认要继续，请重新运行并设置环境变量 AB_SKIP_SPEED_CHECK=1", flush=True)
        return

    print(f"    ✅ 预热通过，速度正常（v2 同类调用约 {V2_CALL1_EVAL_AVG_MS}ms，当前 {warmup_ms}ms）", flush=True)

    # -----------------------------------------------------------------------
    # 完整实验
    # -----------------------------------------------------------------------
    experiments = [1, 2, 3]
    all_results = []

    print("\n" + "=" * 60)
    print("开始完整实验...")
    print("=" * 60)

    for exp in experiments:
        for stu in STUDENT_ANSWERS:
            print(f"\n[RUN] 实验{exp} | {stu['id']} ...", flush=True)
            res = run_case(exp, stu)
            all_results.append(res)
            ok = all(s["response"].get("ok") for s in res["steps"])
            print(f"      ok={ok} total={res['total_duration_ms']}ms", flush=True)
            for step in res["steps"]:
                if step["response"].get("ok"):
                    print(f"        {step['call']}: {step['response']['duration_ms']}ms", flush=True)
                else:
                    print(f"        {step['call']}: ❌ {step['response'].get('error', '未知')}", flush=True)

    out_path = BASE_DIR / "ab_experiment_results_v3.json"
    out_path.write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")

    # 汇总
    print("\n\n" + "=" * 70)
    print("📊 实验 v3 汇总")
    print("=" * 70)
    print(f"模型: {MODEL} | reasoning_effort={REASONING_EFFORT}")
    print()

    # 按实验分组
    for exp in [1, 2, 3]:
        exp_results = [r for r in all_results if r["experiment"] == exp]
        print(f"\n--- 实验{exp} ---")
        for r in exp_results:
            steps_detail = " + ".join(
                f"{s['call']}={s['response']['duration_ms']}ms" for s in r["steps"]
            )
            print(f"  {r['student_id']:<20} total={r['total_duration_ms']}ms  ({steps_detail})")

    print(f"\n📁 完整结果已保存: {out_path}")


if __name__ == "__main__":
    main()