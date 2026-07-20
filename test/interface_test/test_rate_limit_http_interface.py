"""
限流 HTTP 接口测试模块。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from http import HTTPStatus
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.testing.test_app_factory import TestAppFactory
from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.http_contract.request_scope_contract import RequestScope
from src.core.http_contract.security_runtime_contract import RateLimitFailMode
from src.core.security_contract.rate_limit_policy_contract import (
    RateLimitKeyDimension,
    RateLimitPolicyEnvelope,
)
from src.core.security_contract.security_decision_contract import (
    SecurityAction,
    SecurityDecisionEnvelope,
)
from src.infrastructure.middleware_chain.rate_limit_middleware import (
    RATE_LIMIT_REJECTED_MESSAGE,
    RETRY_AFTER_HEADER_NAME,
    RateLimitMiddleware,
)
from src.infrastructure.persistence.orm_model.auth_user_orm_model import AuthUserOrmModel
from src.infrastructure.shared_resource_mount import SharedResourceMount

RATE_LIMIT_TEST_PATH = "/limited"
AUTH_TOKEN_PATH = "/auth/token"
AUTHORIZATION_HEADER = "Authorization"
BEARER_PREFIX = "Bearer"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin"
SECOND_USERNAME = "rate-limit-user"
SECOND_PASSWORD = "rate-limit-password"
SECOND_SUBJECT_ID = "user-rate-limit"
AUTH_TOKEN_POLICY_LIMIT = 10
RATE_LIMIT_POLICY_HEADER_KIND = "rate_limit_policy_header"
RATE_LIMIT_POLICY_DETAIL_KIND = "rate_limit_policy"
RATE_LIMIT_POLICY_SCHEMA_VERSION = "1.0"
RATE_LIMIT_LIMITED_POLICY_NAME = "limited_subject"
RATE_LIMIT_AUTH_FIELD_POLICY_NAME = "limited_auth_field"
RATE_LIMIT_METHOD_GET = "GET"
RATE_LIMIT_HTTP_LIMIT = 1
RATE_LIMIT_HTTP_WINDOW_SECONDS = 60
RATE_LIMIT_HTTP_BLOCK_SECONDS = 60
RATE_LIMIT_FAKE_POLICY_NAME = "test"
RATE_LIMIT_REJECT_REASON_CODE = "rate_limited"
API_KEY_HEADER_NAME = "x-api-key"
FIRST_API_KEY = "api-key-one"
SECOND_API_KEY = "api-key-two"
HTTP_OK = 200
HTTP_TOO_MANY_REQUESTS = 429
HTTP_SERVICE_UNAVAILABLE = 503
RATE_LIMIT_CACHE_UNAVAILABLE_MESSAGE = "限流缓存不可用。"


@dataclass(frozen=True, slots=True)
class FakeFlowControlDetail:
    """
    测试流控配置。
    """

    enabled: bool = True
    default_limit: int = RATE_LIMIT_HTTP_LIMIT
    default_window_seconds: int = RATE_LIMIT_HTTP_WINDOW_SECONDS
    fail_mode: RateLimitFailMode = RateLimitFailMode.FAIL_CLOSED
    policies: list[RateLimitPolicyEnvelope] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class FakeIpBlockDetail:
    """
    测试 IP 封禁配置。
    """

    default_block_seconds: int = RATE_LIMIT_HTTP_BLOCK_SECONDS
    cache_ttl_seconds: int = RATE_LIMIT_HTTP_BLOCK_SECONDS


@dataclass(frozen=True, slots=True)
class FakeProtectionDetail:
    """
    测试安全防护配置。
    """

    flow_control: FakeFlowControlDetail = field(default_factory=FakeFlowControlDetail)
    ip_block: FakeIpBlockDetail = field(default_factory=FakeIpBlockDetail)


@dataclass(frozen=True, slots=True)
class FakeSecurityDetail:
    """
    测试安全配置详情。
    """

    protection: FakeProtectionDetail = field(default_factory=FakeProtectionDetail)


@dataclass(frozen=True, slots=True)
class FakeSecurityRuntime:
    """
    测试安全运行时。
    """

    detail: FakeSecurityDetail = field(default_factory=FakeSecurityDetail)


@dataclass(frozen=True, slots=True)
class FakeRuntimeSettings:
    """
    测试运行时配置。
    """

    security: FakeSecurityRuntime = field(default_factory=FakeSecurityRuntime)


@dataclass(frozen=True, slots=True)
class FakeApplicationSettings:
    """
    测试应用配置。
    """

    runtime: FakeRuntimeSettings = field(default_factory=FakeRuntimeSettings)


@dataclass(frozen=True, slots=True)
class FakeRuntimeBundle:
    """
    测试运行时快照。
    """

    settings: FakeApplicationSettings


class FakeSecurityProtectionGuard:
    """
    测试安全防护门面。
    """

    def __init__(self, *, fault: HttpFaultException | None = None) -> None:
        """
        初始化测试安全防护门面。
        """

        self.received_rate_limit_fail_mode: RateLimitFailMode | None = None
        self._fault = fault

    def evaluate_request(
        self,
        *,
        request,
        limit: int,
        window_seconds: int,
        block_seconds: int,
        ip_block_cache_ttl_seconds: int,
        flow_control_enabled: bool = True,
        ip_block_enabled: bool = True,
        policy_name: str = "test",
        key_dimensions: list[RateLimitKeyDimension] | None = None,
        auth_field_values: list[str] | None = None,
        block_when_exceeded: bool = True,
        rate_limit_fail_mode: RateLimitFailMode = RateLimitFailMode.FAIL_CLOSED,
    ) -> SecurityDecisionEnvelope:
        """
        返回限流拒绝决策。
        """

        self.received_rate_limit_fail_mode = rate_limit_fail_mode
        if self._fault is not None:
            raise self._fault
        return SecurityDecisionEnvelope(
            action=SecurityAction.RETURN_429,
            policy_name=RATE_LIMIT_FAKE_POLICY_NAME,
            reason_code=RATE_LIMIT_REJECT_REASON_CODE,
            retry_after_seconds=window_seconds,
        )


class FakeResourceMount:
    """
    测试资源挂载点。
    """

    def __init__(self, *, fault: HttpFaultException | None = None) -> None:
        """
        初始化测试资源挂载点。
        """

        self.security_protection_guard = FakeSecurityProtectionGuard(fault=fault)

    def get_security_protection_guard(self) -> FakeSecurityProtectionGuard:
        """
        获取安全防护门面。
        """

        return self.security_protection_guard

    def read_runtime_bundle(self) -> FakeRuntimeBundle:
        """
        读取测试运行时快照。
        """

        return FakeRuntimeBundle(settings=FakeApplicationSettings())


class TestRateLimitHttpInterface:
    """
    限流 HTTP 接口测试集合。
    """

    def test_rate_limit_middleware_should_return_429_and_retry_after(self) -> None:
        """
        验证限流中间件返回 429 和 Retry-After。
        """

        app = FastAPI()
        resource_mount = FakeResourceMount()
        app.add_middleware(
            RateLimitMiddleware,
            resource_mount=resource_mount,
        )

        @app.middleware("http")
        async def bind_request_scope(request, call_next):
            request.state.middleware_trace = []
            request.state.request_scope = RequestScope(
                request_id="request-1",
                trace_id=None,
                request_time_epoch=1,
                request_path=request.url.path,
                request_method=request.method,
            )
            return await call_next(request)

        @app.get(RATE_LIMIT_TEST_PATH)
        async def limited_endpoint():
            return {"ok": True}

        with TestClient(app) as client:
            response = client.get(RATE_LIMIT_TEST_PATH)

        assert response.status_code == 429
        assert response.headers[RETRY_AFTER_HEADER_NAME] == "60"
        assert response.json()["header"]["message"] == RATE_LIMIT_REJECTED_MESSAGE
        assert (
            resource_mount.security_protection_guard.received_rate_limit_fail_mode
            == RateLimitFailMode.FAIL_CLOSED
        )

    def test_rate_limit_middleware_when_cache_unavailable_should_return_503(self) -> None:
        """验证中间件链内限流缓存故障按统一契约关闭请求。"""

        app = FastAPI()
        resource_mount = FakeResourceMount(
            fault=HttpFaultException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                error_code=CoreErrorCode.CACHE_UNAVAILABLE,
                message=RATE_LIMIT_CACHE_UNAVAILABLE_MESSAGE,
            )
        )
        app.add_middleware(RateLimitMiddleware, resource_mount=resource_mount)

        @app.middleware("http")
        async def bind_request_scope(request, call_next):
            request.state.middleware_trace = []
            request.state.request_scope = RequestScope(
                request_id="request-cache-unavailable",
                trace_id=None,
                request_time_epoch=1,
                request_path=request.url.path,
                request_method=request.method,
            )
            return await call_next(request)

        @app.get(RATE_LIMIT_TEST_PATH)
        async def limited_endpoint():
            return {"ok": True}

        with TestClient(app) as client:
            response = client.get(RATE_LIMIT_TEST_PATH)

        assert response.status_code == HTTP_SERVICE_UNAVAILABLE
        assert response.json()["header"]["message"] == RATE_LIMIT_CACHE_UNAVAILABLE_MESSAGE

    def test_auth_token_policy_should_return_429_after_threshold(self) -> None:
        """
        验证 /auth/token 命中认证限流策略阈值后返回 429。
        """

        app = TestAppFactory().create(
            overrides={
                "runtime": {
                    "security": {"detail": {"protection": {"ip_block": {"enabled": False}}}}
                }
            }
        )
        with TestClient(app) as client:
            responses = [
                client.post(
                    AUTH_TOKEN_PATH,
                    json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
                )
                for _index in range(AUTH_TOKEN_POLICY_LIMIT + 1)
            ]

        assert responses[AUTH_TOKEN_POLICY_LIMIT - 1].status_code == 200
        assert responses[AUTH_TOKEN_POLICY_LIMIT].status_code == 429
        assert responses[AUTH_TOKEN_POLICY_LIMIT].headers[RETRY_AFTER_HEADER_NAME] == "300"

    def test_subject_dimension_should_count_authenticated_subject_in_http_flow(
        self,
    ) -> None:
        """
        验证 subject 维度已接入真实 HTTP 限流主流程。
        """

        app = TestAppFactory().create(
            overrides=self._build_limited_policy_overrides(
                policy_name=RATE_LIMIT_LIMITED_POLICY_NAME,
                key_dimensions=[RateLimitKeyDimension.SUBJECT_ID.value],
            )
        )

        @app.get(RATE_LIMIT_TEST_PATH)
        async def limited_endpoint() -> dict[str, bool]:
            return {"ok": True}

        with TestClient(app) as client:
            resource_mount = app.state.container.resource_mount
            self._delete_identity(
                resource_mount=resource_mount,
                username=SECOND_USERNAME,
            )
            self._create_active_identity(
                resource_mount=resource_mount,
                username=SECOND_USERNAME,
                password=SECOND_PASSWORD,
                subject_id=SECOND_SUBJECT_ID,
            )
            try:
                admin_token = self._issue_access_token(
                    client=client,
                    username=ADMIN_USERNAME,
                    password=ADMIN_PASSWORD,
                )
                second_token = self._issue_access_token(
                    client=client,
                    username=SECOND_USERNAME,
                    password=SECOND_PASSWORD,
                )
                admin_first_response = client.get(
                    RATE_LIMIT_TEST_PATH,
                    headers=self._build_auth_header(admin_token),
                )
                second_first_response = client.get(
                    RATE_LIMIT_TEST_PATH,
                    headers=self._build_auth_header(second_token),
                )
                admin_second_response = client.get(
                    RATE_LIMIT_TEST_PATH,
                    headers=self._build_auth_header(admin_token),
                )
            finally:
                self._delete_identity(
                    resource_mount=resource_mount,
                    username=SECOND_USERNAME,
                )

        assert admin_first_response.status_code == HTTP_OK
        assert second_first_response.status_code == HTTP_OK
        assert admin_second_response.status_code == HTTP_TOO_MANY_REQUESTS

    def test_auth_field_dimension_should_count_header_digest_in_http_flow(
        self,
    ) -> None:
        """
        验证认证字段摘要维度已接入真实 HTTP 限流主流程。
        """

        app = TestAppFactory().create(
            overrides=self._build_limited_policy_overrides(
                policy_name=RATE_LIMIT_AUTH_FIELD_POLICY_NAME,
                key_dimensions=[RateLimitKeyDimension.AUTH_FIELD_DIGEST.value],
            )
        )

        @app.get(RATE_LIMIT_TEST_PATH)
        async def limited_endpoint() -> dict[str, bool]:
            return {"ok": True}

        with TestClient(app) as client:
            first_key_response = client.get(
                RATE_LIMIT_TEST_PATH,
                headers={API_KEY_HEADER_NAME: FIRST_API_KEY},
            )
            second_key_response = client.get(
                RATE_LIMIT_TEST_PATH,
                headers={API_KEY_HEADER_NAME: SECOND_API_KEY},
            )
            first_key_limited_response = client.get(
                RATE_LIMIT_TEST_PATH,
                headers={API_KEY_HEADER_NAME: FIRST_API_KEY},
            )

        assert first_key_response.status_code == HTTP_OK
        assert second_key_response.status_code == HTTP_OK
        assert first_key_limited_response.status_code == HTTP_TOO_MANY_REQUESTS

    def _build_limited_policy_overrides(
        self,
        *,
        policy_name: str,
        key_dimensions: list[str],
    ) -> dict[str, object]:
        """
        构造限流策略覆盖配置。
        """

        return {
            "runtime": {
                "security": {
                    "detail": {
                        "protection": {
                            "flow_control": {
                                "policies": [
                                    {
                                        "header": {
                                            "kind": RATE_LIMIT_POLICY_HEADER_KIND,
                                            "schema_version": RATE_LIMIT_POLICY_SCHEMA_VERSION,
                                            "detail_kind": RATE_LIMIT_POLICY_DETAIL_KIND,
                                            "policy_name": policy_name,
                                            "enabled": True,
                                        },
                                        "detail": {
                                            "kind": RATE_LIMIT_POLICY_DETAIL_KIND,
                                            "schema_version": RATE_LIMIT_POLICY_SCHEMA_VERSION,
                                            "path": RATE_LIMIT_TEST_PATH,
                                            "method": RATE_LIMIT_METHOD_GET,
                                            "limit": RATE_LIMIT_HTTP_LIMIT,
                                            "window_seconds": RATE_LIMIT_HTTP_WINDOW_SECONDS,
                                            "key_dimensions": key_dimensions,
                                            "block_when_exceeded": False,
                                            "block_seconds": RATE_LIMIT_HTTP_BLOCK_SECONDS,
                                        },
                                    }
                                ]
                            },
                            "ip_block": {"enabled": False},
                        }
                    }
                }
            }
        }

    def _issue_access_token(
        self,
        *,
        client: TestClient,
        username: str,
        password: str,
    ) -> str:
        """
        签发访问令牌。
        """

        token_response = client.post(
            AUTH_TOKEN_PATH,
            json={"username": username, "password": password},
        )
        return str(token_response.json()["data"]["access_token"])

    def _build_auth_header(self, access_token: str) -> dict[str, str]:
        """
        构造授权请求头。
        """

        return {AUTHORIZATION_HEADER: f"{BEARER_PREFIX} {access_token}"}

    def _create_active_identity(
        self,
        *,
        resource_mount: SharedResourceMount,
        username: str,
        password: str,
        subject_id: str,
    ) -> None:
        """
        创建测试用激活身份。
        """

        unit_of_work = resource_mount.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            session.add(
                AuthUserOrmModel(
                    user_id=uuid4(),
                    subject_id=subject_id,
                    username=username,
                    password_hash=resource_mount.get_password_hasher().hash_password(password),
                    is_active=True,
                )
            )
            unit_of_work.commit()
        except Exception:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def _delete_identity(
        self,
        *,
        resource_mount: SharedResourceMount,
        username: str,
    ) -> None:
        """
        删除测试身份并释放数据库资源。
        """

        unit_of_work = resource_mount.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            user = session.query(AuthUserOrmModel).filter_by(username=username).one_or_none()
            if user is not None:
                session.delete(user)
            unit_of_work.commit()
        except Exception:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()
