"""
任务注册契约测试模块。
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ConfigDict

from src.core.task_contract.task_dispatcher_contract import (
    TaskDispatchDescriptor,
)
from src.core.task_contract.task_registration_contract import (
    FunboostTaskRegistrationDetail,
    LocalTaskRegistrationDetail,
    TaskRegistrationEnvelope,
    TaskRegistrationHeader,
)
from src.core.task_contract.task_runtime_contract import (
    FunboostBrokerKind,
    TaskBackend,
)


class DemoPayload(BaseModel):
    """
    示例载荷模型。
    """

    model_config = ConfigDict(extra="forbid")

    kind: str = "demo"
    schema_version: str = "1.0"


class TestTaskRegistrationContract:
    """
    任务注册契约测试集合。
    """

    def test_task_registration_envelope_when_local_detail_should_validate(self) -> None:
        """
        验证本地注册信封应校验通过。
        """

        envelope = TaskRegistrationEnvelope.model_validate(
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

        assert isinstance(envelope.detail, LocalTaskRegistrationDetail)
        assert envelope.header.backend == TaskBackend.LOCAL

    def test_task_registration_envelope_when_funboost_detail_should_validate(self) -> None:
        """
        验证 Funboost 注册信封应校验通过。
        """

        envelope = TaskRegistrationEnvelope.model_validate(
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
                    "retry_limit": 3,
                    "consumer_worker_count": 2,
                },
            }
        )

        assert isinstance(envelope.detail, FunboostTaskRegistrationDetail)
        assert envelope.detail.broker_kind == FunboostBrokerKind.RABBITMQ_COMPLEX_ROUTING

    def test_task_registration_envelope_when_header_backend_mismatch_should_fail(self) -> None:
        """
        验证注册信封当外层后端与内层类型不一致应失败。
        """

        with pytest.raises(Exception) as exc_info:
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
                        "backend": "funboost",
                    },
                    "detail": {
                        "kind": "local",
                        "schema_version": "1.0",
                        "retry_limit": 1,
                    },
                }
            )

        assert "backend" in str(exc_info.value)

    def test_task_registration_header_when_extra_field_present_should_fail(self) -> None:
        """
        验证注册公共头当出现额外字段应失败。
        """

        with pytest.raises(Exception) as exc_info:
            TaskRegistrationHeader.model_validate(
                {
                    "header_kind": "task_registration_header",
                    "schema_version": "1.0",
                    "task_name": "demo_task",
                    "job_kind": "demo_task",
                    "enabled": True,
                    "backend": "local",
                    "extra_field": "x",
                }
            )

        assert "extra_field" in str(exc_info.value)

    def test_task_dispatch_descriptor_should_validate_header_and_payload(self) -> None:
        """
        验证任务派发描述应能通过校验。
        """

        descriptor = TaskDispatchDescriptor.model_validate(
            {
                "header": {
                    "kind": "task_dispatch_descriptor_header",
                    "schema_version": "1.0",
                    "task_id": "task-1",
                    "created_at_epoch": 1,
                },
                "payload": {
                    "kind": "task_dispatch_descriptor",
                    "schema_version": "1.0",
                    "job_kind": "demo_task",
                    "payload_kind": "DemoPayload",
                    "payload_json": '{"kind":"demo","schema_version":"1.0"}',
                    "deduplication_key": "dedupe-1",
                    "retry_limit": 1,
                },
            }
        )

        assert descriptor.payload.job_kind == "demo_task"
