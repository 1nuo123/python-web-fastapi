"""
任务注册契约核心模块。
"""

from __future__ import annotations

from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.core.task_contract.task_runtime_contract import (
    EXCHANGE_NAME_MINIMUM_LENGTH,
    FUNBOOST_TASK_BACKEND_KIND,
    LOCAL_TASK_BACKEND_KIND,
    QUEUE_NAME_MINIMUM_LENGTH,
    RETRY_LIMIT_MINIMUM,
    ROUTING_KEY_MINIMUM_LENGTH,
    WORKER_COUNT_MINIMUM,
    FunboostBrokerKind,
    TaskBackend,
)

TASK_REGISTRATION_SCHEMA_VERSION: Final = "1.0"
TASK_REGISTRATION_HEADER_KIND: Final = "task_registration_header"
TASK_REGISTRATION_ENVELOPE_KIND: Final = "task_registration_envelope"
TASK_NAME_MINIMUM_LENGTH = 1
JOB_KIND_MINIMUM_LENGTH = 1


class TaskRegistrationHeader(BaseModel):
    """
    任务注册公共头字段模型。
    """

    model_config = ConfigDict(extra="forbid")

    header_kind: Literal["task_registration_header"] = TASK_REGISTRATION_HEADER_KIND
    schema_version: Literal["1.0"] = TASK_REGISTRATION_SCHEMA_VERSION
    task_name: str = Field(min_length=TASK_NAME_MINIMUM_LENGTH)
    job_kind: str = Field(min_length=JOB_KIND_MINIMUM_LENGTH)
    enabled: bool
    backend: TaskBackend


class LocalTaskRegistrationDetail(BaseModel):
    """
    本地任务注册扩展配置。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["local"] = LOCAL_TASK_BACKEND_KIND
    schema_version: Literal["1.0"] = TASK_REGISTRATION_SCHEMA_VERSION
    retry_limit: int = Field(ge=RETRY_LIMIT_MINIMUM)


class FunboostTaskRegistrationDetail(BaseModel):
    """
    Funboost 任务注册扩展配置。

    当前快速开发阶段已生效字段：``queue_name``、``exchange_name``、``routing_key``、
    ``broker_kind``、``retry_limit``、``consumer_worker_count``。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["funboost"] = FUNBOOST_TASK_BACKEND_KIND
    schema_version: Literal["1.0"] = TASK_REGISTRATION_SCHEMA_VERSION
    queue_name: str = Field(min_length=QUEUE_NAME_MINIMUM_LENGTH)
    exchange_name: str = Field(min_length=EXCHANGE_NAME_MINIMUM_LENGTH)
    routing_key: str = Field(min_length=ROUTING_KEY_MINIMUM_LENGTH)
    broker_kind: FunboostBrokerKind
    retry_limit: int = Field(ge=RETRY_LIMIT_MINIMUM)
    consumer_worker_count: int = Field(ge=WORKER_COUNT_MINIMUM)


TaskRegistrationDetailUnion = Annotated[
    LocalTaskRegistrationDetail | FunboostTaskRegistrationDetail,
    Field(discriminator="kind"),
]


class TaskRegistrationEnvelope(BaseModel):
    """
    任务注册信封模型。
    """

    model_config = ConfigDict(extra="forbid")

    envelope_kind: Literal["task_registration_envelope"] = TASK_REGISTRATION_ENVELOPE_KIND
    schema_version: Literal["1.0"] = TASK_REGISTRATION_SCHEMA_VERSION
    header: TaskRegistrationHeader
    detail: TaskRegistrationDetailUnion

    @model_validator(mode="after")
    def validate_detail_contract(self) -> TaskRegistrationEnvelope:
        """
        校验公共头字段与扩展字段的一致性。
        :returns: 当前模型实例。
        :rtype: TaskRegistrationEnvelope
        :raises ValueError: 当外层与内层不一致时抛出。
        """

        if self.header.backend.value != self.detail.kind:
            raise ValueError("任务注册 backend 必须与 detail.kind 一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("任务注册 schema_version 必须与 detail.schema_version 一致。")
        if self.schema_version != self.detail.schema_version:
            raise ValueError("任务注册信封 schema_version 必须与 detail.schema_version 一致。")
        return self
