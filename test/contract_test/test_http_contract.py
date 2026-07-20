"""
测试HTTP契约测试模块。
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from src.api.endpoint_auth_access.contract_auth_access import (
    AUTH_PASSWORD_MAX_LENGTH,
    AUTH_REFRESH_TOKEN_MAX_LENGTH,
    AUTH_REFRESH_TOKEN_MIN_LENGTH,
    AUTH_USERNAME_MAX_LENGTH,
    TokenIssueRequest,
    TokenRefreshRequest,
    TokenRevokeRequest,
)
from src.core.auth_contract.auth_identity_status_contract import (
    AUTH_IDENTITY_STATUS_KIND,
    AUTH_IDENTITY_STATUS_SCHEMA_VERSION,
    AuthIdentityStatusPayload,
)
from src.core.auth_contract.authenticated_principal_contract import (
    AUTH_PRINCIPAL_SCHEMA_VERSION,
    AUTHENTICATED_PRINCIPAL_KIND,
    AuthenticatedPrincipal,
)
from src.core.auth_contract.authorization_policy_contract import (
    ROUTE_AUTHORIZATION_REQUIREMENT_KIND,
    ROUTE_AUTHORIZATION_REQUIREMENT_SCHEMA_VERSION,
    RouteAuthorizationRequirement,
)
from src.core.auth_contract.token_payload_contract import TokenIssuePayload, TokenRevokePayload
from src.core.auth_contract.token_session_status_contract import (
    TOKEN_SESSION_STATUS_KIND,
    TOKEN_SESSION_STATUS_SCHEMA_VERSION,
    TokenSessionStatusPayload,
)
from src.core.exception_contract.http_fault_contract import HttpFaultPayload
from src.core.http_contract.request_scope_contract import RequestScope
from src.core.http_contract.response_envelope_contract import ResponseEnvelopeFactory
from src.core.task_contract.message_bus_contract import (
    TaskMessageEnvelope,
    TaskMessageHeader,
    TaskMessagePayload,
)
from src.domain.auth.auth_error_code import AuthErrorCode
from src.domain.auth.auth_role_key import AuthRoleKey
from src.domain.auth.auth_scope_code import AuthScopeCode

ROUTE_AUTHORIZATION_EXAMPLE_REQUIREMENT_NAME = "admin_identity_read"
AUTH_PRINCIPAL_SUBJECT_ID = "user-1"
AUTH_PRINCIPAL_USERNAME = "admin"
AUTH_PRINCIPAL_UNEXPECTED_FIELD = "unexpected"
AUTH_PRINCIPAL_UNEXPECTED_VALUE = "not-allowed"
AUTH_ACCESS_RAW_USERNAME = "  admin  "
AUTH_ACCESS_NORMALIZED_USERNAME = "admin"
AUTH_ACCESS_BLANK_USERNAME = "   "
AUTH_ACCESS_PASSWORD = "admin-password"
AUTH_ACCESS_EMPTY_PASSWORD = ""
AUTH_ACCESS_REFRESH_TOKEN = "A" * AUTH_REFRESH_TOKEN_MIN_LENGTH
AUTH_ACCESS_INVALID_REFRESH_TOKEN = "!" * AUTH_REFRESH_TOKEN_MIN_LENGTH
AUTH_ACCESS_BOUNDARY_EXCESS_LENGTH = 1
AUTH_ACCESS_MAX_USERNAME = "u" * AUTH_USERNAME_MAX_LENGTH
AUTH_ACCESS_OVER_MAX_USERNAME = "u" * (
    AUTH_USERNAME_MAX_LENGTH + AUTH_ACCESS_BOUNDARY_EXCESS_LENGTH
)
AUTH_ACCESS_MAX_PASSWORD = "p" * AUTH_PASSWORD_MAX_LENGTH
AUTH_ACCESS_OVER_MAX_PASSWORD = "p" * (
    AUTH_PASSWORD_MAX_LENGTH + AUTH_ACCESS_BOUNDARY_EXCESS_LENGTH
)
AUTH_ACCESS_BELOW_MIN_REFRESH_TOKEN = "A" * (
    AUTH_REFRESH_TOKEN_MIN_LENGTH - AUTH_ACCESS_BOUNDARY_EXCESS_LENGTH
)
AUTH_ACCESS_MAX_REFRESH_TOKEN = "A" * AUTH_REFRESH_TOKEN_MAX_LENGTH
AUTH_ACCESS_OVER_MAX_REFRESH_TOKEN = "A" * (
    AUTH_REFRESH_TOKEN_MAX_LENGTH + AUTH_ACCESS_BOUNDARY_EXCESS_LENGTH
)
AUTH_PRINCIPAL_FIELD_NAMES = frozenset(
    {
        "kind",
        "schema_version",
        "subject_id",
        "username",
        "roles",
        "scopes",
        "is_admin",
    }
)


class DemoResponsePayload(BaseModel):
    """
    示例响应Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar kind: 结构版本的具体类型标识。约束：需符合 ``str`` 注解。默认值：`'demo_response'`。取值语义：用于承载当前对象中的业务状态。
    :vartype kind: str
    :ivar schema_version: 结构模式版本。约束：需符合 ``str`` 注解。默认值：`'1.0'`。取值语义：用于承载当前对象中的业务状态。
    :vartype schema_version: str
    :ivar value: 缓存值或业务值。约束：需符合 ``str`` 注解。默认值：`'ok'`。取值语义：用于承载当前对象中的业务状态。
    :vartype value: str
    """

    model_config = ConfigDict(extra="forbid")

    kind: str = "demo_response"
    schema_version: str = "1.0"
    value: str = "ok"


class TestHttpContract:
    """
    测试HTTP契约测试集合，用于组织同一主题下的测试场景。
    """

    def test_response_envelope_should_use_header_and_typed_payload(self) -> None:
        """
        验证响应信封应用途头与类型化载荷。

        :returns: 无返回值。
        :rtype: None
        """

        request_scope = RequestScope(
            request_id="request-1",
            trace_id=None,
            request_time_epoch=1,
            request_path="/demo",
            request_method="GET",
        )
        envelope = ResponseEnvelopeFactory().build(
            code="system.success.ok",
            message="成功。",
            request_scope=request_scope,
            data=DemoResponsePayload(),
        )
        assert set(envelope.model_dump().keys()) == {"header", "data"}

    def test_error_payload_should_keep_stable_fields(self) -> None:
        """
        验证错误载荷应保持稳定字段集合。

        :returns: 无返回值。
        :rtype: None
        """

        payload = HttpFaultPayload(
            status_code=400,
            error_code="system.request.invalid",
        )
        assert payload.kind == "http_fault"
        assert payload.status_code == 400
        assert "detail" not in payload.model_dump()

    def test_auth_issue_payload_should_keep_token_contract(self) -> None:
        """
        验证鉴权签发载荷应保持令牌契约。

        :returns: 无返回值。
        :rtype: None
        """

        payload = TokenIssuePayload(
            access_token="a",
            refresh_token="b",
            token_type="Bearer",
            expires_in_seconds=10,
            refresh_expires_in_seconds=20,
        )
        assert payload.kind == "token_issue"
        assert payload.token_type == "Bearer"

    def test_auth_revoke_payload_should_keep_revoke_contract(self) -> None:
        """
        验证鉴权撤销载荷应保持撤销契约。

        :returns: 无返回值。
        :rtype: None
        """

        payload = TokenRevokePayload(
            revoked=True,
            revoked_at_epoch=1,
        )
        assert payload.kind == "token_revoke"
        assert payload.revoked is True

    def test_authenticated_principal_should_keep_typed_fields(self) -> None:
        """
        验证已认证主体应保持类型化字段集合。

        :returns: 无返回值。
        :rtype: None
        """

        principal = AuthenticatedPrincipal(
            subject_id=AUTH_PRINCIPAL_SUBJECT_ID,
            username=AUTH_PRINCIPAL_USERNAME,
            roles=[AuthRoleKey.ADMIN],
            scopes=[AuthScopeCode.SYSTEM_READ],
        )
        dumped_principal = principal.model_dump()

        assert principal.kind == AUTHENTICATED_PRINCIPAL_KIND
        assert principal.schema_version == AUTH_PRINCIPAL_SCHEMA_VERSION
        assert principal.is_admin is True
        assert set(dumped_principal) == AUTH_PRINCIPAL_FIELD_NAMES

    def test_authenticated_principal_should_reject_unknown_fields(self) -> None:
        """
        验证已认证主体契约应拒绝未知字段。

        :returns: 无返回值。
        :rtype: None
        """

        with pytest.raises(ValidationError):
            AuthenticatedPrincipal.model_validate(
                {
                    "subject_id": AUTH_PRINCIPAL_SUBJECT_ID,
                    "username": AUTH_PRINCIPAL_USERNAME,
                    "roles": [AuthRoleKey.ADMIN],
                    "scopes": [AuthScopeCode.SYSTEM_READ],
                    AUTH_PRINCIPAL_UNEXPECTED_FIELD: AUTH_PRINCIPAL_UNEXPECTED_VALUE,
                }
            )

    def test_route_authorization_requirement_should_keep_header_and_extension(self) -> None:
        """
        验证路由授权要求应保持头与扩展。

        :returns: 无返回值。
        :rtype: None
        """

        requirement = RouteAuthorizationRequirement(
            requirement_name=ROUTE_AUTHORIZATION_EXAMPLE_REQUIREMENT_NAME,
            required_roles=[AuthRoleKey.ADMIN],
            required_scopes=[AuthScopeCode.AUTH_READ],
        )
        assert requirement.kind == ROUTE_AUTHORIZATION_REQUIREMENT_KIND
        assert requirement.schema_version == ROUTE_AUTHORIZATION_REQUIREMENT_SCHEMA_VERSION

    def test_auth_identity_status_payload_should_keep_header_and_extension(self) -> None:
        """
        验证鉴权身份状态载荷应保持头与扩展。

        :returns: 无返回值。
        :rtype: None
        """

        payload = AuthIdentityStatusPayload(
            subject_id="user-1",
            is_active=True,
        )
        assert payload.kind == AUTH_IDENTITY_STATUS_KIND
        assert payload.schema_version == AUTH_IDENTITY_STATUS_SCHEMA_VERSION

    def test_token_session_status_payload_should_keep_header_and_extension(self) -> None:
        """
        验证令牌会话状态载荷应保持头与扩展。

        :returns: 无返回值。
        :rtype: None
        """

        payload = TokenSessionStatusPayload(
            token_session_id="session-1",
            subject_id="user-1",
            is_revoked=False,
            revoked_at_epoch=None,
        )
        assert payload.kind == TOKEN_SESSION_STATUS_KIND
        assert payload.schema_version == TOKEN_SESSION_STATUS_SCHEMA_VERSION

    def test_auth_error_code_should_keep_permission_denied_contract(self) -> None:
        """
        验证鉴权错误编码应保持权限拒绝契约。

        :returns: 无返回值。
        :rtype: None
        """

        assert str(AuthErrorCode.PERMISSION_DENIED) == "auth.authorization.permission_denied"

    def test_auth_issue_request_should_trim_username_and_reject_unknown_fields(
        self,
    ) -> None:
        """
        验证鉴权签发请求约束用户名规范化和未知字段拒绝。

        :returns: 无返回值。
        :rtype: None
        """

        request = TokenIssueRequest(
            username=AUTH_ACCESS_RAW_USERNAME,
            password=AUTH_ACCESS_PASSWORD,
        )

        assert request.username == AUTH_ACCESS_NORMALIZED_USERNAME
        with pytest.raises(ValidationError):
            TokenIssueRequest.model_validate(
                {
                    "username": AUTH_ACCESS_NORMALIZED_USERNAME,
                    "password": AUTH_ACCESS_PASSWORD,
                    AUTH_PRINCIPAL_UNEXPECTED_FIELD: AUTH_PRINCIPAL_UNEXPECTED_VALUE,
                }
            )

    def test_auth_issue_request_when_blank_or_empty_should_fail(self) -> None:
        """
        验证鉴权签发请求拒绝空用户名和空密码。

        :returns: 无返回值。
        :rtype: None
        """

        with pytest.raises(ValidationError):
            TokenIssueRequest(
                username=AUTH_ACCESS_BLANK_USERNAME,
                password=AUTH_ACCESS_PASSWORD,
            )
        with pytest.raises(ValidationError):
            TokenIssueRequest(
                username=AUTH_ACCESS_NORMALIZED_USERNAME,
                password=AUTH_ACCESS_EMPTY_PASSWORD,
            )

    def test_auth_issue_request_should_enforce_max_length(self) -> None:
        """
        验证鉴权签发请求强制用户名和密码最大长度。

        :returns: 无返回值。
        :rtype: None
        """

        request = TokenIssueRequest(
            username=AUTH_ACCESS_MAX_USERNAME,
            password=AUTH_ACCESS_MAX_PASSWORD,
        )

        assert request.username == AUTH_ACCESS_MAX_USERNAME
        with pytest.raises(ValidationError):
            TokenIssueRequest(
                username=AUTH_ACCESS_OVER_MAX_USERNAME,
                password=AUTH_ACCESS_PASSWORD,
            )
        with pytest.raises(ValidationError):
            TokenIssueRequest(
                username=AUTH_ACCESS_NORMALIZED_USERNAME,
                password=AUTH_ACCESS_OVER_MAX_PASSWORD,
            )

    def test_auth_refresh_and_revoke_request_should_enforce_token_pattern(
        self,
    ) -> None:
        """
        验证刷新和撤销请求强制刷新令牌格式。

        :returns: 无返回值。
        :rtype: None
        """

        refresh_request = TokenRefreshRequest(refresh_token=AUTH_ACCESS_REFRESH_TOKEN)
        revoke_request = TokenRevokeRequest(refresh_token=AUTH_ACCESS_REFRESH_TOKEN)

        assert refresh_request.refresh_token == AUTH_ACCESS_REFRESH_TOKEN
        assert revoke_request.refresh_token == AUTH_ACCESS_REFRESH_TOKEN
        with pytest.raises(ValidationError):
            TokenRefreshRequest(refresh_token=AUTH_ACCESS_INVALID_REFRESH_TOKEN)
        with pytest.raises(ValidationError):
            TokenRevokeRequest(refresh_token=AUTH_ACCESS_INVALID_REFRESH_TOKEN)

    def test_auth_refresh_and_revoke_request_should_enforce_token_length(
        self,
    ) -> None:
        """
        验证刷新和撤销请求强制刷新令牌长度边界。

        :returns: 无返回值。
        :rtype: None
        """

        refresh_request = TokenRefreshRequest(
            refresh_token=AUTH_ACCESS_MAX_REFRESH_TOKEN,
        )
        revoke_request = TokenRevokeRequest(
            refresh_token=AUTH_ACCESS_MAX_REFRESH_TOKEN,
        )

        assert refresh_request.refresh_token == AUTH_ACCESS_MAX_REFRESH_TOKEN
        assert revoke_request.refresh_token == AUTH_ACCESS_MAX_REFRESH_TOKEN
        for request_model in [TokenRefreshRequest, TokenRevokeRequest]:
            with pytest.raises(ValidationError):
                request_model(refresh_token=AUTH_ACCESS_BELOW_MIN_REFRESH_TOKEN)
            with pytest.raises(ValidationError):
                request_model(refresh_token=AUTH_ACCESS_OVER_MAX_REFRESH_TOKEN)

    def test_task_message_envelope_should_keep_header_plus_payload(self) -> None:
        """
        验证任务消息信封应保持头plus载荷。

        :returns: 无返回值。
        :rtype: None
        """

        message = TaskMessageEnvelope(
            header=TaskMessageHeader(message_id="task-1", created_at_epoch=1),
            payload=TaskMessagePayload(
                job_kind="demo_task",
                deduplication_key="dedupe-1",
                retry_limit=1,
                payload_kind="DemoTaskPayload",
                payload_json='{"task_id":"1"}',
            ),
        )
        assert message.payload.kind == "task_message"
        assert message.header.message_id == "task-1"
