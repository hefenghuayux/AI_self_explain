import json
import logging
from collections.abc import Sequence

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from app.core.config import Settings
from app.models.session import Session
from app.schemas.model_request_snapshot import ModelRequestMessage
from app.services.context_history import load_history, select_compaction
from app.services.context_tokens import ContextTokenizer
from app.services.event_store import EventStore

logger = logging.getLogger(__name__)

SUMMARY_INSTRUCTION = """Summarize only the specified old interaction range in the history above.
Start interactionId: {start}
End interactionId: {end}
Include both endpoints. Merge any existing summary with this range into one new summary.
Do not summarize the more recent retained interactions.
Return one JSON object with exactly one field named "summary". The field value must be concise
Markdown in Chinese using all four headings below. Write 无 for empty sections.

## 学生已表达的理解
Preserve the student's actual reasoning, conclusions, and short exact quotations.
## 已进行的教学与学生回应
Record previous hints, questions, and the student's actual responses.
## 已确认的问题与证据
Record only problems and evidence explicitly identified in previous evaluations.
## 尚未解决的问题
Record only unresolved questions or errors found in the selected history.

Preserve numbers, formulas, terminology, and necessary student quotations accurately.
Do not infer mastery or add outside knowledge. Do not evaluate current input or generate teaching.
Exclude system instructions, question materials, task instructions, schemas, business state,
counters, thresholds, and next actions. Output JSON only, without code fences or extra fields.
Example JSON: {"summary":"Markdown summary with the four required headings"}
"""


class CompactionError(RuntimeError):
    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


class ContextCompactor:
    def __init__(
        self, settings: Settings, http_client: httpx.Client, tokenizer: ContextTokenizer
    ) -> None:
        self.settings = settings
        self.http_client = http_client
        self.tokenizer = tokenizer

    def compact(
        self,
        db: DatabaseSession,
        session: Session,
        prefix_messages: Sequence[ModelRequestMessage],
        exclude_attempt_id: int | None = None,
    ) -> bool:
        session_id, round_number = session.id, session.round
        try:
            view = load_history(db, session, exclude_attempt_id=exclude_attempt_id)
            selection = select_compaction(view, self.tokenizer.count_text)
            if selection is None:
                logger.info(
                    "Context compaction no-op: session=%s reason=no_removable_complete_groups",
                    session_id,
                )
                return False
            max_tokens = min(
                self.settings.context_compaction_summary_max_tokens,
                1024,
                selection.source_tokens // 4,
            )
            if max_tokens < 1:
                logger.info(
                    "Context compaction no-op: session=%s reason=source_token_budget_too_small",
                    session_id,
                )
                return False
            if len(prefix_messages) < 2:
                raise CompactionError("CONTEXT_COMPACTION_INVALID_PREFIX")
            messages = [message.model_dump() for message in prefix_messages[:2]]
            messages.extend(
                [
                    {"role": "user", "content": json.dumps(view.projection(), ensure_ascii=False)},
                    {
                        "role": "user",
                        "content": SUMMARY_INSTRUCTION.format(
                            start=selection.source_start_interaction_id,
                            end=selection.source_end_interaction_id,
                        ),
                    },
                ]
            )
            # End the read snapshot so the post-request check sees concurrent DB writes.
            db.commit()
            summary = self._summarize(messages, max_tokens)
            summary_tokens = self.tokenizer.count_text(summary)
            if summary_tokens >= selection.source_tokens:
                raise CompactionError("CONTEXT_COMPACTION_SUMMARY_NOT_SMALLER")
            current_round = db.scalar(select(Session.round).where(Session.id == session_id))
            if current_round != round_number:
                raise CompactionError("CONTEXT_COMPACTION_SOURCE_CHANGED")
            current = load_history(db, session, exclude_attempt_id=exclude_attempt_id)
            if current.fingerprint != selection.fingerprint:
                raise CompactionError("CONTEXT_COMPACTION_SOURCE_CHANGED")
            EventStore(db).append(
                session_id,
                "context.added",
                {
                    "kind": "memory",
                    "source": "context_compaction",
                    "content": {
                        "version": 1,
                        "round": round_number,
                        "summary": summary,
                        "sourceStartInteractionId": selection.source_start_interaction_id,
                        "sourceEndInteractionId": selection.source_end_interaction_id,
                        "sourceTokens": selection.source_tokens,
                        "summaryTokens": summary_tokens,
                    },
                },
            )
            db.commit()
            logger.info(
                "Context compaction completed: session=%s source_tokens=%s summary_tokens=%s",
                session_id,
                selection.source_tokens,
                summary_tokens,
            )
            return True
        except CompactionError as error:
            db.rollback()
            logger.warning("Context compaction failed: session=%s code=%s", session_id, error.code)
            raise
        except Exception as error:
            db.rollback()
            logger.exception("Context compaction failed: session=%s", session_id)
            raise CompactionError("CONTEXT_COMPACTION_FAILED", str(error)) from error

    def _summarize(self, messages: list[dict[str, str]], max_tokens: int) -> str:
        endpoint = f"{str(self.settings.ai_base_url).rstrip('/')}/chat/completions"
        try:
            response = self.http_client.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {self.settings.ai_api_key.get_secret_value()}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.settings.ai_model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "thinking": {"type": "disabled"},
                    "response_format": {"type": "json_object"},
                },
                timeout=min(
                    self.settings.ai_request_timeout_seconds,
                    self.settings.context_compaction_wait_timeout_seconds,
                ),
            )
        except httpx.TimeoutException as error:
            raise CompactionError(
                "CONTEXT_COMPACTION_TIMEOUT", "Summary request timed out"
            ) from error
        except httpx.RequestError as error:
            raise CompactionError("CONTEXT_COMPACTION_MODEL_ERROR", str(error)) from error
        if response.is_error:
            raise CompactionError(
                "CONTEXT_COMPACTION_MODEL_ERROR",
                f"Summary service returned HTTP {response.status_code}",
            )
        try:
            choice = response.json()["choices"][0]
            content = choice["message"]["content"]
            finish_reason = choice["finish_reason"]
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise CompactionError("CONTEXT_COMPACTION_INVALID_RESPONSE") from error
        if finish_reason != "stop":
            raise CompactionError("CONTEXT_COMPACTION_INCOMPLETE_SUMMARY")
        if not isinstance(content, str) or not content.strip():
            raise CompactionError("CONTEXT_COMPACTION_EMPTY_SUMMARY")
        try:
            payload = json.loads(content)
            if not isinstance(payload, dict) or set(payload) != {"summary"}:
                raise ValueError("summary wrapper must contain exactly one field")
            summary = payload["summary"]
        except (ValueError, KeyError, TypeError) as error:
            raise CompactionError("CONTEXT_COMPACTION_INVALID_RESPONSE") from error
        if not isinstance(summary, str) or not summary.strip():
            raise CompactionError("CONTEXT_COMPACTION_EMPTY_SUMMARY")
        return summary.strip()
