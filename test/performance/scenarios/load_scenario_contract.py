"""负载场景强类型契约。"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

LOAD_SCENARIO_SCHEMA_VERSION = "1.0"
LOAD_SCENARIO_HEADER_KIND = "load_scenario_header"
LOAD_SCENARIO_ENVELOPE_KIND = "load_scenario_envelope"


class LoadScenarioKind(StrEnum):
    """负载场景封闭集合。"""

    STEADY = "steady"
    BURST = "burst"
    OVERLOAD = "overload"
    DEPENDENCY_DEGRADED = "dependency_degraded"
    MULTI_INSTANCE = "multi_instance"


class LoadScenarioHeader(BaseModel):
    """负载场景公共头。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["load_scenario_header"] = LOAD_SCENARIO_HEADER_KIND
    schema_version: Literal["1.0"] = LOAD_SCENARIO_SCHEMA_VERSION
    scenario_name: str = Field(min_length=1)
    scenario_kind: LoadScenarioKind


class SteadyLoadScenarioDetail(BaseModel):
    """稳定负载扩展字段。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["steady"] = LoadScenarioKind.STEADY.value
    schema_version: Literal["1.0"] = LOAD_SCENARIO_SCHEMA_VERSION
    users: int = Field(ge=1)
    spawn_rate: int = Field(ge=1)
    duration_seconds: int = Field(ge=1)


class BurstLoadScenarioDetail(BaseModel):
    """突发负载扩展字段。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["burst"] = LoadScenarioKind.BURST.value
    schema_version: Literal["1.0"] = LOAD_SCENARIO_SCHEMA_VERSION
    baseline_users: int = Field(ge=1)
    peak_users: int = Field(ge=1)
    burst_seconds: int = Field(ge=1)


class OverloadScenarioDetail(BaseModel):
    """过载负载扩展字段。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["overload"] = LoadScenarioKind.OVERLOAD.value
    users: int = Field(ge=1)
    expected_status_code: int = Field(ge=400, le=599)
    duration_seconds: int = Field(ge=1)
    schema_version: Literal["1.0"] = LOAD_SCENARIO_SCHEMA_VERSION


class DependencyDegradedScenarioDetail(BaseModel):
    """依赖退化负载扩展字段。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["dependency_degraded"] = LoadScenarioKind.DEPENDENCY_DEGRADED.value
    schema_version: Literal["1.0"] = LOAD_SCENARIO_SCHEMA_VERSION
    users: int = Field(ge=1)
    injected_latency_milliseconds: int = Field(ge=1)
    duration_seconds: int = Field(ge=1)


class MultiInstanceScenarioDetail(BaseModel):
    """多实例无状态扩容负载扩展字段。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["multi_instance"] = LoadScenarioKind.MULTI_INSTANCE.value
    schema_version: Literal["1.0"] = LOAD_SCENARIO_SCHEMA_VERSION
    users: int = Field(ge=1)
    instance_count: int = Field(ge=2)
    duration_seconds: int = Field(ge=1)


LoadScenarioDetailUnion = Annotated[
    SteadyLoadScenarioDetail
    | BurstLoadScenarioDetail
    | OverloadScenarioDetail
    | DependencyDegradedScenarioDetail
    | MultiInstanceScenarioDetail,
    Field(discriminator="kind"),
]


class LoadScenarioEnvelope(BaseModel):
    """负载场景信封。"""

    model_config = ConfigDict(extra="forbid")

    envelope_kind: Literal["load_scenario_envelope"] = LOAD_SCENARIO_ENVELOPE_KIND
    schema_version: Literal["1.0"] = LOAD_SCENARIO_SCHEMA_VERSION
    header: LoadScenarioHeader
    detail: LoadScenarioDetailUnion

    @model_validator(mode="after")
    def validate_kind_consistency(self) -> LoadScenarioEnvelope:
        """校验公共头与扩展字段的类型、版本一致。"""

        if self.header.scenario_kind.value != self.detail.kind:
            raise ValueError("负载场景公共头类型与扩展字段类型不一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("负载场景公共头版本与扩展字段版本不一致。")
        return self
