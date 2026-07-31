"""生产 WebSocket 准入端口适配器。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from starlette.requests import Request
from starlette.websockets import WebSocket

from src.core.auth_contract.authenticated_principal_contract import AuthenticatedPrincipal
from src.core.auth_contract.authorization_policy_contract import RouteAuthorizationRequirement
from src.core.auth_contract.token_payload_contract import TokenUse
from src.core.security_contract.security_decision_contract import (
    SecurityAction,
    SecurityDecisionEnvelope,
)
from src.infrastructure.auth.authenticated_principal_resolver import (
    AuthenticatedPrincipalResolver,
)
from src.infrastructure.shared_resource_mount import SharedResourceMount
from src.infrastructure.streaming.websocket_connection_guard import (
    StreamPrincipalSnapshot,
    WebSocketAdmissionPort,
    WebSocketSecurityEventKind,
)

WEBSOCKET_AUTH_EXECUTION_NAME = "websocket_authentication"
WEBSOCKET_SECURITY_POLICY_NAME = "websocket_admission"
WEBSOCKET_SECURITY_REJECTED_MESSAGE = "WebSocket 安全策略拒绝连接。"


class ProductionWebSocketAdmissionAdapter(WebSocketAdmissionPort):
    """复用 JWT、授权、IP 封禁、限流和安全事件主链路。"""

    def __init__(
        self,
        *,
        resource_mount: SharedResourceMount,
        operation_name: str,
        authorization_requirement: RouteAuthorizationRequirement,
    ) -> None:
        """初始化生产准入事实源。"""

        self._resource_mount = resource_mount
        self._operation_name = operation_name
        self._authorization_requirement = authorization_requirement
        self._principal_resolver = AuthenticatedPrincipalResolver(resource_mount=resource_mount)

    async def authenticate_bearer(self, *, token: str) -> StreamPrincipalSnapshot:
        """验签访问令牌并读取数据库当前主体与令牌会话状态。"""

        token_payload = self._resource_mount.get_jwt_token_service().decode_token(
            token,
            expected_use=TokenUse.ACCESS,
        )
        principal = cast(
            AuthenticatedPrincipal,
            await self._resource_mount.get_request_execution_bridge().run_sync(
                execution_name=WEBSOCKET_AUTH_EXECUTION_NAME,
                callable_object=self._principal_resolver.resolve,
                token_payload=token_payload,
            ),
        )
        return self._to_snapshot(
            principal,
            expires_at=datetime.fromtimestamp(token_payload.expires_at_epoch, tz=UTC),
        )

    async def load_ticket_subject(self, *, subject_id: str) -> StreamPrincipalSnapshot:
        """读取单次票据绑定主体的当前授权快照。"""

        principal = cast(
            AuthenticatedPrincipal,
            await self._resource_mount.get_request_execution_bridge().run_sync(
                execution_name=WEBSOCKET_AUTH_EXECUTION_NAME,
                callable_object=self._load_principal,
                subject_id=subject_id,
            ),
        )
        return self._to_snapshot(principal, expires_at=None)

    async def assert_operation_allowed(
        self,
        *,
        principal: StreamPrincipalSnapshot,
        operation_name: str,
    ) -> None:
        """使用既有授权策略评估器校验操作权限。"""

        if operation_name != self._operation_name:
            raise PermissionError("WebSocket 操作名不属于当前准入绑定。")
        self._resource_mount.get_authorization_guard().assert_requirement(
            principal=AuthenticatedPrincipal(
                subject_id=principal.subject_id,
                username=principal.subject_id,
                roles=list(principal.roles),
                scopes=list(principal.scopes),
            ),
            requirement=self._authorization_requirement,
        )

    async def assert_ip_allowed(
        self,
        *,
        websocket: WebSocket,
        client_ip: str,
    ) -> None:
        """使用既有 IP 封禁事实源执行建连前校验。"""

        protection = (
            self._resource_mount.read_runtime_bundle().settings.runtime.security.detail.protection
        )
        decision = self._resource_mount.get_security_protection_guard().evaluate_request(
            request=cast(Request, websocket),
            limit=protection.flow_control.default_limit,
            window_seconds=protection.flow_control.default_window_seconds,
            block_seconds=protection.ip_block.default_block_seconds,
            ip_block_cache_ttl_seconds=protection.ip_block.cache_ttl_seconds,
            flow_control_enabled=False,
            ip_block_enabled=protection.ip_block.enabled,
            policy_name=WEBSOCKET_SECURITY_POLICY_NAME,
            rate_limit_fail_mode=protection.flow_control.fail_mode,
        )
        self._reject_security_decision(decision)

    async def assert_rate_limit(
        self,
        *,
        websocket: WebSocket,
        principal: StreamPrincipalSnapshot,
        client_ip: str,
        operation_name: str,
    ) -> None:
        """使用既有限流事实源执行连接频率校验。"""

        websocket.state.authenticated_principal = AuthenticatedPrincipal(
            subject_id=principal.subject_id,
            username=principal.subject_id,
            roles=list(principal.roles),
            scopes=list(principal.scopes),
        )
        protection = (
            self._resource_mount.read_runtime_bundle().settings.runtime.security.detail.protection
        )
        decision = self._resource_mount.get_security_protection_guard().evaluate_request(
            request=cast(Request, websocket),
            limit=protection.flow_control.default_limit,
            window_seconds=protection.flow_control.default_window_seconds,
            block_seconds=protection.ip_block.default_block_seconds,
            ip_block_cache_ttl_seconds=protection.ip_block.cache_ttl_seconds,
            flow_control_enabled=protection.flow_control.enabled,
            ip_block_enabled=False,
            policy_name=WEBSOCKET_SECURITY_POLICY_NAME,
            rate_limit_fail_mode=protection.flow_control.fail_mode,
        )
        self._reject_security_decision(decision)

    async def record_security_event(
        self,
        *,
        event_kind: WebSocketSecurityEventKind,
        operation_name: str,
        reason: str,
    ) -> None:
        """记录不含令牌、票据、正文和连接标识的准入事件。"""

        log_method = (
            self._resource_mount.get_runtime_logger().warning
            if event_kind is WebSocketSecurityEventKind.REJECTED
            else self._resource_mount.get_runtime_logger().info
        )
        log_method(
            "WebSocket 准入事件：operation=%s event=%s reason=%s",
            operation_name,
            event_kind.value,
            reason,
        )

    def _load_principal(self, *, subject_id: str) -> AuthenticatedPrincipal:
        """读取票据绑定主体当前授权事实并释放工作单元。"""

        unit_of_work = self._resource_mount.create_unit_of_work()
        try:
            repository = self._resource_mount.create_auth_identity_repository(
                unit_of_work.get_session()
            )
            snapshot = repository.get_authorization_snapshot_by_subject_id(subject_id)
            if snapshot is None or not snapshot.is_active:
                raise PermissionError("WebSocket 票据绑定主体不存在或已停用。")
            return AuthenticatedPrincipal.from_authorization_snapshot(snapshot)
        finally:
            unit_of_work.dispose()

    def _to_snapshot(
        self,
        principal: AuthenticatedPrincipal,
        *,
        expires_at: datetime | None,
    ) -> StreamPrincipalSnapshot:
        """转换为 WebSocket 最小主体快照。"""

        return StreamPrincipalSnapshot(
            subject_id=principal.subject_id,
            roles=frozenset(principal.roles),
            scopes=frozenset(principal.scopes),
            credential_expires_at=expires_at,
        )

    def _reject_security_decision(self, decision: SecurityDecisionEnvelope) -> None:
        """发射已有安全事件并把拒绝决策转换为准入异常。"""

        if decision.security_event is not None:
            self._resource_mount.emit_security_event(decision.security_event)
        if decision.action is SecurityAction.RETURN_429:
            raise PermissionError(WEBSOCKET_SECURITY_REJECTED_MESSAGE)
