"""
认证绑定中间件基础设施模块。
"""

from __future__ import annotations

import logging
import time
from http import HTTPStatus
from typing import TYPE_CHECKING, cast

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from src.core.auth_contract.authenticated_principal_contract import AuthenticatedPrincipal
from src.core.auth_contract.token_payload_contract import TokenPayload, TokenUse
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.http_contract.request_execution_contract import (
    DEFAULT_SYNC_REQUEST_EXECUTION_NAME,
)
from src.core.http_contract.request_scope_contract import RequestScope
from src.core.http_contract.response_envelope_contract import ResponseEnvelopeFactory
from src.core.security_contract.token_binding_contract import TokenBindingMode
from src.domain.auth.auth_error_code import AuthErrorCode
from src.infrastructure.auth.oauth2_scheme_provider import OAuth2SchemeProvider
from src.infrastructure.orjson_document_response import OrjsonDocumentResponse

if TYPE_CHECKING:
    from src.infrastructure.shared_resource_mount import SharedResourceMount

ACCOUNT_DISABLED_MESSAGE = "账号已停用。"
AUTH_SUBJECT_MISSING_MESSAGE = "访问主体不存在。"
TOKEN_SESSION_REVOKED_MESSAGE = "访问令牌所属会话已吊销。"
TOKEN_SESSION_MISSING_MESSAGE = "访问令牌所属会话不存在。"
TOKEN_SESSION_SUBJECT_MISMATCH_MESSAGE = "访问令牌所属会话主体不匹配。"
TOKEN_SESSION_EXPIRED_MESSAGE = "访问令牌所属会话已过期。"
TOKEN_SESSION_INCONSISTENT_MESSAGE = "访问令牌所属会话状态不一致。"
MIDDLEWARE_TRACE_NAME = "authentication_binding"
AUTH_BINDING_REQUEST_EXECUTION_NAME = DEFAULT_SYNC_REQUEST_EXECUTION_NAME
MISSING_REQUEST_SCOPE_ID = "request-scope-missing"
TOKEN_BINDING_MISMATCH_MESSAGE = "访问令牌绑定信息不匹配。"
TOKEN_BINDING_MISMATCH_REASON = "token_binding.mismatch"


class AuthenticationBindingMiddleware(BaseHTTPMiddleware):
    """
    认证绑定中间件，负责拦截并增强请求链路。

    该中间件会把合法访问令牌解析为请求上下文中的主体快照。
    携带无效 Bearer 时会立即拒绝；未携带令牌时由后续路由守卫决定是否需要认证。
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        oauth2_scheme_provider: OAuth2SchemeProvider,
        resource_mount: SharedResourceMount,
        logger: logging.Logger,
    ) -> None:
        """
        初始化认证绑定中间件。

        :param app: 当前 FastAPI 或 ASGI 应用实例。
        :type app: ASGIApp
        :param oauth2_scheme_provider: OAuth2 Bearer 令牌提取器。约束：需符合 ``OAuth2SchemeProvider`` 注解。
        :type oauth2_scheme_provider: OAuth2SchemeProvider
        :param resource_mount: 共享资源挂载点，用于访问数据库、缓存、消息和鉴权能力。
        :type resource_mount: SharedResourceMount
        :param logger: 当前组件使用的日志记录器。
        :type logger: logging.Logger
        :returns: 无返回值。
        :rtype: None
        """

        super().__init__(app)
        self._oauth2_scheme_provider = oauth2_scheme_provider
        self._resource_mount = resource_mount
        self._logger = logger

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """
        分发当前请求或任务。

        :param request: 当前 HTTP 请求对象，用于读取状态、请求头和依赖。
        :type request: Request
        :param call_next: 当前步骤使用的调用next参数。
        :type call_next: RequestResponseEndpoint
        :returns: 返回当前操作结果。
        :rtype: Response
        :raises HttpFaultException: 携带无效 Bearer 时抛出已归一化鉴权异常。
        """

        request.state.middleware_trace.append(MIDDLEWARE_TRACE_NAME)
        request.state.authenticated_principal = None
        request.state.auth_fault = None
        token = self._oauth2_scheme_provider.extract_bearer_token(request)
        if token is not None:
            try:
                # 认证绑定只负责把合法主体挂到请求上下文，授权策略仍由路由级依赖执行。
                token_payload = self._resource_mount.get_jwt_token_service().decode_token(
                    token,
                    expected_use=TokenUse.ACCESS,
                )
                principal = cast(
                    AuthenticatedPrincipal,
                    await self._resource_mount.get_request_execution_bridge().run_sync(
                        execution_name=AUTH_BINDING_REQUEST_EXECUTION_NAME,
                        callable_object=self._bind_authenticated_principal,
                        token_payload=token_payload,
                    ),
                )
                request.state.authenticated_principal = principal
                request_context_manager = self._resource_mount.get_request_context_manager()
                request_context_manager.bind_authenticated_subject(principal.subject_id)
                current_scope = request_context_manager.get_current_scope()
                if current_scope is not None:
                    request.state.request_scope = current_scope
                token_binding_fault = self._validate_token_binding(
                    request=request,
                    token=token,
                    token_payload=token_payload,
                )
                if token_binding_fault is not None:
                    request.state.auth_fault = token_binding_fault
                    return self._build_auth_fault_response(
                        request,
                        request.state.auth_fault,
                    )
            except HttpFaultException as exc:
                # 携带无效 Bearer 时主动拒绝，避免公共路由出现不一致的令牌语义。
                self._logger.warning("访问令牌绑定失败：%s", str(exc))
                request.state.auth_fault = self._normalize_auth_fault(exc)
                return self._build_auth_fault_response(
                    request,
                    request.state.auth_fault,
                )
        return await call_next(request)

    def _validate_token_binding(
        self,
        *,
        request: Request,
        token: str,
        token_payload: TokenPayload,
    ) -> HttpFaultException | None:
        """
        校验可选 Token-IP 绑定策略。
        """

        policy = self._resource_mount.read_runtime_bundle().settings.runtime.security.detail.protection.token_binding
        if not policy.enabled or policy.mode == TokenBindingMode.DISABLED:
            return None
        if request.url.path not in policy.applicable_paths:
            return None
        if policy.token_uses and token_payload.token_use.value not in policy.token_uses:
            return None
        token_binding_guard = self._resource_mount.get_token_binding_guard()
        binding_result = token_binding_guard.validate_or_bind(
            token=token,
            ip=self._resource_mount.get_client_ip_resolver().resolve_client_ip(request),
            ttl_seconds=policy.ip_digest_ttl_seconds,
        )
        if binding_result.matched:
            return None
        self._resource_mount.emit_security_event(
            self._resource_mount.get_security_event_builder().build_token_binding_event(
                request=request,
                token_digest=binding_result.token_digest,
                ip_digest=binding_result.ip_digest,
                reason_code=TOKEN_BINDING_MISMATCH_REASON,
            )
        )
        return HttpFaultException(
            status_code=HTTPStatus.UNAUTHORIZED,
            error_code=AuthErrorCode.TOKEN_INVALID,
            message=TOKEN_BINDING_MISMATCH_MESSAGE,
        )

    def _bind_authenticated_principal(
        self,
        token_payload: TokenPayload,
    ) -> AuthenticatedPrincipal:
        """
        绑定已认证主体。

        :param token_payload: 已解码并完成基础校验的令牌载荷。约束：需符合 ``TokenPayload`` 注解。
        :type token_payload: TokenPayload
        :returns: 返回当前操作结果。
        :rtype: AuthenticatedPrincipal
        :raises HttpFaultException: 当业务校验失败、资源未就绪、配置错误或令牌状态异常时抛出。
        """

        unit_of_work = self._resource_mount.create_unit_of_work()
        try:
            # 访问令牌里的角色和作用域只作为快照展示，最终授权真值仍以数据库当前状态为准。
            session = unit_of_work.get_session()
            auth_identity_repository = self._resource_mount.create_auth_identity_repository(session)
            refresh_token_repository = self._resource_mount.create_refresh_token_repository(session)
            authorization_snapshot = (
                auth_identity_repository.get_authorization_snapshot_by_subject_id(
                    token_payload.subject_id
                )
            )
            if authorization_snapshot is None:
                raise HttpFaultException(
                    status_code=HTTPStatus.UNAUTHORIZED,
                    error_code=AuthErrorCode.TOKEN_INVALID,
                    message=AUTH_SUBJECT_MISSING_MESSAGE,
                )
            if not authorization_snapshot.is_active:
                raise HttpFaultException(
                    status_code=HTTPStatus.FORBIDDEN,
                    error_code=AuthErrorCode.ACCOUNT_DISABLED,
                    message=ACCOUNT_DISABLED_MESSAGE,
                )
            token_session_status = refresh_token_repository.get_token_session_status(
                token_payload.token_session_id
            )
            if token_session_status is None:
                raise HttpFaultException(
                    status_code=HTTPStatus.UNAUTHORIZED,
                    error_code=AuthErrorCode.TOKEN_INVALID,
                    message=TOKEN_SESSION_MISSING_MESSAGE,
                )
            if token_session_status.subject_id != authorization_snapshot.subject_id:
                raise HttpFaultException(
                    status_code=HTTPStatus.UNAUTHORIZED,
                    error_code=AuthErrorCode.TOKEN_INVALID,
                    message=TOKEN_SESSION_SUBJECT_MISMATCH_MESSAGE,
                )
            if token_session_status.is_inconsistent:
                raise HttpFaultException(
                    status_code=HTTPStatus.UNAUTHORIZED,
                    error_code=AuthErrorCode.TOKEN_INVALID,
                    message=TOKEN_SESSION_INCONSISTENT_MESSAGE,
                )
            if token_session_status.is_revoked:
                raise HttpFaultException(
                    status_code=HTTPStatus.UNAUTHORIZED,
                    error_code=AuthErrorCode.TOKEN_REVOKED,
                    message=TOKEN_SESSION_REVOKED_MESSAGE,
                )
            if token_session_status.is_expired:
                raise HttpFaultException(
                    status_code=HTTPStatus.UNAUTHORIZED,
                    error_code=AuthErrorCode.TOKEN_EXPIRED,
                    message=TOKEN_SESSION_EXPIRED_MESSAGE,
                )
            return AuthenticatedPrincipal.from_authorization_snapshot(authorization_snapshot)
        finally:
            # 中间件只读查询也显式释放工作单元，避免连接泄漏到长请求链。
            unit_of_work.dispose()

    def _normalize_auth_fault(self, exc: HttpFaultException) -> HttpFaultException:
        """
        规范化鉴权故障。

        :param exc: 当前捕获到的异常对象。约束：需符合 ``Exception`` 注解。
        :type exc: HttpFaultException
        :returns: 返回当前操作结果。
        :rtype: HttpFaultException
        :raises HttpFaultException: 返回值本身就是统一化后的 HTTP 故障对象。
        """

        return exc

    def _build_auth_fault_response(
        self,
        request: Request,
        fault: HttpFaultException,
    ) -> OrjsonDocumentResponse:
        """
        构建鉴权绑定失败响应。

        :param request: 当前 HTTP 请求对象。
        :type request: Request
        :param fault: 已归一化的鉴权故障。
        :type fault: HttpFaultException
        :returns: 鉴权失败 JSON 响应。
        :rtype: OrjsonDocumentResponse
        """

        log_event_builder = self._resource_mount.get_log_event_builder()
        self._resource_mount.emit_log_event(
            log_event_builder.build_exception_event(
                request_context=log_event_builder.build_request_context(request),
                exception=fault,
                status_code=fault.status_code,
                error_code=str(fault.error_code),
                include_traceback=False,
            )
        )
        envelope = ResponseEnvelopeFactory().build(
            code=str(fault.error_code),
            message=fault.message,
            request_scope=self._read_request_scope(request),
            data=fault.to_payload(),
        )
        return OrjsonDocumentResponse(
            status_code=fault.status_code,
            content=envelope.model_dump(mode="json"),
        )

    def _read_request_scope(self, request: Request) -> RequestScope:
        """
        读取请求作用域。

        :param request: 当前 HTTP 请求对象。
        :type request: Request
        :returns: 请求作用域。
        :rtype: RequestScope
        """

        request_scope = getattr(request.state, "request_scope", None)
        if isinstance(request_scope, RequestScope):
            return request_scope
        return RequestScope(
            request_id=MISSING_REQUEST_SCOPE_ID,
            trace_id=None,
            request_time_epoch=int(time.time()),
            request_path=request.url.path,
            request_method=request.method,
        )
