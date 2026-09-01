"""App Server capability probe 的严格跨进程契约。"""

from __future__ import annotations

from enum import StrEnum
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.core.codex_contract.app_server_schema_manifest_contract import (
    AppServerCapabilityDetail,
    AppServerMethodName,
)

APP_SERVER_CAPABILITY_PROBE_SCHEMA_VERSION: Final = "1.0"


class AppServerCapabilityProbeOutcome(StrEnum):
    """探针可授予的最高运行权限。"""

    COMPATIBLE = "compatible"
    READ_ONLY = "read_only"
    BLOCKED = "blocked"


class AppServerCapabilityProbeFailure(StrEnum):
    """稳定、无敏感正文的探针失败原因。"""

    INITIALIZE_FAILED = "initialize_failed"
    READ_METHOD_FAILED = "read_method_failed"
    CORE_FIELD_MISSING = "core_field_missing"
    MUTATION_METHOD_FAILED = "mutation_method_failed"
    TURN_FAILED = "turn_failed"
    APPROVAL_FAILED = "approval_failed"
    INTERRUPT_FAILED = "interrupt_failed"
    TIMEOUT = "timeout"
    PROTOCOL_ERROR = "protocol_error"


class AppServerCapabilityProbeResult(BaseModel):
    """Agent hello 携带的有界、可独立校验的探针事实。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = APP_SERVER_CAPABILITY_PROBE_SCHEMA_VERSION
    outcome: AppServerCapabilityProbeOutcome
    initialize_passed: bool
    methods: tuple[AppServerMethodName, ...] = ()
    notification_methods: tuple[str, ...] = Field(default=(), max_length=128)
    capabilities: tuple[AppServerCapabilityDetail, ...] = ()
    read_only_confirmed: bool = False
    mutation_confirmed: bool = False
    approval_confirmed: bool = False
    interrupt_confirmed: bool = False
    thread_cleaned: bool = False
    failure: AppServerCapabilityProbeFailure | None = None

    @model_validator(mode="after")
    def validate_probe_consistency(self) -> AppServerCapabilityProbeResult:
        """拒绝自相矛盾、重复或越权的探针声明。"""

        if len(self.methods) != len(set(self.methods)):
            raise ValueError("capability probe方法不允许重复。")
        if len(self.notification_methods) != len(set(self.notification_methods)):
            raise ValueError("capability probe notification不允许重复。")
        capability_codes = [item.code for item in self.capabilities]
        if len(capability_codes) != len(set(capability_codes)):
            raise ValueError("capability probe能力不允许重复。")
        if self.outcome is AppServerCapabilityProbeOutcome.COMPATIBLE and not all(
            (
                self.initialize_passed,
                self.read_only_confirmed,
                self.mutation_confirmed,
                self.approval_confirmed,
                self.interrupt_confirmed,
            )
        ):
            raise ValueError("compatible probe必须确认核心读写、审批和中断能力。")
        if self.outcome is AppServerCapabilityProbeOutcome.READ_ONLY and not (
            self.initialize_passed and self.read_only_confirmed
        ):
            raise ValueError("read_only probe必须确认initialize和核心只读能力。")
        if self.outcome is AppServerCapabilityProbeOutcome.COMPATIBLE and self.failure is not None:
            raise ValueError("compatible probe不允许携带失败原因。")
        if self.outcome is AppServerCapabilityProbeOutcome.BLOCKED and self.failure is None:
            raise ValueError("blocked probe必须携带失败原因。")
        return self
