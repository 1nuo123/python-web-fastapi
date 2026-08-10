"""Codex App Server稳定审批协议探针结果契约。"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AppServerApprovalMethod(StrEnum):
    """MVP使用的App Server稳定审批server request方法。"""

    COMMAND_EXECUTION = "item/commandExecution/requestApproval"
    FILE_CHANGE = "item/fileChange/requestApproval"
    PERMISSIONS = "item/permissions/requestApproval"


class AppServerApprovalProtocolProbeResult(BaseModel):
    """对指定CLI生成schema的可审计探针结果。"""

    model_config = ConfigDict(extra="forbid")

    codex_version: str = Field(min_length=1)
    approval_schema_digest_sha256: str = Field(min_length=64, max_length=64)
    approval_server_request_methods: list[AppServerApprovalMethod]
    response_required_fields: dict[str, list[str]]
    confirmation_response_expected: Literal[False] = False
