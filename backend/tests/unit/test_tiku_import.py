from sqlalchemy import (
    Column,
    Engine,
    Integer,
    MetaData,
    Table,
    Text,
    create_engine,
    event,
    insert,
    select,
)
from sqlalchemy.orm import Session

from app.models.question import Question
from app.scripts.import_tiku_questions import import_tiku_questions


def _create_source_table(source_engine: Engine) -> Table:
    source_table = Table(
        "tiku_question",
        MetaData(),
        Column("id", Integer, primary_key=True),
        Column("content", Text),
        Column("display_answer", Text),
        Column("analysis", Text),
        Column("grade_period", Integer),
        Column("subject", Text),
        Column("q_type", Integer),
        Column("difficulty_level", Integer),
        Column("review", Text),
        Column("topics", Text),
        Column("method", Text),
        Column("del_status", Integer, nullable=False),
    )
    source_table.create(source_engine)
    return source_table


def test_import_maps_fields_preserves_html_and_only_reads_source() -> None:
    source_engine = create_engine("sqlite:///:memory:")
    target_engine = create_engine("sqlite:///:memory:")
    source_table = _create_source_table(source_engine)
    Question.__table__.create(target_engine)
    with source_engine.begin() as connection:
        connection.execute(
            insert(source_table),
            [
                {
                    "id": 1,
                    "content": "<p>保留 <strong>HTML</strong></p>",
                    "display_answer": "标准答案",
                    "analysis": "完整解析",
                    "grade_period": 2,
                    "subject": "数学",
                    "q_type": 3,
                    "difficulty_level": 4,
                    "review": "复习说明",
                    "topics": "整数",
                    "method": "列式计算",
                    "del_status": 0,
                },
                {
                    "id": 2,
                    "content": "不应导入",
                    "display_answer": None,
                    "analysis": None,
                    "grade_period": None,
                    "subject": None,
                    "q_type": None,
                    "difficulty_level": None,
                    "review": None,
                    "topics": None,
                    "method": None,
                    "del_status": 1,
                },
            ],
        )

    source_statements: list[str] = []

    @event.listens_for(source_engine, "before_cursor_execute")
    def capture_source_statement(*args: object) -> None:
        source_statements.append(str(args[2]))

    result = import_tiku_questions(source_engine, target_engine, batch_size=1)

    with Session(target_engine) as session:
        question = session.scalar(select(Question))
    assert result.read_count == 1
    assert result.inserted_count == 1
    assert result.skipped_count == 0
    assert result.failures == []
    assert question.tiku_question_id == 1
    assert question.question_content == "<p>保留 <strong>HTML</strong></p>"
    assert question.standard_answer == "标准答案"
    assert question.full_solution == "完整解析"
    assert question.grade_period == 2
    assert question.subject == "数学"
    assert question.q_type == 3
    assert question.difficulty_level == 4
    assert question.review == "复习说明"
    assert question.topics == "整数"
    assert question.method == "列式计算"
    assert question.rubric_points is None
    assert all(statement.lstrip().upper().startswith("SELECT") for statement in source_statements)


def test_import_skips_existing_questions_and_records_invalid_source_content() -> None:
    source_engine = create_engine("sqlite:///:memory:")
    target_engine = create_engine("sqlite:///:memory:")
    source_table = _create_source_table(source_engine)
    Question.__table__.create(target_engine)
    with source_engine.begin() as connection:
        connection.execute(
            insert(source_table),
            [
                {"id": 1, "content": "已导入题目", "del_status": 0},
                {"id": 2, "content": "  ", "del_status": 0},
                {
                    "id": 3,
                    "content": "新题目",
                    "display_answer": " ",
                    "analysis": None,
                    "del_status": 0,
                },
            ],
        )
    with target_engine.begin() as connection:
        connection.execute(insert(Question).values(tiku_question_id=1, question_content="人工题目"))

    first_result = import_tiku_questions(source_engine, target_engine)
    second_result = import_tiku_questions(source_engine, target_engine)

    assert first_result.inserted_count == 1
    assert first_result.skipped_count == 1
    assert [(failure.tiku_question_id, failure.error) for failure in first_result.failures] == [
        (2, "content 为空，无法写入必填 question_content")
    ]
    assert second_result.inserted_count == 0
    assert second_result.skipped_count == 2
    with Session(target_engine) as session:
        questions = session.scalars(select(Question).order_by(Question.tiku_question_id)).all()
    assert [(question.tiku_question_id, question.question_content) for question in questions] == [
        (1, "人工题目"),
        (3, "新题目"),
    ]
    assert questions[1].standard_answer is None
    assert questions[1].full_solution is None
