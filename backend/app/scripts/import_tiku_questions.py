import argparse
import json
import logging
from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import Engine, bindparam, create_engine, select, text
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
SOURCE_QUERY_BY_IDS = text(
    """
    SELECT id, content, display_answer, analysis, grade_period, subject, q_type,
           difficulty_level, review, topics, method
    FROM tiku_question
    WHERE del_status = 0 AND id IN :ids
    ORDER BY id ASC
    """
).bindparams(bindparam("ids", expanding=True))


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
    question_ids: Sequence[int] | None = None,
) -> ImportResult:
    if batch_size <= 0:
        raise ValueError("batch_size 必须为正整数")

    started_at = datetime.now().astimezone().isoformat()
    read_count = 0
    inserted_count = 0
    skipped_count = 0
    failures: list[ImportFailure] = []

    if question_ids is None:
        source_filter = SOURCE_FILTER
        batches = _iter_batches_by_cursor(source_engine, batch_size)
    else:
        ordered_ids = sorted({int(value) for value in question_ids})
        if not ordered_ids:
            raise ValueError("question_ids 不能为空")
        source_filter = f"{SOURCE_FILTER} AND id IN ({len(ordered_ids)} 个指定题目)"
        batches = _iter_batches_by_ids(source_engine, batch_size, ordered_ids)

    logger.info(
        "开始导入题库题目",
        extra={"eventName": "tiku_import.started", "sourceFilter": source_filter},
    )
    for source_rows in batches:
        read_count += len(source_rows)
        inserted, skipped, batch_failures = _import_batch(target_engine, source_rows)
        inserted_count += inserted
        skipped_count += skipped
        failures.extend(batch_failures)

    result = ImportResult(
        started_at=started_at,
        source_filter=source_filter,
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


def _iter_batches_by_cursor(
    source_engine: Engine, batch_size: int
) -> Iterator[Sequence[dict[str, object]]]:
    """按 id 游标分批扫全表。"""
    last_id = 0
    with source_engine.connect() as source_connection:
        while True:
            source_rows = (
                source_connection.execute(
                    SOURCE_QUERY, {"last_id": last_id, "batch_size": batch_size}
                )
                .mappings()
                .all()
            )
            if not source_rows:
                return
            last_id = source_rows[-1]["id"]
            yield source_rows


def _iter_batches_by_ids(
    source_engine: Engine, batch_size: int, ordered_ids: Sequence[int]
) -> Iterator[Sequence[dict[str, object]]]:
    """只在给定的题目 id 里分批取数，源库里不存在或已删除的 id 不会出现在结果里。"""
    with source_engine.connect() as source_connection:
        for start in range(0, len(ordered_ids), batch_size):
            chunk = list(ordered_ids[start : start + batch_size])
            source_rows = (
                source_connection.execute(SOURCE_QUERY_BY_IDS, {"ids": chunk}).mappings().all()
            )
            if source_rows:
                yield source_rows


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


def load_question_ids(path: Path) -> list[int]:
    if not path.exists():
        raise SystemExit(f"找不到题目 id 文件：{path}")
    question_ids: list[int] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        try:
            question_ids.append(int(value))
        except ValueError as error:
            raise SystemExit(f"{path} 第 {line_number} 行不是整数：{value}") from error
    if not question_ids:
        raise SystemExit(f"{path} 里没有题目 id")
    return question_ids


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="一次性只读导入 tiku_question 题目")
    parser.add_argument(
        "--source-database-url",
        required=True,
        help="源数据库 SQLAlchemy URL；命令只对源库执行 SELECT",
    )
    parser.add_argument("--batch-size", type=int, default=500, help="每批读取数量，默认 500")
    parser.add_argument(
        "--question-ids-file",
        type=Path,
        help="只导入文件里列出的题目 id（每行一个）；不传则按 del_status = 0 全量导入",
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_args()
    settings = Settings()
    configure_logging(settings.log_dir, settings.log_max_size_mib, settings.log_backup_count)
    source_engine = create_engine(arguments.source_database_url)
    target_engine = create_database_engine(settings)
    question_ids = (
        load_question_ids(arguments.question_ids_file) if arguments.question_ids_file else None
    )
    try:
        result = import_tiku_questions(
            source_engine,
            target_engine,
            batch_size=arguments.batch_size,
            question_ids=question_ids,
        )
        print(json.dumps(result.as_dict(), ensure_ascii=False))
    finally:
        source_engine.dispose()
        target_engine.dispose()


if __name__ == "__main__":
    main()
