"""
任务运行时路径测试模块。
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.testing.demo_task_binding_factory import DemoTaskPayload
from src.api.testing.test_app_factory import TestAppFactory
from src.application.dispatch_background_job_usecase import TaskDispatchCommand
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.task_contract.message_bus_contract import (
    MessageBusBackend,
    TaskMessageEnvelope,
    TaskMessageHeader,
    TaskMessagePayload,
)
from src.core.task_contract.task_execution_record_contract import TaskExecutionStatus
from src.core.task_contract.task_runtime_contract import TaskRuntimeMode
from src.infrastructure.settings.raw_application_settings import SettingsOverrideMapping

RABBITMQ_TEST_URL_ENV = "RABBITMQ_TEST_URL"
RABBITMQ_LOCAL_URL = os.getenv(
    RABBITMQ_TEST_URL_ENV,
    "amqp://fastapi_dev:local-dev-rabbitmq-password@127.0.0.1:5672/",
)
LOCAL_JOB_KIND = "demo_task"
FUNBOOST_JOB_KIND = "demo_task_funboost"


class TestTaskRuntimePath:
    """
    任务运行时路径测试集合。
    """

    def test_app_when_local_task_backend_should_build_local_dispatcher(self) -> None:
        """
        验证应用当本地任务后端启用应装配本地分发器。
        """

        app = TestAppFactory().create()

        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            dispatcher = resource_mount.get_task_dispatcher()
            assert dispatcher.__class__.__name__ == "LocalTaskDispatcher"
            assert resource_mount.get_current_task_runtime_mode() == TaskRuntimeMode.LOCAL_INLINE

    def test_app_when_funboost_task_backend_should_build_funboost_dispatcher(self) -> None:
        """
        验证应用当 Funboost 任务后端启用应装配 Funboost 分发器。
        """

        app = TestAppFactory().create(
            overrides={
                "runtime": {
                    "message": {
                        "backend": "rabbitmq",
                        "backend_detail": {
                            "kind": "rabbitmq",
                            "schema_version": "1.0",
                            "rabbitmq_url": RABBITMQ_LOCAL_URL,
                            "startup_probe_enabled": False,
                            "startup_probe_timeout_seconds": 1,
                            "task_exchange_name": "task.direct",
                            "task_exchange_type": "direct",
                            "task_exchange_durable": True,
                            "task_message_persistent": True,
                            "publisher_confirm_enabled": True,
                            "publisher_confirm_timeout_seconds": 5,
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
            }
        )

        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            dispatcher = resource_mount.get_task_dispatcher()
            assert dispatcher.__class__.__name__ == "FunboostTaskDispatcher"
            assert (
                resource_mount.get_current_task_runtime_mode() == TaskRuntimeMode.FUNBOOST_PRODUCER
            )

    def test_app_when_rabbitmq_message_backend_should_build_rabbitmq_message_bus(
        self,
    ) -> None:
        """
        验证 RabbitMQ 消息后端会装配真实 RabbitMQ 消息总线。
        """

        app = TestAppFactory().create(
            overrides={
                "runtime": {
                    "message": {
                        "backend": "rabbitmq",
                        "backend_detail": {
                            "kind": "rabbitmq",
                            "schema_version": "1.0",
                            "rabbitmq_url": RABBITMQ_LOCAL_URL,
                            "startup_probe_enabled": False,
                            "startup_probe_timeout_seconds": 1,
                            "task_exchange_name": "task.direct",
                            "task_exchange_type": "direct",
                            "task_exchange_durable": True,
                            "task_message_persistent": True,
                            "publisher_confirm_enabled": True,
                            "publisher_confirm_timeout_seconds": 5,
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
            }
        )

        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            message_bus = resource_mount.get_task_message_transport()
            states = {state.resource_name: state for state in resource_mount.get_runtime_states()}

        assert message_bus.__class__.__name__ == "RabbitMqMessageBus"
        assert message_bus.backend == MessageBusBackend.RABBITMQ
        assert "rabbitmq" in str(states["shared_task_message_transport"].detail)
        assert "message transport" in str(states["shared_task_message_transport"].detail)

    def test_dispatch_when_local_runtime_targets_funboost_job_should_fail(self) -> None:
        """
        验证本地运行时派发 Funboost 注册任务应失败。
        """

        app = TestAppFactory().create()

        with TestClient(app):
            with pytest.raises(HttpFaultException) as exc_info:
                app.state.container.dispatch_background_job_usecase.execute(
                    TaskDispatchCommand(
                        payload=DemoTaskPayload(),
                        job_kind=FUNBOOST_JOB_KIND,
                    )
                )

        assert "不一致" in str(exc_info.value)

    def test_task_runtime_port_should_expose_execution_record_queries(self) -> None:
        """
        验证应用层任务运行时端口提供执行记录查询能力。
        """

        app = TestAppFactory().create()

        with TestClient(app):
            dispatch_result = app.state.container.dispatch_background_job_usecase.execute(
                TaskDispatchCommand(payload=DemoTaskPayload())
            )
            resource_mount = app.state.container.resource_mount
            record = resource_mount.get_task_execution_record(dispatch_result.task_id)
            records = resource_mount.list_task_execution_records(
                limit=10,
                status=TaskExecutionStatus.SUCCESS,
                job_kind=LOCAL_JOB_KIND,
            )

        assert record is not None
        assert record.header.task_id == dispatch_result.task_id
        assert any(candidate.header.task_id == dispatch_result.task_id for candidate in records)

    def test_dispatch_when_funboost_runtime_targets_local_job_should_fail(self) -> None:
        """
        验证 Funboost 运行时派发本地注册任务应失败。
        """

        app = TestAppFactory().create(overrides=self._build_funboost_runtime_overrides())

        with TestClient(app):
            with pytest.raises(HttpFaultException) as exc_info:
                app.state.container.dispatch_background_job_usecase.execute(
                    TaskDispatchCommand(
                        payload=DemoTaskPayload(),
                        job_kind=LOCAL_JOB_KIND,
                    )
                )

        assert "不一致" in str(exc_info.value)

    def test_local_dispatcher_when_payload_invalid_should_fail_before_handler(self) -> None:
        """
        验证本地分发器当载荷非法应在处理前失败。
        """

        app = TestAppFactory().create(
            overrides={
                "runtime": {
                    "task": {
                        "worker_enabled": True,
                    }
                }
            }
        )

        with TestClient(app):
            dispatcher = app.state.container.resource_mount.get_task_dispatcher()
            with pytest.raises(HttpFaultException) as exc_info:
                dispatcher.dispatch(
                    TaskMessageEnvelope(
                        header=TaskMessageHeader(
                            message_id=f"task-invalid-local-{uuid4()}",
                            created_at_epoch=1,
                        ),
                        payload=TaskMessagePayload(
                            job_kind="demo_task",
                            deduplication_key=f"dedupe-invalid-local-{uuid4()}",
                            retry_limit=0,
                            payload_kind="DemoTaskPayload",
                            payload_json='{"kind":"demo_task","unexpected":"value"}',
                        ),
                    )
                )

        assert "payload_json 校验失败" in str(exc_info.value)

    def _build_funboost_runtime_overrides(self) -> SettingsOverrideMapping:
        """
        构建 Funboost 运行时覆盖配置。
        """

        return {
            "runtime": {
                "message": {
                    "backend": "rabbitmq",
                    "backend_detail": {
                        "kind": "rabbitmq",
                        "schema_version": "1.0",
                        "rabbitmq_url": RABBITMQ_LOCAL_URL,
                        "startup_probe_enabled": False,
                        "startup_probe_timeout_seconds": 1,
                        "task_exchange_name": "task.direct",
                        "task_exchange_type": "direct",
                        "task_exchange_durable": True,
                        "task_message_persistent": True,
                        "publisher_confirm_enabled": True,
                        "publisher_confirm_timeout_seconds": 5,
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
        }
