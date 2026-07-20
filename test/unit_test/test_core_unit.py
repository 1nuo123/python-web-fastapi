"""
测试核心单元测试模块。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from src.core.auth_contract.authenticated_principal_contract import (
    AuthenticatedPrincipal,
)
from src.core.auth_contract.authorization_policy_contract import (
    AuthorizationPolicy,
    RouteAuthorizationRequirement,
)
from src.core.auth_contract.token_payload_contract import TokenUse
from src.core.http_contract.request_scope_contract import RequestScope
from src.core.http_contract.response_envelope_contract import ResponseEnvelopeFactory
from src.domain.auth.access_token_policy import AccessTokenPolicy
from src.domain.auth.auth_role_key import AuthRoleKey
from src.domain.auth.auth_scope_code import AuthScopeCode
from src.domain.auth.authorization_policy_evaluator import (
    AuthorizationPolicyEvaluator,
)
from src.infrastructure.auth.jwt_token_service import JwtTokenService
from src.infrastructure.cache.memory_cache_store import MemoryCacheStore
from src.infrastructure.testing.fake_clock import FakeClock

ROUTE_AUTHORIZATION_EXAMPLE_REQUIREMENT_NAME = "admin_identity_read"


class DemoPayload(BaseModel):
    """
    示例Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar kind: 结构版本的具体类型标识。约束：需符合 ``str`` 注解。默认值：`'demo'`。取值语义：用于承载当前对象中的业务状态。
    :vartype kind: str
    :ivar schema_version: 结构模式版本。约束：需符合 ``str`` 注解。默认值：`'1.0'`。取值语义：用于承载当前对象中的业务状态。
    :vartype schema_version: str
    :ivar value: 缓存值或业务值。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype value: str
    """

    model_config = ConfigDict(extra="forbid")

    kind: str = "demo"
    schema_version: str = "1.0"
    value: str


class TestCoreUnit:
    """
    测试核心单元测试集合，用于组织同一主题下的测试场景。
    """

    def test_response_envelope_factory_should_include_public_header(self) -> None:
        """
        验证响应信封工厂应包含公共头。

        :returns: 无返回值。
        :rtype: None
        """

        request_scope = RequestScope(
            request_id="request-1",
            trace_id="trace-1",
            request_time_epoch=1,
            request_path="/demo",
            request_method="GET",
        )
        envelope = ResponseEnvelopeFactory().build(
            code="system.success.ok",
            message="执行成功。",
            request_scope=request_scope,
            data=DemoPayload(value="ok"),
        )
        assert envelope.header.request_id == "request-1"
        assert envelope.data.kind == "demo"

    def test_jwt_token_service_issue_and_decode_should_success(self) -> None:
        """
        验证JWT令牌服务签发与解码应成功。

        :returns: 无返回值。
        :rtype: None
        """

        principal = AuthenticatedPrincipal(
            subject_id="user-1",
            username="tester",
            roles=[AuthRoleKey.ADMIN],
            scopes=[AuthScopeCode.SYSTEM_READ],
        )
        token_service = JwtTokenService(
            AccessTokenPolicy(
                jwt_secret="unit-secret-2026-with-safe-length",
                jwt_algorithm="HS256",
                access_token_expires_in_seconds=30,
                refresh_token_expires_in_seconds=60,
                issuer="unit",
                audience="client",
                refresh_token_rotation_enabled=True,
            )
        )
        token_issue = token_service.issue_token_pair(principal, current_epoch=10)
        token_payload = token_service.decode_token(
            token_issue.response_payload.access_token,
            expected_use=TokenUse.ACCESS,
            current_epoch=20,
        )
        assert token_payload.subject_id == "user-1"
        assert token_payload.token_use == TokenUse.ACCESS
        assert (
            token_issue.access_token_payload.token_session_id
            == token_issue.refresh_token_payload.token_session_id
        )
        assert token_payload.roles == [AuthRoleKey.ADMIN]

    def test_authorization_policy_evaluator_when_scope_missing_should_fail(self) -> None:
        """
        验证授权策略评估器当作用域缺失应失败。

        :returns: 无返回值。
        :rtype: None
        """

        principal = AuthenticatedPrincipal(
            subject_id="user-1",
            username="tester",
            roles=[AuthRoleKey.ADMIN],
            scopes=[AuthScopeCode.SYSTEM_READ],
        )
        decision = AuthorizationPolicyEvaluator().evaluate(
            principal,
            AuthorizationPolicy(required_scopes=[AuthScopeCode.TASK_DISPATCH]),
        )
        assert decision.allowed is False
        assert "缺少权限范围" in str(decision.reason)

    def test_authorization_requirement_should_build_policy(self) -> None:
        """
        验证授权要求应构建策略。

        :returns: 无返回值。
        :rtype: None
        """

        requirement = RouteAuthorizationRequirement(
            requirement_name=ROUTE_AUTHORIZATION_EXAMPLE_REQUIREMENT_NAME,
            required_roles=[AuthRoleKey.ADMIN],
            required_scopes=[AuthScopeCode.AUTH_READ],
        )
        policy = requirement.to_policy()
        assert policy.required_roles == [AuthRoleKey.ADMIN]
        assert policy.required_scopes == [AuthScopeCode.AUTH_READ]

    def test_memory_cache_store_when_expired_should_return_none(self) -> None:
        """
        验证内存缓存存储当已过期应返回空。

        :returns: 无返回值。
        :rtype: None
        """

        fake_clock = FakeClock()
        cache_store = MemoryCacheStore(timer=fake_clock.now)
        cache_store.set_value("token", "abc", 5)
        fake_clock.advance(4)
        assert cache_store.get_value("token") == "abc"
        fake_clock.advance(1)
        assert cache_store.get_value("token") is None
