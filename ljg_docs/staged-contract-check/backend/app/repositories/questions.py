from datetime import UTC, datetime

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models.question import Question
from app.schemas.question import QuestionInput, QuestionListQuery


class QuestionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, question_input: QuestionInput) -> Question:
        question = Question(**question_input.model_dump())
        self.session.add(question)
        self.session.commit()
        self.session.refresh(question)
        return question

    def list_questions(
        self, query: QuestionListQuery, *, include_archived: bool
    ) -> tuple[list[Question], int]:
        conditions = []
        if not include_archived:
            conditions.append(Question.archived_at.is_(None))
        if query.grade_period is not None:
            conditions.append(Question.grade_period == query.grade_period)
        if query.subject is not None:
            conditions.append(Question.subject == query.subject)
        if query.keyword is not None:
            escaped_keyword = query.keyword.replace("\\", "\\\\")
            escaped_keyword = escaped_keyword.replace("%", "\\%").replace("_", "\\_")
            conditions.append(Question.question_content.like(f"%{escaped_keyword}%", escape="\\"))

        total = self.session.scalar(select(func.count()).select_from(Question).where(*conditions))
        statement = (
            select(Question)
            .where(*conditions)
            .order_by(
                case((Question.rubric_points.is_not(None), 0), else_=1),
                Question.created_at.desc(),
                Question.id.desc(),
            )
            .offset((query.page - 1) * query.page_size)
            .limit(query.page_size)
        )
        return list(self.session.scalars(statement)), total or 0

    def list_filter_options(self, *, include_archived: bool) -> tuple[list[int], list[str]]:
        conditions = [] if include_archived else [Question.archived_at.is_(None)]
        grade_periods = list(
            self.session.scalars(
                select(Question.grade_period)
                .where(*conditions, Question.grade_period.is_not(None))
                .distinct()
                .order_by(Question.grade_period)
            )
        )
        subjects = list(
            self.session.scalars(
                select(Question.subject)
                .where(*conditions, Question.subject.is_not(None))
                .distinct()
                .order_by(Question.subject)
            )
        )
        return grade_periods, subjects

    def get(self, question_id: int) -> Question | None:
        return self.session.get(Question, question_id)

    def update(self, question: Question, question_input: QuestionInput) -> Question:
        for field_name, value in question_input.model_dump().items():
            setattr(question, field_name, value)
        self.session.commit()
        self.session.refresh(question)
        return question

    def archive(self, question: Question) -> Question:
        if question.archived_at is None:
            question.archived_at = datetime.now(UTC)
            self.session.commit()
            self.session.refresh(question)
        return question

    def restore(self, question: Question) -> Question:
        if question.archived_at is not None:
            question.archived_at = None
            self.session.commit()
            self.session.refresh(question)
        return question
