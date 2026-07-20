"""
Funboost 任务分发器单元测试模块。
"""

from __future__ import annotations

import atexit
from dataclasses import dataclass, field
from typing import cast

import pytest

from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.task_contract.message_bus_contract import (
    TaskMessageEnvelope,
    TaskMessageHeader,
    TaskMessagePayload,
)
from src.core.task_contract.task_dispatcher_contract import TaskFailureStage
from src.core.task_contract.task_execution_record_contract import TaskExecutionStage
from src.core.task_contract.task_registration_contract import (
    FunboostTaskRegistrationDetail,
    TaskRegistrationEnvelope,
)
from src.core.task_contract.task_runtime_contract import (
    FunboostTaskBackendDetail,
    RabbitMqMessageBackendDetail,
    TaskBackend,
)
from src.infrastructure.task.bounded_funboost_rabbitmq_consumer import (
    BoundedFunboostRabbitMqConsumer,
)
from src.infrastructure.task.confirmed_funboost_rabbitmq_publisher import (
    ConfirmedFunboostRabbitMqPublisher,
)
from src.infrastructure.task.failed_task_recorder import (
    FailedTaskRecorder,
    TaskFailureRecord,
)
from src.infrastructure.task.funboost_task_bootstrapper import (
    FUNBOOST_FAILURE_RECORD_MISSING_LOG_MESSAGE,
    FUNBOOST_RUN_STATUS_FINISH,
    FunboostTaskBootstrapper,
)
from src.infrastructure.task.funboost_task_dispatcher import FunboostTaskDispatcher
from src.infrastructure.task.managed_funboost_thread_pool import (
    ManagedFunboostThreadPool,
)
from src.infrastructure.task.task_execution_store import TaskExecutionStore
from src.infrastructure.task.task_registration_registry import TaskRegistrationRegistry
from src.infrastructure.testing.task_execution_test_support import (
    TaskExecutionStoreTestFactory,
    TaskExecutionTestContext,
)

FAILED_RECORDER_MAX_ITEMS = 1
FAILED_RECORDER_FIRST_TASK_ID = "failed-task-first"
FAILED_RECORDER_SECOND_TASK_ID = "failed-task-second"
PUBLISH_ONLY_BUILD_MARKER = "build"
FUNBOOST_DEMO_JOB_KIND = "demo_task_funboost"
FUNBOOST_DEMO_QUEUE_NAME = "demo_task_funboost_queue"
FUNBOOST_DEMO_EXCHANGE_NAME = "task.direct"
FUNBOOST_DEMO_ROUTING_KEY = "demo.task.funboost"
FUNBOOST_DEMO_DLX_NAME = "task.dlx"
FUNBOOST_UNIT_MESSAGE_ID = "task-1"
FUNBOOST_UNIT_CREATED_AT_EPOCH = 1
FUNBOOST_UNIT_DEDUPLICATION_KEY = "dedupe-1"
FUNBOOST_UNIT_RETRY_LIMIT = 1
FUNBOOST_UNIT_PAYLOAD_KIND = "DemoPayload"
FUNBOOST_UNIT_PAYLOAD_JSON = '{"kind":"demo","schema_version":"1.0"}'
FUNBOOST_FAILURE_TASK_ID = "funboost-consume-failed-task-1"
FUNBOOST_FAILURE_RUN_TIMES = 2
FUNBOOST_FAILURE_TIME_END = 1700000000
FUNBOOST_FAILURE_ERROR_MESSAGE = "消费失败"


class StubFunboostTaskBootstrapper:
    """
    模拟 Funboost 装配器。
    """

    def __init__(self) -> None:
        self.messages: list[TaskMessageEnvelope] = []
        self.should_fail = False
        self.shutdown_called = False

    def publish(self, message: TaskMessageEnvelope) -> None:
        if self.should_fail:
            raise RuntimeError("发布失败")
        self.messages.append(message)

    def shutdown(self) -> None:
        self.shutdown_called = True


class StubConsumer:
    """
    模拟消费器。
    """

    def __init__(self, queue_name: str) -> None:
        self.queue_name = queue_name
        self._stop_flag = 0
        self._rp = None


class StubPublisher:
    """
    模拟发布器。
    """

    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def _at_exit(self) -> None:
        """
        模拟退出期回调。
        """


@dataclass(slots=True)
class TaskExecutionFailureCapture:
    """
    任务失败回写捕获结果。
    """

    job_kind: str
    deduplication_key: str
    attempt_count: int
    failed_at_epoch: int
    last_error_type: str
    last_error_message: str
    backend: TaskBackend
    queue_name: str
    stage: TaskExecutionStage


@dataclass(slots=True)
class MissingRecordTaskExecutionStoreStub:
    """
    模拟缺失执行记录的任务执行存储。
    """

    failures: list[TaskExecutionFailureCapture] = field(default_factory=list)

    def try_mark_failed(
        self,
        *,
        job_kind: str,
        deduplication_key: str,
        attempt_count: int,
        failed_at_epoch: int,
        last_error_type: str,
        last_error_message: str,
        backend: TaskBackend,
        queue_name: str,
        stage: TaskExecutionStage,
    ) -> None:
        """
        捕获失败回写并模拟记录不存在。
        """

        self.failures.append(
            TaskExecutionFailureCapture(
                job_kind=job_kind,
                deduplication_key=deduplication_key,
                attempt_count=attempt_count,
                failed_at_epoch=failed_at_epoch,
                last_error_type=last_error_type,
                last_error_message=last_error_message,
                backend=backend,
                queue_name=queue_name,
                stage=stage,
            )
        )
        return None


@dataclass(slots=True)
class StubFunboostLogger:
    """
    模拟 Funboost 日志器。
    """

    warning_messages: list[str] = field(default_factory=list)

    def warning(self, message: str, task_id: str, job_kind: str) -> None:
        """
        捕获警告日志。
        """

        self.warning_messages.append(message % (task_id, job_kind))


class StubFailureCallbackConsumer(StubConsumer):
    """
    模拟带失败回调入口的消费者。
    """

    def __init__(self, queue_name: str) -> None:
        """
        初始化失败回调消费者。
        """

        super().__init__(queue_name=queue_name)
        self.logger = StubFunboostLogger()
        self.original_callback_called = False

    def _frame_custom_record_process_info_func(
        self,
        current_function_result_status: object,
        kw: object,
    ) -> None:
        """
        记录原始 Funboost 处理信息回调已被调用。
        """

        _ = current_function_result_status
        _ = kw
        self.original_callback_called = True


@dataclass(slots=True)
class StubFunctionResultStatus:
    """
    模拟 Funboost 函数执行结果。
    """

    success: bool
    run_status: str
    _has_requeue: bool
    _has_to_dlx_queue: bool
    _has_kill_task: bool
    task_id: str
    run_times: int
    time_end: int
    exception: Exception | None
    exception_msg: str | None


class TestFunboostTaskDispatcherUnit:
    """
    Funboost 任务分发器单元测试集合。
    """

    def test_dispatch_when_publish_success_should_return_result(self) -> None:
        """
        验证分发器当发布成功应返回结果。
        """

        registry = TaskRegistrationRegistry(
            registrations=[self._build_registration("demo_task_funboost")]
        )
        bootstrapper = StubFunboostTaskBootstrapper()
        test_context = TaskExecutionStoreTestFactory().create()
        dispatcher = FunboostTaskDispatcher(
            registration_registry=registry,
            bootstrapper=bootstrapper,  # type: ignore[arg-type]
            failed_task_recorder=FailedTaskRecorder(),
            task_execution_store=test_context.store,
            worker_enabled=True,
        )
        try:
            result = dispatcher.dispatch(self._build_message("demo_task_funboost"))
            assert result.dispatched is True
            assert result.queue_name == "demo_task_funboost_queue"
            assert len(bootstrapper.messages) == 1
        finally:
            test_context.close()

    def test_dispatch_when_publish_fail_should_record_failure(self) -> None:
        """
        验证分发器当发布失败应记录失败。
        """

        registry = TaskRegistrationRegistry(
            registrations=[self._build_registration("demo_task_funboost")]
        )
        bootstrapper = StubFunboostTaskBootstrapper()
        bootstrapper.should_fail = True
        recorder = FailedTaskRecorder()
        test_context = TaskExecutionStoreTestFactory().create()
        dispatcher = FunboostTaskDispatcher(
            registration_registry=registry,
            bootstrapper=bootstrapper,  # type: ignore[arg-type]
            failed_task_recorder=recorder,
            task_execution_store=test_context.store,
            worker_enabled=True,
        )
        try:
            with pytest.raises(HttpFaultException) as exc_info:
                dispatcher.dispatch(self._build_message("demo_task_funboost"))

            assert exc_info.value.error_code == "system.task.failed"
            assert recorder.list_records()[0].queue_name == "demo_task_funboost_queue"
            assert recorder.list_records()[0].stage == TaskFailureStage.DISPATCH_PUBLISH
            assert recorder.list_records()[0].last_error == "发布失败"
        finally:
            test_context.close()

    def test_dispatch_when_registration_backend_is_local_should_fail(self) -> None:
        """
        验证 Funboost 分发器遇到本地注册任务应拒绝执行。
        """

        registry = TaskRegistrationRegistry(
            registrations=[self._build_local_registration("demo_task")]
        )
        bootstrapper = StubFunboostTaskBootstrapper()
        test_context = TaskExecutionStoreTestFactory().create()
        dispatcher = FunboostTaskDispatcher(
            registration_registry=registry,
            bootstrapper=bootstrapper,  # type: ignore[arg-type]
            failed_task_recorder=FailedTaskRecorder(),
            task_execution_store=test_context.store,
            worker_enabled=True,
        )
        try:
            with pytest.raises(HttpFaultException) as exc_info:
                dispatcher.dispatch(self._build_message("demo_task"))

            assert "不一致" in str(exc_info.value)
            assert len(bootstrapper.messages) == 0
        finally:
            test_context.close()

    def test_dispatch_when_worker_disabled_should_publish_without_consumer(self) -> None:
        """
        验证 Funboost worker 禁用时仍可发布 producer-only 消息。
        """

        registry = TaskRegistrationRegistry(
            registrations=[self._build_registration("demo_task_funboost")]
        )
        bootstrapper = StubFunboostTaskBootstrapper()
        test_context = TaskExecutionStoreTestFactory().create()
        dispatcher = FunboostTaskDispatcher(
            registration_registry=registry,
            bootstrapper=bootstrapper,  # type: ignore[arg-type]
            failed_task_recorder=FailedTaskRecorder(),
            task_execution_store=test_context.store,
            worker_enabled=False,
        )
        try:
            result = dispatcher.dispatch(self._build_message("demo_task_funboost"))

            assert result.dispatched is True
            assert result.published is True
            assert result.worker_enabled is False
            assert len(bootstrapper.messages) == 1
        finally:
            test_context.close()

    def test_failed_task_recorder_should_keep_bounded_records(self) -> None:
        """
        验证失败任务记录器只保留容量上限内的最新记录。
        """

        recorder = FailedTaskRecorder(max_items=FAILED_RECORDER_MAX_ITEMS)

        recorder.record(self._build_failure_record(FAILED_RECORDER_FIRST_TASK_ID))
        recorder.record(self._build_failure_record(FAILED_RECORDER_SECOND_TASK_ID))

        assert [record.task_id for record in recorder.list_records()] == [
            FAILED_RECORDER_SECOND_TASK_ID
        ]

    def test_bootstrapper_failure_callback_when_record_missing_should_log_and_record(
        self,
    ) -> None:
        """
        验证消费失败回调在执行记录缺失时仍写入日志与失败记录。
        """

        missing_store = MissingRecordTaskExecutionStoreStub()
        recorder = FailedTaskRecorder()
        consumer = StubFailureCallbackConsumer(queue_name=FUNBOOST_DEMO_QUEUE_NAME)
        bootstrapper = FunboostTaskBootstrapper(
            registration_registry=TaskRegistrationRegistry(
                registrations=[self._build_registration(FUNBOOST_DEMO_JOB_KIND)]
            ),
            runtime_detail=self._build_runtime_detail(),
            message_detail=self._build_message_detail(),
            task_execution_store=cast(TaskExecutionStore, missing_store),
            failure_callback=recorder.record,
        )
        try:
            bootstrapper._bind_consumer_failure_callback(  # noqa: SLF001
                consumer=consumer,  # type: ignore[arg-type]
                queue_name=FUNBOOST_DEMO_QUEUE_NAME,
            )
            consumer._frame_custom_record_process_info_func(
                self._build_failed_function_status(),
                {
                    "body": {
                        "task_message": self._build_message(FUNBOOST_DEMO_JOB_KIND).model_dump(
                            mode="python"
                        )
                    }
                },
            )
        finally:
            bootstrapper.shutdown()

        recorded_failures = recorder.list_records()
        assert consumer.original_callback_called is True
        assert len(missing_store.failures) == 1
        assert missing_store.failures[0].job_kind == FUNBOOST_DEMO_JOB_KIND
        assert missing_store.failures[0].deduplication_key == FUNBOOST_UNIT_DEDUPLICATION_KEY
        assert missing_store.failures[0].attempt_count == FUNBOOST_FAILURE_RUN_TIMES
        assert missing_store.failures[0].backend == TaskBackend.FUNBOOST
        assert missing_store.failures[0].stage == TaskExecutionStage.CONSUME_EXECUTION
        assert missing_store.failures[0].last_error_message == (FUNBOOST_FAILURE_ERROR_MESSAGE)
        assert consumer.logger.warning_messages == [
            FUNBOOST_FAILURE_RECORD_MISSING_LOG_MESSAGE
            % (FUNBOOST_FAILURE_TASK_ID, FUNBOOST_DEMO_JOB_KIND)
        ]
        assert len(recorded_failures) == 1
        assert recorded_failures[0].task_id == FUNBOOST_FAILURE_TASK_ID
        assert recorded_failures[0].stage == TaskFailureStage.CONSUME_EXECUTION

    def test_bootstrapper_shutdown_when_consumer_started_should_clear_running_mark(
        self,
    ) -> None:
        """
        验证装配器当消费者已启动应清除运行标记。
        """

        consumer = StubConsumer(queue_name="demo_task_funboost_queue")
        test_context = TaskExecutionStoreTestFactory().create()
        bootstrapper = FunboostTaskBootstrapper(
            registration_registry=TaskRegistrationRegistry(
                registrations=[self._build_registration("demo_task_funboost")]
            ),
            runtime_detail=FunboostTaskBackendDetail(
                kind="funboost",
                schema_version="1.0",
                broker_kind="RABBITMQ_COMPLEX_ROUTING",
            ),
            message_detail=RabbitMqMessageBackendDetail(
                kind="rabbitmq",
                schema_version="1.0",
                rabbitmq_url="amqp://guest:guest@127.0.0.1:5672/",
                startup_probe_enabled=False,
                startup_probe_timeout_seconds=1,
                task_exchange_name="task.direct",
                task_exchange_type="direct",
                task_exchange_durable=True,
                task_message_persistent=True,
                publisher_confirm_enabled=True,
                publisher_confirm_timeout_seconds=1,
            ),
            task_execution_store=test_context.store,
        )
        try:
            bootstrapper._consumer_by_job_kind["demo_task_funboost"] = consumer  # noqa: SLF001
            bootstrapper._booster_by_job_kind["demo_task_funboost"] = object()  # noqa: SLF001
            bootstrapper.shutdown()

            assert consumer._stop_flag == 1  # noqa: SLF001
        finally:
            test_context.close()

    def test_bootstrapper_shutdown_when_consumer_pool_exists_should_close_pool(
        self,
    ) -> None:
        """验证装配器关闭时应同步释放 Funboost 任务线程池。"""

        consumer = StubConsumer(queue_name=FUNBOOST_DEMO_QUEUE_NAME)
        consumer._concurrent_pool = ManagedFunboostThreadPool(max_workers=1)  # noqa: SLF001
        completed = consumer._concurrent_pool.submit(lambda: True).result()  # noqa: SLF001
        test_context = TaskExecutionStoreTestFactory().create()
        bootstrapper = self._build_bootstrapper_for_publish_only(test_context)
        try:
            bootstrapper._consumer_by_job_kind[FUNBOOST_DEMO_JOB_KIND] = consumer  # noqa: SLF001

            bootstrapper.shutdown()

            assert completed is True
            assert consumer._concurrent_pool is None  # noqa: SLF001
        finally:
            test_context.close()

    def test_bootstrapper_when_consumer_has_publishers_should_close_all_publishers(
        self,
    ) -> None:
        """
        验证装配器关闭时应释放消费者内部发布者。
        """

        consumer = StubConsumer(queue_name="demo_task_funboost_queue")
        same_queue_publisher = StubPublisher()
        dlx_publisher = StubPublisher()
        consumer._publisher_of_same_queue = same_queue_publisher  # noqa: SLF001
        consumer._publisher_of_dlx_queue = dlx_publisher  # noqa: SLF001
        test_context = TaskExecutionStoreTestFactory().create()
        bootstrapper = FunboostTaskBootstrapper(
            registration_registry=TaskRegistrationRegistry(
                registrations=[self._build_registration("demo_task_funboost")]
            ),
            runtime_detail=FunboostTaskBackendDetail(
                kind="funboost",
                schema_version="1.0",
                broker_kind="RABBITMQ_COMPLEX_ROUTING",
            ),
            message_detail=RabbitMqMessageBackendDetail(
                kind="rabbitmq",
                schema_version="1.0",
                rabbitmq_url="amqp://guest:guest@127.0.0.1:5672/",
                startup_probe_enabled=False,
                startup_probe_timeout_seconds=1,
                task_exchange_name="task.direct",
                task_exchange_type="direct",
                task_exchange_durable=True,
                task_message_persistent=True,
                publisher_confirm_enabled=True,
                publisher_confirm_timeout_seconds=1,
            ),
            task_execution_store=test_context.store,
        )
        try:
            bootstrapper._consumer_by_job_kind["demo_task_funboost"] = consumer  # noqa: SLF001

            bootstrapper.shutdown()

            assert same_queue_publisher.closed is True
            assert dlx_publisher.closed is True
        finally:
            test_context.close()

    def test_bootstrapper_when_consumer_has_runtime_binding_publisher_should_close_it(
        self,
    ) -> None:
        """
        验证装配器关闭时应释放复杂路由消费者内部 `_rp` 发布者。
        """

        consumer = StubConsumer(queue_name="demo_task_funboost_queue")
        runtime_binding_publisher = StubPublisher()
        consumer._rp = runtime_binding_publisher  # noqa: SLF001
        test_context = TaskExecutionStoreTestFactory().create()
        bootstrapper = FunboostTaskBootstrapper(
            registration_registry=TaskRegistrationRegistry(
                registrations=[self._build_registration("demo_task_funboost")]
            ),
            runtime_detail=FunboostTaskBackendDetail(
                kind="funboost",
                schema_version="1.0",
                broker_kind="RABBITMQ_COMPLEX_ROUTING",
            ),
            message_detail=RabbitMqMessageBackendDetail(
                kind="rabbitmq",
                schema_version="1.0",
                rabbitmq_url="amqp://guest:guest@127.0.0.1:5672/",
                startup_probe_enabled=False,
                startup_probe_timeout_seconds=1,
                task_exchange_name="task.direct",
                task_exchange_type="direct",
                task_exchange_durable=True,
                task_message_persistent=True,
                publisher_confirm_enabled=True,
                publisher_confirm_timeout_seconds=1,
            ),
            task_execution_store=test_context.store,
        )
        try:
            bootstrapper._consumer_by_job_kind["demo_task_funboost"] = consumer  # noqa: SLF001

            bootstrapper.shutdown()

            assert runtime_binding_publisher.closed is True
            assert consumer._rp is None  # noqa: SLF001
        finally:
            test_context.close()

    def test_bootstrapper_shutdown_when_publisher_exists_should_close_publisher(
        self,
    ) -> None:
        """
        验证装配器当存在发布器应关闭发布器。
        """

        consumer = StubConsumer(queue_name="demo_task_funboost_queue")
        publisher = StubPublisher()

        class BoosterLike:
            """
            模拟 Booster。
            """

            def __init__(self, publisher: StubPublisher) -> None:
                self.publisher = publisher

        test_context = TaskExecutionStoreTestFactory().create()
        bootstrapper = FunboostTaskBootstrapper(
            registration_registry=TaskRegistrationRegistry(
                registrations=[self._build_registration("demo_task_funboost")]
            ),
            runtime_detail=FunboostTaskBackendDetail(
                kind="funboost",
                schema_version="1.0",
                broker_kind="RABBITMQ_COMPLEX_ROUTING",
            ),
            message_detail=RabbitMqMessageBackendDetail(
                kind="rabbitmq",
                schema_version="1.0",
                rabbitmq_url="amqp://guest:guest@127.0.0.1:5672/",
                startup_probe_enabled=False,
                startup_probe_timeout_seconds=1,
                task_exchange_name="task.direct",
                task_exchange_type="direct",
                task_exchange_durable=True,
                task_message_persistent=True,
                publisher_confirm_enabled=True,
                publisher_confirm_timeout_seconds=1,
            ),
            task_execution_store=test_context.store,
        )
        try:
            bootstrapper._consumer_by_job_kind["demo_task_funboost"] = consumer  # noqa: SLF001
            bootstrapper._booster_by_job_kind["demo_task_funboost"] = BoosterLike(publisher)  # noqa: SLF001

            bootstrapper.shutdown()

            assert publisher.closed is True
        finally:
            test_context.close()

    def test_bootstrapper_shutdown_when_publisher_exists_should_unregister_atexit(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        验证装配器关闭时应注销发布器退出期回调。
        """

        consumer = StubConsumer(queue_name="demo_task_funboost_queue")
        publisher = StubPublisher()
        unregister_calls: list[object] = []

        class BoosterLike:
            """
            模拟 Booster。
            """

            def __init__(self, publisher: StubPublisher) -> None:
                self.publisher = publisher

        def fake_unregister(callback: object) -> None:
            unregister_calls.append(callback)

        monkeypatch.setattr(atexit, "unregister", fake_unregister)
        test_context = TaskExecutionStoreTestFactory().create()
        bootstrapper = FunboostTaskBootstrapper(
            registration_registry=TaskRegistrationRegistry(
                registrations=[self._build_registration("demo_task_funboost")]
            ),
            runtime_detail=FunboostTaskBackendDetail(
                kind="funboost",
                schema_version="1.0",
                broker_kind="RABBITMQ_COMPLEX_ROUTING",
            ),
            message_detail=RabbitMqMessageBackendDetail(
                kind="rabbitmq",
                schema_version="1.0",
                rabbitmq_url="amqp://guest:guest@127.0.0.1:5672/",
                startup_probe_enabled=False,
                startup_probe_timeout_seconds=1,
                task_exchange_name="task.direct",
                task_exchange_type="direct",
                task_exchange_durable=True,
                task_message_persistent=True,
                publisher_confirm_enabled=True,
                publisher_confirm_timeout_seconds=1,
            ),
            task_execution_store=test_context.store,
        )
        try:
            bootstrapper._consumer_by_job_kind["demo_task_funboost"] = consumer  # noqa: SLF001
            bootstrapper._booster_by_job_kind["demo_task_funboost"] = BoosterLike(publisher)  # noqa: SLF001

            bootstrapper.shutdown()

            assert len(unregister_calls) == 1
            assert unregister_calls[0] == publisher._at_exit
        finally:
            test_context.close()

    def test_bootstrapper_register_publisher_should_delay_connection_until_publish(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        验证 producer-only 注册阶段不会提前创建 RabbitMQ 发布器。
        """

        build_calls: list[str] = []
        test_context = TaskExecutionStoreTestFactory().create()
        bootstrapper = self._build_bootstrapper_for_publish_only(test_context)

        def fake_build_publisher(detail: object) -> StubBooster:
            _ = detail
            build_calls.append(PUBLISH_ONLY_BUILD_MARKER)
            return StubBooster()

        monkeypatch.setattr(
            bootstrapper,
            "_build_publisher",
            fake_build_publisher,
        )
        try:
            bootstrapper.register_publisher("demo_task_funboost")

            assert build_calls == []
            assert "demo_task_funboost" not in bootstrapper._publisher_by_job_kind  # noqa: SLF001

            bootstrapper.publish(self._build_message("demo_task_funboost"))
            lazy_publisher = cast(
                StubBooster,
                bootstrapper._publisher_by_job_kind["demo_task_funboost"],  # noqa: SLF001
            )

            assert build_calls == [PUBLISH_ONLY_BUILD_MARKER]
            assert isinstance(lazy_publisher, StubBooster)
            assert len(lazy_publisher.messages) == 1
        finally:
            bootstrapper.shutdown()
            test_context.close()

    def test_bootstrapper_params_should_apply_production_rabbitmq_contract(self) -> None:
        """验证 Funboost 主链应用确认、持久化、有界队列、预取和死信配置。"""

        test_context = TaskExecutionStoreTestFactory().create()
        bootstrapper = self._build_bootstrapper_for_publish_only(test_context)
        detail = cast(
            FunboostTaskRegistrationDetail,
            self._build_registration(FUNBOOST_DEMO_JOB_KIND).detail,
        )
        try:
            params = bootstrapper._build_booster_params(detail)  # noqa: SLF001

            assert params.publisher_override_cls is ConfirmedFunboostRabbitMqPublisher
            assert params.consumer_override_cls is BoundedFunboostRabbitMqConsumer
            assert params.broker_exclusive_config["message_persistent"] is True
            assert params.broker_exclusive_config["publisher_confirm_enabled"] is True
            assert params.broker_exclusive_config["queue_max_length"] > 0
            assert params.broker_exclusive_config["prefetch_count"] > 0
            assert params.broker_exclusive_config["dead_letter_exchange_name"]
        finally:
            bootstrapper.shutdown()
            test_context.close()

    def _build_runtime_detail(self) -> FunboostTaskBackendDetail:
        """
        构建 Funboost 任务后端配置。
        """

        return FunboostTaskBackendDetail(
            kind="funboost",
            schema_version="1.0",
            broker_kind="RABBITMQ_COMPLEX_ROUTING",
        )

    def _build_message_detail(self) -> RabbitMqMessageBackendDetail:
        """
        构建 RabbitMQ 消息后端配置。
        """

        return RabbitMqMessageBackendDetail(
            kind="rabbitmq",
            schema_version="1.0",
            rabbitmq_url="amqp://guest:guest@127.0.0.1:5672/",
            startup_probe_enabled=False,
            startup_probe_timeout_seconds=1,
            task_exchange_name=FUNBOOST_DEMO_EXCHANGE_NAME,
            task_exchange_type="direct",
            task_exchange_durable=True,
            task_message_persistent=True,
            publisher_confirm_enabled=True,
            publisher_confirm_timeout_seconds=1,
        )

    def _build_failed_function_status(self) -> StubFunctionResultStatus:
        """
        构建 Funboost 消费失败状态。
        """

        return StubFunctionResultStatus(
            success=False,
            run_status=FUNBOOST_RUN_STATUS_FINISH,
            _has_requeue=False,
            _has_to_dlx_queue=False,
            _has_kill_task=False,
            task_id=FUNBOOST_FAILURE_TASK_ID,
            run_times=FUNBOOST_FAILURE_RUN_TIMES,
            time_end=FUNBOOST_FAILURE_TIME_END,
            exception=RuntimeError(FUNBOOST_FAILURE_ERROR_MESSAGE),
            exception_msg=FUNBOOST_FAILURE_ERROR_MESSAGE,
        )

    def _build_registration(self, job_kind: str) -> TaskRegistrationEnvelope:
        """
        构建 Funboost 注册项。
        """

        return TaskRegistrationEnvelope.model_validate(
            {
                "envelope_kind": "task_registration_envelope",
                "schema_version": "1.0",
                "header": {
                    "header_kind": "task_registration_header",
                    "schema_version": "1.0",
                    "task_name": job_kind,
                    "job_kind": job_kind,
                    "enabled": True,
                    "backend": "funboost",
                },
                "detail": {
                    "kind": "funboost",
                    "schema_version": "1.0",
                    "queue_name": FUNBOOST_DEMO_QUEUE_NAME,
                    "exchange_name": FUNBOOST_DEMO_EXCHANGE_NAME,
                    "routing_key": FUNBOOST_DEMO_ROUTING_KEY,
                    "broker_kind": "RABBITMQ_COMPLEX_ROUTING",
                    "retry_limit": 1,
                    "consumer_worker_count": 1,
                },
            }
        )

    def _build_local_registration(self, job_kind: str) -> TaskRegistrationEnvelope:
        """
        构建本地注册项。
        """

        return TaskRegistrationEnvelope.model_validate(
            {
                "envelope_kind": "task_registration_envelope",
                "schema_version": "1.0",
                "header": {
                    "header_kind": "task_registration_header",
                    "schema_version": "1.0",
                    "task_name": job_kind,
                    "job_kind": job_kind,
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

    def _build_message(self, job_kind: str) -> TaskMessageEnvelope:
        """
        构建任务消息。
        """

        return TaskMessageEnvelope(
            header=TaskMessageHeader(
                message_id=FUNBOOST_UNIT_MESSAGE_ID,
                created_at_epoch=FUNBOOST_UNIT_CREATED_AT_EPOCH,
            ),
            payload=TaskMessagePayload(
                job_kind=job_kind,
                deduplication_key=FUNBOOST_UNIT_DEDUPLICATION_KEY,
                retry_limit=FUNBOOST_UNIT_RETRY_LIMIT,
                payload_kind=FUNBOOST_UNIT_PAYLOAD_KIND,
                payload_json=FUNBOOST_UNIT_PAYLOAD_JSON,
            ),
        )

    def _build_failure_record(self, task_id: str) -> TaskFailureRecord:
        """
        构建失败任务记录。
        """

        return TaskFailureRecord(
            task_id=task_id,
            job_kind="demo_task_funboost",
            message="失败任务",
            retry_count=0,
            backend=TaskBackend.FUNBOOST,
            stage=TaskFailureStage.DISPATCH_PUBLISH,
        )

    def _build_bootstrapper_for_publish_only(
        self,
        test_context: TaskExecutionTestContext,
    ) -> FunboostTaskBootstrapper:
        """
        构建 producer-only 装配器。
        """

        return FunboostTaskBootstrapper(
            registration_registry=TaskRegistrationRegistry(
                registrations=[self._build_registration("demo_task_funboost")]
            ),
            runtime_detail=self._build_runtime_detail(),
            message_detail=self._build_message_detail(),
            task_execution_store=test_context.store,
        )


class StubBooster:
    """
    模拟 Funboost Booster。
    """

    def __init__(self) -> None:
        """
        初始化模拟 Booster。
        """

        self.messages: list[object] = []
        self.publisher = None

    def publish(self, message: object) -> None:
        """
        记录发布消息。
        """

        self.messages.append(message)
