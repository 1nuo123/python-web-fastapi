"""
出站 URL 安全 httpx 钩子模块。
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Protocol

import httpx

from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.http_contract.request_scope_contract import RequestScope
from src.core.security_contract.outbound_url_safety_contract import (
    OutboundUrlSafetyAction,
    OutboundUrlSafetyDecision,
)
from src.core.security_contract.security_event_contract import SecurityEventEnvelope
from src.infrastructure.context.request_context_manager_impl import (
    RequestContextManagerImpl,
)
from src.infrastructure.security.outbound_url_safety_validator import (
    OutboundUrlSafetyValidator,
)
from src.infrastructure.security.security_event_builder import SecurityEventBuilder

OUTBOUND_SSRF_BLOCKED_MESSAGE = "出站 URL 被安全策略拒绝。"
OUTBOUND_CONTEXT_REQUEST_ID = "outbound-request-scope"
OUTBOUND_CONTEXT_PATH = "outbound_http"
OUTBOUND_CONTEXT_METHOD = "OUTBOUND"
OUTBOUND_CONTEXT_REQUEST_TIME_EPOCH = 0


class SecurityEventEmitter(Protocol):
    """
    安全事件写入协议。
    """

    def emit_security_event(self, event: SecurityEventEnvelope) -> None:
        """
        写入安全事件。
        """


class OutboundUrlSafetyHookBase:
    """
    出站 URL 安全钩子基类。
    """

    def __init__(
        self,
        *,
        validator: OutboundUrlSafetyValidator,
        request_context_manager: RequestContextManagerImpl,
        security_event_builder: SecurityEventBuilder,
        security_event_emitter: SecurityEventEmitter,
    ) -> None:
        """
        初始化出站 URL 安全钩子。
        """

        self._validator = validator
        self._request_context_manager = request_context_manager
        self._security_event_builder = security_event_builder
        self._security_event_emitter = security_event_emitter

    def _validate_request(self, request: httpx.Request) -> None:
        """
        校验 httpx 请求。
        """

        decision = self._validator.validate_url(str(request.url))
        if decision.action == OutboundUrlSafetyAction.ALLOW:
            return
        self.emit_denied_event(decision)
        raise HttpFaultException(
            status_code=HTTPStatus.BAD_REQUEST,
            error_code=CoreErrorCode.REQUEST_INVALID,
            message=OUTBOUND_SSRF_BLOCKED_MESSAGE,
            detail=decision.reason_code,
        )

    def emit_denied_event(self, decision: OutboundUrlSafetyDecision) -> None:
        """
        写入出站 URL 拒绝安全事件。

        :param decision: 出站 URL 安全拒绝决策。
        :type decision: OutboundUrlSafetyDecision
        :returns: 无返回值。
        :rtype: None
        """

        self._security_event_emitter.emit_security_event(
            self._security_event_builder.build_ssrf_event(
                request_scope=self._read_request_scope(),
                host_digest=decision.host_digest,
                reason_code=decision.reason_code,
            )
        )

    def get_validator(self) -> OutboundUrlSafetyValidator:
        """
        读取连接层复用的出站 URL 安全校验器。
        """

        return self._validator

    def _read_request_scope(self) -> RequestScope:
        """
        读取当前请求作用域。
        """

        request_scope = self._request_context_manager.get_current_scope()
        if request_scope is not None:
            return request_scope
        return RequestScope(
            request_id=OUTBOUND_CONTEXT_REQUEST_ID,
            trace_id=None,
            request_time_epoch=OUTBOUND_CONTEXT_REQUEST_TIME_EPOCH,
            request_path=OUTBOUND_CONTEXT_PATH,
            request_method=OUTBOUND_CONTEXT_METHOD,
        )


class SyncOutboundUrlSafetyHook(OutboundUrlSafetyHookBase):
    """
    同步 httpx 出站 URL 安全钩子。
    """

    def __call__(self, request: httpx.Request) -> None:
        """
        校验同步请求。
        """

        self._validate_request(request)


class AsyncOutboundUrlSafetyHook(OutboundUrlSafetyHookBase):
    """
    异步 httpx 出站 URL 安全钩子。
    """

    async def __call__(self, request: httpx.Request) -> None:
        """
        校验异步请求。
        """

        self._validate_request(request)
