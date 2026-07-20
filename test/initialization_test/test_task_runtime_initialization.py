"""
任务运行时初始化测试模块。
"""

from __future__ import annotations

import os
from typing import NoReturn

import pytest
from amqpstorm import AMQPError
from fastapi.testclient import TestClient

from src.api.testing.test_app_factory import TestAppFactory
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.http_contract.runtime_resource_contract import RuntimeResourceStatus
from src.core.task_contract.message_bus_contract import MessageBusBackend
from src.core.task_contract.task_runtime_contract import TaskRuntimeMode
from src.infrastructure.task import rabbitmq_message_gateway

RABBITMQ_TEST_URL_ENV = "RABBITMQ_TEST_URL"
RABBITMQ_RUNTIME_URL_ENV = "RABBITMQ_URL"
RABBITMQ_LOCAL_URL = os.getenv(
    RABBITMQ_TEST_URL_ENV,
    "amqp://fastapi_dev:local-dev-rabbitmq-password@127.0.0.1:5672/",
)
RABBITMQ_UNAVAILABLE_URL = "amqp://fastapi_dev:local-dev-rabbitmq-password@127.0.0.1:1/"
RABBITMQ_UNAVAILABLE_MESSAGE = "模拟 RabbitMQ 不可用。"


class UnavailableRabbitMqConnectionFactory:
    """提供不触发真实网络连接的 RabbitMQ 失败替身。"""

    def __call__(self, *_args: object, **_kwargs: object) -> NoReturn:
        """稳定抛出 AMQP 连接异常。"""

        raise AMQPError(RABBITMQ_UNAVAILABLE_MESSAGE)


class TestTaskRuntimeInitialization:
    """
    任务运行时初始化测试集合。
    """

    def test_startup_when_local_backend_should_mark_task_resource_ready(self) -> None:
        """
        验证启动当本地任务后端启用应标记任务资源就绪。
        """

        app = TestAppFactory().create()

        with TestClient(app):
            states = {
                state.resource_name: state
                for state in app.state.container.resource_mount.get_runtime_states()
            }
            task_state = states["shared_task_dispatcher"]
            assert task_state.status == RuntimeResourceStatus.READY
            assert (
                app.state.container.resource_mount.get_current_task_runtime_mode()
                == TaskRuntimeMode.LOCAL_INLINE
            )
            assert app.state.container.resource_mount.get_task_bootstrap_snapshot() is not None

    def test_startup_when_funboost_backend_should_mark_task_resource_ready(self) -> None:
        """
        验证启动当 Funboost 任务后端启用应标记任务资源就绪。
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
            states = {
                state.resource_name: state
                for state in app.state.container.resource_mount.get_runtime_states()
            }
            task_state = states["shared_task_dispatcher"]
            message_state = states["shared_task_message_transport"]
            assert task_state.status == RuntimeResourceStatus.READY
            assert message_state.status == RuntimeResourceStatus.READY
            assert "rabbitmq task message transport" in str(message_state.detail)
            assert "funboost rabbitmq broker" in str(message_state.detail)
            assert (
                app.state.container.resource_mount.get_task_message_transport().backend
                == MessageBusBackend.RABBITMQ
            )
            assert (
                app.state.container.resource_mount.get_current_task_runtime_mode()
                == TaskRuntimeMode.FUNBOOST_PRODUCER
            )
            with pytest.raises(HttpFaultException):
                app.state.container.resource_mount.list_local_task_messages()

    def test_startup_when_local_backend_should_expose_local_message_list(self) -> None:
        """
        验证本地消息总线会显式暴露本地消息列表。
        """

        app = TestAppFactory().create()

        with TestClient(app):
            messages = app.state.container.resource_mount.list_local_task_messages()

        assert messages == []

    def test_startup_when_local_task_with_rabbitmq_message_should_fail(self) -> None:
        """
        验证本地任务后端禁止搭配 RabbitMQ 消息总线。
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
                    }
                }
            }
        )

        with pytest.raises(HttpFaultException) as exc_info:
            with TestClient(app):
                pass

        assert "本地任务后端禁止搭配 RabbitMQ 消息总线" in str(exc_info.value)

    def test_startup_when_rabbitmq_probe_fail_should_record_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        验证启动期 RabbitMQ 探测失败应记录失败任务。
        """

        monkeypatch.delenv(RABBITMQ_RUNTIME_URL_ENV, raising=False)
        monkeypatch.setattr(
            rabbitmq_message_gateway,
            "UriConnection",
            UnavailableRabbitMqConnectionFactory(),
        )
        app = TestAppFactory().create(
            overrides={
                "runtime": {
                    "message": {
                        "backend": "rabbitmq",
                        "backend_detail": {
                            "kind": "rabbitmq",
                            "schema_version": "1.0",
                            "rabbitmq_url": RABBITMQ_UNAVAILABLE_URL,
                            "startup_probe_enabled": True,
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

        with pytest.raises(HttpFaultException):
            with TestClient(app):
                pass

        records = app.state.container.resource_mount.get_failed_task_recorder().list_records()
        assert len(records) == 1
        assert records[0].message == "RabbitMQ 启动探测失败。"
