"""
测试运行时异常测试模块。
"""

from __future__ import annotations

from http import HTTPStatus
from typing import NoReturn, cast

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict
from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.api.testing.test_app_factory import TestAppFactory
from src.core.auth_contract.auth_throttle_state_contract import AuthThrottleStatePayload
from src.core.cache_contract.cache_namespace_contract import CacheNamespace
from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.task_contract.task_handler_contract import TaskHandler
from src.core.task_contract.task_invocation_contract import TypedTaskInvocation
from src.infrastructure.cache.cache_key_builder import CacheKeyBuilder
from src.infrastructure.cache.cache_payload_codec import CachePayloadCodec
from src.infrastructure.cache.cache_service import (
    CacheDeleteRequest,
    CacheIncrementRequest,
    CacheReadRequest,
    CacheService,
    CacheWriteRequest,
)
from src.infrastructure.cache.redis_cache_store import RedisCacheStore
from src.infrastructure.persistence.sqlalchemy_engine_factory import (
    SqlAlchemyEngineFactory,
)
from src.infrastructure.settings.app_settings_loader import (
    AppSettingsLoader,
)
from src.infrastructure.settings.application_settings import (
    AppEnvironment,
)
from src.infrastructure.task.task_registration_registry import RegisteredTaskBinding
from src.infrastructure.testing.cache_policy_test_support import CachePolicyTestFactory
from src.infrastructure.testing.fake_cache_store import (
    FakeCacheStore,
    UnavailableCacheStore,
)

AUTHORIZATION_HEADER = "Authorization"
AUTH_BINDING_REPOSITORY_FAILURE_MESSAGE = "模拟认证主体仓储故障"
AUTH_ME_PATH = "/auth/me"
AUTH_TOKEN_PATH = "/auth/token"
BEARER_PREFIX = "Bearer"
DATA_FIELD = "data"
ERROR_CODE_FIELD = "error_code"
DATABASE_CONNECTION_FAILURE_MESSAGE = "模拟数据库连接失败。"
REDIS_UNAVAILABLE_MESSAGE = "模拟 Redis 不可用。"


class DatabaseConnectionFailureEngine:
    """提供不触发真实网络连接的数据库失败替身。"""

    def connect(self) -> NoReturn:
        """稳定抛出 SQLAlchemy 连接异常。"""

        raise SQLAlchemyError(DATABASE_CONNECTION_FAILURE_MESSAGE)


class UnavailableRedisClient:
    """提供不触发真实网络连接的 Redis 失败替身。"""

    def __call__(self) -> UnavailableRedisClient:
        """作为缓存客户端工厂返回自身。"""

        return self

    def ping(self) -> NoReturn:
        """稳定抛出 Redis 连接异常。"""

        raise RedisConnectionError(REDIS_UNAVAILABLE_MESSAGE)


ACCESS_TOKEN_FIELD = "access_token"
EXCEPTION_CACHE_KEY_PREFIX = "exception_cache"
EXCEPTION_CACHE_TTL_SECONDS = 30
EXCEPTION_CACHE_KEY_DIGEST = "exception-digest"


class DemoTaskPayload(BaseModel):
    """
    示例任务载荷模型。
    """

    model_config = ConfigDict(extra="forbid")

    kind: str = "demo_task"
    schema_version: str = "1.0"
    task_id: str = "task-1"


class FailingTaskHandler(TaskHandler[DemoTaskPayload]):
    """
    失败任务处理器类型，用于封装当前模块中的相关行为或状态。
    """

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
        raise RuntimeError("任务执行异常")


class FailingAuthIdentityRepositoryFactory:
    """
    失败鉴权身份仓储工厂，用于模拟认证绑定阶段的基础设施故障。
    """

    def create_repository(self, session: Session) -> NoReturn:
        """
        创建失败仓储。

        :param session: 当前数据库会话。
        :type session: Session
        :returns: 无返回值。
        :rtype: NoReturn
        :raises RuntimeError: 始终抛出，用于模拟仓储故障。
        """

        _ = session
        raise RuntimeError(AUTH_BINDING_REPOSITORY_FAILURE_MESSAGE)


class TestRuntimeException:
    """
    测试运行时异常测试集合，用于组织同一主题下的测试场景。
    """

    def test_invalid_config_should_raise_http_fault(self) -> None:
        """
        验证无效配置应抛出HTTP故障。

        :returns: 无返回值。
        :rtype: None
        """

        loader = AppSettingsLoader()
        with pytest.raises(HttpFaultException) as fault:
            loader.load_from_mapping(
                environment=AppEnvironment.TEST,
                overrides={"runtime": {"web": {"max_request_body_bytes": "bad"}}},
            )
        assert fault.value.error_code == "system.config.invalid"

    def test_jwt_invalid_should_return_http_fault(self) -> None:
        """
        验证JWT无效应返回HTTP故障。

        :returns: 无返回值。
        :rtype: None
        """

        app = TestAppFactory().create()
        with TestClient(app) as client:
            response = client.get(
                "/auth/me",
                headers={"Authorization": "Bearer invalid"},
            )
            assert response.status_code == 401

    def test_auth_binding_when_repository_failure_should_return_unexpected_fault(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        验证认证绑定当仓储故障时不应伪装为令牌无效。

        :param monkeypatch: pytest 动态替换工具。
        :type monkeypatch: pytest.MonkeyPatch
        :returns: 无返回值。
        :rtype: None
        """

        app = TestAppFactory().create()
        with TestClient(app, raise_server_exceptions=False) as client:
            token_response = client.post(
                AUTH_TOKEN_PATH,
                json={"username": "admin", "password": "admin"},
            )
            access_token = token_response.json()[DATA_FIELD][ACCESS_TOKEN_FIELD]
            monkeypatch.setattr(
                app.state.container.resource_mount,
                "create_auth_identity_repository",
                FailingAuthIdentityRepositoryFactory().create_repository,
            )

            response = client.get(
                AUTH_ME_PATH,
                headers={AUTHORIZATION_HEADER: f"{BEARER_PREFIX} {access_token}"},
            )

            assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
            assert response.json()[DATA_FIELD][ERROR_CODE_FIELD] == str(
                CoreErrorCode.INTERNAL_UNEXPECTED
            )

    def test_database_connection_failure_should_raise_http_fault(self) -> None:
        """
        验证数据库连接失败应抛出HTTP故障。

        :returns: 无返回值。
        :rtype: None
        """

        engine = cast(Engine, DatabaseConnectionFailureEngine())
        with pytest.raises(HttpFaultException) as fault:
            SqlAlchemyEngineFactory().validate(engine)
        assert fault.value.error_code == "system.database.unavailable"

    def test_cache_backend_failure_should_raise_http_fault(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        验证缓存后端失败应抛出HTTP故障。

        :returns: 无返回值。
        :rtype: None
        """

        unavailable_client = cast(Redis, UnavailableRedisClient())
        cache_store = RedisCacheStore(unavailable_client)
        with pytest.raises(HttpFaultException) as fault:
            cache_store.assert_available()
        assert fault.value.error_code == "system.cache.unavailable"

    def test_loader_when_cache_backend_detail_invalid_should_raise_http_fault(self) -> None:
        """
        验证加载器当缓存后端详情无效应抛出HTTP故障。

        :returns: 无返回值。
        :rtype: None
        """

        loader = AppSettingsLoader()
        with pytest.raises(HttpFaultException) as fault:
            loader.load_from_mapping(
                environment=AppEnvironment.TEST,
                overrides={
                    "runtime": {
                        "redis_resource": {
                            "header": {"enabled": True},
                            "detail": {"connect_timeout_seconds": 0},
                        },
                        "cache": {
                            "backend": "redis",
                            "backend_detail": {
                                "kind": "redis_cache_backend",
                                "schema_version": "1.0",
                            },
                        },
                    }
                },
            )
        assert "connect_timeout_seconds" in str(fault.value.detail)

    def test_cache_service_when_payload_corrupted_should_clear_and_return_miss(self) -> None:
        """
        验证缓存服务当载荷损坏应清理与返回未命中。

        :returns: 无返回值。
        :rtype: None
        """

        cache_key_builder = CacheKeyBuilder(key_prefix=EXCEPTION_CACHE_KEY_PREFIX)
        cache_service = CacheService(
            cache_store=FakeCacheStore(),
            key_builder=cache_key_builder,
            payload_codec=CachePayloadCodec(),
            policy_resolver=CachePolicyTestFactory().build_resolver(
                runtime_default_ttl_seconds=EXCEPTION_CACHE_TTL_SECONDS,
            ),
            default_ttl_seconds=EXCEPTION_CACHE_TTL_SECONDS,
        )
        cache_key = cache_key_builder.build(
            namespace=CacheNamespace.AUTH_THROTTLE,
            key_parts=["refresh_access_token", EXCEPTION_CACHE_KEY_DIGEST],
        )
        cache_service._cache_store.set_value(  # noqa: SLF001
            cache_key,
            "{bad-json}",
            EXCEPTION_CACHE_TTL_SECONDS,
        )

        read_result = cache_service.read_payload(
            CacheReadRequest(
                namespace=CacheNamespace.AUTH_THROTTLE,
                key_parts=["refresh_access_token", EXCEPTION_CACHE_KEY_DIGEST],
                payload_type=AuthThrottleStatePayload,
            )
        )

        assert read_result.hit is False
        assert read_result.payload is None
        assert cache_service._cache_store.get_value(cache_key) is None  # noqa: SLF001

    def test_cache_service_when_fail_closed_cache_unavailable_should_raise(self) -> None:
        """
        验证失败关闭策略遇到缓存不可用时应继续抛出异常。

        :returns: 无返回值。
        :rtype: None
        """

        cache_service = self._build_unavailable_cache_service()

        with pytest.raises(HttpFaultException) as read_fault:
            cache_service.read_payload(
                CacheReadRequest(
                    namespace=CacheNamespace.AUTH_THROTTLE,
                    key_parts=["refresh_access_token", EXCEPTION_CACHE_KEY_DIGEST],
                    payload_type=AuthThrottleStatePayload,
                )
            )
        with pytest.raises(HttpFaultException) as write_fault:
            cache_service.write_payload(
                CacheWriteRequest(
                    namespace=CacheNamespace.AUTH_THROTTLE,
                    key_parts=["refresh_access_token", EXCEPTION_CACHE_KEY_DIGEST],
                    payload=AuthThrottleStatePayload(
                        failure_count=1,
                        locked_until_epoch=None,
                    ),
                )
            )
        with pytest.raises(HttpFaultException) as delete_fault:
            cache_service.delete_payload(
                CacheDeleteRequest(
                    namespace=CacheNamespace.AUTH_THROTTLE,
                    key_parts=["refresh_access_token", EXCEPTION_CACHE_KEY_DIGEST],
                )
            )

        assert read_fault.value.error_code == CoreErrorCode.CACHE_UNAVAILABLE
        assert write_fault.value.error_code == CoreErrorCode.CACHE_UNAVAILABLE
        assert delete_fault.value.error_code == CoreErrorCode.CACHE_UNAVAILABLE

        with pytest.raises(HttpFaultException) as increment_fault:
            cache_service.increment_counter(
                CacheIncrementRequest(
                    namespace=CacheNamespace.AUTH_THROTTLE,
                    key_parts=["refresh_access_token", EXCEPTION_CACHE_KEY_DIGEST],
                )
            )

        assert increment_fault.value.error_code == CoreErrorCode.CACHE_UNAVAILABLE

    def test_cache_service_when_fail_open_cache_unavailable_should_return_miss(
        self,
    ) -> None:
        """
        验证失败开放策略遇到缓存不可用时应按未命中处理。

        :returns: 无返回值。
        :rtype: None
        """

        cache_service = self._build_unavailable_cache_service()

        read_result = cache_service.read_payload(
            CacheReadRequest(
                namespace=CacheNamespace.QUERY_RESULT,
                key_parts=["system_overview", EXCEPTION_CACHE_KEY_DIGEST],
                payload_type=AuthThrottleStatePayload,
            )
        )
        cache_service.write_payload(
            CacheWriteRequest(
                namespace=CacheNamespace.QUERY_RESULT,
                key_parts=["system_overview", EXCEPTION_CACHE_KEY_DIGEST],
                payload=AuthThrottleStatePayload(
                    failure_count=1,
                    locked_until_epoch=None,
                ),
            )
        )
        cache_service.delete_payload(
            CacheDeleteRequest(
                namespace=CacheNamespace.QUERY_RESULT,
                key_parts=["system_overview", EXCEPTION_CACHE_KEY_DIGEST],
            )
        )
        count = cache_service.increment_counter(
            CacheIncrementRequest(
                namespace=CacheNamespace.QUERY_RESULT,
                key_parts=["system_overview", EXCEPTION_CACHE_KEY_DIGEST],
            )
        )

        assert read_result.hit is False
        assert read_result.payload is None
        assert count == 0

    def test_task_failure_should_raise_http_fault(self) -> None:
        """
        验证任务失败应抛出HTTP故障。

        :returns: 无返回值。
        :rtype: None
        """

        app = TestAppFactory().create(
            task_bindings=[
                RegisteredTaskBinding(
                    job_kind="demo_task",
                    payload_model=self._build_task_payload_model(),
                    handler=FailingTaskHandler(),
                )
            ]
        )
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            with pytest.raises(HttpFaultException) as fault:
                app.state.container.dispatch_background_job_usecase.execute(
                    self._build_task_command()
                )
            assert fault.value.error_code == "system.task.failed"
            records = resource_mount.get_failed_task_recorder().list_records()
            assert len(records) == 1
            assert records[0].backend.value == "local"

    def test_loader_when_funboost_backend_without_rabbitmq_should_fail(self) -> None:
        """
        验证加载器当 Funboost 任务后端未配 RabbitMQ 应失败。
        """

        loader = AppSettingsLoader()

        with pytest.raises(HttpFaultException) as fault:
            loader.load_from_mapping(
                environment=AppEnvironment.TEST,
                overrides={
                    "runtime": {
                        "message": {
                            "backend": "local",
                            "backend_detail": {
                                "kind": "local",
                                "schema_version": "1.0",
                            },
                        },
                        "task": {
                            "backend": "funboost",
                            "worker_enabled": False,
                            "backend_detail": {
                                "kind": "funboost",
                                "schema_version": "1.0",
                                "broker_kind": "RABBITMQ_COMPLEX_ROUTING",
                            },
                        },
                    }
                },
            )

        assert "runtime.message.backend_detail" in str(fault.value.detail)

    def test_refresh_when_token_revoked_should_return_http_fault(self) -> None:
        """
        验证当令牌已撤销应返回HTTP故障。

        :returns: 无返回值。
        :rtype: None
        """

        app = TestAppFactory().create()
        with TestClient(app) as client:
            token_response = client.post(
                "/auth/token",
                json={"username": "admin", "password": "admin"},
            )
            refresh_token = token_response.json()["data"]["refresh_token"]
            revoke_response = client.post(
                "/auth/revoke",
                json={"refresh_token": refresh_token},
            )
            refresh_response = client.post(
                "/auth/refresh",
                json={"refresh_token": refresh_token},
            )
            assert revoke_response.status_code == 200
            assert refresh_response.status_code == 401
            assert refresh_response.json()["data"]["error_code"] == "auth.token.revoked"

    def test_issue_access_token_when_failure_limit_reached_should_return_429(self) -> None:
        """
        验证访问令牌当失败限制达到应返回429。

        :returns: 无返回值。
        :rtype: None
        """

        app = TestAppFactory().create()
        with TestClient(app) as client:
            for _ in range(3):
                response = client.post(
                    "/auth/token",
                    json={"username": "admin", "password": "wrong-password"},
                )
                assert response.status_code == 401
            throttled_response = client.post(
                "/auth/token",
                json={"username": "admin", "password": "wrong-password"},
            )
            assert throttled_response.status_code == 429
            assert throttled_response.json()["data"]["error_code"] == "auth.request.throttled"

    def _build_task_command(self):
        """
        构建任务命令。

        :returns: 返回当前操作结果。
        :rtype: Any
        """

        from pydantic import BaseModel, ConfigDict

        from src.application.dispatch_background_job_usecase import TaskDispatchCommand

        class DemoTaskPayload(BaseModel):
            model_config = ConfigDict(extra="forbid")

            kind: str = "demo_task"
            schema_version: str = "1.0"
            task_id: str = "task-1"

        return TaskDispatchCommand(payload=DemoTaskPayload())

    def _build_task_payload_model(self):
        """
        构建任务载荷模型类型。
        """

        from pydantic import BaseModel, ConfigDict

        class DemoTaskPayload(BaseModel):
            model_config = ConfigDict(extra="forbid")

            kind: str = "demo_task"
            schema_version: str = "1.0"
            task_id: str = "task-1"

        return DemoTaskPayload

    def _build_unavailable_cache_service(self) -> CacheService:
        """
        构建缓存不可用的缓存服务。

        :returns: 返回缓存服务。
        :rtype: CacheService
        """

        return CacheService(
            cache_store=UnavailableCacheStore(),
            key_builder=CacheKeyBuilder(key_prefix=EXCEPTION_CACHE_KEY_PREFIX),
            payload_codec=CachePayloadCodec(),
            policy_resolver=CachePolicyTestFactory().build_resolver(
                runtime_default_ttl_seconds=EXCEPTION_CACHE_TTL_SECONDS,
            ),
            default_ttl_seconds=EXCEPTION_CACHE_TTL_SECONDS,
        )
