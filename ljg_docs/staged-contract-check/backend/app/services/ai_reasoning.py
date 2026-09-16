"""Provider-aware reasoning effort resolution.

各模型对推理强度（reasoning_effort）的参数格式不同，本模块统一将
配置值映射为 provider 所需的实际请求参数。
"""


def resolve_reasoning_params(model: str, reasoning_effort: str | None) -> dict[str, object]:
    """根据模型名称和配置值，返回 provider 特有的请求参数。

    当 reasoning_effort 为 None 或空字符串时返回空 dict，行为和未配置时一致。
    """
    if not reasoning_effort:
        return {}

    model_lower = model.lower().strip()

    # DeepSeek 系列：标准 reasoning_effort + thinking type
    if model_lower.startswith("deepseek"):
        return {
            "reasoning_effort": reasoning_effort,
            "thinking": {"type": "enabled"},
        }

    # GLM / 智谱系列：标准 reasoning_effort + thinking type + clear_thinking
    if model_lower.startswith("glm"):
        return {
            "reasoning_effort": reasoning_effort,
            "thinking": {"type": "enabled", "clear_thinking": False},
        }

    # Qwen 系列（阿里百炼）：不支持 reasoning_effort，改用 enable_thinking 布尔值
    if model_lower.startswith("qwen"):
        return {
            "enable_thinking": reasoning_effort in ("high", "max", "on", "true"),
        }

    # 兜底：标准 OpenAI reasoning_effort，由模型自行忽略或处理
    return {"reasoning_effort": reasoning_effort}