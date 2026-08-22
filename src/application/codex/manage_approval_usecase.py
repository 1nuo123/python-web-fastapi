"""Codex 基础审批列表与幂等决定用例。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from uuid import UUID, uuid4

from pydantic import JsonValue

from src.application.ports.codex_agent_command_dispatch_port import (
    CodexAgentCommandDispatchPort,
)
from src.application.ports.codex_command_payload_cipher_port import (
    CodexCommandPayloadCipherPort,
)
from src.application.ports.codex_control_port import CodexControlPort
from src.application.ports.codex_realtime_event_port import CodexRealtimeEventPort
from src.application.ports.step_up_grant_port import StepUpGrantPort
from src.core.auth_contract.authorization_policy_contract import RouteAuthorizationRequirement
from src.core.auth_contract.step_up_grant_contract import StepUpGrantPurpose
from src.core.codex_contract.agent_protocol_contract import CodexAgentCommand
from src.core.codex_contract.approval_contract import (
    CodexApprovalAuditSnapshot,
    CodexApprovalCollection,
    CodexApprovalDecision,
    CodexApprovalState,
)
from src.core.codex_contract.command_outbox_contract import (
    CodexCommandOutboxSnapshot,
    CodexCommandOutboxState,
)
from src.core.codex_contract.connection_session_contract import CodexHostOfflineError
from src.core.codex_contract.operation_contract import CodexControlOperationSnapshot
from src.core.codex_contract.turn_contract import CodexOperationAccepted
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.domain.codex.agent_command_policy import calculate_agent_request_digest
from src.domain.codex.codex_authorization_policy import (
    build_codex_approval_decision_authorization_requirement,
)
from src.domain.codex.codex_error_code import CodexErrorCode
from src.domain.codex.host_status import CodexOperationStatus


@dataclass(frozen=True, slots=True)
class PreparedApprovalDecision:
    """数据库已提交、可按固定 command id 投递的审批决定。"""

    approval: CodexApprovalAuditSnapshot
    operation: CodexControlOperationSnapshot
    command: CodexAgentCommand
    replayed: bool


class ManageCodexApprovalUsecase:
    """审批 CAS、HTTP 幂等与 Agent 本地 journal 三层收敛。"""

    def __init__(
        self,
        *,
        control_port: CodexControlPort,
        dispatch_port: CodexAgentCommandDispatchPort,
        payload_cipher: CodexCommandPayloadCipherPort,
        ack_timeout_seconds: int,
        outbox_ttl_seconds: int,
        event_port: CodexRealtimeEventPort,
        step_up_port: StepUpGrantPort,
    ) -> None:
        self._control_port = control_port
        self._dispatch_port = dispatch_port
        self._payload_cipher = payload_cipher
        self._ack_timeout_seconds = ack_timeout_seconds
        self._outbox_ttl_seconds = outbox_ttl_seconds
        self._event_port = event_port
        self._step_up_port = step_up_port

    def list(self, *, owner_subject_id: str) -> CodexApprovalCollection:
        unit_of_work = self._control_port.create_unit_of_work()
        try:
            repository = self._control_port.create_codex_approval_repository(
                unit_of_work.get_session()
            )
            return CodexApprovalCollection(items=repository.list_by_owner(owner_subject_id))
        finally:
            unit_of_work.dispose()

    def read_decision_authorization_requirement(
        self,
        *,
        approval_id: UUID,
        owner_subject_id: str,
        decision: str,
    ) -> RouteAuthorizationRequirement:
        """读取审批并返回接受该具体能力所需的额外 scope。"""

        unit_of_work = self._control_port.create_unit_of_work()
        try:
            approval = self._control_port.create_codex_approval_repository(
                unit_of_work.get_session()
            ).get_by_id_and_owner(approval_id, owner_subject_id)
            if approval is None:
                raise self._not_found()
            return build_codex_approval_decision_authorization_requirement(
                approval,
                CodexApprovalDecision(decision),
            )
        finally:
            unit_of_work.dispose()

    async def decide(
        self,
        *,
        approval_id: UUID,
        approval_version: int,
        decision: str,
        actor_subject_id: str,
        idempotency_key: str,
        step_up_token: str | None,
    ) -> CodexOperationAccepted:
        step_up_verified = False
        if step_up_token is not None:
            step_up_verified = await self._step_up_port.consume(
                token=step_up_token,
                subject_id=actor_subject_id,
                purpose=StepUpGrantPurpose.CODEX_HIGH_RISK_APPROVAL,
            )
        prepared = await asyncio.to_thread(
            self._prepare,
            approval_id=approval_id,
            approval_version=approval_version,
            decision=decision,
            actor_subject_id=actor_subject_id,
            idempotency_key=idempotency_key,
            step_up_verified=step_up_verified,
        )
        if prepared.replayed:
            return self._acceptance(prepared.operation, replayed=True)
        try:
            ack = await self._dispatch_port.dispatch(
                prepared.command,
                ack_timeout_seconds=self._ack_timeout_seconds,
            )
        except CodexHostOfflineError as exc:
            await asyncio.to_thread(
                self._update_delivery,
                prepared,
                CodexOperationStatus.FAILED,
                CodexApprovalState.DELIVERY_FAILED,
                CodexErrorCode.HOST_OFFLINE.value,
            )
            raise HttpFaultException(
                status_code=HTTPStatus.CONFLICT,
                error_code=CodexErrorCode.HOST_OFFLINE,
                message="Codex主机离线，审批可按原Idempotency-Key重试。",
            ) from exc
        except TimeoutError as exc:
            await asyncio.to_thread(
                self._update_delivery,
                prepared,
                CodexOperationStatus.TIMED_OUT,
                CodexApprovalState.CLAIMED,
                CodexErrorCode.AGENT_ACK_TIMEOUT.value,
            )
            raise HttpFaultException(
                status_code=HTTPStatus.GATEWAY_TIMEOUT,
                error_code=CodexErrorCode.AGENT_ACK_TIMEOUT,
                message="审批交付结果未知，必须按原command_id核对。",
            ) from exc
        applied = ack.state in {"accepted", "executing", "completed"}
        operation, approval = await asyncio.to_thread(
            self._update_delivery,
            prepared,
            CodexOperationStatus.COMPLETED if applied else CodexOperationStatus.FAILED,
            (CodexApprovalState.APPLIED if applied else CodexApprovalState.DELIVERY_FAILED),
        )
        await self._event_port.publish_approval_resolved(approval)
        return self._acceptance(operation, replayed=ack.replayed)

    def _prepare(
        self,
        *,
        approval_id: UUID,
        approval_version: int,
        decision: str,
        actor_subject_id: str,
        idempotency_key: str,
        step_up_verified: bool,
    ) -> PreparedApprovalDecision:
        unit_of_work = self._control_port.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            approval_repository = self._control_port.create_codex_approval_repository(session)
            approval = approval_repository.get_by_id_and_owner(
                approval_id,
                actor_subject_id,
            )
            if approval is None:
                raise self._not_found()
            parsed_decision = self._parse_decision(decision)
            # Agent 未明确广告的动作不能由历史默认值补全，避免 API 接受浏览器未展示的授权。
            allowed_actions = approval.display_summary.allowed_actions
            if parsed_decision not in allowed_actions:
                raise HttpFaultException(
                    status_code=HTTPStatus.CONFLICT,
                    error_code=CodexErrorCode.STATE_CONFLICT,
                    message="该审批请求不支持所选官方动作。",
                )
            params: dict[str, JsonValue] = {
                "approvalId": str(approval_id),
                "decision": parsed_decision.value,
                "approvalVersion": approval_version,
            }
            digest = calculate_agent_request_digest("approval.decision", params)
            operation_repository = self._control_port.create_codex_operation_repository(session)
            existing = operation_repository.get_by_actor_and_idempotency_key(
                actor_subject_id,
                idempotency_key,
            )
            now = datetime.now(UTC)
            if existing is not None:
                if existing.request_digest != digest:
                    raise HttpFaultException(
                        status_code=HTTPStatus.CONFLICT,
                        error_code=CodexErrorCode.IDEMPOTENCY_CONFLICT,
                        message="Idempotency-Key已用于不同请求。",
                    )
                replayed = existing.status in {
                    CodexOperationStatus.COMPLETED.value,
                    CodexOperationStatus.ACKNOWLEDGED.value,
                }
                if replayed:
                    operation = existing
                else:
                    operation = existing.model_copy(
                        update={
                            "status": CodexOperationStatus.DISPATCHED.value,
                            "dispatch_attempt": existing.dispatch_attempt + 1,
                            "last_dispatched_at": now,
                            "ack_deadline_at": now + timedelta(seconds=self._ack_timeout_seconds),
                            "error_code": None,
                            "updated_at": now,
                        }
                    )
                    operation_repository.save(operation)
                    if approval.state == CodexApprovalState.DELIVERY_FAILED:
                        approval = approval.model_copy(
                            update={
                                "state": CodexApprovalState.CLAIMED,
                                "updated_at": now,
                            }
                        )
                        approval_repository.save(approval)
            else:
                if approval.risk_level == "high" and parsed_decision in {
                    CodexApprovalDecision.ACCEPT,
                    CodexApprovalDecision.ACCEPT_FOR_SESSION,
                    CodexApprovalDecision.ACCEPT_WITH_EXECPOLICY_AMENDMENT,
                    CodexApprovalDecision.APPLY_NETWORK_POLICY_AMENDMENT,
                }:
                    if not step_up_verified:
                        raise HttpFaultException(
                            status_code=HTTPStatus.FORBIDDEN,
                            error_code=CodexErrorCode.STATE_CONFLICT,
                            message="高风险审批需要有效的step-up授权。",
                        )
                claimed = approval_repository.claim_decision(
                    approval_id=approval_id,
                    owner_subject_id=actor_subject_id,
                    expected_version=approval_version,
                    decided_by=actor_subject_id,
                    decision=parsed_decision.value,
                    decided_at=now,
                )
                if claimed is None:
                    raise HttpFaultException(
                        status_code=HTTPStatus.GONE,
                        error_code=CodexErrorCode.APPROVAL_GONE,
                        message="审批已处理、过期或版本冲突。",
                    )
                approval = claimed
                self._control_port.create_codex_thread_repository(session).advance_activity(
                    host_id=approval.host_id,
                    upstream_thread_id=approval.thread_id,
                    owner_subject_id=actor_subject_id,
                    occurred_at=now,
                )
                operation = CodexControlOperationSnapshot(
                    operation_id=uuid4(),
                    command_id=uuid4(),
                    actor_subject_id=actor_subject_id,
                    owner_subject_id=actor_subject_id,
                    host_id=approval.host_id,
                    workspace_id=approval.workspace_id,
                    thread_id=approval.thread_id,
                    operation_type="approval.decision",
                    idempotency_key=idempotency_key,
                    request_digest=digest,
                    status=CodexOperationStatus.DISPATCHED.value,
                    dispatch_attempt=1,
                    last_dispatched_at=now,
                    ack_deadline_at=now + timedelta(seconds=self._ack_timeout_seconds),
                    created_at=now,
                    updated_at=now,
                )
                operation_repository.add(operation)
                unit_of_work.flush()
                replayed = False
            command = CodexAgentCommand(
                command_id=operation.command_id,
                operation_id=operation.operation_id,
                host_id=operation.host_id,
                request_digest=operation.request_digest,
                command_type="approval.decision",
                params=params,
                deadline=now + timedelta(seconds=self._ack_timeout_seconds),
            )
            outbox_repository = self._control_port.create_codex_command_outbox_repository(session)
            if outbox_repository.get_by_command_id(operation.command_id) is None:
                outbox_repository.add(
                    CodexCommandOutboxSnapshot(
                        outbox_id=uuid4(),
                        operation_id=operation.operation_id,
                        command_id=operation.command_id,
                        host_id=operation.host_id,
                        owner_subject_id=actor_subject_id,
                        payload=self._payload_cipher.encrypt(command, actor_subject_id),
                        state=CodexCommandOutboxState.PENDING,
                        dispatch_attempt=0,
                        available_at=now,
                        expires_at=now + timedelta(seconds=self._outbox_ttl_seconds),
                        created_at=now,
                        updated_at=now,
                        version=1,
                    )
                )
            unit_of_work.commit()
            return PreparedApprovalDecision(approval, operation, command, replayed)
        except BaseException:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def _update_delivery(
        self,
        prepared: PreparedApprovalDecision,
        operation_status: CodexOperationStatus,
        approval_state: CodexApprovalState,
        error_code: str | None = None,
    ) -> tuple[CodexControlOperationSnapshot, CodexApprovalAuditSnapshot]:
        unit_of_work = self._control_port.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            operation_repository = self._control_port.create_codex_operation_repository(session)
            approval_repository = self._control_port.create_codex_approval_repository(session)
            operation = operation_repository.get_by_id_and_owner(
                prepared.operation.operation_id,
                prepared.operation.owner_subject_id,
            )
            approval = approval_repository.get_by_id_and_owner(
                prepared.approval.approval_id,
                prepared.approval.owner_subject_id,
            )
            if operation is None or approval is None:
                raise RuntimeError("审批交付状态更新目标不存在。")
            now = datetime.now(UTC)
            updated_operation = operation.model_copy(
                update={
                    "status": operation_status.value,
                    "accepted_at": now
                    if operation_status == CodexOperationStatus.COMPLETED
                    else operation.accepted_at,
                    "completed_at": now
                    if operation_status
                    in {CodexOperationStatus.COMPLETED, CodexOperationStatus.FAILED}
                    else operation.completed_at,
                    "error_code": error_code,
                    "updated_at": now,
                }
            )
            operation_repository.save(updated_operation)
            updated_approval = approval.model_copy(
                update={
                    "state": approval_state,
                    "applied_at": now if approval_state == "applied" else approval.applied_at,
                    "updated_at": now,
                }
            )
            approval_repository.save(updated_approval)
            unit_of_work.commit()
            return updated_operation, updated_approval
        except BaseException:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def _acceptance(
        self,
        operation: CodexControlOperationSnapshot,
        *,
        replayed: bool,
    ) -> CodexOperationAccepted:
        return CodexOperationAccepted(
            operation_id=operation.operation_id,
            command_id=operation.command_id,
            status=operation.status,
            replayed=replayed,
        )

    @staticmethod
    def _parse_decision(decision: str) -> CodexApprovalDecision:
        """把 API 输入限制为 App Server 官方动作集合。"""

        try:
            return CodexApprovalDecision(decision)
        except ValueError as exc:
            raise HttpFaultException(
                status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                error_code=CodexErrorCode.STATE_CONFLICT,
                message="审批决定不受支持。",
            ) from exc

    def _not_found(self) -> HttpFaultException:
        return HttpFaultException(
            status_code=HTTPStatus.NOT_FOUND,
            error_code=CodexErrorCode.RESOURCE_NOT_FOUND,
            message="Codex资源不存在。",
        )
