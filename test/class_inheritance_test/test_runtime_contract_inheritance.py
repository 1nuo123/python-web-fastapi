"""
测试运行时契约继承测试模块。
"""

from __future__ import annotations

from typing import cast

from pydantic import BaseModel, ConfigDict
from redis import Redis
from sqlalchemy.orm import Session

from src.core.cache_contract.cache_store_contract import CacheStore
from src.core.persistence_contract.repository_contract import Repository
from src.core.persistence_contract.unit_of_work_contract import UnitOfWork
from src.core.task_contract.message_bus_contract import (
    MessageBus,
    TaskMessageEnvelope,
    TaskMessageHeader,
    TaskMessagePayload,
)
from src.core.task_contract.task_dispatcher_contract import TaskDispatcher
from src.core.task_contract.task_handler_contract import TaskHandler
from src.core.task_contract.task_invocation_contract import TypedTaskInvocation
from src.infrastructure.cache.memory_cache_store import MemoryCacheStore
from src.infrastructure.cache.redis_cache_store import RedisCacheStore
from src.infrastructure.persistence.repository_impl.admin_identity_repository_impl import (
    AdminIdentityRepositoryImpl,
)
from src.infrastructure.persistence.repository_impl.auth_identity_repository_impl import (
    AuthIdentityRepositoryImpl,
)
from src.infrastructure.persistence.repository_impl.log_record_repository_impl import (
    LogRecordRepositoryImpl,
)
from src.infrastructure.persistence.repository_impl.refresh_token_repository_impl import (
    RefreshTokenRepositoryImpl,
)
from src.infrastructure.persistence.repository_impl.runtime_state_repository_impl import (
    RuntimeStateRepositoryImpl,
)
from src.infrastructure.persistence.repository_impl.security_ip_block_repository import (
    SecurityIpBlockRepository,
)
from src.infrastructure.persistence.repository_impl.task_execution_outbox_repository_impl import (
    TaskExecutionOutboxRepositoryImpl,
)
from src.infrastructure.persistence.repository_impl.task_execution_record_repository_impl import (
    TaskExecutionRecordRepositoryImpl,
)
from src.infrastructure.persistence.sqlalchemy_session_factory import SqlAlchemyUnitOfWork
from src.infrastructure.task.failed_task_recorder import FailedTaskRecorder
from src.infrastructure.task.local_message_bus import LocalMessageBus
from src.infrastructure.task.local_task_dispatcher import LocalTaskDispatcher
from src.infrastructure.task.task_registration_registry import TaskRegistrationRegistry
from src.infrastructure.task.task_worker_supervisor import TaskWorkerSupervisor
from src.infrastructure.testing.task_execution_test_support import (
    TaskExecutionStoreTestFactory,
)

EXPECTED_REPOSITORY_IMPLEMENTATION_COUNT = 7
SELECT_ONE_STATEMENT_TEXT = "SELECT 1"


class DemoTaskPayload(BaseModel):
    """
    示例任务载荷模型。
    """

    model_config = ConfigDict(extra="forbid")

    task_id: str


class FakeRedisClient:
    """
    模拟Redis客户端类型，用于封装当前模块中的相关行为或状态。
    """

    def __init__(self) -> None:
        """
        初始化模拟Redis客户端。

        :returns: 无返回值。
        :rtype: None
        """

        self.closed = False
        self._values: dict[str, bytes] = {}

    def ping(self) -> bool:
        """
        处理探活。

        :returns: 返回布尔判断结果。
        :rtype: bool
        """

        return True

    def get(self, key: str) -> bytes | None:
        """
        处理获取。

        :param key: 缓存键。约束：需符合 ``str`` 注解。
        :type key: str
        :returns: 返回当前操作结果。
        :rtype: bytes | None
        """

        return self._values.get(key)

    def set(self, name: str, value: str, ex: int) -> bool:
        """
        处理设置。

        :param name: 当前步骤使用的名称参数。约束：需符合 ``str`` 注解。
        :type name: str
        :param value: 当前流程要写入或比较的值。约束：需符合 ``str`` 注解。
        :type value: str
        :param ex: 当前步骤使用的ex参数。约束：需符合 ``int`` 注解。
        :type ex: int
        :returns: 返回布尔判断结果。
        :rtype: bool
        """

        self._values[name] = value.encode("utf-8")
        return ex >= 0

    def delete(self, key: str) -> int:
        """
        处理删除。

        :param key: 缓存键。约束：需符合 ``str`` 注解。
        :type key: str
        :returns: 返回当前操作结果。
        :rtype: int
        """

        return 1 if self._values.pop(key, None) is not None else 0

    def close(self) -> None:
        """
        处理关闭。

        :returns: 无返回值。
        :rtype: None
        """

        self.closed = True


class RecordingOrmSession:
    """
    记录ORM会话类型，用于封装当前模块中的相关行为或状态。
    """

    def __init__(self) -> None:
        """
        初始化记录ORM会话。

        :returns: 无返回值。
        :rtype: None
        """

        self.executed_statements: list[str] = []

    def execute(self, statement) -> None:
        """
        执行当前主流程。

        :param statement: 当前步骤使用的声明参数。
        :type statement: Any
        :returns: 无返回值。
        :rtype: None
        """

        self.executed_statements.append(str(statement))


class RecordingSqlAlchemySession:
    """
    记录SQLAlchemy会话类型，用于封装当前模块中的相关行为或状态。
    """

    def __init__(self) -> None:
        """
        初始化记录SQLAlchemy会话。

        :returns: 无返回值。
        :rtype: None
        """

        self.committed = False
        self.flushed = False
        self.rolled_back = False
        self.closed = False

    def commit(self) -> None:
        """
        处理提交。

        :returns: 无返回值。
        :rtype: None
        """

        self.committed = True

    def flush(self) -> None:
        """
        处理刷新。

        :returns: 无返回值。
        :rtype: None
        """

        self.flushed = True

    def rollback(self) -> None:
        """
        处理回滚。

        :returns: 无返回值。
        :rtype: None
        """

        self.rolled_back = True

    def close(self) -> None:
        """
        处理关闭。

        :returns: 无返回值。
        :rtype: None
        """

        self.closed = True


class RecordingTaskHandler(TaskHandler[DemoTaskPayload]):
    """
    记录任务处理器类型，用于封装当前模块中的相关行为或状态。
    """

    def __init__(self) -> None:
        """
        初始化记录任务处理器。

        :returns: 无返回值。
        :rtype: None
        """

        self.handled_message_ids: list[str] = []

    def handle(self, invocation: TypedTaskInvocation[DemoTaskPayload]) -> None:
        """
        处理处理。

        :param invocation: 任务执行对象。约束：需符合 ``TypedTaskInvocation`` 注解。
        :type invocation: TypedTaskInvocation[DemoTaskPayload]
        :returns: 无返回值。
        :rtype: None
        """

        self.handled_message_ids.append(invocation.message.header.message_id)


class TestRuntimeContractInheritance:
    """
    测试运行时契约继承测试集合，用于组织同一主题下的测试场景。
    """

    def test_memory_cache_store_should_preserve_cache_store_contract(self) -> None:
        """
        验证内存缓存存储应保持缓存存储契约。

        :returns: 无返回值。
        :rtype: None
        """

        cache_store: CacheStore = MemoryCacheStore(max_entries=2)
        try:
            cache_store.set_value("token", "abc", 5)
            assert cache_store.get_value("token") == "abc"
            cache_store.delete_value("token")
            assert cache_store.get_value("token") is None
        finally:
            cache_store.close()

    def test_redis_cache_store_should_preserve_cache_store_contract(self) -> None:
        """
        验证Redis缓存存储应保持缓存存储契约。

        :returns: 无返回值。
        :rtype: None
        """

        fake_redis_client = FakeRedisClient()
        redis_cache_store = RedisCacheStore(cast(Redis, fake_redis_client))
        cache_store: CacheStore = redis_cache_store
        try:
            cache_store.set_value("token", "abc", 10)
            assert cache_store.get_value("token") == "abc"
            cache_store.delete_value("token")
            assert cache_store.get_value("token") is None
        finally:
            cache_store.close()
            fake_redis_client.close()
        assert fake_redis_client.closed is True

    def test_local_message_bus_should_preserve_message_bus_contract(self) -> None:
        """
        验证本地消息总线应保持消息总线契约。

        :returns: 无返回值。
        :rtype: None
        """

        local_message_bus = LocalMessageBus()
        message_bus: MessageBus = local_message_bus

        message_bus.publish(self._build_task_message(message_id="task-bus-1"))

        assert local_message_bus.list_messages()[0].header.message_id == "task-bus-1"

    def test_local_task_dispatcher_should_preserve_task_dispatcher_contract(self) -> None:
        """
        验证本地任务分发器应保持任务分发器契约。

        :returns: 无返回值。
        :rtype: None
        """

        local_message_bus = LocalMessageBus()
        worker_supervisor = TaskWorkerSupervisor()
        failed_task_recorder = FailedTaskRecorder()
        task_handler = RecordingTaskHandler()
        from src.core.task_contract.task_registration_contract import TaskRegistrationEnvelope

        registration_registry = TaskRegistrationRegistry(
            registrations=[
                TaskRegistrationEnvelope.model_validate(
                    {
                        "envelope_kind": "task_registration_envelope",
                        "schema_version": "1.0",
                        "header": {
                            "header_kind": "task_registration_header",
                            "schema_version": "1.0",
                            "task_name": "demo_task",
                            "job_kind": "demo_task",
                            "enabled": True,
                            "backend": "local",
                        },
                        "detail": {
                            "kind": "local",
                            "schema_version": "1.0",
                            "retry_limit": 1,
                        },
                    }
                )
            ]
        )
        worker_supervisor.register_handler(
            job_kind="demo_task",
            payload_model=DemoTaskPayload,
            handler=task_handler,
        )
        for binding in worker_supervisor.list_bindings():
            registration_registry.register_binding(binding)
        test_context = TaskExecutionStoreTestFactory().create()
        dispatcher: TaskDispatcher = LocalTaskDispatcher(
            message_bus=local_message_bus,
            registration_registry=registration_registry,
            failed_task_recorder=failed_task_recorder,
            task_execution_store=test_context.store,
            worker_enabled=True,
            inline_execute_enabled=True,
        )

        try:
            result = dispatcher.dispatch(self._build_task_message())
            assert result.dispatched is True
            assert task_handler.handled_message_ids == ["task-1"]
        finally:
            dispatcher.shutdown()
            test_context.close()

    def test_runtime_state_repository_impl_should_preserve_repository_contract(self) -> None:
        """
        验证运行时状态仓储实现应保持仓储契约。

        :returns: 无返回值。
        :rtype: None
        """

        orm_session = RecordingOrmSession()
        repository: Repository = RuntimeStateRepositoryImpl(cast(Session, orm_session))

        assert repository.ping() is True
        assert orm_session.executed_statements == [SELECT_ONE_STATEMENT_TEXT]

    def test_main_repository_impls_should_preserve_repository_contract(self) -> None:
        """
        验证主要仓储实现统一继承仓储契约。
        """

        repository_types: tuple[type[Repository], ...] = (
            AdminIdentityRepositoryImpl,
            AuthIdentityRepositoryImpl,
            LogRecordRepositoryImpl,
            RefreshTokenRepositoryImpl,
            SecurityIpBlockRepository,
            TaskExecutionOutboxRepositoryImpl,
            TaskExecutionRecordRepositoryImpl,
        )

        assert len(repository_types) == EXPECTED_REPOSITORY_IMPLEMENTATION_COUNT
        assert all(issubclass(repository_type, Repository) for repository_type in repository_types)

    def test_sqlalchemy_unit_of_work_should_preserve_unit_of_work_contract(self) -> None:
        """
        验证SQLAlchemy单元工作应保持单元工作契约。

        :returns: 无返回值。
        :rtype: None
        """

        orm_session = RecordingSqlAlchemySession()
        unit_of_work: UnitOfWork = SqlAlchemyUnitOfWork(cast(Session, orm_session))

        assert unit_of_work.get_session() is orm_session
        unit_of_work.commit()
        unit_of_work.flush()
        unit_of_work.rollback()
        unit_of_work.dispose()

        assert orm_session.committed is True
        assert orm_session.flushed is True
        assert orm_session.rolled_back is True
        assert orm_session.closed is True

    def _build_task_message(self, *, message_id: str = "task-1") -> TaskMessageEnvelope:
        """
        构建任务消息。

        :param message_id: ``message_id`` 对应的实体标识。默认值：`'task-1'`。约束：需符合 ``str`` 注解。
        :type message_id: str
        :returns: 返回当前操作结果。
        :rtype: TaskMessageEnvelope
        """

        return TaskMessageEnvelope(
            header=TaskMessageHeader(
                message_id=message_id,
                created_at_epoch=1,
            ),
            payload=TaskMessagePayload(
                job_kind="demo_task",
                deduplication_key=f"dedupe-{message_id}",
                retry_limit=1,
                payload_kind="DemoTaskPayload",
                payload_json='{"task_id":"1"}',
            ),
        )
