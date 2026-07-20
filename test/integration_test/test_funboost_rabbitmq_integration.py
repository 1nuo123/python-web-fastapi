"""
Funboost RabbitMQ 集成测试模块。
"""

from __future__ import annotations

import json
import os
from threading import Event
from time import monotonic, sleep
from typing import Protocol
from uuid import uuid4

import psycopg
import pytest
from amqpstorm import UriConnection
from fastapi.testclient import TestClient
from psycopg import sql
from pydantic import BaseModel, ConfigDict

from src.api.asgi_entry import create_app
from src.api.task_binding_provider import (
    TASK_EXECUTION_PROBE_JOB_KIND,
    ApplicationTaskBindingProvider,
)
from src.api.testing.test_app_factory import TestAppFactory
from src.application.dispatch_background_job_usecase import TaskDispatchCommand
from src.application.task.task_execution_probe_handler import TaskExecutionProbePayload
from src.cli.run_task_worker import TASK_WORKER_SETTINGS_OVERRIDES
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.task_contract.message_bus_contract import (
    TaskMessageEnvelope,
    TaskMessageHeader,
    TaskMessagePayload,
)
from src.core.task_contract.task_execution_record_contract import (
    TaskExecutionRecordEnvelope,
    TaskExecutionStatus,
)
from src.core.task_contract.task_handler_contract import TaskHandler
from src.core.task_contract.task_invocation_contract import TypedTaskInvocation
from src.core.task_contract.task_runtime_contract import RabbitMqMessageBackendDetail
from src.infrastructure.persistence.orm_model.key_ring_snapshot_orm_model import (
    KEY_RING_SNAPSHOT_TABLE_NAME,
)
from src.infrastructure.settings.application_settings import AppEnvironment
from src.infrastructure.task.rabbitmq_message_bus import (
    RABBITMQ_CONTENT_TYPE_JSON,
    RABBITMQ_DELIVERY_MODE_PERSISTENT,
    RABBITMQ_HEADER_REQUEST_ID,
    RABBITMQ_HEADER_TRACE_ID,
    RabbitMqMessageBus,
)
from src.infrastructure.task.rabbitmq_message_gateway import RabbitMqMessageGateway
from src.infrastructure.task.task_registration_registry import RegisteredTaskBinding

RABBITMQ_TEST_URL_ENV = "RABBITMQ_TEST_URL"
RABBITMQ_LOCAL_URL = os.getenv(
    RABBITMQ_TEST_URL_ENV,
    "amqp://fastapi_dev:local-dev-rabbitmq-password@127.0.0.1:5672/",
)
RABBITMQ_PUBLISH_TEST_EXCHANGE_PREFIX = "task.integration.message_bus"
RABBITMQ_PUBLISH_TEST_QUEUE_PREFIX = "task.integration.message_bus.queue"
RABBITMQ_PUBLISH_TEST_EXCHANGE_TYPE = "direct"
RABBITMQ_PUBLISH_TEST_TIMEOUT_SECONDS = 5
RABBITMQ_PUBLISH_TEST_RETRY_LIMIT = 1
RABBITMQ_PUBLISH_TEST_CREATED_AT_EPOCH = 1700000000
RABBITMQ_PUBLISH_TEST_PAYLOAD_KIND = "RabbitMqIntegrationPayload"
RABBITMQ_PUBLISH_TEST_PAYLOAD_JSON = '{"kind":"rabbitmq_integration","schema_version":"1.0"}'
RABBITMQ_PUBLISH_TEST_DEDUPLICATION_PREFIX = "rabbitmq-integration-dedupe"
RABBITMQ_EMPTY_MESSAGE = None
FUNBOOST_JOB_KIND = "demo_task_funboost"
FUNBOOST_TEST_QUEUE_NAME = "demo_task_funboost_queue_test"
FUNBOOST_PRODUCTION_QUEUE_NAME = "task.execution.probe"
FUNBOOST_PRODUCTION_ROUTING_KEY = "task.execution.probe"
FUNBOOST_DEDUPLICATION_KEY_PREFIX = "integration-rabbitmq-dedupe"
FUNBOOST_CONSUME_TIMEOUT_SECONDS = 15
FUNBOOST_STATUS_POLL_INTERVAL_SECONDS = 0.01
PRODUCTION_TEST_JWT_SECRET = "production-valid-secret-7f6d0c4b9a2e8d1c"
PRODUCTION_TEST_ADMIN_PASSWORD = "production-test-admin-password"
RABBITMQ_URL_ENVIRONMENT_VARIABLE = "RABBITMQ_URL"
JWT_SECRET_ENVIRONMENT_VARIABLE = "JWT_SECRET"
BOOTSTRAP_ADMIN_PASSWORD_ENVIRONMENT_VARIABLE = "AUTH_BOOTSTRAP_ADMIN_PASSWORD"
pytestmark = [
    pytest.mark.integration,
    pytest.mark.rabbitmq,
]


class DemoTaskPayload(BaseModel):
    """
    示例任务载荷。
    """

    model_config = ConfigDict(extra="forbid")

    kind: str = "demo_task"
    schema_version: str = "1.0"
    task_id: str = "integration-rabbitmq-task"


class DemoTaskHandler(TaskHandler[DemoTaskPayload]):
    """
    示例任务处理器。
    """

    def handle(self, invocation: TypedTaskInvocation[DemoTaskPayload]) -> None:
        _ = invocation
        return None


class ObservedDemoTaskHandler(TaskHandler[DemoTaskPayload]):
    """可观测的真实消费处理器。"""

    def __init__(self) -> None:
        """初始化消费完成事件。"""

        self.completed = Event()

    def handle(self, invocation: TypedTaskInvocation[DemoTaskPayload]) -> None:
        """记录真实消息已进入处理器。"""

        _ = invocation.payload.task_id
        self.completed.set()


class TaskRecordReader(Protocol):
    """任务执行记录读取边界。"""

    def get_task_execution_record(
        self,
        task_id: str,
    ) -> TaskExecutionRecordEnvelope | None:
        """按任务标识读取执行记录。"""


class TestFunboostRabbitMqIntegration:
    """
    Funboost RabbitMQ 集成测试集合。
    """

    def test_rabbitmq_gateway_when_runtime_available_should_pass_probe(self) -> None:
        """
        验证 RabbitMQ 网关当运行时可达应通过探测。
        """

        gateway = RabbitMqMessageGateway(RABBITMQ_LOCAL_URL)
        health = gateway.assert_available(timeout_seconds=3)

        assert health.connected is True

    def test_rabbitmq_message_bus_should_publish_to_real_broker(self) -> None:
        """
        验证 RabbitMQ 独立消息总线会把消息发布到真实 broker。
        """

        unique_suffix = uuid4().hex
        exchange_name = f"{RABBITMQ_PUBLISH_TEST_EXCHANGE_PREFIX}.{unique_suffix}"
        queue_name = f"{RABBITMQ_PUBLISH_TEST_QUEUE_PREFIX}.{unique_suffix}"
        message = self._build_rabbitmq_message(job_kind=queue_name)
        gateway = RabbitMqMessageGateway(RABBITMQ_LOCAL_URL)
        connection = UriConnection(
            gateway.build_connection_uri(timeout_seconds=RABBITMQ_PUBLISH_TEST_TIMEOUT_SECONDS)
        )
        channel = connection.channel(rpc_timeout=RABBITMQ_PUBLISH_TEST_TIMEOUT_SECONDS)
        bus = RabbitMqMessageBus(detail=self._build_rabbitmq_message_detail(exchange_name))
        try:
            channel.exchange.declare(
                exchange=exchange_name,
                exchange_type=RABBITMQ_PUBLISH_TEST_EXCHANGE_TYPE,
                durable=True,
            )
            channel.queue.declare(queue=queue_name, durable=False, exclusive=False)
            channel.queue.bind(
                queue=queue_name,
                exchange=exchange_name,
                routing_key=queue_name,
            )

            bus.publish(message)
            broker_message = channel.basic.get(queue=queue_name, no_ack=True)

            assert broker_message is not RABBITMQ_EMPTY_MESSAGE
            assert json.loads(broker_message.body)["header"]["message_id"] == (
                message.header.message_id
            )
            assert broker_message.properties["content_type"] == RABBITMQ_CONTENT_TYPE_JSON
            assert broker_message.properties["delivery_mode"] == RABBITMQ_DELIVERY_MODE_PERSISTENT
            assert broker_message.properties["message_id"] == message.header.message_id
            assert broker_message.properties["correlation_id"] == message.header.request_id
            assert (
                broker_message.properties["headers"][RABBITMQ_HEADER_REQUEST_ID]
                == message.header.request_id
            )
            assert (
                broker_message.properties["headers"][RABBITMQ_HEADER_TRACE_ID]
                == message.header.trace_id
            )
        finally:
            bus.close()
            try:
                channel.queue.delete(queue=queue_name)
            finally:
                try:
                    channel.exchange.delete(exchange=exchange_name)
                finally:
                    channel.close()
                    connection.close()

    def test_app_when_funboost_worker_disabled_should_publish_dispatch(self) -> None:
        """
        验证 Funboost worker 禁用时仍可作为 producer-only 节点发布任务。
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
                            "startup_probe_enabled": True,
                            "startup_probe_timeout_seconds": 3,
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
            },
            task_bindings=[
                RegisteredTaskBinding(
                    job_kind="demo_task_funboost",
                    payload_model=DemoTaskPayload,
                    handler=DemoTaskHandler(),
                )
            ],
        )

        deduplication_key = f"{FUNBOOST_DEDUPLICATION_KEY_PREFIX}-{uuid4()}"

        try:
            with TestClient(app):
                result = app.state.container.dispatch_background_job_usecase.execute(
                    TaskDispatchCommand(
                        payload=DemoTaskPayload(),
                        job_kind=FUNBOOST_JOB_KIND,
                        deduplication_key=deduplication_key,
                    )
                )
        finally:
            self._purge_funboost_queue()

        assert result.dispatched is True
        assert result.published is True
        assert result.worker_enabled is False

    def test_app_when_funboost_worker_enabled_should_complete_consume_loop(self) -> None:
        """验证生产 Funboost 主链完成持久发布、确认、消费与状态回写。"""

        self._purge_funboost_queue()
        handler = ObservedDemoTaskHandler()
        app = TestAppFactory().create(
            overrides={
                "runtime": {
                    "message": {
                        "backend": "rabbitmq",
                        "backend_detail": {
                            "kind": "rabbitmq",
                            "schema_version": "1.0",
                            "rabbitmq_url": RABBITMQ_LOCAL_URL,
                            "startup_probe_enabled": True,
                            "startup_probe_timeout_seconds": 5,
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
                        "worker_enabled": True,
                        "backend_detail": {
                            "kind": "funboost",
                            "schema_version": "1.0",
                            "broker_kind": "RABBITMQ_COMPLEX_ROUTING",
                        },
                    },
                }
            },
            task_bindings=[
                RegisteredTaskBinding(
                    job_kind=FUNBOOST_JOB_KIND,
                    payload_model=DemoTaskPayload,
                    handler=handler,
                )
            ],
        )
        deduplication_key = f"{FUNBOOST_DEDUPLICATION_KEY_PREFIX}-{uuid4()}"

        try:
            with TestClient(app):
                result = app.state.container.dispatch_background_job_usecase.execute(
                    TaskDispatchCommand(
                        payload=DemoTaskPayload(),
                        job_kind=FUNBOOST_JOB_KIND,
                        deduplication_key=deduplication_key,
                    )
                )
                completed = handler.completed.wait(timeout=FUNBOOST_CONSUME_TIMEOUT_SECONDS)
                record = self._wait_for_task_status(
                    resource_mount=app.state.container.resource_mount,
                    task_id=result.task_id,
                    expected_status=TaskExecutionStatus.SUCCESS,
                )
        finally:
            self._purge_funboost_queue()

        assert completed is True
        assert record is not None
        assert record.detail.status == TaskExecutionStatus.SUCCESS

    def test_production_binding_should_complete_real_rabbitmq_state_writeback(self) -> None:
        """验证 production 注册、应用绑定和真实 worker 完成状态回写闭环。"""

        deduplication_key = f"production-probe-{uuid4().hex}"
        app = TestAppFactory().create(
            overrides={
                "task_module": {
                    "default_retry_limit": 3,
                    "default_job_kind": TASK_EXECUTION_PROBE_JOB_KIND,
                    "registrations": [
                        {
                            "envelope_kind": "task_registration_envelope",
                            "schema_version": "1.0",
                            "header": {
                                "header_kind": "task_registration_header",
                                "schema_version": "1.0",
                                "task_name": TASK_EXECUTION_PROBE_JOB_KIND,
                                "job_kind": TASK_EXECUTION_PROBE_JOB_KIND,
                                "enabled": True,
                                "backend": "funboost",
                            },
                            "detail": {
                                "kind": "funboost",
                                "schema_version": "1.0",
                                "queue_name": FUNBOOST_PRODUCTION_QUEUE_NAME,
                                "exchange_name": "task.direct",
                                "routing_key": FUNBOOST_PRODUCTION_ROUTING_KEY,
                                "broker_kind": "RABBITMQ_COMPLEX_ROUTING",
                                "retry_limit": 3,
                                "consumer_worker_count": 2,
                            },
                        }
                    ],
                },
                "runtime": {
                    "message": {
                        "backend": "rabbitmq",
                        "backend_detail": {
                            "kind": "rabbitmq",
                            "schema_version": "1.0",
                            "rabbitmq_url": RABBITMQ_LOCAL_URL,
                            "startup_probe_enabled": True,
                            "startup_probe_timeout_seconds": 5,
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
                        "worker_enabled": True,
                        "backend_detail": {
                            "kind": "funboost",
                            "schema_version": "1.0",
                            "broker_kind": "RABBITMQ_COMPLEX_ROUTING",
                        },
                    },
                },
            },
            task_bindings=ApplicationTaskBindingProvider().build(),
        )

        try:
            with TestClient(app):
                result = app.state.container.dispatch_background_job_usecase.execute(
                    TaskDispatchCommand(
                        payload=TaskExecutionProbePayload(probe_id=deduplication_key),
                        job_kind=TASK_EXECUTION_PROBE_JOB_KIND,
                        deduplication_key=deduplication_key,
                    )
                )
                record = self._wait_for_task_status(
                    resource_mount=app.state.container.resource_mount,
                    task_id=result.task_id,
                    expected_status=TaskExecutionStatus.SUCCESS,
                )
        finally:
            self._purge_funboost_queue(queue_name=FUNBOOST_PRODUCTION_QUEUE_NAME)

        assert result.published is True
        assert record.detail.status == TaskExecutionStatus.SUCCESS

    @pytest.mark.postgres
    @pytest.mark.redis
    def test_production_config_worker_should_complete_real_rabbitmq_state_writeback(
        self,
        integration_database: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """验证真实 production 配置链、应用绑定和 worker 状态回写闭环。"""

        _ = integration_database
        monkeypatch.setenv(RABBITMQ_URL_ENVIRONMENT_VARIABLE, RABBITMQ_LOCAL_URL)
        monkeypatch.setenv(JWT_SECRET_ENVIRONMENT_VARIABLE, PRODUCTION_TEST_JWT_SECRET)
        monkeypatch.setenv(
            BOOTSTRAP_ADMIN_PASSWORD_ENVIRONMENT_VARIABLE,
            PRODUCTION_TEST_ADMIN_PASSWORD,
        )
        deduplication_key = f"production-config-probe-{uuid4().hex}"
        self._purge_funboost_queue(queue_name=FUNBOOST_PRODUCTION_QUEUE_NAME)
        self._delete_key_ring_snapshots(integration_database)

        try:
            app = create_app(
                environment=AppEnvironment.PRODUCTION,
                settings_overrides=TASK_WORKER_SETTINGS_OVERRIDES,
            )
            with TestClient(app):
                settings_snapshot = (
                    app.state.container.resource_mount.read_application_settings_snapshot()
                )
                result = app.state.container.dispatch_background_job_usecase.execute(
                    TaskDispatchCommand(
                        payload=TaskExecutionProbePayload(probe_id=deduplication_key),
                        job_kind=TASK_EXECUTION_PROBE_JOB_KIND,
                        deduplication_key=deduplication_key,
                    )
                )
                record = self._wait_for_task_status(
                    resource_mount=app.state.container.resource_mount,
                    task_id=result.task_id,
                    expected_status=TaskExecutionStatus.SUCCESS,
                )
        finally:
            self._purge_funboost_queue(queue_name=FUNBOOST_PRODUCTION_QUEUE_NAME)
            self._delete_key_ring_snapshots(integration_database)

        assert settings_snapshot.environment == AppEnvironment.PRODUCTION.value
        assert result.published is True
        assert record.detail.status == TaskExecutionStatus.SUCCESS

    def test_funboost_consumer_when_payload_invalid_should_fail_before_handler(self) -> None:
        """
        验证 Funboost 消费侧当载荷非法应提前失败。
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
                            "startup_probe_timeout_seconds": 3,
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
            },
            task_bindings=[
                RegisteredTaskBinding(
                    job_kind="demo_task_funboost",
                    payload_model=DemoTaskPayload,
                    handler=DemoTaskHandler(),
                )
            ],
        )

        with TestClient(app):
            dispatcher = app.state.container.resource_mount.get_task_dispatcher()
            bootstrapper = dispatcher._bootstrapper  # noqa: SLF001
            bootstrapper.register_consumer(FUNBOOST_JOB_KIND)
            booster = bootstrapper._booster_by_job_kind[FUNBOOST_JOB_KIND]  # noqa: SLF001
            consume_function = booster.consuming_function

            with pytest.raises(HttpFaultException) as exc_info:
                consume_function(
                    {
                        "header": {
                            "message_id": "funboost-invalid-task",
                            "created_at_epoch": 1,
                        },
                        "payload": {
                            "job_kind": "demo_task_funboost",
                            "deduplication_key": "funboost-invalid-dedupe",
                            "retry_limit": 1,
                            "payload_kind": DemoTaskPayload.__name__,
                            "payload_json": '{"kind":"demo_task","unexpected":"value"}',
                        },
                    }
                )

        assert "payload_json 校验失败" in str(exc_info.value)

    def _build_rabbitmq_message_detail(
        self,
        exchange_name: str,
    ) -> RabbitMqMessageBackendDetail:
        """
        构建 RabbitMQ 消息总线集成测试配置。
        """

        return RabbitMqMessageBackendDetail(
            rabbitmq_url=RABBITMQ_LOCAL_URL,
            startup_probe_enabled=False,
            startup_probe_timeout_seconds=RABBITMQ_PUBLISH_TEST_TIMEOUT_SECONDS,
            task_exchange_name=exchange_name,
            task_exchange_type=RABBITMQ_PUBLISH_TEST_EXCHANGE_TYPE,
            task_exchange_durable=True,
            task_message_persistent=True,
            publisher_confirm_enabled=True,
            publisher_confirm_timeout_seconds=RABBITMQ_PUBLISH_TEST_TIMEOUT_SECONDS,
        )

    def _purge_funboost_queue(self, queue_name: str = FUNBOOST_TEST_QUEUE_NAME) -> None:
        """清理 Funboost 集成测试队列并释放 AMQP 资源。"""

        gateway = RabbitMqMessageGateway(RABBITMQ_LOCAL_URL)
        connection = UriConnection(
            gateway.build_connection_uri(timeout_seconds=RABBITMQ_PUBLISH_TEST_TIMEOUT_SECONDS)
        )
        channel = connection.channel(rpc_timeout=RABBITMQ_PUBLISH_TEST_TIMEOUT_SECONDS)
        try:
            channel.queue.purge(queue=queue_name)
        finally:
            channel.close()
            connection.close()

    @staticmethod
    def _delete_key_ring_snapshots(database_url: str) -> None:
        """隔离并清理 production 密钥派生测试产生的数据库快照。"""

        connection_url = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        with psycopg.connect(connection_url, autocommit=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL("DELETE FROM {}").format(sql.Identifier(KEY_RING_SNAPSHOT_TABLE_NAME))
                )

    def _wait_for_task_status(
        self,
        *,
        resource_mount: TaskRecordReader,
        task_id: str,
        expected_status: TaskExecutionStatus,
    ) -> TaskExecutionRecordEnvelope:
        """等待任务执行记录进入目标状态。"""

        deadline = monotonic() + FUNBOOST_CONSUME_TIMEOUT_SECONDS
        last_record: TaskExecutionRecordEnvelope | None = None
        while monotonic() < deadline:
            last_record = resource_mount.get_task_execution_record(task_id)
            if last_record is not None and last_record.detail.status == expected_status:
                return last_record
            sleep(FUNBOOST_STATUS_POLL_INTERVAL_SECONDS)
        observed_status = last_record.detail.status if last_record is not None else None
        raise AssertionError(f"任务执行记录未在超时前进入目标状态，最后状态：{observed_status}。")

    def _build_rabbitmq_message(self, *, job_kind: str) -> TaskMessageEnvelope:
        """
        构建 RabbitMQ 消息总线集成测试消息。
        """

        message_id = f"rabbitmq-integration-message-{uuid4().hex}"
        request_id = f"rabbitmq-integration-request-{uuid4().hex}"
        trace_id = f"rabbitmq-integration-trace-{uuid4().hex}"
        return TaskMessageEnvelope(
            header=TaskMessageHeader(
                message_id=message_id,
                request_id=request_id,
                trace_id=trace_id,
                created_at_epoch=RABBITMQ_PUBLISH_TEST_CREATED_AT_EPOCH,
            ),
            payload=TaskMessagePayload(
                job_kind=job_kind,
                deduplication_key=(f"{RABBITMQ_PUBLISH_TEST_DEDUPLICATION_PREFIX}-{uuid4().hex}"),
                retry_limit=RABBITMQ_PUBLISH_TEST_RETRY_LIMIT,
                payload_kind=RABBITMQ_PUBLISH_TEST_PAYLOAD_KIND,
                payload_json=RABBITMQ_PUBLISH_TEST_PAYLOAD_JSON,
            ),
        )
