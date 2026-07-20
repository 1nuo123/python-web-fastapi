"""
任务注册中心单元测试模块。
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
from src.core.task_contract.task_runtime_contract import TaskBackend
from src.infrastructure.task.task_registration_registry import (
    RegisteredTaskBinding,
    TaskRegistrationRegistry,
)


class DemoPayload(BaseModel):
    """
    示例载荷模型。
    """

    model_config = ConfigDict(extra="forbid")

    kind: str = "demo"
    schema_version: str = "1.0"


class DemoTaskHandler(TaskHandler[DemoPayload]):
    """
    示例任务处理器。
    """

    def __init__(self) -> None:
        self.handled = 0

    def handle(self, invocation: TypedTaskInvocation[DemoPayload]) -> None:
        _ = invocation
        self.handled += 1


class TestTaskRegistrationRegistryUnit:
    """
    任务注册中心单元测试集合。
    """

    def test_registry_when_register_binding_should_resolve_binding(self) -> None:
        """
        验证注册中心当注册绑定应可解析绑定。
        """

        registry = self._build_registry()
        handler = DemoTaskHandler()

        registry.register_binding(
            RegisteredTaskBinding(
                job_kind="demo_task",
                payload_model=DemoPayload,
                handler=handler,
            )
        )

        resolved_binding = registry.get_resolved_binding("demo_task")
        assert resolved_binding.binding.handler is handler
        assert resolved_binding.registration.header.job_kind == "demo_task"

    def test_registry_when_duplicate_job_kind_should_fail(self) -> None:
        """
        验证注册中心当任务键重复应失败。
        """

        with pytest.raises(HttpFaultException) as exc_info:
            TaskRegistrationRegistry(
                registrations=[
                    self._build_registration("demo_task"),
                    self._build_registration("demo_task"),
                ]
            )

        assert "注册重复" in str(exc_info.value)

    def test_registry_when_register_duplicate_binding_should_fail(self) -> None:
        """
        验证注册中心当处理器重复注册应失败。
        """

        registry = self._build_registry()
        handler = DemoTaskHandler()
        binding = RegisteredTaskBinding(
            job_kind="demo_task",
            payload_model=DemoPayload,
            handler=handler,
        )
        registry.register_binding(binding)

        with pytest.raises(HttpFaultException) as exc_info:
            registry.register_binding(binding)

        assert "处理器重复注册" in str(exc_info.value)

    def test_registry_when_binding_missing_should_fail(self) -> None:
        """
        验证注册中心当任务未绑定处理器应失败。
        """

        registry = self._build_registry()

        with pytest.raises(HttpFaultException) as exc_info:
            registry.get_resolved_binding("demo_task")

        assert "尚未绑定处理器" in str(exc_info.value)

    def test_registry_when_payload_model_is_base_model_should_fail(self) -> None:
        """
        验证注册中心当使用 BaseModel 占位时应失败。
        """

        registry = self._build_registry()

        with pytest.raises(HttpFaultException) as exc_info:
            registry.register_binding(
                RegisteredTaskBinding(
                    job_kind="demo_task",
                    payload_model=BaseModel,
                    handler=DemoTaskHandler(),
                )
            )

        assert exc_info.value.error_code == CoreErrorCode.CONFIG_INVALID
        assert "禁止使用 BaseModel" in str(exc_info.value)

    def test_registry_when_payload_json_invalid_should_fail_early(self) -> None:
        """
        验证注册中心当载荷非法时应提前失败。
        """

        registry = self._build_registry()
        registry.register_binding(
            RegisteredTaskBinding(
                job_kind="demo_task",
                payload_model=DemoPayload,
                handler=DemoTaskHandler(),
            )
        )

        with pytest.raises(HttpFaultException) as exc_info:
            registry.validate_message_payload(
                TaskMessageEnvelope(
                    header=TaskMessageHeader(
                        message_id="task-1",
                        created_at_epoch=1,
                    ),
                    payload=TaskMessagePayload(
                        job_kind="demo_task",
                        deduplication_key="dedupe-1",
                        retry_limit=1,
                        payload_kind="WrongPayload",
                        payload_json="{}",
                    ),
                )
            )

        assert exc_info.value.error_code == CoreErrorCode.CONFIG_INVALID
        assert "payload_kind 与 payload_model 不一致" in str(exc_info.value)

    def test_registry_when_payload_valid_should_return_typed_invocation(self) -> None:
        """
        验证注册中心当载荷有效应返回强类型执行对象。
        """

        registry = self._build_registry()
        handler = DemoTaskHandler()
        registry.register_binding(
            RegisteredTaskBinding(
                job_kind="demo_task",
                payload_model=DemoPayload,
                handler=handler,
            )
        )

        invocation = registry.validate_message_payload(
            TaskMessageEnvelope(
                header=TaskMessageHeader(
                    message_id="task-1",
                    created_at_epoch=1,
                ),
                payload=TaskMessagePayload(
                    job_kind="demo_task",
                    deduplication_key="dedupe-1",
                    retry_limit=1,
                    payload_kind="DemoPayload",
                    payload_json='{"kind":"demo","schema_version":"1.0"}',
                ),
            )
        )

        assert invocation.payload.kind == "demo"
        assert invocation.message.header.message_id == "task-1"
        assert invocation.binding.handler is handler

    def test_registry_when_enabled_task_missing_binding_should_fail_assertion(self) -> None:
        """
        验证注册中心当启用任务缺失绑定应在装配前失败。
        """

        registry = self._build_registry()

        with pytest.raises(HttpFaultException) as exc_info:
            registry.assert_all_enabled_tasks_bound(TaskBackend.LOCAL)

        assert exc_info.value.error_code == CoreErrorCode.CONFIG_INVALID
        assert "尚未绑定处理器" in str(exc_info.value)

    def test_registry_when_backend_mismatch_should_fail(self) -> None:
        """
        验证注册中心当后端不一致应失败。
        """

        registry = TaskRegistrationRegistry(
            registrations=[
                self._build_registration("demo_task"),
                self._build_funboost_registration("demo_task_funboost"),
            ]
        )

        with pytest.raises(HttpFaultException) as exc_info:
            registry.get_enabled_registration_for_backend(
                "demo_task_funboost",
                backend=TaskBackend.LOCAL,
            )

        assert exc_info.value.error_code == CoreErrorCode.CONFIG_INVALID
        assert "不一致" in str(exc_info.value)

    def test_registry_should_allow_producer_only_enabled_declaration(self) -> None:
        """
        验证 producer-only 节点只要求存在启用任务声明。
        """

        registry = TaskRegistrationRegistry(
            registrations=[self._build_funboost_registration("demo_task_funboost")]
        )

        registry.assert_enabled_tasks_declarable_for_producer(TaskBackend.FUNBOOST)

    def test_registry_when_producer_only_declaration_missing_should_fail(self) -> None:
        """
        验证 producer-only 节点缺少当前后端启用声明时失败。
        """

        registry = self._build_registry()

        with pytest.raises(HttpFaultException) as exc_info:
            registry.assert_enabled_tasks_declarable_for_producer(TaskBackend.FUNBOOST)

        assert exc_info.value.error_code == CoreErrorCode.CONFIG_INVALID
        assert "producer-only" in str(exc_info.value)

    def _build_registry(self) -> TaskRegistrationRegistry:
        """
        构建注册中心。
        """

        return TaskRegistrationRegistry(registrations=[self._build_registration("demo_task")])

    def _build_registration(self, job_kind: str) -> TaskRegistrationEnvelope:
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

    def _build_funboost_registration(self, job_kind: str) -> TaskRegistrationEnvelope:
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
                    "queue_name": "demo_task_funboost_queue",
                    "exchange_name": "task.direct",
                    "routing_key": "demo.task.funboost",
                    "broker_kind": "RABBITMQ_COMPLEX_ROUTING",
                    "retry_limit": 1,
                    "consumer_worker_count": 1,
                },
            }
        )
