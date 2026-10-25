"""从在线 Agent 读取 thread 权威正文快照。"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from uuid import UUID, uuid4

from pydantic import JsonValue

from src.application.codex.codex_history_pagination import (
    CodexHistoryCursorStaleError,
    CodexHistoryPageResolver,
    SignedCodexHistoryCursorCodec,
)
from src.application.codex.codex_protocol_mapper import CodexProtocolMapper
from src.application.ports.codex_agent_command_dispatch_port import (
    CodexAgentCommandDispatchPort,
)
from src.application.ports.codex_control_port import CodexControlPort
from src.application.ports.codex_realtime_event_port import CodexRealtimeEventPort
from src.core.codex_contract.agent_history_window_contract import (
    AgentHistoryWindowRequest,
    AgentHistoryWindowResult,
)
from src.core.codex_contract.agent_protocol_contract import CodexAgentCommand
from src.core.codex_contract.connection_session_contract import CodexHostOfflineError
from src.core.codex_contract.thread_contract import (
    CodexThreadAuthoritySnapshot,
    CodexThreadHistoryItemReload,
    CodexThreadHistoryPage,
    CodexThreadHistoryQuery,
    CodexThreadHistoryStatus,
    CodexThreadIndexSnapshot,
    CodexTimelineItemEnvelope,
    CodexTurnSnapshot,
)
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.domain.codex.agent_command_policy import calculate_agent_request_digest
from src.domain.codex.codex_error_code import CodexErrorCode
from src.domain.codex.thread_execution_state import merge_authoritative_execution


@dataclass(frozen=True, slots=True)
class OwnedCodexThreadContext:
    """已通过所有权校验的线程读取上下文。"""

    thread: CodexThreadIndexSnapshot
    workspace_key: str


class ReadCodexThreadSnapshotUsecase:
    """所有权校验后通过 Agent thread/read 恢复浏览器权威状态。"""

    def __init__(
        self,
        *,
        control_port: CodexControlPort,
        dispatch_port: CodexAgentCommandDispatchPort,
        timeout_seconds: int,
        ack_timeout_seconds: int = 5,
        history_cursor_signing_key: bytes,
        history_cursor_ttl_seconds: int = 300,
        event_port: CodexRealtimeEventPort | None = None,
    ) -> None:
        self._control_port = control_port
        self._dispatch_port = dispatch_port
        self._timeout_seconds = timeout_seconds
        self._ack_timeout_seconds = ack_timeout_seconds
        self._mapper = CodexProtocolMapper()
        self._event_port = event_port
        self._history_page_resolver = CodexHistoryPageResolver(
            SignedCodexHistoryCursorCodec(
                signing_key=history_cursor_signing_key,
                ttl_seconds=history_cursor_ttl_seconds,
                clock=lambda: datetime.now(UTC),
            )
        )

    async def execute(
        self,
        *,
        host_id: UUID,
        upstream_thread_id: str,
        owner_subject_id: str,
        include_history: bool = False,
        history_limit: int = 50,
        before_cursor: str | None = None,
        requested_item_ids: frozenset[str] | None = None,
    ) -> CodexThreadAuthoritySnapshot:
        context = await asyncio.to_thread(
            self._read_owned_thread,
            host_id,
            upstream_thread_id,
            owner_subject_id,
        )
        thread = context.thread
        params: dict[str, JsonValue] = {
            "threadId": upstream_thread_id,
            "includeTurns": include_history or before_cursor is not None,
            "workspace_key": context.workspace_key,
        }
        window = None
        history_requested = include_history or before_cursor is not None
        if (
            history_requested
            and requested_item_ids is None
            and await self._dispatch_port.supports_history_windows(host_id)
        ):
            claims = (
                self._history_page_resolver.cursor_codec.decode(before_cursor)
                if before_cursor
                else None
            )
            if claims is not None:
                if (
                    claims.owner_subject_id != owner_subject_id
                    or claims.host_id != host_id
                    or claims.upstream_thread_id != upstream_thread_id
                    or claims.window_cursor is None
                ):
                    raise CodexHistoryCursorStaleError("历史窗口游标不属于当前读取范围。")
            window = AgentHistoryWindowRequest(
                limit=history_limit,
                cursor=claims.window_cursor if claims else None,
                revision=claims.history_revision if claims else None,
            )
            params["history_window"] = window.model_dump(mode="json")
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
                ack_timeout_seconds=self._ack_timeout_seconds,
                result_timeout_seconds=self._timeout_seconds,
            )
        except CodexHostOfflineError:
            return self._build_unavailable_snapshot(thread)
        except TimeoutError as exc:
            if include_history or before_cursor is not None or requested_item_ids is not None:
                raise HttpFaultException(
                    status_code=HTTPStatus.GATEWAY_TIMEOUT,
                    error_code=CodexErrorCode.QUERY_TIMEOUT,
                    message="历史读取超时，请稍后重试。",
                ) from exc
            return self._build_unavailable_snapshot(thread)
        if result.outcome != "completed" or result.result is None:
            if result.error_code == "query_overloaded":
                raise HttpFaultException(
                    status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                    error_code=CodexErrorCode.QUERY_OVERLOADED,
                    message="本机查询暂时繁忙，请稍后重试。",
                )
            if result.error_code == "history_cursor_stale":
                raise CodexHistoryCursorStaleError("历史窗口版本已变化。")
            if result.error_code in {"result_unknown", "deadline_expired", "query_timeout"}:
                if include_history or before_cursor is not None or requested_item_ids is not None:
                    raise HttpFaultException(
                        status_code=HTTPStatus.GATEWAY_TIMEOUT,
                        error_code=CodexErrorCode.QUERY_TIMEOUT,
                        message="历史读取超时。",
                    )
                return self._build_unavailable_snapshot(thread)
            if result.error_code == "response_too_large":
                return CodexThreadAuthoritySnapshot(
                    thread=thread,
                    turns=[],
                    items=[],
                    history_status=CodexThreadHistoryStatus.OMITTED_TOO_LARGE,
                )
            # Codex 0.145 can acknowledge a brand-new thread before its rollout
            # is loadable by thread/read. The control-plane index is still the
            # authoritative identity; expose an empty timeline until the first
            # turn materializes the rollout instead of returning a 500.
            if (
                result.error_code == "-32600"
                and thread.source_kind == "remote"
                and thread.turn_runtime is None
                and any(
                    marker in (result.error_message or "").lower()
                    for marker in ("thread not found", "no rollout", "not materialized")
                )
            ):
                return CodexThreadAuthoritySnapshot(
                    thread=thread,
                    turns=[],
                    items=[],
                    history_status=CodexThreadHistoryStatus.NOT_MATERIALIZED,
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
        history_requested = include_history or before_cursor is not None
        turns = (
            [CodexTurnSnapshot.model_validate(value) for value in mapped.turns]
            if history_requested
            else []
        )
        history_status: CodexThreadHistoryStatus = (
            CodexThreadHistoryStatus.COMPLETE
            if history_requested
            else CodexThreadHistoryStatus.NOT_REQUESTED
        )
        if isinstance(result.result, Mapping):
            marker = result.result.get("historyStatus")
            if marker == "omitted_too_large":
                history_status = CodexThreadHistoryStatus.OMITTED_TOO_LARGE
        all_items = [CodexTimelineItemEnvelope.model_validate(value) for value in mapped.items]
        history_page: CodexThreadHistoryPage | None = None
        reloaded_items: list[CodexTimelineItemEnvelope] | None = None
        if requested_item_ids is not None and history_status is CodexThreadHistoryStatus.COMPLETE:
            reloaded_items = [
                item for item in all_items if item.header.item_id in requested_item_ids
            ]
        elif window is not None and history_status is CodexThreadHistoryStatus.COMPLETE:
            if not isinstance(result.result, Mapping) or result.result.get("historyWindow") is None:
                raise ValueError("已协商窗口查询但Agent没有返回分页合同。")
            returned = AgentHistoryWindowResult.model_validate(result.result["historyWindow"])
            if window.revision is not None and window.revision != returned.revision:
                raise CodexHistoryCursorStaleError("历史版本已变化。")
            if returned.has_more != (returned.cursor is not None):
                raise ValueError("历史窗口完整性标记与游标不一致。")
            history_page = CodexThreadHistoryPage(
                items=all_items,
                has_more=returned.has_more,
                history_revision=returned.revision,
                before_cursor=self._history_page_resolver.cursor_codec.encode(
                    owner_subject_id=owner_subject_id,
                    host_id=host_id,
                    upstream_thread_id=upstream_thread_id,
                    history_revision=returned.revision,
                    boundary_item_id="window",
                    window_cursor=returned.cursor,
                )
                if returned.has_more
                else None,
            )
        elif history_requested and history_status is CodexThreadHistoryStatus.COMPLETE:
            history_page = self._read_history_page(
                owner_subject_id=owner_subject_id,
                host_id=host_id,
                upstream_thread_id=upstream_thread_id,
                items=all_items,
                query=CodexThreadHistoryQuery(
                    before_cursor=before_cursor,
                    limit=history_limit,
                ),
            )
        merged = self._merge_authoritative_thread(
            thread, mapped.thread, [] if before_cursor else turns
        )
        persisted = await asyncio.to_thread(self._reconcile_execution, thread, merged)
        if self._event_port is not None and persisted != thread:
            await self._event_port.publish_thread_updated(persisted, occurred_at=datetime.now(UTC))
        covered_item_ids: list[str] = []
        if isinstance(result.result, Mapping):
            product = result.result.get("productThreadRead")
            if isinstance(product, Mapping) and isinstance(product.get("covered_item_ids"), list):
                covered_item_ids = [
                    value for value in product["covered_item_ids"] if isinstance(value, str)
                ]
        return CodexThreadAuthoritySnapshot(
            source_epoch=mapped.source_epoch,
            source_seq=mapped.source_seq,
            covered_item_ids=covered_item_ids,
            thread=persisted,
            turns=turns,
            items=(
                reloaded_items
                if reloaded_items is not None
                else (history_page.items if history_page is not None else [])
            ),
            history_status=history_status,
            history_before_cursor=(
                history_page.before_cursor if history_page is not None else None
            ),
            history_has_more=history_page.has_more if history_page is not None else False,
            history_revision=(history_page.history_revision if history_page is not None else None),
        )

    async def read_history_page(
        self,
        *,
        host_id: UUID,
        upstream_thread_id: str,
        owner_subject_id: str,
        query: CodexThreadHistoryQuery,
    ) -> CodexThreadHistoryPage:
        """读取一页更早历史，并保留游标失效的显式冲突语义。"""

        try:
            snapshot = await self.execute(
                host_id=host_id,
                upstream_thread_id=upstream_thread_id,
                owner_subject_id=owner_subject_id,
                include_history=True,
                history_limit=query.limit,
                before_cursor=query.before_cursor,
            )
        except CodexHistoryCursorStaleError as exc:
            raise HttpFaultException(
                status_code=HTTPStatus.CONFLICT,
                error_code=CodexErrorCode.HISTORY_CURSOR_STALE,
                message="Codex历史游标已失效，请重新加载稳定时间线窗口。",
            ) from exc
        if (
            snapshot.history_status is not CodexThreadHistoryStatus.COMPLETE
            or snapshot.history_revision is None
        ):
            raise HttpFaultException(
                status_code=HTTPStatus.CONFLICT,
                error_code=CodexErrorCode.HISTORY_CURSOR_STALE,
                message="Codex历史当前不可稳定分页，请重新同步会话。",
            )
        return CodexThreadHistoryPage(
            items=snapshot.items,
            before_cursor=snapshot.history_before_cursor,
            has_more=snapshot.history_has_more,
            history_revision=snapshot.history_revision,
        )

    async def read_history_items(
        self,
        *,
        host_id: UUID,
        upstream_thread_id: str,
        owner_subject_id: str,
        item_ids: list[str],
    ) -> CodexThreadHistoryItemReload:
        """按稳定 ID 读取当前权威历史中的少量已回收正文，不支持 offset 回退。"""

        requested_item_ids = frozenset(item_ids)
        snapshot = await self.execute(
            host_id=host_id,
            upstream_thread_id=upstream_thread_id,
            owner_subject_id=owner_subject_id,
            include_history=True,
            requested_item_ids=requested_item_ids,
        )
        found_item_ids = {item.header.item_id for item in snapshot.items}
        return CodexThreadHistoryItemReload(
            items=snapshot.items,
            missing_item_ids=[item_id for item_id in item_ids if item_id not in found_item_ids],
        )

    def _read_history_page(
        self,
        *,
        owner_subject_id: str,
        host_id: UUID,
        upstream_thread_id: str,
        items: list[CodexTimelineItemEnvelope],
        query: CodexThreadHistoryQuery,
    ) -> CodexThreadHistoryPage:
        """计算一页稳定窗口；解析失败由调用方转换为 HTTP stale 错误。"""

        return self._history_page_resolver.build_page(
            owner_subject_id=owner_subject_id,
            host_id=host_id,
            upstream_thread_id=upstream_thread_id,
            items=items,
            before_cursor=query.before_cursor,
            limit=query.limit,
        )

    @staticmethod
    def _build_unavailable_snapshot(
        thread: CodexThreadIndexSnapshot,
    ) -> CodexThreadAuthoritySnapshot:
        """Serve persisted thread metadata when live agent authority is unavailable."""

        return CodexThreadAuthoritySnapshot(
            thread=thread,
            turns=[],
            items=[],
            history_status=CodexThreadHistoryStatus.NOT_AVAILABLE_YET,
        )

    @staticmethod
    def _merge_authoritative_thread(
        indexed: CodexThreadIndexSnapshot,
        mapped: dict[str, JsonValue],
        turns: list[CodexTurnSnapshot],
    ) -> CodexThreadIndexSnapshot:
        """保留索引权威字段，仅合并 ``thread/read`` 的易失状态。"""

        mapped_status = mapped.get("status")
        return merge_authoritative_execution(
            indexed,
            mapped_status if isinstance(mapped_status, str) else None,
            turns[-1] if turns else None,
            observed_at=datetime.now(UTC),
        )

    def _reconcile_execution(
        self,
        expected: CodexThreadIndexSnapshot,
        observed: CodexThreadIndexSnapshot,
    ) -> CodexThreadIndexSnapshot:
        unit_of_work = self._control_port.create_unit_of_work()
        try:
            repository = self._control_port.create_codex_thread_repository(
                unit_of_work.get_session()
            )
            persisted = repository.reconcile_execution(
                expected=expected,
                observed=observed,
                synchronized_at=datetime.now(UTC),
            )
            unit_of_work.commit()
            return persisted or expected
        except BaseException:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def _read_owned_thread(
        self,
        host_id: UUID,
        upstream_thread_id: str,
        owner_subject_id: str,
    ) -> OwnedCodexThreadContext:
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
            return OwnedCodexThreadContext(
                thread=thread,
                workspace_key=workspace.agent_workspace_key,
            )
        finally:
            unit_of_work.dispose()
