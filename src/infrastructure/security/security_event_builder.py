"""
安全事件构建器模块。
"""

from __future__ import annotations

import time
from http import HTTPStatus

from fastapi import Request

from src.core.http_contract.request_scope_contract import RequestScope
from src.core.security_contract.security_event_contract import (
    AdminIdentitySecurityEventDetail,
    AuthFailureSecurityEventDetail,
    AuthorizationSecurityEventDetail,
    ConfigSecurityEventDetail,
    IpBlockSecurityEventDetail,
    PayloadSecurityEventDetail,
    RateLimitSecurityEventDetail,
    SecurityEventDecision,
    SecurityEventEnvelope,
    SecurityEventHeader,
    SecurityEventSeverity,
    SecurityEventType,
    SsrfSecurityEventDetail,
    TokenBindingSecurityEventDetail,
)

SECURITY_EVENT_POLICY_DEFAULT = "security_default"
MISSING_REQUEST_SCOPE_ID = "request-scope-missing"
MISSING_REQUEST_TIME_EPOCH = 0
SECURITY_EVENT_ALLOWED_REASON = "security.allowed"
CONFIG_SECURITY_REJECTED_PATH = "runtime.settings"
CONFIG_SECURITY_REJECTED_METHOD = "RELOAD"
CONFIG_SECURITY_REJECTED_REQUEST_ID = "settings-apply"
CONFIG_SECURITY_REJECTED_FIELD_COUNT = 1


class SecurityEventBuilder:
    """
    安全事件构建器。
    """

    def build_rate_limit_event(
        self,
        *,
        request: Request,
        ip_digest: str,
        count: int,
        limit: int,
        blocked: bool,
    ) -> SecurityEventEnvelope:
        """
        构建限流安全事件。
        """

        request_scope = self._read_request_scope(request)
        detail = RateLimitSecurityEventDetail(
            ip_digest=ip_digest,
            count=count,
            limit=limit,
            blocked=blocked,
        )
        return SecurityEventEnvelope(
            header=self._build_header(
                event_type=SecurityEventType.RATE_LIMIT_BLOCKED,
                detail_kind=detail.kind,
                severity=SecurityEventSeverity.WARNING,
                decision=SecurityEventDecision.THROTTLE,
                reason_code=SecurityEventType.RATE_LIMIT_BLOCKED.value,
                request_id=request_scope.request_id,
                trace_id=request_scope.trace_id,
                path=request.url.path,
                method=request.method,
                status_code=int(HTTPStatus.TOO_MANY_REQUESTS),
                subject_id=request_scope.authenticated_subject_id,
                ip_digest=ip_digest,
                policy_name=SECURITY_EVENT_POLICY_DEFAULT,
            ),
            detail=detail,
        )

    def build_auth_failure_event(
        self,
        *,
        request: Request,
        subject_digest: str | None,
        ip_digest: str | None,
        reason_code: str,
        event_type: SecurityEventType = SecurityEventType.AUTH_LOGIN_FAILURE,
        status_code: int | None = HTTPStatus.UNAUTHORIZED,
        user_agent_digest: str | None = None,
    ) -> SecurityEventEnvelope:
        """
        构建认证失败安全事件。
        """

        detail = AuthFailureSecurityEventDetail(
            subject_digest=subject_digest,
            ip_digest=ip_digest,
            reason_code=reason_code,
        )
        request_scope = self._read_request_scope(request)
        return SecurityEventEnvelope(
            header=self._build_header(
                event_type=event_type,
                detail_kind=detail.kind,
                severity=SecurityEventSeverity.WARNING,
                decision=SecurityEventDecision.DENY,
                reason_code=reason_code,
                request_id=request_scope.request_id,
                trace_id=request_scope.trace_id,
                path=request.url.path,
                method=request.method,
                status_code=None if status_code is None else int(status_code),
                subject_id=None,
                ip_digest=ip_digest,
                user_agent_digest=user_agent_digest,
                policy_name=SECURITY_EVENT_POLICY_DEFAULT,
            ),
            detail=detail,
        )

    def build_payload_event(
        self,
        *,
        request_scope: RequestScope,
        path: str,
        method: str,
        limit_bytes: int,
    ) -> SecurityEventEnvelope:
        """
        构建请求体过大安全事件。
        """

        detail = PayloadSecurityEventDetail(limit_bytes=limit_bytes)
        return SecurityEventEnvelope(
            header=self._build_header(
                event_type=SecurityEventType.PAYLOAD_TOO_LARGE,
                detail_kind=detail.kind,
                severity=SecurityEventSeverity.WARNING,
                decision=SecurityEventDecision.DENY,
                reason_code=SecurityEventType.PAYLOAD_TOO_LARGE.value,
                request_id=request_scope.request_id,
                trace_id=request_scope.trace_id,
                path=path,
                method=method,
                status_code=int(HTTPStatus.REQUEST_ENTITY_TOO_LARGE),
                policy_name=SECURITY_EVENT_POLICY_DEFAULT,
            ),
            detail=detail,
        )

    def build_token_binding_event(
        self,
        *,
        request: Request,
        token_digest: str,
        ip_digest: str,
        reason_code: str,
    ) -> SecurityEventEnvelope:
        """
        构建 Token-IP 绑定安全事件。
        """

        detail = TokenBindingSecurityEventDetail(
            token_digest=token_digest,
            ip_digest=ip_digest,
            reason_code=reason_code,
        )
        request_scope = self._read_request_scope(request)
        return SecurityEventEnvelope(
            header=self._build_header(
                event_type=SecurityEventType.TOKEN_BINDING_MISMATCH,
                detail_kind=detail.kind,
                severity=SecurityEventSeverity.HIGH,
                decision=SecurityEventDecision.DENY,
                reason_code=reason_code,
                request_id=request_scope.request_id,
                trace_id=request_scope.trace_id,
                path=request.url.path,
                method=request.method,
                status_code=int(HTTPStatus.UNAUTHORIZED),
                subject_id=request_scope.authenticated_subject_id,
                ip_digest=ip_digest,
                policy_name=SECURITY_EVENT_POLICY_DEFAULT,
            ),
            detail=detail,
        )

    def build_ssrf_event(
        self,
        *,
        request_scope: RequestScope,
        host_digest: str | None,
        reason_code: str,
    ) -> SecurityEventEnvelope:
        """
        构建 SSRF 拦截安全事件。
        """

        detail = SsrfSecurityEventDetail(
            host_digest=host_digest,
            reason_code=reason_code,
        )
        return SecurityEventEnvelope(
            header=self._build_header(
                event_type=SecurityEventType.SSRF_BLOCKED,
                detail_kind=detail.kind,
                severity=SecurityEventSeverity.HIGH,
                decision=SecurityEventDecision.DENY,
                reason_code=reason_code,
                request_id=request_scope.request_id,
                trace_id=request_scope.trace_id,
                path=request_scope.request_path,
                method=request_scope.request_method,
                status_code=int(HTTPStatus.BAD_REQUEST),
                policy_name=SECURITY_EVENT_POLICY_DEFAULT,
            ),
            detail=detail,
        )

    def build_ip_block_event(
        self,
        *,
        request: Request,
        ip_digest: str,
        reason_code: str,
        event_type: SecurityEventType,
        status_code: int | HTTPStatus,
        blocked: bool,
        blocked_until_epoch: int | None = None,
        retry_after_seconds: int | None = None,
    ) -> SecurityEventEnvelope:
        """
        构建 IP 封禁安全事件。

        :param request: 当前请求。
        :type request: Request
        :param ip_digest: IP 摘要。
        :type ip_digest: str
        :param reason_code: 事件原因。
        :type reason_code: str
        :param event_type: 事件类型。
        :type event_type: SecurityEventType
        :param status_code: HTTP 状态码。
        :type status_code: int | HTTPStatus
        :returns: 安全事件信封。
        :rtype: SecurityEventEnvelope
        """

        detail = IpBlockSecurityEventDetail(
            ip_digest=ip_digest,
            reason_code=reason_code,
            blocked=blocked,
            blocked_until_epoch=blocked_until_epoch,
            retry_after_seconds=retry_after_seconds,
        )
        request_scope = self._read_request_scope(request)
        return self._build_ip_block_event_from_scope(
            request_scope=request_scope,
            path=request.url.path,
            method=request.method,
            ip_digest=ip_digest,
            reason_code=reason_code,
            event_type=event_type,
            status_code=status_code,
            detail=detail,
        )

    def build_ip_block_event_from_scope(
        self,
        *,
        request_scope: RequestScope,
        ip_digest: str,
        reason_code: str,
        event_type: SecurityEventType,
        status_code: int | HTTPStatus,
        blocked: bool,
        blocked_until_epoch: int | None = None,
        retry_after_seconds: int | None = None,
    ) -> SecurityEventEnvelope:
        """
        基于请求作用域构建 IP 封禁安全事件。
        """

        detail = IpBlockSecurityEventDetail(
            ip_digest=ip_digest,
            reason_code=reason_code,
            blocked=blocked,
            blocked_until_epoch=blocked_until_epoch,
            retry_after_seconds=retry_after_seconds,
        )
        return self._build_ip_block_event_from_scope(
            request_scope=request_scope,
            path=request_scope.request_path,
            method=request_scope.request_method,
            ip_digest=ip_digest,
            reason_code=reason_code,
            event_type=event_type,
            status_code=status_code,
            detail=detail,
        )

    def _build_ip_block_event_from_scope(
        self,
        *,
        request_scope: RequestScope,
        path: str,
        method: str,
        ip_digest: str,
        reason_code: str,
        event_type: SecurityEventType,
        status_code: int | HTTPStatus,
        detail: IpBlockSecurityEventDetail,
    ) -> SecurityEventEnvelope:
        """
        构建 IP 封禁安全事件信封。
        """

        return SecurityEventEnvelope(
            header=self._build_header(
                event_type=event_type,
                detail_kind=detail.kind,
                severity=SecurityEventSeverity.WARNING,
                decision=SecurityEventDecision.RECORD_ONLY,
                reason_code=reason_code,
                request_id=request_scope.request_id,
                trace_id=request_scope.trace_id,
                path=path,
                method=method,
                status_code=int(status_code),
                subject_id=request_scope.authenticated_subject_id,
                ip_digest=ip_digest,
                policy_name=SECURITY_EVENT_POLICY_DEFAULT,
            ),
            detail=detail,
        )

    def build_authorization_denied_event(
        self,
        *,
        request: Request,
        subject_id: str | None,
        reason_code: str,
        status_code: int | HTTPStatus,
    ) -> SecurityEventEnvelope:
        """
        构建授权拒绝安全事件。

        :param request: 当前请求。
        :type request: Request
        :param subject_id: 授权主体标识。
        :type subject_id: str | None
        :param reason_code: 事件原因。
        :type reason_code: str
        :param status_code: HTTP 状态码。
        :type status_code: int | HTTPStatus
        :returns: 安全事件信封。
        :rtype: SecurityEventEnvelope
        """

        detail = AuthorizationSecurityEventDetail(
            subject_id=subject_id,
            reason_code=reason_code,
        )
        request_scope = self._read_request_scope(request)
        return SecurityEventEnvelope(
            header=self._build_header(
                event_type=SecurityEventType.AUTHZ_DENIED,
                detail_kind=detail.kind,
                severity=SecurityEventSeverity.WARNING,
                decision=SecurityEventDecision.DENY,
                reason_code=reason_code,
                request_id=request_scope.request_id,
                trace_id=request_scope.trace_id,
                path=request.url.path,
                method=request.method,
                status_code=int(status_code),
                subject_id=subject_id,
                policy_name=SECURITY_EVENT_POLICY_DEFAULT,
            ),
            detail=detail,
        )

    def build_config_security_rejected_event(
        self,
        *,
        reason_code: str,
    ) -> SecurityEventEnvelope:
        """
        构建安全配置拒绝事件。

        :param reason_code: 配置拒绝原因。
        :type reason_code: str
        :returns: 安全事件信封。
        :rtype: SecurityEventEnvelope
        """

        detail = ConfigSecurityEventDetail(
            reason_code=reason_code,
            rejected_field_count=CONFIG_SECURITY_REJECTED_FIELD_COUNT,
        )
        return SecurityEventEnvelope(
            header=self._build_header(
                event_type=SecurityEventType.CONFIG_SECURITY_REJECTED,
                detail_kind=detail.kind,
                severity=SecurityEventSeverity.WARNING,
                decision=SecurityEventDecision.DENY,
                reason_code=reason_code,
                request_id=CONFIG_SECURITY_REJECTED_REQUEST_ID,
                trace_id=None,
                path=CONFIG_SECURITY_REJECTED_PATH,
                method=CONFIG_SECURITY_REJECTED_METHOD,
                status_code=int(HTTPStatus.INTERNAL_SERVER_ERROR),
                policy_name=SECURITY_EVENT_POLICY_DEFAULT,
            ),
            detail=detail,
        )

    def build_admin_identity_changed_event(
        self,
        *,
        request: Request,
        actor_subject_id: str,
        operation_name: str,
        target_kind: str,
        target_id: str,
        status_code: int | HTTPStatus,
    ) -> SecurityEventEnvelope:
        """
        构建管理员身份变更安全事件。

        :param request: 当前请求。
        :type request: Request
        :param actor_subject_id: 操作者主体标识。
        :type actor_subject_id: str
        :param operation_name: 操作名称。
        :type operation_name: str
        :param target_kind: 目标类型。
        :type target_kind: str
        :param target_id: 目标标识。
        :type target_id: str
        :param status_code: HTTP 状态码。
        :type status_code: int | HTTPStatus
        :returns: 安全事件信封。
        :rtype: SecurityEventEnvelope
        """

        detail = AdminIdentitySecurityEventDetail(
            operation_name=operation_name,
            target_kind=target_kind,
            target_id=target_id,
            actor_subject_id=actor_subject_id,
        )
        request_scope = self._read_request_scope(request)
        return SecurityEventEnvelope(
            header=self._build_header(
                event_type=SecurityEventType.ADMIN_IDENTITY_CHANGED,
                detail_kind=detail.kind,
                severity=SecurityEventSeverity.INFO,
                decision=SecurityEventDecision.RECORD_ONLY,
                reason_code=SecurityEventType.ADMIN_IDENTITY_CHANGED.value,
                request_id=request_scope.request_id,
                trace_id=request_scope.trace_id,
                path=request.url.path,
                method=request.method,
                status_code=int(status_code),
                subject_id=actor_subject_id,
                policy_name=SECURITY_EVENT_POLICY_DEFAULT,
            ),
            detail=detail,
        )

    def _read_request_scope(self, request: Request) -> RequestScope:
        """
        读取请求作用域。
        """

        request_scope = getattr(request.state, "request_scope", None)
        if isinstance(request_scope, RequestScope):
            return request_scope
        return RequestScope(
            request_id=MISSING_REQUEST_SCOPE_ID,
            trace_id=None,
            request_time_epoch=MISSING_REQUEST_TIME_EPOCH,
            request_path=request.url.path,
            request_method=request.method,
        )

    def _build_header(
        self,
        *,
        event_type: str,
        detail_kind: str,
        severity: SecurityEventSeverity,
        decision: SecurityEventDecision,
        reason_code: str,
        request_id: str,
        trace_id: str | None,
        path: str,
        method: str,
        status_code: int | None = None,
        subject_id: str | None = None,
        ip_digest: str | None = None,
        user_agent_digest: str | None = None,
        policy_name: str,
    ) -> SecurityEventHeader:
        """
        构建安全事件公共头。
        """

        return SecurityEventHeader(
            event_type=event_type,
            detail_kind=detail_kind,
            severity=severity,
            decision=decision,
            reason_code=reason_code,
            request_id=request_id,
            trace_id=trace_id,
            path=path,
            method=method,
            status_code=status_code,
            subject_id=subject_id,
            ip_digest=ip_digest,
            user_agent_digest=user_agent_digest,
            policy_name=policy_name,
            occurred_at_epoch=int(time.time()),
        )
