from app.schemas.question import QuestionProgress

PROGRESS_COMPLETED: QuestionProgress = "COMPLETED"
PROGRESS_ATTEMPTED: QuestionProgress = "ATTEMPTED"
PROGRESS_NOT_ATTEMPTED: QuestionProgress = "NOT_ATTEMPTED"


def question_progress(*, has_completed: bool, has_attempt: bool) -> QuestionProgress:
    """按「已完成 > 尝试过 > 未尝试」的优先级判定单题自讲进度。

    has_completed 表示该用户对该题目存在学习成功终态会话（含重新自讲前已完成的会话）；
    has_attempt 表示该用户对该题目提交过至少一次自讲（含语音转写确认）。
    """
    if has_completed:
        return PROGRESS_COMPLETED
    if has_attempt:
        return PROGRESS_ATTEMPTED
    return PROGRESS_NOT_ATTEMPTED
