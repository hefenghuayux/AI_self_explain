import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session as DatabaseSession

from app.models.ai_evaluation import AIEvaluation
from app.models.explanation_attempt import ExplanationAttempt
from app.models.session import Session
from app.models.session_event import SessionEvent
from app.models.support_event import SupportEvent

HistoryEvent = dict[str, object]
HistoryGroup = list[HistoryEvent]


def _serialize(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


@dataclass(frozen=True)
class HistoryView:
    groups: list[HistoryGroup]
    summary: str | None = None
    memory_event_id: str | None = None
    unresolved_interaction_ids: frozenset[str] = frozenset()

    def projection(self) -> dict[str, object]:
        result: dict[str, object] = {"events": [event for group in self.groups for event in group]}
        if self.summary is not None:
            result["summary"] = self.summary
        return result

    @property
    def fingerprint(self) -> str:
        value = {
            "history": self.projection(), "memoryEventId": self.memory_event_id,
            "unresolvedInteractionIds": sorted(self.unresolved_interaction_ids),
        }
        return hashlib.sha256(_serialize(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CompactionSelection:
    source_history: dict[str, object]
    source_start_interaction_id: str
    source_end_interaction_id: str
    source_tokens: int
    retained_groups: list[HistoryGroup]
    fingerprint: str


def group_history(events: list[HistoryEvent]) -> list[HistoryGroup]:
    groups: list[HistoryGroup] = []
    for event in events:
        kind = event.get("kind")
        if kind == "explanation":
            groups.append([event])
        elif kind == "teaching":
            # Keep the preceding explanation with its first teaching response.
            if groups and len(groups[-1]) == 1 and groups[-1][0].get("kind") == "explanation":
                groups[-1].append(event)
            else:
                groups.append([event])
        elif kind in {"guided_answer", "follow_up"}:
            interaction_id = str(event.get("interactionId", ""))
            teaching_id = (
                interaction_id.removesuffix(":followup")
                if kind == "follow_up"
                else event.get("replyTo", interaction_id)
            )
            if not groups or not any(
                item.get("kind") == "teaching" and item.get("interactionId") == teaching_id
                for item in groups[-1]
            ):
                raise ValueError("CONTEXT_HISTORY_INCOMPLETE_INTERACTION")
            groups[-1].append(event)
        else:
            raise ValueError(f"CONTEXT_HISTORY_UNSUPPORTED_EVENT: {kind}")
    return groups


def load_history(
    database_session: DatabaseSession,
    session: Session,
    *,
    exclude_attempt_id: int | None = None,
) -> HistoryView:
    # The existing event projection is shared without importing AI services eagerly.
    from app.services.ai_evaluation import build_progress_context

    attempts_query = select(ExplanationAttempt).where(
        ExplanationAttempt.session_id == session.id,
        ExplanationAttempt.round == session.round,
        ExplanationAttempt.id.in_(select(AIEvaluation.attempt_id)),
    )
    if exclude_attempt_id is not None:
        attempts_query = attempts_query.where(ExplanationAttempt.id != exclude_attempt_id)
    attempts = list(
        database_session.scalars(
            attempts_query.order_by(ExplanationAttempt.id).execution_options(populate_existing=True)
        )
    )
    supports = list(
        database_session.scalars(
            select(SupportEvent)
            .where(SupportEvent.session_id == session.id, SupportEvent.round == session.round)
            .order_by(SupportEvent.id)
            .execution_options(populate_existing=True)
        )
    )
    events = build_progress_context(
        previous_attempts=attempts,
        previous_support=supports,
        max_interactions=len(attempts) + len(supports) + 1,
    )["events"]
    groups = group_history(events)
    unresolved_ids = frozenset(
        f"support:{support.id}"
        for support in supports
        if {str(question["id"]) for question in support.guided_questions or [] if "id" in question}
        - {
            str(answer["question_id"])
            for answer in support.guided_answers or []
            if "question_id" in answer
        }
    )
    memories = database_session.scalars(
        select(SessionEvent)
        .where(SessionEvent.session_id == session.id, SessionEvent.event_type == "context.added")
        .order_by(SessionEvent.seq.desc())
        .execution_options(populate_existing=True)
    )
    for memory in memories:
        data = memory.data
        content = data.get("content")
        if (
            data.get("kind") != "memory"
            or data.get("source") != "context_compaction"
            or not isinstance(content, dict)
            or content.get("round") != session.round
        ):
            continue
        summary = content.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("CONTEXT_COMPACTION_INVALID_MEMORY")
        end_id = content.get("sourceEndInteractionId")
        for index, group in enumerate(groups):
            if group[-1].get("interactionId") == end_id:
                return HistoryView(groups[index + 1 :], summary, memory.event_id, unresolved_ids)
        raise ValueError("CONTEXT_COMPACTION_SOURCE_BOUNDARY_MISSING")
    return HistoryView(groups, unresolved_interaction_ids=unresolved_ids)


def build_shared_history(
    database_session: DatabaseSession,
    session: Session,
    *,
    exclude_attempt_id: int | None = None,
) -> dict[str, object]:
    return load_history(
        database_session, session, exclude_attempt_id=exclude_attempt_id
    ).projection()


def select_compaction(
    view: HistoryView, count_tokens: Callable[[str], int]
) -> CompactionSelection | None:
    if len(view.groups) <= 2:
        return None
    retain_budget = count_tokens(_serialize(view.projection())) // 3
    first_retained = len(view.groups) - 2
    # Unanswered questions must stay visible with any answers added later.
    for index, group in enumerate(view.groups):
        if any(event.get("interactionId") in view.unresolved_interaction_ids for event in group):
            first_retained = min(first_retained, index)
            break
    while first_retained > 0:
        candidate = HistoryView(view.groups[first_retained - 1 :]).projection()
        if count_tokens(_serialize(candidate)) > retain_budget:
            break
        first_retained -= 1
    if first_retained == 0:
        return None
    source_groups = view.groups[:first_retained]
    source = HistoryView(source_groups, view.summary).projection()
    return CompactionSelection(
        source_history=source,
        source_start_interaction_id=str(source_groups[0][0]["interactionId"]),
        source_end_interaction_id=str(source_groups[-1][-1]["interactionId"]),
        source_tokens=count_tokens(_serialize(source)),
        retained_groups=view.groups[first_retained:],
        fingerprint=view.fingerprint,
    )
