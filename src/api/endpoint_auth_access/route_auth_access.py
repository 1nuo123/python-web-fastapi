"""
路由鉴权访问API 接口层模块。
"""

from __future__ import annotations

from http import HTTPStatus

from fastapi import APIRouter, Depends, Request, Response, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.api.dependency_context_accessor import DependencyContextAccessor
from src.api.endpoint_auth_access.contract_auth_access import (
    BrowserTokenIssuePayload,
    StepUpGrantPayload,
    StepUpGrantRequest,
    TokenIssueRequest,
    TokenRefreshRequest,
    TokenRevokeRequest,
    UserRegistrationPayload,
    UserRegistrationRequest,
)
from src.api.web_bundle_catalog import (
    WebBundleProvider,
    WebBundleProviderDetail,
    WebBundleProviderEnvelope,
    WebBundleProviderHeader,
)
from src.application.issue_access_token_usecase import CredentialInput
from src.application.issue_step_up_grant_usecase import IssueStepUpGrantUsecase
from src.application.refresh_access_token_usecase import RefreshTokenInput
from src.application.register_user_usecase import (
    RegisterUserUsecase,
    UserRegistrationCommand,
    UserRegistrationPolicy,
)
from src.application.revoke_access_token_usecase import RevokeTokenInput
from src.core.auth_contract.authenticated_principal_contract import AuthenticatedPrincipal
from src.core.auth_contract.token_payload_contract import (
    TokenIssuePayload,
    TokenRevokePayload,
)
from src.core.exception_contract.error_code_catalog_contract import SuccessCode
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.http_contract.request_execution_contract import (
    DEFAULT_SYNC_REQUEST_EXECUTION_NAME,
)
from src.core.http_contract.response_envelope_contract import ResponseEnvelope
from src.core.http_contract.web_bundle_contract import ApplicationModuleName, WebBundle
from src.core.security_contract.security_event_contract import SecurityEventType
from src.domain.auth.auth_error_code import AuthErrorCode
from src.infrastructure.security.browser_origin_resolver import (
    build_allowed_browser_origins,
    is_trusted_https_request,
)
from src.infrastructure.settings.application_settings import AppEnvironment

AUTH_ROUTE_TAG = "auth"
AUTH_TOKEN_PATH = "/auth/token"
AUTH_REFRESH_PATH = "/auth/refresh"
AUTH_REVOKE_PATH = "/auth/revoke"
AUTH_ME_PATH = "/auth/me"
AUTH_REGISTER_PATH = "/auth/register"
AUTH_BROWSER_TOKEN_PATH = "/auth/browser/token"
AUTH_BROWSER_REFRESH_PATH = "/auth/browser/refresh"
AUTH_BROWSER_REVOKE_PATH = "/auth/browser/revoke"
AUTH_BROWSER_REFRESH_COOKIE_NAME = "codex_refresh_token"
AUTH_BROWSER_COOKIE_PATH = "/auth/browser"
AUTH_STEP_UP_PATH = "/auth/step-up"
ORIGIN_HEADER_NAME = "origin"
AUTH_REQUEST_EXECUTION_NAME = DEFAULT_SYNC_REQUEST_EXECUTION_NAME
AUTH_BEARER_SCHEME = HTTPBearer(auto_error=False)
USER_AGENT_HEADER_NAME = "user-agent"


class AuthAccessRouteCatalog:
    """
    鉴权访问路由目录，负责注册接口与响应契约。
    """

    def __init__(self) -> None:
        """
        初始化鉴权访问路由目录。

        :returns: 无返回值。
        :rtype: None
        """

        self._accessor = DependencyContextAccessor()
        self.router = APIRouter(tags=[AUTH_ROUTE_TAG])
        self.router.add_api_route(
            AUTH_REGISTER_PATH,
            self.post_register,
            methods=["POST"],
            response_model=ResponseEnvelope[UserRegistrationPayload],
            status_code=HTTPStatus.CREATED,
        )
        self.router.add_api_route(
            AUTH_TOKEN_PATH,
            self.post_token,
            methods=["POST"],
            response_model=ResponseEnvelope[TokenIssuePayload],
        )
        self.router.add_api_route(
            AUTH_REFRESH_PATH,
            self.post_refresh,
            methods=["POST"],
            response_model=ResponseEnvelope[TokenIssuePayload],
        )
        self.router.add_api_route(
            AUTH_REVOKE_PATH,
            self.post_revoke,
            methods=["POST"],
            response_model=ResponseEnvelope[TokenRevokePayload],
        )
        self.router.add_api_route(
            AUTH_STEP_UP_PATH,
            self.post_step_up,
            methods=["POST"],
            response_model=ResponseEnvelope[StepUpGrantPayload],
            dependencies=[Depends(self.require_auth_me)],
        )
        self.router.add_api_route(
            AUTH_ME_PATH,
            self.get_me,
            methods=["GET"],
            response_model=ResponseEnvelope[AuthenticatedPrincipal],
            dependencies=[Depends(self.require_auth_me)],
        )
        self.router.add_api_route(
            AUTH_BROWSER_TOKEN_PATH,
            self.post_browser_token,
            methods=["POST"],
            response_model=ResponseEnvelope[BrowserTokenIssuePayload],
        )
        self.router.add_api_route(
            AUTH_BROWSER_REFRESH_PATH,
            self.post_browser_refresh,
            methods=["POST"],
            response_model=ResponseEnvelope[BrowserTokenIssuePayload],
        )
        self.router.add_api_route(
            AUTH_BROWSER_REVOKE_PATH,
            self.post_browser_revoke,
            methods=["POST"],
            response_model=ResponseEnvelope[TokenRevokePayload],
        )

    async def post_register(
        self,
        request: Request,
        command: UserRegistrationRequest,
    ) -> ResponseEnvelope[UserRegistrationPayload]:
        """注册普通用户，角色完全由服务端策略决定。"""

        self._validate_browser_origin(request)
        resource_mount = self._accessor.read_resource_mount(request)
        policy = resource_mount.read_runtime_bundle().settings.modules.auth.public_registration
        snapshot = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name=AUTH_REQUEST_EXECUTION_NAME,
            callable_object=RegisterUserUsecase(registration_port=resource_mount).execute,
            command=UserRegistrationCommand(
                username=command.username,
                password_plain=command.password.get_secret_value(),
            ),
            policy=UserRegistrationPolicy(
                enabled=policy.enabled,
                default_role_key=policy.default_role_key,
            ),
        )
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message="注册成功。",
            request_scope=self._accessor.read_request_scope(request),
            data=UserRegistrationPayload(
                subject_id=snapshot.subject_id,
                username=snapshot.username,
            ),
        )

    async def require_auth_me(
        self,
        request: Request,
        _credentials: HTTPAuthorizationCredentials | None = Security(AUTH_BEARER_SCHEME),
    ) -> None:
        """
        校验当前主体读取接口的路由级授权。

        :param request: 当前 HTTP 请求对象。
        :type request: Request
        :param _credentials: OpenAPI Bearer 安全声明载荷。
        :type _credentials: HTTPAuthorizationCredentials | None
        :returns: 无返回值。
        :rtype: None
        """

        self._accessor.read_authenticated_principal(request)

    async def post_token(
        self,
        request: Request,
        command: TokenIssueRequest,
    ) -> ResponseEnvelope[TokenIssuePayload]:
        """
        提交用户名密码并签发访问令牌。

        :param request: 当前 HTTP 请求对象，用于读取状态、请求头和依赖。约束：需符合 ``Request`` 注解。
        :type request: Request
        :param command: 接口层命令对象，承载当前操作所需输入。约束：需符合 ``TokenIssueRequest`` 注解。
        :type command: TokenIssueRequest
        :returns: 返回当前操作结果。
        :rtype: ResponseEnvelope[TokenIssuePayload]
        """

        try:
            # 认证用例当前保留同步主干，通过桥接器卸载避免阻塞异步路由。
            payload = await self._accessor.read_request_execution_bridge(request).run_sync(
                execution_name=AUTH_REQUEST_EXECUTION_NAME,
                callable_object=self._accessor.read_issue_access_token_usecase(request).execute,
                credential_input=CredentialInput(
                    username=command.username,
                    password_plain=command.password,
                ),
            )
        except HttpFaultException as exc:
            self._record_token_issue_failure(
                request=request,
                username=command.username,
                fault=exc,
            )
            raise
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message="令牌签发成功。",
            request_scope=self._accessor.read_request_scope(request),
            data=payload,
        )

    async def post_refresh(
        self,
        request: Request,
        command: TokenRefreshRequest,
    ) -> ResponseEnvelope[TokenIssuePayload]:
        """
        提交刷新令牌并换发访问令牌。

        :param request: 当前 HTTP 请求对象，用于读取状态、请求头和依赖。约束：需符合 ``Request`` 注解。
        :type request: Request
        :param command: 接口层命令对象，承载当前操作所需输入。约束：需符合 ``TokenRefreshRequest`` 注解。
        :type command: TokenRefreshRequest
        :returns: 返回当前操作结果。
        :rtype: ResponseEnvelope[TokenIssuePayload]
        """

        try:
            # 刷新令牌链路仍走同步用例，统一通过桥接器卸载。
            payload = await self._accessor.read_request_execution_bridge(request).run_sync(
                execution_name=AUTH_REQUEST_EXECUTION_NAME,
                callable_object=self._accessor.read_refresh_access_token_usecase(request).execute,
                refresh_token_input=RefreshTokenInput(
                    refresh_token=command.refresh_token,
                    client_ip=self._resolve_client_ip(request),
                ),
            )
        except HttpFaultException as exc:
            self._record_refresh_failure(
                request=request,
                refresh_token=command.refresh_token,
                fault=exc,
            )
            raise
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message="令牌刷新成功。",
            request_scope=self._accessor.read_request_scope(request),
            data=payload,
        )

    async def post_revoke(
        self,
        request: Request,
        command: TokenRevokeRequest,
    ) -> ResponseEnvelope[TokenRevokePayload]:
        """
        提交刷新令牌并吊销令牌会话。

        :param request: 当前 HTTP 请求对象，用于读取状态、请求头和依赖。约束：需符合 ``Request`` 注解。
        :type request: Request
        :param command: 接口层命令对象，承载当前操作所需输入。约束：需符合 ``TokenRevokeRequest`` 注解。
        :type command: TokenRevokeRequest
        :returns: 返回当前操作结果。
        :rtype: ResponseEnvelope[TokenRevokePayload]
        """

        # 吊销用例包含同步持久化访问，因此同样通过桥接器执行。
        payload = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name=AUTH_REQUEST_EXECUTION_NAME,
            callable_object=self._accessor.read_revoke_access_token_usecase(request).execute,
            revoke_token_input=RevokeTokenInput(refresh_token=command.refresh_token),
        )
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message="令牌吊销成功。",
            request_scope=self._accessor.read_request_scope(request),
            data=payload,
        )

    async def get_me(self, request: Request) -> ResponseEnvelope[AuthenticatedPrincipal]:
        """
        获取当前主体。

        :param request: 当前 HTTP 请求对象，用于读取状态、请求头和依赖。约束：需符合 ``Request`` 注解。
        :type request: Request
        :returns: 返回读取到的对象或状态快照。
        :rtype: ResponseEnvelope[AuthenticatedPrincipal]
        """

        # 当前主体读取只依赖中间件已绑定的主体与授权守卫，无需再次跨线程调用用例。
        principal = self._accessor.read_authenticated_principal(request)
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message="当前主体读取成功。",
            request_scope=self._accessor.read_request_scope(request),
            data=principal,
        )

    async def post_browser_token(
        self,
        request: Request,
        response: Response,
        command: TokenIssueRequest,
    ) -> ResponseEnvelope[BrowserTokenIssuePayload]:
        """签发浏览器 access token，并通过 HttpOnly Cookie 下发 refresh token。"""

        self._validate_browser_origin(request)
        try:
            token_bundle = await self._accessor.read_request_execution_bridge(request).run_sync(
                execution_name=AUTH_REQUEST_EXECUTION_NAME,
                callable_object=self._accessor.read_issue_access_token_usecase(request).execute,
                credential_input=CredentialInput(
                    username=command.username,
                    password_plain=command.password,
                ),
            )
        except HttpFaultException as exc:
            self._record_token_issue_failure(
                request=request,
                username=command.username,
                fault=exc,
            )
            raise
        self._set_browser_refresh_cookie(request, response, token_bundle)
        return self._build_browser_token_response(request, token_bundle)

    async def post_browser_refresh(
        self,
        request: Request,
        response: Response,
    ) -> ResponseEnvelope[BrowserTokenIssuePayload]:
        """从 HttpOnly Cookie 轮换 refresh token，不接收正文令牌。"""

        self._validate_browser_origin(request)
        refresh_token = self._read_browser_refresh_cookie(request)
        try:
            token_bundle = await self._accessor.read_request_execution_bridge(request).run_sync(
                execution_name=AUTH_REQUEST_EXECUTION_NAME,
                callable_object=self._accessor.read_refresh_access_token_usecase(request).execute,
                refresh_token_input=RefreshTokenInput(
                    refresh_token=refresh_token,
                    client_ip=self._resolve_client_ip(request),
                ),
            )
        except HttpFaultException as exc:
            self._record_refresh_failure(
                request=request,
                refresh_token=refresh_token,
                fault=exc,
            )
            raise
        self._set_browser_refresh_cookie(request, response, token_bundle)
        return self._build_browser_token_response(request, token_bundle)

    async def post_browser_revoke(
        self,
        request: Request,
        response: Response,
    ) -> ResponseEnvelope[TokenRevokePayload]:
        """吊销 Cookie 对应令牌会话并清除浏览器 Cookie。"""

        self._validate_browser_origin(request)
        refresh_token = self._read_browser_refresh_cookie(request)
        payload = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name=AUTH_REQUEST_EXECUTION_NAME,
            callable_object=self._accessor.read_revoke_access_token_usecase(request).execute,
            revoke_token_input=RevokeTokenInput(refresh_token=refresh_token),
        )
        response.delete_cookie(
            key=AUTH_BROWSER_REFRESH_COOKIE_NAME,
            path=AUTH_BROWSER_COOKIE_PATH,
            secure=self._should_use_secure_browser_cookie(request),
            httponly=True,
            samesite="strict",
        )
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message="浏览器令牌吊销成功。",
            request_scope=self._accessor.read_request_scope(request),
            data=payload,
        )

    async def post_step_up(
        self,
        request: Request,
        command: StepUpGrantRequest,
    ) -> ResponseEnvelope[StepUpGrantPayload]:
        """密码再验证后签发不持久化的一次性增强授权。"""

        self._validate_browser_origin(request)
        principal = self._accessor.read_authenticated_principal(request)
        resource_mount = self._accessor.read_resource_mount(request)
        issue = await IssueStepUpGrantUsecase(
            runtime_port=resource_mount,
            grant_port=resource_mount.get_codex_control_runtime().step_up_grant_service,
        ).execute(
            subject_id=principal.subject_id,
            password_plain=command.password,
            purpose=command.purpose,
        )
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message="增强验证已通过。",
            request_scope=self._accessor.read_request_scope(request),
            data=StepUpGrantPayload(
                grant_token=issue.token,
                expires_at=issue.expires_at,
            ),
        )

    def _validate_browser_origin(self, request: Request) -> None:
        """严格校验浏览器写接口 Origin。"""

        origin = request.headers.get(ORIGIN_HEADER_NAME)
        settings = self._accessor.read_resource_mount(request).read_runtime_bundle().settings
        resource_mount = self._accessor.read_resource_mount(request)
        allowed_origins = build_allowed_browser_origins(
            request,
            configured_origins=settings.runtime.web.cors.allow_origins,
            client_ip_resolver=resource_mount.get_client_ip_resolver(),
        )
        if origin is None or origin.rstrip("/") not in {
            allowed.rstrip("/") for allowed in allowed_origins
        }:
            raise HttpFaultException(
                status_code=HTTPStatus.FORBIDDEN,
                error_code=AuthErrorCode.BROWSER_ORIGIN_FORBIDDEN,
                message="浏览器请求来源不允许。",
            )

    def _read_browser_refresh_cookie(self, request: Request) -> str:
        """读取仅由浏览器自动携带的 refresh Cookie。"""

        refresh_token = request.cookies.get(AUTH_BROWSER_REFRESH_COOKIE_NAME)
        if refresh_token is None or refresh_token == "":
            raise HttpFaultException(
                status_code=HTTPStatus.UNAUTHORIZED,
                error_code=AuthErrorCode.BROWSER_REFRESH_COOKIE_MISSING,
                message="浏览器刷新凭据缺失。",
            )
        return refresh_token

    def _set_browser_refresh_cookie(
        self,
        request: Request,
        response: Response,
        token_bundle: TokenIssuePayload,
    ) -> None:
        """按冻结安全属性写入 refresh Cookie。"""

        response.set_cookie(
            key=AUTH_BROWSER_REFRESH_COOKIE_NAME,
            value=token_bundle.refresh_token,
            max_age=token_bundle.refresh_expires_in_seconds,
            path=AUTH_BROWSER_COOKIE_PATH,
            secure=self._should_use_secure_browser_cookie(request),
            httponly=True,
            samesite="strict",
        )

    def _build_browser_token_response(
        self,
        request: Request,
        token_bundle: TokenIssuePayload,
    ) -> ResponseEnvelope[BrowserTokenIssuePayload]:
        """丢弃 refresh token 后构造浏览器响应。"""

        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message="浏览器令牌签发成功。",
            request_scope=self._accessor.read_request_scope(request),
            data=BrowserTokenIssuePayload(
                access_token=token_bundle.access_token,
                expires_in_seconds=token_bundle.expires_in_seconds,
            ),
        )

    def _should_use_secure_browser_cookie(self, request: Request) -> bool:
        """按环境和可信公共传输层决定浏览器 Cookie 的 Secure 属性。

        生产环境始终要求 Secure Cookie。开发环境保留直连 HTTP 调试能力，
        但只要请求位于直连 HTTPS 或受信 Caddy 所声明的 HTTPS 边界，
        Cookie 就必须同样带有 Secure，避免开发 HTTPS 与生产行为分叉。
        """

        resource_mount = self._accessor.read_resource_mount(request)
        settings = resource_mount.read_runtime_bundle().settings
        return settings.app.environment == AppEnvironment.PRODUCTION or is_trusted_https_request(
            request,
            resource_mount.get_client_ip_resolver(),
        )

    def _record_token_issue_failure(
        self,
        *,
        request: Request,
        username: str,
        fault: HttpFaultException,
    ) -> None:
        """
        记录登录失败安全事件和风险信号。
        """

        if fault.error_code not in {
            AuthErrorCode.INVALID_CREDENTIALS,
            AuthErrorCode.REQUEST_THROTTLED,
        }:
            return
        resource_mount = request.app.state.container.resource_mount
        digest_service = resource_mount.get_sensitive_digest_service()
        ip = self._resolve_client_ip(request)
        ip_digest = digest_service.digest(ip)
        username_digest = digest_service.digest(username)
        user_agent_digest = digest_service.digest(request.headers.get(USER_AGENT_HEADER_NAME, ""))
        event_type = SecurityEventType.AUTH_LOGIN_FAILURE
        if fault.status_code == int(HTTPStatus.TOO_MANY_REQUESTS):
            event_type = SecurityEventType.AUTH_LOGIN_THROTTLED
        resource_mount.emit_security_event(
            resource_mount.get_security_event_builder().build_auth_failure_event(
                request=request,
                subject_digest=username_digest,
                ip_digest=ip_digest,
                reason_code=str(fault.error_code),
                event_type=event_type,
                status_code=fault.status_code,
                user_agent_digest=user_agent_digest,
            )
        )
        risk_control = resource_mount.read_runtime_bundle().settings.runtime.security.detail.protection.risk_control
        if not risk_control.enabled:
            return
        risk_result = resource_mount.get_risk_signal_guard().record_auth_failure(
            username=username,
            ip=ip,
            window_seconds=risk_control.password_spray_window_seconds,
            password_spray_limit=risk_control.password_spray_limit,
        )
        if not risk_result.password_spray_suspected:
            return
        resource_mount.emit_security_event(
            resource_mount.get_security_event_builder().build_auth_failure_event(
                request=request,
                subject_digest=username_digest,
                ip_digest=ip_digest,
                reason_code=SecurityEventType.AUTH_PASSWORD_SPRAY_SUSPECTED.value,
                event_type=SecurityEventType.AUTH_PASSWORD_SPRAY_SUSPECTED,
                status_code=fault.status_code,
                user_agent_digest=user_agent_digest,
            )
        )

    def _record_refresh_failure(
        self,
        *,
        request: Request,
        refresh_token: str,
        fault: HttpFaultException,
    ) -> None:
        """
        记录刷新令牌失败安全事件。
        """

        resource_mount = request.app.state.container.resource_mount
        digest_service = resource_mount.get_sensitive_digest_service()
        ip_digest = digest_service.digest(self._resolve_client_ip(request))
        token_digest = digest_service.digest(refresh_token)
        event_type = SecurityEventType.AUTH_TOKEN_INVALID
        if fault.error_code == AuthErrorCode.TOKEN_REUSED:
            event_type = SecurityEventType.AUTH_REFRESH_REUSED
        resource_mount.emit_security_event(
            resource_mount.get_security_event_builder().build_auth_failure_event(
                request=request,
                subject_digest=token_digest,
                ip_digest=ip_digest,
                reason_code=str(fault.error_code),
                event_type=event_type,
                status_code=fault.status_code,
                user_agent_digest=digest_service.digest(
                    request.headers.get(USER_AGENT_HEADER_NAME, "")
                ),
            )
        )

    def _resolve_client_ip(self, request: Request) -> str:
        """
        解析客户端 IP。
        """

        return (
            self._accessor.read_resource_mount(request)
            .get_client_ip_resolver()
            .resolve_client_ip(request)
        )


class AuthAccessBundleProvider(WebBundleProvider):
    """
    鉴权访问模块提供者。
    """

    module_name = ApplicationModuleName.AUTH_ACCESS.value

    def provide(self) -> WebBundleProviderEnvelope:
        """
        提供鉴权访问模块信封。
        """

        return WebBundleProviderEnvelope(
            header=WebBundleProviderHeader(module_name=self.module_name),
            detail=WebBundleProviderDetail(provider_name=self.__class__.__name__),
            bundle=WebBundle(
                module_name=self.module_name,
                router=AuthAccessRouteCatalog().router,
            ),
        )
