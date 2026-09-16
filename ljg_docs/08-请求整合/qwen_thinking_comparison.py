# -*- coding: utf-8 -*-
"""
Qwen3.8-flash thinking 开关对比测试：enable_thinking=True vs False。
同一请求（实验3合并版，学生A），其他参数完全一致。
"""
import json
import pathlib
import time
import urllib.request
import urllib.error

QWEN_CFG = {
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "api_key": "sk-ws-H.EHDYIPL.cCpm.MEUCIQDt2RlXes4TEuKyFq7tf7-_4-ZXGa0GHcm8juhKZkm39AIgHWVN5OQcRLEkojoY1Et-VMBpJKVN3vSWc21uILbZ4DM",
    "model": "qwen3.8-flash",
}

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

STUDENT_A = {
    "confirmedText": (
        "这题二次函数开口向上，因为 x² 系数是 1 大于 0。闭区间 [0,2] 上的最大值"
        "应该在端点 x=0 或 x=2 取到。先算 f(0)=2a-1，f(2)=3-2a，"
        "然后令 f(0)=3 得 a=2，这时候 f(2)=-1。最大值就是 3。"
    ),
    "progressContext": {"previousExplanations": [], "previousTeaching": []},
}

EVAL_TEMPLATE = r"""你是 AI 自讲 Demo 的评价与教学内容生成器。基于提供的题目材料和学生最终确认文本完成两项工作：第一步评价学生的正确性和完整性；第二步根据评价结果和进展情况生成教学内容。

后端在上下文中传入 `taskType = EXPLANATION`，你不能自行选择或切换任务类型。只有上下文中由后端明确提供的评价或动作才能视为已确定，不能假定本次答案已经评价。状态、计数和阈值由后端控制。

必须只输出符合下方 JSON Schema 的 JSON 对象，不要输出 Markdown、解释或额外字段。

## 第一步：评价

- `correctness`：`CORRECT`（正确）、`WRONG`（有错误）、`UNCERTAIN`（无法可靠判断）
- `completeness`：`COMPLETE`（完整覆盖全部评分点）、`INCOMPLETE`（存在缺失）
- `correctness = UNCERTAIN` 时必须填写非空的 `needHumanReason`；其他正确性下必须为 `null`

评价依据写入评价字段，面向学生的帮助写入教学字段。

## 第二步：教学内容生成

根据评价结果和是否有解题进展来决定 `main_reason`、`other_reasons`、`judge_reason`、`teachingAction`、`content` 和 `questions`。`hasProgress` 必须返回；教学动作由模型直接选择，后端只记录该判断。

### 原因

填写本轮当前卡点的一个主要原因到 `main_reason`，只能使用以下名称之一：`表达与输入问题`、`题意理解问题`、`知识理解与回忆问题`、`知识应用问题`、`执行错误`、`原因未明`。将其他可能或次要原因填入 `other_reasons`，没有时返回 `[]`。`judge_reason` 用一小段话说明依据。原因是本轮可修正的假设，不是学生的长期标签。终态和 `UNCERTAIN` 仍必须填写这些字段，但不得生成教学内容。

### 如何判断是否有解题进展

返回布尔值 `hasProgress`。根据历史自讲和当前确认文本判断是否出现有效的新推理、纠正错误、补充依据或合理的替代解法。

首次自讲没有历史时，只要提出了与本题有关的有效推理就视为有进展；只表达疑问或不知道、机械复述已有内容，不算进展。结合 `progressContext.previousTeaching` 区分学生自己的推理与提示复述。完成和无法可靠判断时仍填写 `hasProgress`，但优先执行终态或不确定评价规则。

### 动作选择表

| 判断顺序 | content | questions |
|---|---|---|
| `CORRECT + COMPLETE` 或 `UNCERTAIN` | `null` | `[]` |
| `hasProgress = false` | 提示正文 | `[]` |
| `WRONG` | 纠错正文 | `[]` |
| `INCOMPLETE` | 聚焦追问正文 | 恰好一个问题 |

### 教学内容约束

- 不得直接复述标准答案或完整解析，不得泄露后续评分点答案
- `content` 中不得包含待回答的问题文本；追问问题只能放在 `questions` 中
- 反馈只说有依据的具体变化；确有进展时可逐字引用一句原话，无须固定表扬；没有明确进展时直接提供当前所需的帮助
- `content` 不加标题、标记或格式前缀，直接输出完整文本

### 各动作的具体要求

- `ASK_FOCUSED_QUESTION`：用一个有区分力的开放问题验证关键依据，不先提供答案；`content` 是追问引导（1～2句），`questions` 中是具体问题
- `GIVE_HINT`：提供推动当前步骤的最小提示，不展开完整基础讲解
- `GIVE_CORRECTION`：修正已确认的局部错误并说明必要依据，用陈述式引导学生重新组织该步解释
- `CORRECT_AND_ASK`：先指出已确认的局部错误，再用一个问题验证关键依据；纠错内容不要提前回答该问题

### 原因假设（可选推理框架）

生成教学内容前，先根据学生原文、评价结果和已有历史确定 `main_reason`，再列出可选的 `other_reasons` 并填写 `judge_reason`。原因只用于本轮内容组织，不能作为长期标签。证据不足时使用"原因未明"，不得强行归因。

- 表达与输入问题：理解正确但表达遗漏或文本含义不清 → 先请学生补充或确认原意
- 题意理解问题：误解或遗漏条件 → 请学生复述相关条件
- 知识理解与回忆问题：不知道或误解概念 → 最小问题确认或正反例区分
- 知识应用问题：知道知识但不会用于本题 → 说明条件与知识的联系
- 执行错误：计算、抄写等操作出错 → 请学生对出错局部重算核对
- 原因未明：信息不足或证据冲突 → 最小澄清问题

### 错误处理

- 若提供了上一轮校验错误，必须保留符合学生文本的正确性、完整性和评分点判断，只修正结构或关系错误
- 不能为了通过校验随意改成 `UNCERTAIN`

JSON Schema：
{{JSON_SCHEMA}}

评价上下文：
{{CONTEXT_JSON}}

如上一轮结构校验失败，请依据以下错误重新输出完整 JSON：
{{VALIDATION_ERRORS}}"""


def build_schema():
    return json.dumps({
        "type": "object",
        "properties": {
            "correctness": {"type": "string", "enum": ["CORRECT", "WRONG", "UNCERTAIN"]},
            "completeness": {"type": "string", "enum": ["COMPLETE", "INCOMPLETE"]},
            "hasProgress": {"type": "boolean"},
            "main_reason": {"type": "string", "enum": ["表达与输入问题", "题意理解问题", "知识理解与回忆问题", "知识应用问题", "执行错误", "原因未明"]},
            "other_reasons": {"type": "array", "items": {"type": "string", "enum": ["表达与输入问题", "题意理解问题", "知识理解与回忆问题", "知识应用问题", "执行错误", "原因未明"]}},
            "judge_reason": {"type": "string"},
            "content": {"type": "string"},
            "questions": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "string"}, "question": {"type": "string"}}, "required": ["question"], "additionalProperties": False}},
        },
        "required": ["correctness", "completeness", "hasProgress", "main_reason", "other_reasons", "judge_reason", "content", "questions"],
        "additionalProperties": False,
    }, ensure_ascii=False, indent=2)


def build_context_json():
    return json.dumps({
        "taskType": "EXPLANATION",
        "questionContent": QUESTION["questionContent"],
        "standardAnswer": QUESTION["standardAnswer"],
        "rubricPoints": QUESTION["rubricPoints"],
        "commonErrors": QUESTION["commonErrors"],
        "alternativeSolutions": QUESTION["alternativeSolutions"],
        "layeredHints": QUESTION["layeredHints"],
        "guidedQuestions": QUESTION["guidedQuestions"],
        "fullSolution": QUESTION["fullSolution"],
        "confirmedText": STUDENT_A["confirmedText"],
        "progressContext": STUDENT_A["progressContext"],
    }, ensure_ascii=False, indent=2)


def build_prompt():
    t = EVAL_TEMPLATE
    t = t.replace(
        "`main_reason`、`other_reasons`、`judge_reason`、`teachingAction`、`content` 和 `questions`。`hasProgress` 必须返回；教学动作由模型直接选择，后端只记录该判断。",
        "`main_reason`、`other_reasons`、`judge_reason`、`content` 和 `questions`。`hasProgress` 必须返回。"
    )
    old_table = (
        "| 判断顺序 | teachingAction | content | questions |\n"
        "|---|---|---|---|\n"
        "| `CORRECT + COMPLETE` 或 `UNCERTAIN` | `null` | `null` | `[]` |\n"
        "| `hasProgress = false` | `GIVE_HINT` | 提示正文 | `[]` |\n"
        "| `WRONG` | `GIVE_CORRECTION` | 纠错正文 | `[]` |\n"
        "| `INCOMPLETE` | `ASK_FOCUSED_QUESTION` | 聚焦追问正文 | 恰好一个问题 |"
    )
    new_table = (
        "| 判断顺序 | content | questions |\n"
        "|---|---|---|\n"
        "| `CORRECT + COMPLETE` 或 `UNCERTAIN` | `null` | `[]` |\n"
        "| `hasProgress = false` | 提示正文 | `[]` |\n"
        "| `WRONG` | 纠错正文 | `[]` |\n"
        "| `INCOMPLETE` | 聚焦追问正文 | 恰好一个问题 |"
    )
    t = t.replace(old_table, new_table)
    t = t.replace("{{JSON_SCHEMA}}", build_schema())
    t = t.replace("{{CONTEXT_JSON}}", build_context_json())
    t = t.replace("{{VALIDATION_ERRORS}}", "[]")
    return t


def call_qwen(prompt: str, enable_thinking: bool, timeout_sec: int = 180) -> dict:
    """
    调用 qwen3.8-flash，控制 enable_thinking 参数。
    使用 extra_body 传递 enable_thinking（类似用户提供的 OpenAI 客户端方式）。
    """
    url = QWEN_CFG["base_url"].rstrip("/") + "/chat/completions"

    payload = {
        "model": QWEN_CFG["model"],
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "temperature": 0.3,
        "max_tokens": 4000,
        # Qwen 通过 extra_body 传递 enable_thinking
        "enable_thinking": enable_thinking,
    }

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {QWEN_CFG['api_key']}",
        "Content-Type": "application/json",
    }

    started = time.perf_counter()
    try:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            resp_body = resp.read().decode("utf-8")
            elapsed_ms = round((time.perf_counter() - started) * 1000)
            result = json.loads(resp_body)
            content = result["choices"][0]["message"]["content"]
            return {
                "ok": True,
                "content": content,
                "duration_ms": elapsed_ms,
                "usage": result.get("usage"),
            }
    except urllib.error.HTTPError as e:
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        err_body = e.read().decode("utf-8", errors="replace")
        return {"ok": False, "duration_ms": elapsed_ms, "error": f"HTTP {e.code}: {err_body}"}
    except Exception as e:
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        return {"ok": False, "duration_ms": elapsed_ms, "error": str(e)}


def main():
    prompt = build_prompt()
    prompt_len = len(prompt)
    print(f"Prompt 长度: {prompt_len} 字符\n")

    test_cases = [
        ("enable_thinking=True", True),
        ("enable_thinking=False", False),
    ]

    results = []

    for label, thinking_val in test_cases:
        print(f"\n▶ 测试: qwen3.8-flash | {label}")
        r = call_qwen(prompt, thinking_val)
        results.append({"label": label, "enable_thinking": thinking_val, "response": r})

        if r["ok"]:
            usage = r.get("usage", {})
            details = (usage.get("completion_tokens_details") or {}) if usage else {}
            reasoning_tokens = details.get("reasoning_tokens", "N/A")
            print(f"  ✅ 成功 | 耗时: {r['duration_ms']}ms")
            print(f"     Usage: {json.dumps(usage, ensure_ascii=False)}")
            print(f"     推理tokens: {reasoning_tokens}")
            print(f"     输出预览: {r['content'][:200]}...")
        else:
            print(f"  ❌ 失败 | 耗时: {r['duration_ms']}ms | 错误: {r.get('error', '未知')}")

    # 汇总
    print("\n\n" + "=" * 70)
    print("📊 Qwen3.8-flash Thinking 开关对比")
    print("=" * 70)
    print(f"{'配置':<25} {'状态':<8} {'耗时(ms)':<12} {'输出长度':<10} {'总tokens':<10} {'推理tokens':<12}")
    print("-" * 77)

    for r in results:
        resp = r["response"]
        status = "✅" if resp["ok"] else "❌"
        dur = resp["duration_ms"]
        out_len = len(resp.get("content", "")) if resp.get("content") else 0
        usage = resp.get("usage")
        total_tokens = usage.get("total_tokens", "N/A") if usage else "N/A"
        details = (usage.get("completion_tokens_details") or {}) if usage else {}
        reasoning_tokens = details.get("reasoning_tokens", "N/A")
        print(f"{r['label']:<25} {status:<8} {str(dur)+'ms':<12} {out_len:<10} {str(total_tokens):<10} {str(reasoning_tokens):<12}")

    if len(results) >= 2 and results[0]["response"]["ok"] and results[1]["response"]["ok"]:
        t1 = results[0]["response"]["duration_ms"]
        t2 = results[1]["response"]["duration_ms"]
        ratio = t1 / t2 if t2 > 0 else 0
        print(f"\n📈 速度比 (True/False): {ratio:.1f}x")
        print(f"    (enable_thinking=True 比 False 慢 {ratio:.1f} 倍)")

    # 保存
    out_dir = pathlib.Path(__file__).resolve().parent
    out_path = out_dir / "qwen_thinking_comparison.json"
    output = {
        "prompt_char_len": prompt_len,
        "test_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "student": "A-有进展正确不完整",
        "results": [],
    }
    for r in results:
        entry = {
            "label": r["label"],
            "enable_thinking": r["enable_thinking"],
            "ok": r["response"]["ok"],
            "duration_ms": r["response"]["duration_ms"],
            "usage": r["response"].get("usage"),
        }
        if r["response"]["ok"]:
            entry["content_preview"] = r["response"]["content"][:500]
        else:
            entry["error"] = r["response"].get("error")
        output["results"].append(entry)

    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n📁 结果已保存: {out_path}")


if __name__ == "__main__":
    main()