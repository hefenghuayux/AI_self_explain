from decimal import ROUND_HALF_UP, Decimal

FIRST_EXPLANATION_GRADING_VERSION = "FIRST_SELF_EXPLANATION_V1"


def calculate_total_score(correctness_score: int, completeness_score: int) -> float:
    if not 0 <= correctness_score <= 4 or not 0 <= completeness_score <= 4:
        raise ValueError("正确性和完整性分数必须在 0 到 4 之间")
    value = Decimal(100) * Decimal(correctness_score + completeness_score) / Decimal(8)
    return float(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
