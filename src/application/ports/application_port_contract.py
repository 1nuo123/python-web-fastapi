"""
应用端口契约模型。
"""

from __future__ import annotations

from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

APPLICATION_PORT_SCHEMA_VERSION: Final = "1.0"
AUTH_RUNTIME_PORT_KIND: Final = "auth_runtime_port"
SETTINGS_READER_PORT_KIND: Final = "settings_reader_port"
TASK_RUNTIME_PORT_KIND: Final = "task_runtime_port"


class ApplicationPortHeader(BaseModel):
    """
    应用端口公共头。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal[
        "auth_runtime_port",
        "settings_reader_port",
        "task_runtime_port",
    ]
    schema_version: Literal["1.0"] = APPLICATION_PORT_SCHEMA_VERSION
    port_name: str


class AuthRuntimePortDetail(BaseModel):
    """
    鉴权运行时端口扩展。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["auth_runtime_port"] = AUTH_RUNTIME_PORT_KIND
    schema_version: Literal["1.0"] = APPLICATION_PORT_SCHEMA_VERSION


class SettingsReaderPortDetail(BaseModel):
    """
    配置读取端口扩展。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["settings_reader_port"] = SETTINGS_READER_PORT_KIND
    schema_version: Literal["1.0"] = APPLICATION_PORT_SCHEMA_VERSION
    snapshot_read_enabled: bool = True


class TaskRuntimePortDetail(BaseModel):
    """
    任务运行时端口扩展。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["task_runtime_port"] = TASK_RUNTIME_PORT_KIND
    schema_version: Literal["1.0"] = APPLICATION_PORT_SCHEMA_VERSION
    dispatch_enabled: bool = True
    registration_read_enabled: bool = True


ApplicationPortDetail = Annotated[
    AuthRuntimePortDetail | SettingsReaderPortDetail | TaskRuntimePortDetail,
    Field(discriminator="kind"),
]


class ApplicationPortEnvelope(BaseModel):
    """
    应用端口信封。
    """

    model_config = ConfigDict(extra="forbid")

    header: ApplicationPortHeader
    detail: ApplicationPortDetail

    @model_validator(mode="after")
    def validate_application_port_contract(self) -> ApplicationPortEnvelope:
        """
        校验应用端口公共头与扩展字段一致。
        """

        if self.header.kind != self.detail.kind:
            raise ValueError("应用端口 header.kind 必须与 detail.kind 一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("应用端口 header.schema_version 必须与 detail.schema_version 一致。")
        return self
