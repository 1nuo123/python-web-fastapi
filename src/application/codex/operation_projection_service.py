"""Codex 已受理控制操作的派生投影服务。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.application.ports.codex_control_port import CodexControlPort
from src.core.codex_contract.operation_contract import (
    CodexControlOperationSnapshot,
    CodexTurnSubmissionProjectionDetail,
)
from src.core.codex_contract.thread_contract import (
    CodexThreadIndexSnapshot,
    CodexThreadTitleSource,
)
from src.core.persistence_contract.unit_of_work_contract import PersistenceSession


@dataclass(frozen=True, slots=True)
class CodexAppliedOperationProjection:
    """已应用并可向浏览器发布的会话投影。"""

    thread: CodexThreadIndexSnapshot
    occurred_at: datetime


class CodexOperationProjectionService:
    """在调用方事务内应用不包含原始正文的控制操作投影。"""

    def __init__(self, control_port: CodexControlPort) -> None:
        self._control_port = control_port

    def apply_accepted(
        self,
        *,
        session: PersistenceSession,
        operation: CodexControlOperationSnapshot,
    ) -> CodexAppliedOperationProjection | None:
        """幂等应用已受理 turn 的短标题与单调活动时间。"""

        if operation.thread_id is None or operation.projection is None:
            return None
        detail = operation.projection.detail
        if not isinstance(detail, CodexTurnSubmissionProjectionDetail):
            return None
        repository = self._control_port.create_codex_thread_repository(session)
        thread: CodexThreadIndexSnapshot | None = None
        if detail.display_name is not None:
            thread = repository.promote_title(
                host_id=operation.host_id,
                upstream_thread_id=operation.thread_id,
                owner_subject_id=operation.owner_subject_id,
                display_name=detail.display_name,
                source=CodexThreadTitleSource.FIRST_USER_MESSAGE,
                updated_at=detail.occurred_at,
            )
        thread = (
            repository.advance_activity(
                host_id=operation.host_id,
                upstream_thread_id=operation.thread_id,
                owner_subject_id=operation.owner_subject_id,
                occurred_at=detail.occurred_at,
            )
            or thread
        )
        if thread is None:
            return None
        return CodexAppliedOperationProjection(
            thread=thread,
            occurred_at=detail.occurred_at,
        )
