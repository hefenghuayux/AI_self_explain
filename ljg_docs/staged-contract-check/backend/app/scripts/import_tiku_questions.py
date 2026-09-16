import argparse
import json
import logging
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime

from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import create_database_engine
from app.core.logging import configure_logging
from app.models.question import Question

logger = logging.getLogger(__name__)

SOURCE_FILTER = "del_status = 0"
SOURCE_QUERY = text(
    """
    SELECT id, content, display_answer, analysis, grade_period, subject, q_type,
           difficulty_level, review, topics, method
    FROM tiku_question
    WHERE del_status = 0 AND id > :last_id
    ORDER BY id ASC
    LIMIT :batch_size
    """
)


@dataclass(frozen=True)
class ImportFailure:
    tiku_question_id: int
    error: str


@dataclass(frozen=True)
class ImportResult:
    started_at: str
    source_filter: str
    read_count: int
    inserted_count: int
    skipped_count: int
    failures: list[ImportFailure]

    def as_dict(self) -> dict[str, object]:
        return {
            **asdict(self),
            "failure_count": len(self.failures),
        }


def import_tiku_questions(
    source_engine: Engine,
    target_engine: Engine,
    *,
    batch_size: int = 500,
) -> ImportResult:
    if batch_size <= 0:
        raise ValueError("batch_size 必须为正整数")

    started_at = datetime.now().astimezone().isoformat()
    read_count = 0
    inserted_count = 0
    skipped_count = 0
    failures: list[ImportFailure] = []
    last_id = 0

    logger.info(
        "开始导入题库题目",
        extra={"eventName": "tiku_import.started", "sourceFilter": SOURCE_FILTER},
    )
    with source_engine.connect() as source_connection:
        while True:
            source_rows = source_connection.execute(
                SOURCE_QUERY, {"last_id": last_id, "batch_size": batch_size}
            ).mappings().all()
            if not source_rows:
                break

            last_id = source_rows[-1]["id"]
            read_count += len(source_rows)
            inserted, skipped, batch_failures = _import_batch(target_engine, source_rows)
            inserted_count += inserted
            skipped_count += skipped
            failures.extend(batch_failures)

    result = ImportResult(
        started_at=started_at,
        source_filter=SOURCE_FILTER,
        read_count=read_count,
        inserted_count=inserted_count,
        skipped_count=skipped_count,
        failures=failures,
    )
    logger.info(
        "题库题目导入完成",
        extra={
            "eventName": "tiku_import.completed",
            "readCount": result.read_count,
            "insertedCount": result.inserted_count,
            "skippedCount": result.skipped_count,
            "failureCount": len(result.failures),
        },
    )
    return result


def _import_batch(
    target_engine: Engine,
    source_rows: Sequence[dict[str, object]],
) -> tuple[int, int, list[ImportFailure]]:
    source_ids = [int(row["id"]) for row in source_rows]
    with Session(target_engine) as target_session:
        existing_ids = set(
            target_session.scalars(
                select(Question.tiku_question_id).where(Question.tiku_question_id.in_(source_ids))
            )
        )
        inserted = 0
        skipped = 0
        failures: list[ImportFailure] = []
        for source_row in source_rows:
            tiku_question_id = int(source_row["id"])
            if tiku_question_id in existing_ids:
                skipped += 1
                logger.info(
                    "跳过已导入题目",
                    extra={
                        "eventName": "tiku_import.skipped",
                        "tikuQuestionId": tiku_question_id,
                    },
                )
                continue
            try:
                target_session.add(_question_from_source_row(source_row))
            except ValueError as error:
                failure = ImportFailure(tiku_question_id=tiku_question_id, error=str(error))
                failures.append(failure)
                logger.error(
                    "跳过无效源题目",
                    extra={
                        "eventName": "tiku_import.failed",
                        "tikuQuestionId": tiku_question_id,
                        "error": failure.error,
                    },
                )
                continue
            inserted += 1
        target_session.commit()
    return inserted, skipped, failures


def _question_from_source_row(source_row: dict[str, object]) -> Question:
    question_content = source_row["content"]
    if not isinstance(question_content, str) or not question_content.strip():
        raise ValueError("content 为空，无法写入必填 question_content")

    return Question(
        tiku_question_id=int(source_row["id"]),
        question_content=question_content,
        standard_answer=_nullable_text(source_row["display_answer"]),
        full_solution=_nullable_text(source_row["analysis"]),
        grade_period=source_row["grade_period"],
        subject=_nullable_text(source_row["subject"]),
        q_type=source_row["q_type"],
        difficulty_level=source_row["difficulty_level"],
        review=_nullable_text(source_row["review"]),
        topics=_nullable_text(source_row["topics"]),
        method=_nullable_text(source_row["method"]),
    )


def _nullable_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"文本字段类型错误：{type(value).__name__}")
    return value if value.strip() else None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="一次性只读导入 tbox_test.tiku_question")
    parser.add_argument(
        "--source-database-url",
        required=True,
        help="源数据库 SQLAlchemy URL；命令只对源库执行 SELECT",
    )
    parser.add_argument("--batch-size", type=int, default=500, help="每批读取数量，默认 500")
    return parser.parse_args()


def main() -> None:
    arguments = parse_args()
    settings = Settings()
    configure_logging(settings.log_dir, settings.log_max_size_mib, settings.log_backup_count)
    source_engine = create_engine(arguments.source_database_url)
    target_engine = create_database_engine(settings)
    try:
        result = import_tiku_questions(
            source_engine,
            target_engine,
            batch_size=arguments.batch_size,
        )
        print(json.dumps(result.as_dict(), ensure_ascii=False))
    finally:
        source_engine.dispose()
        target_engine.dispose()


if __name__ == "__main__":
    main()
