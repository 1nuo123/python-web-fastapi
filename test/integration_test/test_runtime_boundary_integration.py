"""
测试运行时边界测试模块。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict
from sqlalchemy import create_engine
from sqlalchemy.exc import TimeoutError as SqlAlchemyTimeoutError
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.api.testing.test_app_factory import TestAppFactory
from src.api.web_bundle_catalog import ENABLED_MODULES_CONFIG_PATH
from src.application.dispatch_background_job_usecase import TaskDispatchCommand
from src.core.auth_contract.authenticated_principal_contract import (
    AuthenticatedPrincipal,
)
from src.core.auth_contract.token_payload_contract import TokenUse
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.http_contract.request_scope_contract import RequestScope
from src.core.security_contract.security_event_contract import SecurityEventEnvelope
from src.core.task_contract.task_handler_contract import TaskHandler
from src.core.task_contract.task_invocation_contract import TypedTaskInvocation
from src.domain.auth.access_token_policy import AccessTokenPolicy
from src.domain.auth.auth_error_code import AuthErrorCode
from src.domain.auth.auth_role_key import AuthRoleKey
from src.domain.auth.auth_scope_code import AuthScopeCode
from src.infrastructure.auth.jwt_token_service import JwtTokenService
from src.infrastructure.cache.memory_cache_store import MemoryCacheStore
from src.infrastructure.middleware_chain.payload_guard_middleware import (
    CONTENT_LENGTH_HEADER_NAME,
    HTTP_REQUEST_MESSAGE_TYPE,
    HTTP_RESPONSE_START_MESSAGE_TYPE,
    HTTP_SCOPE_TYPE,
    PayloadGuardMiddleware,
)
from src.infrastructure.persistence.orm_model.auth_user_orm_model import AuthUserOrmModel
from src.infrastructure.settings.app_settings_loader import (
    AppSettingsLoader,
)
from src.infrastructure.settings.application_settings import (
    AppEnvironment,
    ApplicationSettings,
)
from src.infrastructure.settings.parsers.module_settings_parser import (
    AppSettingsSectionDetail,
    ModuleSettingsParser,
)
from src.infrastructure.settings.parsers.module_settings_parser import (
    SettingsSectionEnvelope as ModuleSettingsSectionEnvelope,
)
from src.infrastructure.settings.parsers.runtime_settings_parser import (
    RuntimeSettingsParser,
)
from src.infrastructure.settings.parsers.runtime_settings_parser import (
    SettingsSectionEnvelope as RuntimeSettingsSectionEnvelope,
)
from src.infrastructure.task.task_registration_registry import RegisteredTaskBinding
from src.infrastructure.testing.fake_clock import FakeClock

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.usefixtures("integration_database"),
]

AUTHORIZATION_HEADER = "Authorization"
AUTH_ME_PATH = "/auth/me"
AUTH_REFRESH_PATH = "/auth/refresh"
AUTH_TOKEN_PATH = "/auth/token"
BEARER_PREFIX = "Bearer"
DATA_FIELD = "data"
DEFAULT_REQUEST_ID = "request-boundary"
DEFAULT_SCOPE_LIMIT = 8
DEFAULT_TRACE_ID = "trace-boundary"
ERROR_CODE_FIELD = "error_code"
HTTP_RESPONSE_BODY_MESSAGE_TYPE = "http.response.body"
POST_METHOD = "POST"
REFRESH_TOKEN_FIELD = "refresh_token"
ACCESS_TOKEN_FIELD = "access_token"
TOKEN_BOUNDARY_ACCESS_EXPIRES_IN_SECONDS = 10
TOKEN_BOUNDARY_BEFORE_EXPIRY_EPOCH = 109
TOKEN_BOUNDARY_EXPIRY_EPOCH = 110
TOKEN_BOUNDARY_ISSUED_AT_EPOCH = 100
DATABASE_POOL_EXHAUSTION_TIMEOUT_SECONDS = 0.1
TOKEN_BOUNDARY_REFRESH_EXPIRES_IN_SECONDS = 20
TOKEN_BOUNDARY_SUBJECT_ID = "user-1"
UNKNOWN_WEB_MODULE_NAME = "unknown_module"
DISABLED_ACCOUNT_USERNAME_PREFIX = "disabled-account"
DISABLED_ACCOUNT_SUBJECT_PREFIX = "user-disabled-account"
DISABLED_ACCOUNT_PASSWORD = "disabled-password"
DISABLED_ACCOUNT_WRONG_PASSWORD = "disabled-wrong-password"


class DemoTaskPayload(BaseModel):
    """
    示例任务Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar kind: 结构版本的具体类型标识。约束：需符合 ``str`` 注解。默认值：`'demo_task'`。取值语义：用于承载当前对象中的业务状态。
    :vartype kind: str
    :ivar schema_version: 结构模式版本。约束：需符合 ``str`` 注解。默认值：`'1.0'`。取值语义：用于承载当前对象中的业务状态。
    :vartype schema_version: str
    :ivar task_id: ``task_id`` 字段。约束：需符合 ``str`` 注解。默认值：`'task-1'`。取值语义：用于唯一标识对应实体。
    :vartype task_id: str
    """

    model_config = ConfigDict(extra="forbid")

    kind: str = "demo_task"
    schema_version: str = "1.0"
    task_id: str = "task-1"


class RetryFailingTaskHandler(TaskHandler[DemoTaskPayload]):
    """
    重试失败任务处理器类型，用于封装当前模块中的相关行为或状态。
    """

    def __init__(self) -> None:
        """
        初始化重试失败任务处理器。

        :returns: 无返回值。
        :rtype: None
        """

        self.attempt_count = 0

    def handle(self, invocation: TypedTaskInvocation[DemoTaskPayload]) -> None:
        """
        处理处理。

        :param invocation: 任务执行对象。约束：需符合 ``TypedTaskInvocation`` 注解。
        :type invocation: TypedTaskInvocation[DemoTaskPayload]
        :returns: 无返回值。
        :rtype: None
        :raises RuntimeError: 当运行时状态与当前流程要求不一致时抛出。
        """

        _ = invocation
        self.attempt_count += 1
        raise RuntimeError("重试失败")


class ReceiveSequence:
    """
    接收序列类型，用于封装当前模块中的相关行为或状态。
    """

    def __init__(self, messages: list[Message]) -> None:
        """
        初始化接收序列。

        :param messages: 当前步骤使用的消息集合参数。约束：需符合 ``list[Message]`` 注解。
        :type messages: list[Message]
        :returns: 无返回值。
        :rtype: None
        """

        self._messages = list(messages)
        self.call_count = 0

    async def receive(self) -> Message:
        """
        处理接收。

        :returns: 返回当前操作结果。
        :rtype: Message
        """

        self.call_count += 1
        if self._messages:
            return self._messages.pop(0)
        return {
            "type": HTTP_REQUEST_MESSAGE_TYPE,
            "body": b"",
            "more_body": False,
        }


class SendRecorder:
    """
    发送记录器，负责收集运行时记录。
    """

    def __init__(self) -> None:
        """
        初始化发送记录器。

        :returns: 无返回值。
        :rtype: None
        """

        self.messages: list[Message] = []

    async def send(self, message: Message) -> None:
        """
        处理发送。

        :param message: 消息对象或消息文本。约束：需符合 ``Message`` 注解。
        :type message: Message
        :returns: 无返回值。
        :rtype: None
        """

        self.messages.append(message)

    def read_status_code(self) -> int:
        """
        读取状态编码。

        :returns: 返回读取到的对象或状态快照。
        :rtype: int
        """

        return int(self.messages[0]["status"])


class BodyReadingAsgiApp:
    """
    请求体读取ASGI应用类型，用于封装当前模块中的相关行为或状态。
    """

    def __init__(self) -> None:
        """
        初始化请求体读取ASGI应用。

        :returns: 无返回值。
        :rtype: None
        """

        self.invocation_count = 0
        self.received_messages: list[Message] = []

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """
        执行当前可调用对象。

        :param scope: ASGI 作用域对象。约束：需符合 ``Scope`` 注解。
        :type scope: Scope
        :param receive: ASGI 接收函数。约束：需符合 ``Receive`` 注解。
        :type receive: Receive
        :param send: ASGI 发送函数。约束：需符合 ``Send`` 注解。
        :type send: Send
        :returns: 无返回值。
        :rtype: None
        """

        self.invocation_count += 1
        while True:
            message = await receive()
            self.received_messages.append(message)
            if not message.get("more_body", False):
                break
        await send(
            {
                "type": HTTP_RESPONSE_START_MESSAGE_TYPE,
                "status": 200,
                "headers": [],
            }
        )
        await send(
            {
                "type": HTTP_RESPONSE_BODY_MESSAGE_TYPE,
                "body": b"ok",
            }
        )


class PayloadGuardScopeFactory:
    """
    载荷守卫作用域工厂，负责构建目标对象。
    """

    def build(self, *, content_length: bytes | None) -> Scope:
        """
        处理构建。

        :param content_length: 当前步骤使用的内容长度参数。约束：需符合 ``bytes | None`` 注解。
        :type content_length: bytes | None
        :returns: 返回当前操作结果。
        :rtype: Scope
        """

        headers = []
        if content_length is not None:
            headers.append((CONTENT_LENGTH_HEADER_NAME.encode("latin-1"), content_length))
        return {
            "type": HTTP_SCOPE_TYPE,
            "http_version": "1.1",
            "method": POST_METHOD,
            "scheme": "http",
            "path": AUTH_TOKEN_PATH,
            "raw_path": AUTH_TOKEN_PATH.encode("utf-8"),
            "query_string": b"",
            "root_path": "",
            "headers": headers,
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
            "extensions": {},
            "state": {
                "middleware_trace": ["request_scope"],
                "request_scope": RequestScope(
                    request_id=DEFAULT_REQUEST_ID,
                    trace_id=DEFAULT_TRACE_ID,
                    request_time_epoch=1,
                    request_path=AUTH_TOKEN_PATH,
                    request_method=POST_METHOD,
                ),
            },
        }


class PayloadGuardMiddlewareFactory:
    """
    载荷守卫中间件工厂，负责构建目标对象。
    """

    def build(
        self,
        *,
        app: ASGIApp,
        request_limit: int = DEFAULT_SCOPE_LIMIT,
    ) -> PayloadGuardMiddleware:
        """
        处理构建。

        :param app: 当前 FastAPI 或 ASGI 应用实例。约束：需符合 ``ASGIApp`` 注解。
        :type app: ASGIApp
        :param request_limit: 当前步骤使用的请求限制参数。默认值：`DEFAULT_SCOPE_LIMIT`。约束：需符合 ``int`` 注解。
        :type request_limit: int
        :returns: 返回当前操作结果。
        :rtype: PayloadGuardMiddleware
        """

        settings = AppSettingsLoader().load_from_mapping(
            environment=AppEnvironment.TEST,
            overrides={"runtime": {"web": {"max_request_body_bytes": request_limit}}},
        )
        return PayloadGuardMiddleware(
            app=app,
            resource_mount=FakeRuntimeResourceMount(settings=settings),
        )


@dataclass(frozen=True, slots=True)
class FakeRuntimeBundle:
    """
    测试运行时快照。
    """

    settings: ApplicationSettings


class FakeRuntimeResourceMount:
    """
    测试运行时资源挂载点。
    """

    def __init__(self, *, settings: ApplicationSettings) -> None:
        """
        初始化测试运行时资源挂载点。
        """

        self._settings = settings
        self.events: list[SecurityEventEnvelope] = []

    def read_runtime_bundle(self) -> FakeRuntimeBundle:
        """
        读取测试运行时快照。
        """

        return FakeRuntimeBundle(settings=self._settings)

    def emit_security_event(self, event: SecurityEventEnvelope) -> None:
        """
        写入测试安全事件。
        """

        self.events.append(event)


class TestRuntimeBoundary:
    """
    测试运行时边界测试集合，用于组织同一主题下的测试场景。
    """

    def test_token_when_equal_expiry_should_be_expired(self) -> None:
        """
        验证令牌当等于过期点应判定为过期。

        :returns: 无返回值。
        :rtype: None
        """

        principal = AuthenticatedPrincipal(
            subject_id=TOKEN_BOUNDARY_SUBJECT_ID,
            username="tester",
            roles=[AuthRoleKey.ADMIN],
            scopes=[AuthScopeCode.SYSTEM_READ],
        )
        token_service = JwtTokenService(
            AccessTokenPolicy(
                jwt_secret="boundary-secret-2026-with-safe-length",
                jwt_algorithm="HS256",
                access_token_expires_in_seconds=TOKEN_BOUNDARY_ACCESS_EXPIRES_IN_SECONDS,
                refresh_token_expires_in_seconds=TOKEN_BOUNDARY_REFRESH_EXPIRES_IN_SECONDS,
                issuer="boundary",
                audience="client",
                refresh_token_rotation_enabled=True,
            )
        )
        token_issue = token_service.issue_token_pair(
            principal,
            current_epoch=TOKEN_BOUNDARY_ISSUED_AT_EPOCH,
        )

        with pytest.raises(HttpFaultException) as fault:
            token_service.decode_token(
                token_issue.response_payload.access_token,
                expected_use=TokenUse.ACCESS,
                current_epoch=TOKEN_BOUNDARY_EXPIRY_EPOCH,
            )

        assert fault.value.error_code == AuthErrorCode.TOKEN_EXPIRED

    def test_token_when_before_expiry_should_still_be_valid(self) -> None:
        """
        验证令牌当早于过期点应仍然有效。
        """

        principal = AuthenticatedPrincipal(
            subject_id=TOKEN_BOUNDARY_SUBJECT_ID,
            username="tester",
            roles=[AuthRoleKey.ADMIN],
            scopes=[AuthScopeCode.SYSTEM_READ],
        )
        token_service = JwtTokenService(
            AccessTokenPolicy(
                jwt_secret="boundary-secret-2026-with-safe-length",
                jwt_algorithm="HS256",
                access_token_expires_in_seconds=TOKEN_BOUNDARY_ACCESS_EXPIRES_IN_SECONDS,
                refresh_token_expires_in_seconds=TOKEN_BOUNDARY_REFRESH_EXPIRES_IN_SECONDS,
                issuer="boundary",
                audience="client",
                refresh_token_rotation_enabled=True,
            )
        )
        token_issue = token_service.issue_token_pair(
            principal,
            current_epoch=TOKEN_BOUNDARY_ISSUED_AT_EPOCH,
        )
        decoded = token_service.decode_token(
            token_issue.response_payload.access_token,
            expected_use=TokenUse.ACCESS,
            current_epoch=TOKEN_BOUNDARY_BEFORE_EXPIRY_EPOCH,
        )
        assert decoded.subject_id == TOKEN_BOUNDARY_SUBJECT_ID

    def test_memory_cache_ttl_boundary_should_expire_on_limit(self) -> None:
        """
        验证内存缓存TTL边界应过期在限制。

        :returns: 无返回值。
        :rtype: None
        """

        fake_clock = FakeClock()
        cache_store = MemoryCacheStore(timer=fake_clock.now)
        cache_store.set_value("k", "v", 3)
        fake_clock.advance(2.9)
        assert cache_store.get_value("k") == "v"
        fake_clock.advance(0.1)
        assert cache_store.get_value("k") is None

    def test_memory_cache_when_max_entries_is_one_should_evict_old_value(self) -> None:
        """
        验证内存缓存当最大条目是否单个应淘汰旧值。

        :returns: 无返回值。
        :rtype: None
        """

        cache_store = MemoryCacheStore(max_entries=1)
        cache_store.set_value("k1", "v1", 30)
        cache_store.set_value("k2", "v2", 30)

        assert cache_store.get_value("k1") is None
        assert cache_store.get_value("k2") == "v2"

    def test_retry_limit_zero_should_only_execute_once(self) -> None:
        """
        验证重试限制零应仅执行一次。

        :returns: 无返回值。
        :rtype: None
        """

        handler = RetryFailingTaskHandler()
        app = TestAppFactory().create(
            task_bindings=[
                RegisteredTaskBinding(
                    job_kind="demo_task",
                    payload_model=DemoTaskPayload,
                    handler=handler,
                )
            ]
        )
        with TestClient(app):
            with pytest.raises(Exception):
                app.state.container.dispatch_background_job_usecase.execute(
                    TaskDispatchCommand(
                        payload=DemoTaskPayload(),
                        retry_limit=0,
                    )
                )
        assert handler.attempt_count == 1

    def test_loader_when_task_registration_queue_duplicated_should_fail(self) -> None:
        """
        验证加载器当 Funboost 队列重复应失败。
        """

        loader = AppSettingsLoader()

        with pytest.raises(HttpFaultException) as fault:
            loader.load_from_mapping(
                environment=AppEnvironment.TEST,
                overrides={
                    "task_module": {
                        "registrations": [
                            {
                                "envelope_kind": "task_registration_envelope",
                                "schema_version": "1.0",
                                "header": {
                                    "header_kind": "task_registration_header",
                                    "schema_version": "1.0",
                                    "task_name": "demo_task_funboost",
                                    "job_kind": "demo_task_funboost",
                                    "enabled": True,
                                    "backend": "funboost",
                                },
                                "detail": {
                                    "kind": "funboost",
                                    "schema_version": "1.0",
                                    "queue_name": "demo_task_funboost_queue_test",
                                    "exchange_name": "task.direct",
                                    "routing_key": "demo.task.funboost.one",
                                    "broker_kind": "RABBITMQ_COMPLEX_ROUTING",
                                    "retry_limit": 1,
                                    "consumer_worker_count": 1,
                                },
                            },
                            {
                                "envelope_kind": "task_registration_envelope",
                                "schema_version": "1.0",
                                "header": {
                                    "header_kind": "task_registration_header",
                                    "schema_version": "1.0",
                                    "task_name": "demo_task_funboost_2",
                                    "job_kind": "demo_task_funboost_2",
                                    "enabled": True,
                                    "backend": "funboost",
                                },
                                "detail": {
                                    "kind": "funboost",
                                    "schema_version": "1.0",
                                    "queue_name": "demo_task_funboost_queue_test",
                                    "exchange_name": "task.direct",
                                    "routing_key": "demo.task.funboost.two",
                                    "broker_kind": "RABBITMQ_COMPLEX_ROUTING",
                                    "retry_limit": 1,
                                    "consumer_worker_count": 1,
                                },
                            },
                        ]
                    }
                },
            )

        assert "queue_name" in str(fault.value.detail)

    def test_payload_guard_when_content_length_exceeds_limit_should_reject_before_reading_body(
        self,
    ) -> None:
        """
        验证载荷守卫当内容长度超出限制应拒绝之前读取请求体。

        :returns: 无返回值。
        :rtype: None
        """

        downstream_app = BodyReadingAsgiApp()
        middleware = PayloadGuardMiddlewareFactory().build(app=downstream_app)
        receive_sequence = ReceiveSequence(
            [
                {
                    "type": HTTP_REQUEST_MESSAGE_TYPE,
                    "body": b"123456789",
                    "more_body": False,
                }
            ]
        )
        send_recorder = SendRecorder()

        asyncio.run(
            middleware(
                PayloadGuardScopeFactory().build(content_length=b"9"),
                receive_sequence.receive,
                send_recorder.send,
            )
        )

        assert receive_sequence.call_count == 0
        assert downstream_app.invocation_count == 0
        assert send_recorder.read_status_code() == 413

    def test_payload_guard_when_stream_body_equals_limit_should_allow_request(
        self,
    ) -> None:
        """
        验证载荷守卫当流式请求体等于限制应允许请求。

        :returns: 无返回值。
        :rtype: None
        """

        downstream_app = BodyReadingAsgiApp()
        middleware = PayloadGuardMiddlewareFactory().build(app=downstream_app)
        receive_sequence = ReceiveSequence(
            [
                {
                    "type": HTTP_REQUEST_MESSAGE_TYPE,
                    "body": b"1234",
                    "more_body": True,
                },
                {
                    "type": HTTP_REQUEST_MESSAGE_TYPE,
                    "body": b"5678",
                    "more_body": False,
                },
            ]
        )
        send_recorder = SendRecorder()

        asyncio.run(
            middleware(
                PayloadGuardScopeFactory().build(content_length=None),
                receive_sequence.receive,
                send_recorder.send,
            )
        )

        assert downstream_app.invocation_count == 1
        assert receive_sequence.call_count == 2
        assert send_recorder.read_status_code() == 200

    def test_payload_guard_when_stream_body_exceeds_limit_should_reject(self) -> None:
        """
        验证载荷守卫当流式请求体超出限制应拒绝。

        :returns: 无返回值。
        :rtype: None
        """

        downstream_app = BodyReadingAsgiApp()
        middleware = PayloadGuardMiddlewareFactory().build(app=downstream_app)
        receive_sequence = ReceiveSequence(
            [
                {
                    "type": HTTP_REQUEST_MESSAGE_TYPE,
                    "body": b"1234",
                    "more_body": True,
                },
                {
                    "type": HTTP_REQUEST_MESSAGE_TYPE,
                    "body": b"56789",
                    "more_body": False,
                },
            ]
        )
        send_recorder = SendRecorder()

        asyncio.run(
            middleware(
                PayloadGuardScopeFactory().build(content_length=None),
                receive_sequence.receive,
                send_recorder.send,
            )
        )

        assert downstream_app.invocation_count == 1
        assert receive_sequence.call_count == 2
        assert send_recorder.read_status_code() == 413

    def test_payload_guard_when_content_length_is_forged_smaller_should_still_reject(
        self,
    ) -> None:
        """
        验证载荷守卫当内容长度是否伪造更小应仍然拒绝。

        :returns: 无返回值。
        :rtype: None
        """

        downstream_app = BodyReadingAsgiApp()
        middleware = PayloadGuardMiddlewareFactory().build(app=downstream_app)
        receive_sequence = ReceiveSequence(
            [
                {
                    "type": HTTP_REQUEST_MESSAGE_TYPE,
                    "body": b"1234",
                    "more_body": True,
                },
                {
                    "type": HTTP_REQUEST_MESSAGE_TYPE,
                    "body": b"56789",
                    "more_body": False,
                },
            ]
        )
        send_recorder = SendRecorder()

        asyncio.run(
            middleware(
                PayloadGuardScopeFactory().build(content_length=b"1"),
                receive_sequence.receive,
                send_recorder.send,
            )
        )

        assert downstream_app.invocation_count == 1
        assert receive_sequence.call_count == 2
        assert send_recorder.read_status_code() == 413

    def test_refresh_token_when_reused_should_return_reused_error(self) -> None:
        """
        验证令牌当已重用应返回已重用错误。

        :returns: 无返回值。
        :rtype: None
        """

        app = TestAppFactory().create()
        with TestClient(app) as client:
            token_response = client.post(
                AUTH_TOKEN_PATH,
                json={"username": "admin", "password": "admin"},
            )
            refresh_token = token_response.json()[DATA_FIELD][REFRESH_TOKEN_FIELD]
            first_refresh_response = client.post(
                AUTH_REFRESH_PATH,
                json={REFRESH_TOKEN_FIELD: refresh_token},
            )
            first_refresh_payload = first_refresh_response.json()[DATA_FIELD]
            refreshed_access_token = first_refresh_payload[ACCESS_TOKEN_FIELD]
            refreshed_refresh_token = first_refresh_payload[REFRESH_TOKEN_FIELD]
            second_refresh_response = client.post(
                AUTH_REFRESH_PATH,
                json={REFRESH_TOKEN_FIELD: refresh_token},
            )
            revoked_access_response = client.get(
                AUTH_ME_PATH,
                headers={AUTHORIZATION_HEADER: f"{BEARER_PREFIX} {refreshed_access_token}"},
            )
            revoked_refresh_response = client.post(
                AUTH_REFRESH_PATH,
                json={REFRESH_TOKEN_FIELD: refreshed_refresh_token},
            )
            assert first_refresh_response.status_code == 200
            assert second_refresh_response.status_code == 401
            assert (
                second_refresh_response.json()[DATA_FIELD][ERROR_CODE_FIELD]
                == AuthErrorCode.TOKEN_REUSED
            )
            assert revoked_access_response.status_code == 401
            assert (
                revoked_access_response.json()[DATA_FIELD][ERROR_CODE_FIELD]
                == AuthErrorCode.TOKEN_REVOKED
            )
            assert revoked_refresh_response.status_code == 401
            assert (
                revoked_refresh_response.json()[DATA_FIELD][ERROR_CODE_FIELD]
                == AuthErrorCode.TOKEN_REVOKED
            )

    def test_refresh_token_throttle_when_window_elapsed_should_recover(self) -> None:
        """
        验证令牌节流当窗口耗时应恢复。

        :returns: 无返回值。
        :rtype: None
        :raises AssertionError: 当当前步骤检测到异常条件时抛出。
        """

        app = TestAppFactory().create()
        with TestClient(app) as client:
            invalid_refresh_token = "invalid-refresh-token"
            for _ in range(3):
                response = client.post(
                    "/auth/refresh",
                    json={"refresh_token": invalid_refresh_token},
                )
                assert response.status_code == 401

            throttled_response = client.post(
                "/auth/refresh",
                json={"refresh_token": invalid_refresh_token},
            )
            assert throttled_response.status_code == 429

            throttle = app.state.container.resource_mount.get_auth_failure_throttle()
            current_timer = throttle._timer  # noqa: SLF001
            if not callable(current_timer):
                raise AssertionError("频控计时器未正确装配。")
            throttle._timer = lambda: current_timer() + 31  # noqa: SLF001
            recovered_response = client.post(
                "/auth/refresh",
                json={"refresh_token": invalid_refresh_token},
            )
            assert recovered_response.status_code == 401

    def test_auth_token_when_account_disabled_should_match_invalid_password_signal(
        self,
    ) -> None:
        """
        验证禁用账号登录与错误密码应返回一致的外部失败语义。
        """

        app = TestAppFactory().create()
        username = f"{DISABLED_ACCOUNT_USERNAME_PREFIX}-{uuid4()}"
        subject_id = f"{DISABLED_ACCOUNT_SUBJECT_PREFIX}-{uuid4()}"
        with TestClient(app) as client:
            resource_mount = app.state.container.resource_mount
            self._create_disabled_identity(
                resource_mount=resource_mount,
                username=username,
                subject_id=subject_id,
            )
            try:
                disabled_response = client.post(
                    AUTH_TOKEN_PATH,
                    json={
                        "username": username,
                        "password": DISABLED_ACCOUNT_PASSWORD,
                    },
                )
                invalid_password_response = client.post(
                    AUTH_TOKEN_PATH,
                    json={
                        "username": username,
                        "password": DISABLED_ACCOUNT_WRONG_PASSWORD,
                    },
                )
            finally:
                self._delete_identity(
                    resource_mount=resource_mount,
                    username=username,
                )

        assert disabled_response.status_code == 401
        assert invalid_password_response.status_code == 401
        assert disabled_response.json()[DATA_FIELD][ERROR_CODE_FIELD] == str(
            AuthErrorCode.INVALID_CREDENTIALS
        )
        assert (
            disabled_response.json()[DATA_FIELD][ERROR_CODE_FIELD]
            == (invalid_password_response.json()[DATA_FIELD][ERROR_CODE_FIELD])
        )

    def test_loader_when_module_enabled_contains_duplicate_should_fail(self) -> None:
        """
        验证加载器当模块启用包含重复应失败。

        :returns: 无返回值。
        :rtype: None
        """

        loader = AppSettingsLoader()
        with pytest.raises(HttpFaultException) as fault:
            loader.load_from_mapping(
                environment=AppEnvironment.TEST,
                overrides={
                    "app": {
                        "modules": {
                            "enabled": ["health_probe", "health_probe"],
                        }
                    }
                },
            )
        assert "app.modules.enabled 不允许重复" in str(fault.value.detail)

    def test_app_startup_when_module_enabled_contains_unknown_value_should_fail(self) -> None:
        """
        验证应用启动当模块启用包含未知值应失败。

        :returns: 无返回值。
        :rtype: None
        """

        with pytest.raises(ValueError) as fault:
            TestAppFactory().create(
                overrides={
                    "app": {
                        "modules": {
                            "enabled": ["health_probe", UNKNOWN_WEB_MODULE_NAME],
                        }
                    }
                },
            )

        error_message = str(fault.value)
        assert ENABLED_MODULES_CONFIG_PATH in error_message
        assert UNKNOWN_WEB_MODULE_NAME in error_message

    def test_loader_when_module_enabled_contains_unknown_value_should_load(self) -> None:
        """
        验证配置加载器当模块启用包含未知值应交由启动装配边界校验。

        :returns: 无返回值。
        :rtype: None
        """

        loader = AppSettingsLoader()
        settings = loader.load_from_mapping(
            environment=AppEnvironment.TEST,
            overrides={
                "app": {
                    "modules": {
                        "enabled": ["health_probe", UNKNOWN_WEB_MODULE_NAME],
                    }
                }
            },
        )

        assert settings.app.modules.enabled == ["health_probe", UNKNOWN_WEB_MODULE_NAME]

    def test_loader_when_bootstrap_role_binding_scope_empty_should_fail(self) -> None:
        """
        验证加载器当引导角色绑定作用域空值应失败。

        :returns: 无返回值。
        :rtype: None
        """

        loader = AppSettingsLoader()
        with pytest.raises(HttpFaultException) as fault:
            loader.load_from_mapping(
                environment=AppEnvironment.TEST,
                overrides={
                    "auth_module": {
                        "bootstrap_admin": {
                            "enabled": True,
                            "username": "admin",
                            "subject_id": "user-admin",
                            "role_bindings": [
                                {
                                    "kind": "bootstrap_role_binding",
                                    "schema_version": "v1",
                                    "role_key": "admin",
                                    "scope_codes": [],
                                }
                            ],
                        }
                    }
                },
            )
        assert "role_bindings.scope_codes 不能为空" in str(fault.value.detail)

    def test_loader_when_auth_runtime_ttl_is_zero_should_fail(self) -> None:
        """
        验证加载器当鉴权运行时TTL是否零应失败。

        :returns: 无返回值。
        :rtype: None
        """

        loader = AppSettingsLoader()
        with pytest.raises(HttpFaultException) as fault:
            loader.load_from_mapping(
                environment=AppEnvironment.TEST,
                overrides={
                    "runtime": {
                        "auth": {
                            "access_token_expires_in_seconds": 0,
                        }
                    }
                },
            )
        assert "runtime.auth.access_token_expires_in_seconds 必须大于 0" in str(fault.value.detail)

    def test_loader_when_database_pool_size_is_zero_should_fail(self) -> None:
        """
        验证加载器当数据库连接池大小是否零应失败。

        :returns: 无返回值。
        :rtype: None
        """

        loader = AppSettingsLoader()
        with pytest.raises(HttpFaultException) as fault:
            loader.load_from_mapping(
                environment=AppEnvironment.TEST,
                overrides={
                    "runtime": {
                        "database": {
                            "pool_size": 0,
                        }
                    }
                },
            )
        assert "runtime.database.pool_size 必须大于 0" in str(fault.value.detail)

    def test_database_pool_when_exhausted_should_timeout_and_release(
        self,
        integration_database: str,
    ) -> None:
        """验证真实 PostgreSQL 连接池耗尽后超时，释放后可重新获取。"""

        engine = create_engine(
            integration_database,
            pool_size=1,
            max_overflow=0,
            pool_timeout=DATABASE_POOL_EXHAUSTION_TIMEOUT_SECONDS,
        )
        first_connection = engine.connect()
        try:
            with pytest.raises(SqlAlchemyTimeoutError):
                engine.connect()
        finally:
            first_connection.close()

        try:
            with engine.connect() as recovered_connection:
                assert recovered_connection.closed is False
        finally:
            engine.dispose()

    def _create_disabled_identity(
        self,
        *,
        resource_mount,
        username: str,
        subject_id: str,
    ) -> None:
        """
        创建禁用身份。
        """

        unit_of_work = resource_mount.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            session.add(
                AuthUserOrmModel(
                    user_id=uuid4(),
                    subject_id=subject_id,
                    username=username,
                    password_hash=resource_mount.get_password_hasher().hash_password(
                        DISABLED_ACCOUNT_PASSWORD
                    ),
                    is_active=False,
                )
            )
            unit_of_work.commit()
        except Exception:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def _delete_identity(self, *, resource_mount, username: str) -> None:
        """
        删除测试身份。
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

    def test_module_settings_parser_should_return_header_and_detail_envelope(self) -> None:
        """
        验证模块配置解析器应返回 header 与 detail 信封。
        """

        envelope = ModuleSettingsParser().parse_section(
            file_path=AppSettingsLoader()._config_root / "app_test.toml",  # noqa: SLF001
            file_content={"app": {"environment": "test"}},
        )

        assert isinstance(envelope, ModuleSettingsSectionEnvelope)
        assert isinstance(envelope.detail, AppSettingsSectionDetail)
        assert envelope.header.section_name == "app"

    def test_runtime_settings_parser_should_return_header_and_detail_envelope(self) -> None:
        """
        验证运行时配置解析器应返回 header 与 detail 信封。
        """

        envelope = RuntimeSettingsParser().parse_section(
            file_path=Path("runtime") / "web_runtime" / "web_runtime_test.toml",
            file_content={"runtime": {"api_prefix": "/api/v1"}},
        )

        assert isinstance(envelope, RuntimeSettingsSectionEnvelope)
        assert envelope.detail.runtime_key == "web"
        assert envelope.header.section_name == "web"
