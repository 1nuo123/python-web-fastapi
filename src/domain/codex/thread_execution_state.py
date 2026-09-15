"""Thread lifecycle projection from the observed turn and fenced runtime."""

from __future__ import annotations

from datetime import UTC, datetime

from src.core.codex_contract.thread_contract import (
    CodexThreadIndexSnapshot,
    CodexThreadStatus,
    CodexTurnSnapshot,
)
from src.core.codex_contract.turn_runtime_contract import CodexTurnPhase, CodexTurnRuntime

TERMINAL_TURN_PHASES = frozenset(
    {CodexTurnPhase.COMPLETED, CodexTurnPhase.FAILED, CodexTurnPhase.INTERRUPTED}
)


def thread_status_for_phase(phase: CodexTurnPhase) -> CodexThreadStatus:
    """Project a turn result without losing failure or interruption."""

    return {
        CodexTurnPhase.COMPLETED: CodexThreadStatus.IDLE,
        CodexTurnPhase.FAILED: CodexThreadStatus.FAILED,
        CodexTurnPhase.INTERRUPTED: CodexThreadStatus.INTERRUPTED,
    }.get(phase, CodexThreadStatus.ACTIVE)


def phase_for_observed_turn(status: str) -> CodexTurnPhase | None:
    """Unknown and notLoaded are observations, not new execution results."""

    return {
        "active": CodexTurnPhase.RUNNING,
        "inProgress": CodexTurnPhase.RUNNING,
        "completed": CodexTurnPhase.COMPLETED,
        "failed": CodexTurnPhase.FAILED,
        "systemError": CodexTurnPhase.FAILED,
        "interrupted": CodexTurnPhase.INTERRUPTED,
        "cancelled": CodexTurnPhase.INTERRUPTED,
    }.get(status)


def merge_authoritative_execution(
    indexed: CodexThreadIndexSnapshot,
    observed_status: str | None,
    latest_turn: CodexTurnSnapshot | None,
    *,
    observed_at: datetime,
) -> CodexThreadIndexSnapshot:
    """Merge an App Server read into one internally consistent execution view."""

    runtime = indexed.turn_runtime
    if latest_turn is None:
        if runtime is not None or observed_status in {None, "unknown", "notLoaded"}:
            return indexed
        try:
            status = CodexThreadStatus(observed_status)
        except ValueError:
            return indexed
        return indexed.model_copy(update={"status": status})
    phase = phase_for_observed_turn(latest_turn.status)
    if phase is None:
        return indexed
    started_at = _observed_time(latest_turn.started_at)
    completed_at = _observed_time(latest_turn.completed_at)
    if (
        runtime is not None
        and runtime.turn_id != latest_turn.turn_id
        and runtime.phase not in TERMINAL_TURN_PHASES
        and (started_at is None or started_at <= runtime.last_activity_at)
    ):
        return indexed
    same_turn = runtime is not None and runtime.turn_id == latest_turn.turn_id
    if same_turn and runtime is not None:
        if runtime.phase in TERMINAL_TURN_PHASES and phase != runtime.phase:
            return indexed
        if phase is CodexTurnPhase.RUNNING and runtime.phase is CodexTurnPhase.AWAITING_APPROVAL:
            phase = runtime.phase
    terminal = phase in TERMINAL_TURN_PHASES
    activity = completed_at or started_at
    if activity is None:
        activity = runtime.last_activity_at if same_turn and runtime is not None else observed_at
    if same_turn and runtime is not None:
        activity = max(activity, runtime.last_activity_at)
    merged_runtime = CodexTurnRuntime(
        thread_id=indexed.upstream_thread_id,
        turn_id=latest_turn.turn_id,
        phase=phase,
        last_activity_at=activity,
        lease_generation=runtime.lease_generation if same_turn and runtime is not None else 0,
        lease_expires_at=(
            runtime.lease_expires_at if same_turn and runtime is not None and not terminal else None
        ),
    )
    return indexed.model_copy(
        update={
            # Archive is an independent collection flag. It must never hide an
            # active turn or replace its terminal result.
            "status": thread_status_for_phase(phase),
            "active_turn_id": None if terminal else latest_turn.turn_id,
            "turn_runtime": merged_runtime,
            "recency_at": max(indexed.recency_at, activity),
        }
    )


def _observed_time(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
