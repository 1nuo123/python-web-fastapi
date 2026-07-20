"""
通用限流中间件模块。
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.http_contract.response_envelope_contract import ResponseEnvelopeFactory
from src.core.http_contract.security_runtime_contract import (
    FlowControlRuntimeDetail,
    RateLimitFailMode,
)
from src.core.security_contract.rate_limit_policy_contract import RateLimitPolicyEnvelope
from src.core.security_contract.security_decision_contract import SecurityAction
from src.infrastructure.orjson_document_response import OrjsonDocumentResponse

if TYPE_CHECKING:
    from src.infrastructure.shared_resource_mount import SharedResourceMount

MIDDLEWARE_TRACE_NAME = "rate_limit"
RETRY_AFTER_HEADER_NAME = "Retry-After"
RATE_LIMIT_REJECTED_MESSAGE = "请求过于频繁。"
POLICY_METHOD_ANY = "*"
AUTHORIZATION_HEADER_NAME = "authorization"
API_KEY_HEADER_NAME = "x-api-key"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    通用限流中间件。
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        resource_mount: SharedResourceMount,
    ) -> None:
        """
        初始化通用限流中间件。
        """

        super().__init__(app)
        self._resource_mount = resource_mount
        self._response_factory = ResponseEnvelopeFactory()

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """
        执行限流链路。
        """

        request.state.middleware_trace.append(MIDDLEWARE_TRACE_NAME)
        protection = (
            self._resource_mount.read_runtime_bundle().settings.runtime.security.detail.protection
        )
        flow_control_enabled = protection.flow_control.enabled
        ip_block_enabled = getattr(protection.ip_block, "enabled", True)
        if not flow_control_enabled and not ip_block_enabled:
            return await call_next(request)
        policy = self._resolve_policy(
            path=request.url.path,
            method=request.method,
            flow_control=protection.flow_control,
        )
        limit = protection.flow_control.default_limit
        window_seconds = protection.flow_control.default_window_seconds
        block_seconds = protection.ip_block.default_block_seconds
        policy_name = MIDDLEWARE_TRACE_NAME
        key_dimensions = None
        block_when_exceeded = True
        if policy is not None:
            limit = policy.detail.limit
            window_seconds = policy.detail.window_seconds
            block_seconds = policy.detail.block_seconds
            policy_name = policy.header.policy_name
            key_dimensions = policy.detail.key_dimensions
            block_when_exceeded = policy.detail.block_when_exceeded
        try:
            decision = self._resource_mount.get_security_protection_guard().evaluate_request(
                request=request,
                limit=limit,
                window_seconds=window_seconds,
                block_seconds=block_seconds,
                ip_block_cache_ttl_seconds=protection.ip_block.cache_ttl_seconds,
                flow_control_enabled=flow_control_enabled,
                ip_block_enabled=ip_block_enabled,
                policy_name=policy_name,
                key_dimensions=key_dimensions,
                auth_field_values=self._extract_auth_field_values(request),
                block_when_exceeded=block_when_exceeded,
                rate_limit_fail_mode=self._resolve_fail_mode(protection.flow_control),
            )
        except HttpFaultException as runtime_fault:
            return self._build_fault_response(request=request, fault=runtime_fault)
        if decision.action != SecurityAction.RETURN_429:
            return await call_next(request)
        if decision.security_event is not None:
            self._resource_mount.emit_security_event(decision.security_event)
        rejection_fault = HttpFaultException(
            status_code=HTTPStatus.TOO_MANY_REQUESTS,
            error_code=CoreErrorCode.REQUEST_INVALID,
            message=RATE_LIMIT_REJECTED_MESSAGE,
        )
        return self._build_fault_response(
            request=request,
            fault=rejection_fault,
            retry_after_seconds=decision.retry_after_seconds,
        )

    def _build_fault_response(
        self,
        *,
        request: Request,
        fault: HttpFaultException,
        retry_after_seconds: int | None = None,
    ) -> Response:
        """把中间件链内故障转换为统一响应契约。"""

        envelope = self._response_factory.build(
            code=str(fault.error_code),
            message=fault.message,
            request_scope=request.state.request_scope,
            data=fault.to_payload(),
        )
        response = OrjsonDocumentResponse(
            status_code=fault.status_code,
            content=envelope.model_dump(mode="json"),
        )
        if retry_after_seconds is not None:
            response.headers[RETRY_AFTER_HEADER_NAME] = str(retry_after_seconds)
        return response

    def _resolve_fail_mode(
        self,
        flow_control: FlowControlRuntimeDetail,
    ) -> RateLimitFailMode:
        """
        解析限流缓存故障处理模式。
        """

        return flow_control.fail_mode

    def _extract_auth_field_values(self, request: Request) -> list[str]:
        """
        提取参与限流键构造的认证字段。
        """

        auth_field_values: list[str] = []
        authorization_header = request.headers.get(AUTHORIZATION_HEADER_NAME)
        if authorization_header:
            auth_field_values.append(authorization_header)
        api_key_header = request.headers.get(API_KEY_HEADER_NAME)
        if api_key_header:
            auth_field_values.append(api_key_header)
        return auth_field_values

    def _resolve_policy(
        self,
        *,
        path: str,
        method: str,
        flow_control: FlowControlRuntimeDetail,
    ) -> RateLimitPolicyEnvelope | None:
        """
        按请求路径和方法解析限流策略。
        """

        for policy in flow_control.policies:
            if not policy.header.enabled:
                continue
            if policy.detail.path is not None and policy.detail.path != path:
                continue
            if policy.detail.method is None:
                return policy
            if policy.detail.method.upper() in {method.upper(), POLICY_METHOD_ANY}:
                return policy
        return None
