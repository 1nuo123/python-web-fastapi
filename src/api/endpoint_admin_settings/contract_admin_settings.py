"""
管理员配置热更新 HTTP 契约。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.application.ports.admin_settings_reload_port import (
    AdminSettingsReloadCandidateSnapshot,
    AdminSettingsReloadResultSnapshot,
)

ADMIN_SETTINGS_RELOAD_SCHEMA_VERSION: Final = "1.0"
ADMIN_SETTINGS_RELOAD_CANDIDATE_KIND: Final = "admin_settings_reload_candidate"
ADMIN_SETTINGS_RELOAD_REQUEST_KIND: Final = "admin_settings_reload"
ADMIN_SETTINGS_RELOAD_RESULT_KIND: Final = "admin_settings_reload_result"


class AdminSettingsReloadOperationName(StrEnum):
    """
    管理员配置热更新操作名称枚举。
    """

    READ_CANDIDATE = "read_candidate"
    APPLY_RELOAD = "apply_reload"
    RELOAD_RESULT = "reload_result"


class AdminSettingsReloadKind(StrEnum):
    """
    管理员配置热更新载荷类型枚举。
    """

    CANDIDATE = ADMIN_SETTINGS_RELOAD_CANDIDATE_KIND
    REQUEST = ADMIN_SETTINGS_RELOAD_REQUEST_KIND
    RESULT = ADMIN_SETTINGS_RELOAD_RESULT_KIND


class AdminSettingsReloadHeader(BaseModel):
    """
    管理员配置热更新公共头。
    """

    model_config = ConfigDict(extra="forbid")

    kind: AdminSettingsReloadKind
    schema_version: Literal["1.0"] = ADMIN_SETTINGS_RELOAD_SCHEMA_VERSION
    operation_name: AdminSettingsReloadOperationName


class AdminSettingsReloadCandidatePayload(BaseModel):
    """
    管理员配置热更新候选载荷。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_settings_reload_candidate"] = ADMIN_SETTINGS_RELOAD_CANDIDATE_KIND
    schema_version: Literal["1.0"] = ADMIN_SETTINGS_RELOAD_SCHEMA_VERSION
    candidate_version: str
    digest: str

    @classmethod
    def from_candidate(
        cls,
        candidate: AdminSettingsReloadCandidateSnapshot,
    ) -> AdminSettingsReloadCandidatePayload:
        """
        从配置热更新候选载荷构建管理员载荷。

        :param candidate: 配置热更新候选载荷。
        :type candidate: AdminSettingsReloadCandidateSnapshot
        :returns: 管理员配置热更新候选载荷。
        :rtype: AdminSettingsReloadCandidatePayload
        """

        return cls(
            candidate_version=candidate.candidate_version,
            digest=candidate.digest,
        )


class AdminSettingsReloadRequestDetail(BaseModel):
    """
    管理员配置热更新请求扩展字段。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_settings_reload"] = ADMIN_SETTINGS_RELOAD_REQUEST_KIND
    schema_version: Literal["1.0"] = ADMIN_SETTINGS_RELOAD_SCHEMA_VERSION


class AdminSettingsReloadResultPayload(BaseModel):
    """
    管理员配置热更新结果载荷。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_settings_reload_result"] = ADMIN_SETTINGS_RELOAD_RESULT_KIND
    schema_version: Literal["1.0"] = ADMIN_SETTINGS_RELOAD_SCHEMA_VERSION
    success: bool
    rolled_back: bool
    reason: str | None
    candidate_version: str | None
    restored_resources: list[str] = Field(default_factory=list)
    active_snapshot_id: str | None

    @classmethod
    def from_result(
        cls,
        result: AdminSettingsReloadResultSnapshot,
    ) -> AdminSettingsReloadResultPayload:
        """
        从配置热更新结果构建管理员载荷。

        :param result: 配置热更新结果。
        :type result: AdminSettingsReloadResultSnapshot
        :returns: 管理员配置热更新结果载荷。
        :rtype: AdminSettingsReloadResultPayload
        """

        return cls(
            success=result.success,
            rolled_back=result.rolled_back,
            reason=result.reason,
            candidate_version=result.candidate_version,
            restored_resources=result.restored_resources,
            active_snapshot_id=result.active_snapshot_id,
        )


AdminSettingsReloadCandidateDetail = Annotated[
    AdminSettingsReloadCandidatePayload,
    Field(discriminator="kind"),
]
AdminSettingsReloadRequestDetailUnion = Annotated[
    AdminSettingsReloadRequestDetail,
    Field(discriminator="kind"),
]
AdminSettingsReloadResultDetail = Annotated[
    AdminSettingsReloadResultPayload,
    Field(discriminator="kind"),
]


class AdminSettingsReloadCandidateEnvelope(BaseModel):
    """
    管理员配置热更新候选信封。
    """

    model_config = ConfigDict(extra="forbid")

    header: AdminSettingsReloadHeader
    detail: AdminSettingsReloadCandidateDetail

    @model_validator(mode="after")
    def validate_detail_contract(self) -> AdminSettingsReloadCandidateEnvelope:
        """
        校验配置热更新候选公共头与扩展字段一致。

        :returns: 当前信封。
        :rtype: AdminSettingsReloadCandidateEnvelope
        """

        if self.header.kind.value != self.detail.kind:
            raise ValueError("配置热更新候选 header.kind 必须与 detail.kind 一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("配置热更新候选 schema_version 必须一致。")
        return self


class AdminSettingsReloadRequestEnvelope(BaseModel):
    """
    管理员配置热更新请求信封。
    """

    model_config = ConfigDict(extra="forbid")

    header: AdminSettingsReloadHeader
    detail: AdminSettingsReloadRequestDetailUnion

    @model_validator(mode="after")
    def validate_detail_contract(self) -> AdminSettingsReloadRequestEnvelope:
        """
        校验配置热更新请求公共头与扩展字段一致。

        :returns: 当前信封。
        :rtype: AdminSettingsReloadRequestEnvelope
        """

        if self.header.kind.value != self.detail.kind:
            raise ValueError("配置热更新请求 header.kind 必须与 detail.kind 一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("配置热更新请求 schema_version 必须一致。")
        return self


class AdminSettingsReloadResultEnvelope(BaseModel):
    """
    管理员配置热更新结果信封。
    """

    model_config = ConfigDict(extra="forbid")

    header: AdminSettingsReloadHeader
    detail: AdminSettingsReloadResultDetail

    @model_validator(mode="after")
    def validate_detail_contract(self) -> AdminSettingsReloadResultEnvelope:
        """
        校验配置热更新结果公共头与扩展字段一致。

        :returns: 当前信封。
        :rtype: AdminSettingsReloadResultEnvelope
        """

        if self.header.kind.value != self.detail.kind:
            raise ValueError("配置热更新结果 header.kind 必须与 detail.kind 一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("配置热更新结果 schema_version 必须一致。")
        return self
