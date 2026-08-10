"""从在线 Agent 读取 thread 权威正文快照。"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from typing import Literal
from uuid import UUID, uuid4

from pydantic import JsonValue

from src.application.codex.codex_protocol_mapper import CodexProtocolMapper
from src.application.ports.codex_agent_command_dispatch_port import (
    CodexAgentCommandDispatchPort,
)
from src.application.ports.codex_control_port import CodexControlPort
from src.core.codex_contract.agent_protocol_contract import CodexAgentCommand
from src.core.codex_contract.connection_session_contract import CodexHostOfflineError
from src.core.codex_contract.thread_contract import (
    CodexThreadAuthoritySnapshot,
    CodexThreadIndexSnapshot,
    CodexTimelineItemSnapshot,
    CodexTurnSnapshot,
)
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.domain.codex.agent_command_policy import calculate_agent_request_digest
from src.domain.codex.codex_error_code import CodexErrorCode


class ReadCodexThreadSnapshotUsecase:
    """所有权校验后通过 Agent thread/read 恢复浏览器权威状态。"""

    def __init__(
        self,
        *,
        control_port: CodexControlPort,
        dispatch_port: CodexAgentCommandDispatchPort,
        timeout_seconds: int,
    ) -> None:
        self._control_port = control_port
        self._dispatch_port = dispatch_port
        self._timeout_seconds = timeout_seconds
        self._mapper = CodexProtocolMapper()

    async def execute(
        self,
        *,
        host_id: UUID,
        upstream_thread_id: str,
        owner_subject_id: str,
        include_history: bool = False,
        history_cursor: str | None = None,
        history_limit: int = 100,
    ) -> CodexThreadAuthoritySnapshot:
        thread, workspace_key = self._read_owned_thread(
            host_id,
            upstream_thread_id,
            owner_subject_id,
        )
        params: dict[str, JsonValue] = {
            "threadId": upstream_thread_id,
            "includeTurns": include_history or history_cursor is not None,
            "workspace_key": workspace_key,
        }
        command = CodexAgentCommand(
            command_id=uuid4(),
            operation_id=uuid4(),
            host_id=host_id,
            request_digest=calculate_agent_request_digest("thread.read", params),
            command_type="thread.read",
            params=params,
            deadline=datetime.now(UTC) + timedelta(seconds=self._timeout_seconds),
        )
        try:
            result = await self._dispatch_port.dispatch_and_wait_result(
                command,
                ack_timeout_seconds=self._timeout_seconds,
                result_timeout_seconds=self._timeout_seconds,
            )
        except CodexHostOfflineError:
            return self._build_unavailable_snapshot(thread)
        except TimeoutError:
            if thread.source_kind == "remote":
                return self._build_unavailable_snapshot(thread)
            raise
        except RuntimeError:
            if thread.source_kind == "remote":
                return self._build_unavailable_snapshot(thread)
            raise
        if result.outcome != "completed" or result.result is None:
            if result.error_code == "response_too_large":
                return CodexThreadAuthoritySnapshot(
                    thread=thread,
                    turns=[],
                    items=[],
                    history_status="omitted_too_large",
                )
            # Codex 0.145 can acknowledge a brand-new thread before its rollout
            # is loadable by thread/read. The control-plane index is still the
            # authoritative identity; expose an empty timeline until the first
            # turn materializes the rollout instead of returning a 500.
            if result.error_code == "-32600" and thread.source_kind == "remote":
                return CodexThreadAuthoritySnapshot(
                    thread=thread,
                    turns=[],
                    items=[],
                    history_status="not_available_yet",
                )
            raise HttpFaultException(
                status_code=HTTPStatus.BAD_GATEWAY,
                error_code=CodexErrorCode.UPSTREAM_FAILURE,
                message="Codex thread权威快照读取失败。",
            )
        mapped = self._mapper.to_thread_snapshot(
            result.result,
            host_id=host_id,
            workspace_id=thread.workspace_id,
        )
        turns = (
            [CodexTurnSnapshot.model_validate(value) for value in mapped.turns]
            if include_history or history_cursor is not None
            else []
        )
        history_status: Literal["complete", "not_requested", "omitted_too_large"] = (
            "complete" if include_history or history_cursor is not None else "not_requested"
        )
        if isinstance(result.result, Mapping):
            marker = result.result.get("historyStatus")
            if marker == "omitted_too_large":
                history_status = "omitted_too_large"
        offset = self._decode_history_cursor(history_cursor)
        bounded_limit = max(1, min(history_limit, 500))
        page_items = mapped.items[offset : offset + bounded_limit]
        next_cursor = (
            self._encode_history_cursor(offset + bounded_limit)
            if offset + bounded_limit < len(mapped.items)
            else None
        )
        return CodexThreadAuthoritySnapshot(
            thread=self._merge_authoritative_thread(thread, mapped.thread, turns),
            turns=turns,
            items=(
                [CodexTimelineItemSnapshot.model_validate(value) for value in page_items]
                if include_history or history_cursor is not None
                else []
            ),
            history_status=history_status,
            next_history_cursor=next_cursor,
        )

    def _encode_history_cursor(self, offset: int) -> str:
        """生成不暴露上游结构的历史游标。"""

        return base64.urlsafe_b64encode(f"history:{offset}".encode()).decode()

    def _decode_history_cursor(self, cursor: str | None) -> int:
        if cursor is None:
            return 0
        try:
            value = base64.urlsafe_b64decode(cursor.encode()).decode()
            prefix, raw_offset = value.split(":", maxsplit=1)
            if prefix != "history":
                raise ValueError
            return max(0, int(raw_offset))
        except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
            raise HttpFaultException(
                status_code=HTTPStatus.BAD_REQUEST,
                error_code=CodexErrorCode.STATE_CONFLICT,
                message="Codex历史游标无效。",
            ) from exc

    @staticmethod
    def _build_unavailable_snapshot(
        thread: CodexThreadIndexSnapshot,
    ) -> CodexThreadAuthoritySnapshot:
        """Serve persisted thread metadata when live agent authority is unavailable."""

        return CodexThreadAuthoritySnapshot(
            thread=thread,
            turns=[],
            items=[],
            history_status="not_available_yet",
        )

    @staticmethod
    def _merge_authoritative_thread(
        indexed: CodexThreadIndexSnapshot,
        mapped: dict[str, JsonValue],
        turns: list[CodexTurnSnapshot],
    ) -> CodexThreadIndexSnapshot:
        """Preserve ownership fields while converging volatile state from thread/read."""

        mapped_status = mapped.get("status")
        status = mapped_status if isinstance(mapped_status, str) else indexed.status
        active_turn_id: str | None = None
        if turns:
            latest = turns[-1]
            if latest.status in {"active", "inProgress"}:
                status = "active"
                active_turn_id = latest.turn_id
            elif latest.status in {"interrupted", "cancelled"}:
                status = "interrupted"
            elif latest.status == "completed":
                status = "idle"
            elif latest.status in {"failed", "systemError"}:
                status = "failed"
            else:
                status = "unknown"
        elif status == "notLoaded" and indexed.status == "active":
            status = "unknown"

        updates: dict[str, object] = {
            "status": status,
            "active_turn_id": active_turn_id,
        }
        for field_name in ("display_name", "model", "created_at", "updated_at"):
            value = mapped.get(field_name)
            if value is not None:
                updates[field_name] = value
        return CodexThreadIndexSnapshot.model_validate({**indexed.model_dump(), **updates})

    def _read_owned_thread(
        self,
        host_id: UUID,
        upstream_thread_id: str,
        owner_subject_id: str,
    ) -> tuple[CodexThreadIndexSnapshot, str]:
        unit_of_work = self._control_port.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            thread = self._control_port.create_codex_thread_repository(
                session
            ).get_by_upstream_id_and_owner(
                host_id,
                upstream_thread_id,
                owner_subject_id,
            )
            if thread is None:
                raise HttpFaultException(
                    status_code=HTTPStatus.NOT_FOUND,
                    error_code=CodexErrorCode.RESOURCE_NOT_FOUND,
                    message="Codex资源不存在。",
                )
            workspace = self._control_port.create_codex_workspace_repository(
                session
            ).get_by_id_and_owner(thread.workspace_id, owner_subject_id)
            if workspace is None or not workspace.enabled:
                raise HttpFaultException(
                    status_code=HTTPStatus.NOT_FOUND,
                    error_code=CodexErrorCode.RESOURCE_NOT_FOUND,
                    message="Codex资源不存在。",
                )
            return thread, workspace.agent_workspace_key
        finally:
            unit_of_work.dispose()
