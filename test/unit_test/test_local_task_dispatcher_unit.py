"""
本地任务分发器单元测试模块。
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ConfigDict

from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.task_contract.message_bus_contract import (
    TaskMessageEnvelope,
    TaskMessageHeader,
    TaskMessagePayload,
)
from src.core.task_contract.task_handler_contract import TaskHandler
from src.core.task_contract.task_invocation_contract import TypedTaskInvocation
from src.core.task_contract.task_registration_contract import TaskRegistrationEnvelope
from src.infrastructure.task.failed_task_recorder import FailedTaskRecorder
from src.infrastructure.task.local_message_bus import (
    LOCAL_MESSAGE_BUS_CAPACITY_EXHAUSTED_MESSAGE,
    LocalMessageBus,
)
from src.infrastructure.task.local_task_dispatcher import LocalTaskDispatcher
from src.infrastructure.task.task_registration_registry import (
    RegisteredTaskBinding,
    TaskRegistrationRegistry,
)
from src.infrastructure.testing.task_execution_test_support import (
    TaskExecutionStoreTestFactory,
)

LOCAL_MESSAGE_BUS_MAX_ITEMS = 1
LOCAL_MESSAGE_FIRST_ID = "task-first"
LOCAL_MESSAGE_SECOND_ID = "task-second"


class DemoTaskPayload(BaseModel):
    """
    示例任务载荷。
    """

    model_config = ConfigDict(extra="forbid")

    task_id: str


class RecordingTaskHandler(TaskHandler[DemoTaskPayload]):
    """
    记录型任务处理器。
    """

    def __init__(self) -> None:
        self.handled_count = 0

    def handle(self, invocation: TypedTaskInvocation[DemoTaskPayload]) -> None:
        _ = invocation
        self.handled_count += 1


class FlakyTaskHandler(TaskHandler[DemoTaskPayload]):
    """
    首次失败任务处理器。
    """

    def __init__(self) -> None:
        self.handled_count = 0

    def handle(self, invocation: TypedTaskInvocation[DemoTaskPayload]) -> None:
        _ = invocation
        self.handled_count += 1
        if self.handled_count == 1:
            raise RuntimeError("首次失败")


class AlwaysFailTaskHandler(TaskHandler[DemoTaskPayload]):
    """
    持续失败任务处理器。
    """

    def handle(self, invocation: TypedTaskInvocation[DemoTaskPayload]) -> None:
        _ = invocation
        raise RuntimeError("持续失败")


class TestLocalTaskDispatcherUnit:
    """
    本地任务分发器单元测试集合。
    """

    def test_dispatch_when_duplicate_message_should_reuse_existing_record(self) -> None:
        """
        验证本地分发器遇到重复任务应复用已有记录。
        """

        test_context = TaskExecutionStoreTestFactory().create()
        try:
            handler = RecordingTaskHandler()
            dispatcher = self._build_dispatcher(
                handler=handler,
                task_execution_store=test_context.store,
            )
            first_result = dispatcher.dispatch(self._build_message())
            second_result = dispatcher.dispatch(self._build_message())

            assert first_result.dispatched is True
            assert second_result.dispatched is False
            assert second_result.reused_existing_record is True
            assert handler.handled_count == 1
        finally:
            test_context.close()

    def test_dispatch_when_handler_retry_then_success_should_return_success(self) -> None:
        """
        验证本地分发器遇到可恢复失败后应重试成功。
        """

        test_context = TaskExecutionStoreTestFactory().create()
        try:
            handler = FlakyTaskHandler()
            dispatcher = self._build_dispatcher(
                handler=handler,
                task_execution_store=test_context.store,
            )

            result = dispatcher.dispatch(self._build_message())

            assert result.execution_status.value == "SUCCESS"
            assert handler.handled_count == 2
        finally:
            test_context.close()

    def test_dispatch_when_handler_always_fail_should_record_failure(self) -> None:
        """
        验证本地分发器当处理器持续失败应记录失败。
        """

        test_context = TaskExecutionStoreTestFactory().create()
        recorder = FailedTaskRecorder()
        try:
            dispatcher = self._build_dispatcher(
                handler=AlwaysFailTaskHandler(),
                task_execution_store=test_context.store,
                failed_task_recorder=recorder,
            )

            with pytest.raises(HttpFaultException):
                dispatcher.dispatch(self._build_message())

            assert recorder.list_records()[0].message == "任务执行失败。"
            assert recorder.list_records()[0].attempt_count == 2
        finally:
            test_context.close()

    def test_dispatch_when_registration_backend_is_funboost_should_fail(self) -> None:
        """
        验证本地分发器遇到 Funboost 注册任务应拒绝执行。
        """

        test_context = TaskExecutionStoreTestFactory().create()
        try:
            registry = TaskRegistrationRegistry(registrations=[self._build_funboost_registration()])
            registry.register_binding(
                RegisteredTaskBinding(
                    job_kind="demo_task_funboost",
                    payload_model=DemoTaskPayload,
                    handler=RecordingTaskHandler(),
                )
            )
            dispatcher = LocalTaskDispatcher(
                message_bus=LocalMessageBus(),
                registration_registry=registry,
                failed_task_recorder=FailedTaskRecorder(),
                task_execution_store=test_context.store,
                worker_enabled=True,
                inline_execute_enabled=True,
            )

            with pytest.raises(HttpFaultException) as exc_info:
                dispatcher.dispatch(self._build_message("demo_task_funboost"))

            assert "不一致" in str(exc_info.value)
        finally:
            test_context.close()

    def test_dispatch_when_inline_disabled_should_publish_without_execute(self) -> None:
        """
        验证本地 inline 禁用时仍发布消息但不执行处理器。
        """

        test_context = TaskExecutionStoreTestFactory().create()
        message_bus = LocalMessageBus()
        try:
            handler = RecordingTaskHandler()
            dispatcher = self._build_dispatcher(
                handler=handler,
                task_execution_store=test_context.store,
                message_bus=message_bus,
                worker_enabled=False,
                inline_execute_enabled=False,
            )

            result = dispatcher.dispatch(self._build_message())

            assert result.published is True
            assert result.worker_enabled is False
            assert result.inline_execute_enabled is False
            assert handler.handled_count == 0
            assert len(message_bus.list_messages()) == 1
        finally:
            test_context.close()

    def test_local_message_bus_when_capacity_exhausted_should_reject_new_message(
        self,
    ) -> None:
        """
        验证本地消息总线容量耗尽时拒绝新消息且不淘汰已接收消息。
        """

        message_bus = LocalMessageBus(max_items=LOCAL_MESSAGE_BUS_MAX_ITEMS)
        first_message = self._build_message(message_id=LOCAL_MESSAGE_FIRST_ID)
        second_message = self._build_message(message_id=LOCAL_MESSAGE_SECOND_ID)

        message_bus.publish(first_message)
        result = message_bus.publish(second_message)

        assert [message.header.message_id for message in message_bus.list_messages()] == [
            LOCAL_MESSAGE_FIRST_ID
        ]
        assert result.published is False
        assert result.failure_reason == LOCAL_MESSAGE_BUS_CAPACITY_EXHAUSTED_MESSAGE

    def test_local_message_bus_when_message_republished_should_keep_idempotent(
        self,
    ) -> None:
        """
        验证本地消息总线按 message_id 幂等处理重复发布。
        """

        message_bus = LocalMessageBus(max_items=LOCAL_MESSAGE_BUS_MAX_ITEMS)
        message = self._build_message(message_id=LOCAL_MESSAGE_FIRST_ID)

        first_result = message_bus.publish(message)
        second_result = message_bus.publish(message)

        assert first_result.published is True
        assert second_result.published is True
        assert [
            queued_message.header.message_id for queued_message in message_bus.list_messages()
        ] == [LOCAL_MESSAGE_FIRST_ID]

    def test_dispatch_when_message_capacity_exhausted_should_raise_capacity_fault(
        self,
    ) -> None:
        """验证本地消息容量拒绝会传播为统一容量故障。"""

        test_context = TaskExecutionStoreTestFactory().create()
        message_bus = LocalMessageBus(max_items=LOCAL_MESSAGE_BUS_MAX_ITEMS)
        message_bus.publish(self._build_message(message_id=LOCAL_MESSAGE_FIRST_ID))
        try:
            dispatcher = self._build_dispatcher(
                handler=RecordingTaskHandler(),
                task_execution_store=test_context.store,
                message_bus=message_bus,
                worker_enabled=False,
                inline_execute_enabled=False,
            )

            with pytest.raises(HttpFaultException) as exc_info:
                dispatcher.dispatch(self._build_message(message_id=LOCAL_MESSAGE_SECOND_ID))

            assert exc_info.value.error_code == CoreErrorCode.CAPACITY_EXHAUSTED
            assert [message.header.message_id for message in message_bus.list_messages()] == [
                LOCAL_MESSAGE_FIRST_ID
            ]
        finally:
            test_context.close()

    def _build_dispatcher(
        self,
        *,
        handler: TaskHandler[DemoTaskPayload],
        task_execution_store,
        failed_task_recorder: FailedTaskRecorder | None = None,
        message_bus: LocalMessageBus | None = None,
        worker_enabled: bool = True,
        inline_execute_enabled: bool = True,
    ) -> LocalTaskDispatcher:
        """
        构建本地任务分发器。
        """

        recorder = failed_task_recorder or FailedTaskRecorder()
        registry = TaskRegistrationRegistry(registrations=[self._build_registration()])
        registry.register_binding(
            RegisteredTaskBinding(
                job_kind="demo_task",
                payload_model=DemoTaskPayload,
                handler=handler,
            )
        )
        return LocalTaskDispatcher(
            message_bus=message_bus or LocalMessageBus(),
            registration_registry=registry,
            failed_task_recorder=recorder,
            task_execution_store=task_execution_store,
            worker_enabled=worker_enabled,
            inline_execute_enabled=inline_execute_enabled,
        )

    def _build_registration(self) -> TaskRegistrationEnvelope:
        """
        构建注册项。
        """

        return TaskRegistrationEnvelope.model_validate(
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

    def _build_funboost_registration(self) -> TaskRegistrationEnvelope:
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
                    "task_name": "demo_task_funboost",
                    "job_kind": "demo_task_funboost",
                    "enabled": True,
                    "backend": "funboost",
                },
                "detail": {
                    "kind": "funboost",
                    "schema_version": "1.0",
                    "queue_name": "demo_task_funboost_queue",
                    "exchange_name": "task.direct",
                    "routing_key": "demo.task.funboost",
                    "broker_kind": "RABBITMQ_COMPLEX_ROUTING",
                    "retry_limit": 1,
                    "consumer_worker_count": 1,
                },
            }
        )

    def _build_message(
        self,
        job_kind: str = "demo_task",
        *,
        message_id: str = "task-1",
    ) -> TaskMessageEnvelope:
        """
        构建任务消息。
        """

        return TaskMessageEnvelope(
            header=TaskMessageHeader(
                message_id=message_id,
                request_id="request-1",
                trace_id="trace-1",
                created_at_epoch=1,
            ),
            payload=TaskMessagePayload(
                job_kind=job_kind,
                deduplication_key="dedupe-1",
                retry_limit=1,
                payload_kind="DemoTaskPayload",
                payload_json='{"task_id":"task-1"}',
            ),
        )
