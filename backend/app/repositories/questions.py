from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.question import Question
from app.schemas.question import QuestionInput


class QuestionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, question_input: QuestionInput) -> Question:
        question = Question(**question_input.model_dump())
        self.session.add(question)
        self.session.commit()
        self.session.refresh(question)
        return question

    def list_questions(self, include_archived: bool) -> list[Question]:
        statement = select(Question).order_by(Question.created_at.desc(), Question.id.desc())
        if not include_archived:
            statement = statement.where(Question.archived_at.is_(None))
        return list(self.session.scalars(statement))

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
