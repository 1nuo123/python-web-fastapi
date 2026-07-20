"""
配置应用契约基础设施模块。
"""

from __future__ import annotations

from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

SETTINGS_APPLY_SCHEMA_VERSION: Final = "1.0"
SETTINGS_APPLY_OPERATION_HEADER_KIND: Final = "settings_apply_operation_header"
SETTINGS_APPLY_RESULT_KIND: Final = "settings_apply_result"
HTTP_RESOURCE_SWITCH_DETAIL_KIND: Final = "http_resource_switch"
TASK_REGISTRY_RELOAD_DETAIL_KIND: Final = "task_registry_reload"


class SettingsApplyOperationHeader(BaseModel):
    """
    配置应用公共头字段模型。
    """

    model_config = ConfigDict(extra="forbid")

    header_kind: Literal["settings_apply_operation_header"] = SETTINGS_APPLY_OPERATION_HEADER_KIND
    schema_version: Literal["1.0"] = SETTINGS_APPLY_SCHEMA_VERSION
    operation_name: str
    target_resource: str
    candidate_version: str


class HttpResourceSwitchDetail(BaseModel):
    """
    HTTP 资源切换扩展模型。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["http_resource_switch"] = HTTP_RESOURCE_SWITCH_DETAIL_KIND
    schema_version: Literal["1.0"] = SETTINGS_APPLY_SCHEMA_VERSION
    switched_resources: list[str]
    rollback_resources: list[str]


class TaskRegistryReloadDetail(BaseModel):
    """
    任务注册切换扩展模型。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["task_registry_reload"] = TASK_REGISTRY_RELOAD_DETAIL_KIND
    schema_version: Literal["1.0"] = SETTINGS_APPLY_SCHEMA_VERSION
    registered_job_kinds: list[str]
    restored_job_kinds: list[str]


SettingsApplyDetail = Annotated[
    HttpResourceSwitchDetail | TaskRegistryReloadDetail,
    Field(discriminator="kind"),
]


class SettingsApplyOperationEnvelope(BaseModel):
    """
    配置应用操作信封模型。
    """

    model_config = ConfigDict(extra="forbid")

    header: SettingsApplyOperationHeader
    detail: SettingsApplyDetail


class SettingsApplyResultPayload(BaseModel):
    """
    配置应用结果载荷模型。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["settings_apply_result"] = SETTINGS_APPLY_RESULT_KIND
    schema_version: Literal["1.0"] = SETTINGS_APPLY_SCHEMA_VERSION
    success: bool
    rolled_back: bool
    active_snapshot_id: str | None = None
    restored_resources: list[str] = Field(default_factory=list)
    failure_reason: str | None = None
