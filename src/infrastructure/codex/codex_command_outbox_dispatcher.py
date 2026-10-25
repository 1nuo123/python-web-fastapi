"""加密 Codex command outbox 的多实例路由与恢复。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from src.application.ports.codex_command_payload_cipher_port import (
    CodexCommandPayloadCipherPort,
)
from src.application.ports.codex_control_port import CodexControlPort
from src.core.codex_contract.agent_protocol_contract import (
    CodexAgentCommand,
    CodexAgentCommandAck,
)
from src.core.codex_contract.command_outbox_contract import (
    CodexCommandOutboxSnapshot,
    CodexCommandOutboxState,
)
from src.core.codex_contract.connection_session_contract import CodexHostOfflineError
from src.core.codex_contract.instance_control_contract import (
    CodexDispatchSignalDetail,
    CodexInstanceControlSignal,
)
from src.core.outbox_contract.reliable_outbox_contract import (
    AsyncReliableOutboxAdapterPort,
    OutboxDeliveryOutcome,
)
from src.infrastructure.codex.codex_connection_registry import CodexConnectionRegistry
from src.infrastructure.codex.codex_host_actor import CodexHostActorRegistry
from src.infrastructure.codex.codex_host_presence_adapter import CodexHostPresenceAdapter
from src.infrastructure.codex.codex_active_host_service import CodexActiveHostService
from src.infrastructure.codex.codex_instance_control_signal_adapter import (
    CodexInstanceControlSignalAdapter,
)


class CodexCommandOutboxDispatcher(AsyncReliableOutboxAdapterPort[CodexCommandOutboxSnapshot]):
    """claim 后按 presence 选择本地 socket 或远端引用信号。"""

    def __init__(
        self,
        *,
        control_port: CodexControlPort,
        active_host: CodexActiveHostService,
        payload_cipher: CodexCommandPayloadCipherPort,
        presence: CodexHostPresenceAdapter,
        connection_registry: CodexConnectionRegistry,
        actor_registry: CodexHostActorRegistry,
        signal_adapter: CodexInstanceControlSignalAdapter,
        instance_id: UUID,
        ack_timeout_seconds: int,
        retry_seconds: int,
        completed_retention_seconds: int,
    ) -> None:
        self._active_host = active_host
        self._control_port = control_port
        self._payload_cipher = payload_cipher
        self._presence = presence
        self._connection_registry = connection_registry
        self._actor_registry = actor_registry
        self._signal_adapter = signal_adapter
        self._instance_id = instance_id
        self._ack_timeout_seconds = ack_timeout_seconds
        self._retry_seconds = retry_seconds
        self._completed_retention_seconds = completed_retention_seconds

    async def claim(
        self,
        *,
        limit: int,
        stale_before_epoch: int | None,
    ) -> list[CodexCommandOutboxSnapshot]:
        return await asyncio.to_thread(self._claim_ready, limit, stale_before_epoch)

    async def deliver(self, record: CodexCommandOutboxSnapshot) -> OutboxDeliveryOutcome:
        ack = await self._deliver_claimed(record, expected_fencing_token=None)
        if ack.state == "deferred":
            return OutboxDeliveryOutcome.DEFERRED
        if ack.state == "unknown":
            return OutboxDeliveryOutcome.UNKNOWN
        return OutboxDeliveryOutcome.DELIVERED

    async def record_failure(
        self,
        record: CodexCommandOutboxSnapshot,
        failure_reason: str,
    ) -> None:
        await asyncio.to_thread(
            self._mark,
            record.command_id,
            CodexCommandOutboxState.FAILED,
            "codex.command.dispatch_failed",
            None,
        )

    async def dispatch_command(self, command: CodexAgentCommand) -> CodexAgentCommandAck:
        """HTTP commit 后立即 claim 固定 command id；失败仍由 runner 恢复。"""

        record = await asyncio.to_thread(self._claim_by_command_id, command.command_id)
        if record is None:
            current = await asyncio.to_thread(self._read_by_command_id, command.command_id)
            if current is None:
                raise RuntimeError("Codex command outbox不存在。")
            if current.state in {
                CodexCommandOutboxState.ACCEPTED,
                CodexCommandOutboxState.COMPLETED,
            }:
                return CodexAgentCommandAck(
                    command_id=command.command_id,
                    operation_id=command.operation_id,
                    state="accepted",
                    replayed=True,
                )
            return self._deferred_ack(command)
        return await self._deliver_claimed(record, expected_fencing_token=None)

    async def dispatch_signaled(
        self,
        *,
        command_id: UUID,
        route_fencing_token: int,
    ) -> None:
        record = await asyncio.to_thread(self._claim_by_command_id, command_id)
        if record is None:
            return
        await self._deliver_claimed(
            record,
            expected_fencing_token=route_fencing_token,
        )

    async def _deliver_claimed(
        self,
        record: CodexCommandOutboxSnapshot,
        *,
        expected_fencing_token: int | None,
    ) -> CodexAgentCommandAck:
        active = await self._active_host.reconcile(record.owner_subject_id)
        if (
            active.active_host_id != record.host_id
            or active.activated_at is None
            or record.created_at < active.activated_at
        ):
            await asyncio.to_thread(
                self._mark,
                record.command_id,
                CodexCommandOutboxState.FAILED,
                "codex.connection.inactive_generation",
                record.route_epoch,
            )
            return CodexAgentCommandAck(
                command_id=record.command_id,
                operation_id=record.operation_id,
                state="failed",
                replayed=False,
            )
        try:
            command = (await asyncio.to_thread(self._decrypt_command, record)).model_copy(
                update={"execution_generation": active.version}
            )
        except (RuntimeError, ValueError):
            await asyncio.to_thread(
                self._mark,
                record.command_id,
                CodexCommandOutboxState.FAILED,
                "codex.command.decrypt_failed",
                record.route_epoch,
            )
            return CodexAgentCommandAck(
                command_id=record.command_id,
                operation_id=record.operation_id,
                state="unknown",
                replayed=False,
            )
        try:
            presence = await self._presence.read(record.host_id)
        except RuntimeError:
            await asyncio.to_thread(
                self._mark_deferred,
                record.command_id,
                "codex.route.redis_unavailable",
                None,
            )
            return self._deferred_ack(command)
        if presence is None:
            await asyncio.to_thread(
                self._mark_deferred,
                record.command_id,
                "codex.route.host_offline",
                None,
            )
            return self._deferred_ack(command)
        if expected_fencing_token is not None and presence.fencing_token != expected_fencing_token:
            await asyncio.to_thread(
                self._mark_deferred,
                record.command_id,
                "codex.route.stale_fence",
                presence.fencing_token,
            )
            return self._deferred_ack(command)
        if presence.owner.instance_id != self._instance_id:
            try:
                await self._signal_adapter.publish(
                    CodexInstanceControlSignal(
                        signal_id=uuid4(),
                        target_instance_id=presence.owner.instance_id,
                        detail=CodexDispatchSignalDetail(
                            command_id=record.command_id,
                            host_id=record.host_id,
                            route_fencing_token=presence.fencing_token,
                        ),
                    )
                )
            except RuntimeError:
                await asyncio.to_thread(
                    self._mark_deferred,
                    record.command_id,
                    "codex.route.remote_signal_failed",
                    presence.fencing_token,
                )
                return self._deferred_ack(command)
            await asyncio.to_thread(
                self._mark_routed,
                record.command_id,
                presence.fencing_token,
            )
            return self._deferred_ack(command)
        local_lease = await self._connection_registry.read(record.host_id)
        if local_lease is None or local_lease.epoch != presence.owner.connection_epoch:
            await asyncio.to_thread(
                self._mark_deferred,
                record.command_id,
                "codex.route.local_epoch_stale",
                presence.fencing_token,
            )
            return self._deferred_ack(command)
        try:
            accepted = await self._actor_registry.get(record.host_id).dispatch(
                command,
                ack_timeout_seconds=self._ack_timeout_seconds,
            )
        except (CodexHostOfflineError, TimeoutError):
            await asyncio.to_thread(
                self._mark_deferred,
                record.command_id,
                "codex.route.ack_deferred",
                presence.fencing_token,
            )
            return self._deferred_ack(command)
        state = (
            CodexCommandOutboxState.UNKNOWN
            if accepted.ack.state == "unknown"
            else CodexCommandOutboxState.ACCEPTED
        )
        await asyncio.to_thread(
            self._mark,
            record.command_id,
            state,
            None,
            presence.fencing_token,
        )
        return accepted.ack

    def _claim_ready(
        self,
        limit: int,
        stale_before_epoch: int | None,
    ) -> list[CodexCommandOutboxSnapshot]:
        unit_of_work = self._control_port.create_unit_of_work()
        try:
            repository = self._control_port.create_codex_command_outbox_repository(
                unit_of_work.get_session()
            )
            repository.delete_completed_before(
                datetime.now(UTC) - timedelta(seconds=self._completed_retention_seconds)
            )
            records = repository.claim_ready(
                claimed_by=str(self._instance_id),
                current_time=datetime.now(UTC),
                stale_before=(
                    datetime.fromtimestamp(stale_before_epoch, tz=UTC)
                    if stale_before_epoch is not None
                    else datetime.now(UTC) - timedelta(seconds=self._retry_seconds)
                ),
                limit=limit,
            )
            unit_of_work.commit()
            return records
        except BaseException:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def _claim_by_command_id(self, command_id: UUID) -> CodexCommandOutboxSnapshot | None:
        unit_of_work = self._control_port.create_unit_of_work()
        try:
            record = self._control_port.create_codex_command_outbox_repository(
                unit_of_work.get_session()
            ).claim_by_command_id(
                command_id=command_id,
                claimed_by=str(self._instance_id),
                current_time=datetime.now(UTC),
            )
            unit_of_work.commit()
            return record
        except BaseException:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def _read_by_command_id(self, command_id: UUID) -> CodexCommandOutboxSnapshot | None:
        unit_of_work = self._control_port.create_unit_of_work()
        try:
            return self._control_port.create_codex_command_outbox_repository(
                unit_of_work.get_session()
            ).get_by_command_id(command_id)
        finally:
            unit_of_work.dispose()

    def _decrypt_command(self, record: CodexCommandOutboxSnapshot) -> CodexAgentCommand:
        unit_of_work = self._control_port.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            operation = self._control_port.create_codex_operation_repository(
                session
            ).get_by_id_and_owner(record.operation_id, record.owner_subject_id)
            if operation is None:
                raise RuntimeError("Codex outbox关联operation不存在。")
            reference = CodexAgentCommand(
                command_id=record.command_id,
                operation_id=record.operation_id,
                host_id=record.host_id,
                request_digest=operation.request_digest,
                command_type=operation.operation_type,
                params={},
                deadline=record.expires_at,
            )
            command = self._payload_cipher.decrypt(
                record.payload,
                reference,
                record.owner_subject_id,
            )
            return command
        finally:
            unit_of_work.dispose()

    def _mark_deferred(
        self,
        command_id: UUID,
        error_code: str,
        route_epoch: int | None,
    ) -> None:
        self._mark(
            command_id,
            CodexCommandOutboxState.DEFERRED,
            error_code,
            route_epoch,
        )

    def _mark_routed(
        self,
        command_id: UUID,
        route_epoch: int,
    ) -> None:
        self._mark(
            command_id,
            CodexCommandOutboxState.ROUTED,
            None,
            route_epoch,
        )

    def _mark(
        self,
        command_id: UUID,
        state: CodexCommandOutboxState,
        error_code: str | None,
        route_epoch: int | None,
    ) -> None:
        unit_of_work = self._control_port.create_unit_of_work()
        try:
            repository = self._control_port.create_codex_command_outbox_repository(
                unit_of_work.get_session()
            )
            current = repository.get_by_command_id(command_id)
            if current is None:
                raise RuntimeError("Codex command outbox状态更新目标不存在。")
            now = datetime.now(UTC)
            repository.save(
                current.model_copy(
                    update={
                        "state": state,
                        "route_epoch": route_epoch,
                        "available_at": (
                            now + timedelta(seconds=self._retry_seconds)
                            if state
                            in {
                                CodexCommandOutboxState.DEFERRED,
                                CodexCommandOutboxState.ROUTED,
                            }
                            else current.available_at
                        ),
                        "accepted_at": (
                            now
                            if state == CodexCommandOutboxState.ACCEPTED
                            else current.accepted_at
                        ),
                        "completed_at": (
                            now
                            if state
                            in {
                                CodexCommandOutboxState.COMPLETED,
                                CodexCommandOutboxState.FAILED,
                            }
                            else current.completed_at
                        ),
                        "last_error_code": error_code,
                        "updated_at": now,
                        "version": current.version + 1,
                    }
                )
            )
            if state is CodexCommandOutboxState.FAILED:
                operations = self._control_port.create_codex_operation_repository(
                    unit_of_work.get_session()
                )
                operation = operations.get_by_id_and_owner(
                    current.operation_id, current.owner_subject_id
                )
                if operation is not None and operation.status not in {"completed", "cancelled"}:
                    operations.save(
                        operation.model_copy(
                            update={
                                "status": "failed",
                                "error_code": error_code,
                                "completed_at": now,
                                "updated_at": now,
                            }
                        )
                    )
            unit_of_work.commit()
        except BaseException:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def _deferred_ack(self, command: CodexAgentCommand) -> CodexAgentCommandAck:
        return CodexAgentCommandAck(
            command_id=command.command_id,
            operation_id=command.operation_id,
            state="deferred",
            replayed=False,
        )
