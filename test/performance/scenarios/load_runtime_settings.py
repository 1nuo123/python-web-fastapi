"""Locust 场景运行时强类型配置。"""

from __future__ import annotations

import os
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

from test.performance.scenarios.load_scenario_contract import (
    BurstLoadScenarioDetail,
    DependencyDegradedScenarioDetail,
    LoadScenarioEnvelope,
    LoadScenarioHeader,
    LoadScenarioKind,
    MultiInstanceScenarioDetail,
    OverloadScenarioDetail,
    SteadyLoadScenarioDetail,
)

LOAD_MINIMUM_WAIT_SECONDS_ENVIRONMENT_VARIABLE = "LOAD_MINIMUM_WAIT_SECONDS"
LOAD_MAXIMUM_WAIT_SECONDS_ENVIRONMENT_VARIABLE = "LOAD_MAXIMUM_WAIT_SECONDS"
LOAD_EXPECTED_STATUS_CODES_ENVIRONMENT_VARIABLE = "LOAD_EXPECTED_STATUS_CODES"
LOAD_SCENARIO_KIND_ENVIRONMENT_VARIABLE = "LOAD_SCENARIO_KIND"
LOAD_SCENARIO_NAME_ENVIRONMENT_VARIABLE = "LOAD_SCENARIO_NAME"
LOAD_USERS_ENVIRONMENT_VARIABLE = "LOAD_USERS"
LOAD_SPAWN_RATE_ENVIRONMENT_VARIABLE = "LOAD_SPAWN_RATE"
LOAD_DURATION_SECONDS_ENVIRONMENT_VARIABLE = "LOAD_DURATION_SECONDS"
LOAD_BASELINE_USERS_ENVIRONMENT_VARIABLE = "LOAD_BASELINE_USERS"
LOAD_PEAK_USERS_ENVIRONMENT_VARIABLE = "LOAD_PEAK_USERS"
LOAD_BURST_SECONDS_ENVIRONMENT_VARIABLE = "LOAD_BURST_SECONDS"
LOAD_EXPECTED_STATUS_CODE_ENVIRONMENT_VARIABLE = "LOAD_EXPECTED_STATUS_CODE"
LOAD_INJECTED_LATENCY_MILLISECONDS_ENVIRONMENT_VARIABLE = "LOAD_INJECTED_LATENCY_MILLISECONDS"
LOAD_INSTANCE_COUNT_ENVIRONMENT_VARIABLE = "LOAD_INSTANCE_COUNT"
DEFAULT_MINIMUM_WAIT_SECONDS = 0.55
DEFAULT_MAXIMUM_WAIT_SECONDS = 0.75
DEFAULT_EXPECTED_STATUS_CODES = "200"
DEFAULT_SCENARIO_NAME = "steady-runtime-probe"
DEFAULT_USERS = 8
DEFAULT_SPAWN_RATE = 2
DEFAULT_DURATION_SECONDS = 60
DEFAULT_BASELINE_USERS = 8
DEFAULT_PEAK_USERS = 32
DEFAULT_BURST_SECONDS = 15
DEFAULT_OVERLOAD_STATUS_CODE = 429
DEFAULT_INJECTED_LATENCY_MILLISECONDS = 500
DEFAULT_INSTANCE_COUNT = 2


class LoadScenarioRuntimeSettings(BaseModel):
    """Locust 场景运行时强类型配置。"""

    model_config = ConfigDict(extra="forbid")

    minimum_wait_seconds: float = Field(gt=0)
    maximum_wait_seconds: float = Field(gt=0)
    expected_status_codes: frozenset[int] = Field(min_length=1)
    scenario: LoadScenarioEnvelope

    @model_validator(mode="after")
    def validate_wait_range(self) -> LoadScenarioRuntimeSettings:
        """校验等待时间区间。"""

        if self.minimum_wait_seconds > self.maximum_wait_seconds:
            raise ValueError("负载场景最小等待时间不得大于最大等待时间。")
        return self

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> LoadScenarioRuntimeSettings:
        """从显式环境映射加载负载场景配置。"""

        source = os.environ if environment is None else environment
        raw_status_codes = source.get(
            LOAD_EXPECTED_STATUS_CODES_ENVIRONMENT_VARIABLE,
            DEFAULT_EXPECTED_STATUS_CODES,
        )
        try:
            expected_status_codes = frozenset(
                int(status_code.strip())
                for status_code in raw_status_codes.split(",")
                if status_code.strip()
            )
        except ValueError as error:
            raise ValueError("负载场景预期状态码必须是逗号分隔的整数。") from error
        scenario = cls._build_scenario(source)
        return cls(
            minimum_wait_seconds=float(
                source.get(
                    LOAD_MINIMUM_WAIT_SECONDS_ENVIRONMENT_VARIABLE,
                    DEFAULT_MINIMUM_WAIT_SECONDS,
                )
            ),
            maximum_wait_seconds=float(
                source.get(
                    LOAD_MAXIMUM_WAIT_SECONDS_ENVIRONMENT_VARIABLE,
                    DEFAULT_MAXIMUM_WAIT_SECONDS,
                )
            ),
            expected_status_codes=expected_status_codes,
            scenario=scenario,
        )

    @classmethod
    def _build_scenario(cls, source: Mapping[str, str]) -> LoadScenarioEnvelope:
        """从环境构建会实际驱动 Locust 的强类型场景。"""

        scenario_kind = LoadScenarioKind(
            source.get(
                LOAD_SCENARIO_KIND_ENVIRONMENT_VARIABLE,
                LoadScenarioKind.STEADY.value,
            )
        )
        scenario_name = source.get(
            LOAD_SCENARIO_NAME_ENVIRONMENT_VARIABLE,
            DEFAULT_SCENARIO_NAME,
        )
        detail = cls._build_scenario_detail(source=source, scenario_kind=scenario_kind)
        return LoadScenarioEnvelope(
            header=LoadScenarioHeader(
                scenario_name=scenario_name,
                scenario_kind=scenario_kind,
            ),
            detail=detail,
        )

    @staticmethod
    def _build_scenario_detail(
        *,
        source: Mapping[str, str],
        scenario_kind: LoadScenarioKind,
    ) -> (
        SteadyLoadScenarioDetail
        | BurstLoadScenarioDetail
        | OverloadScenarioDetail
        | DependencyDegradedScenarioDetail
        | MultiInstanceScenarioDetail
    ):
        """按封闭场景类型解析对应扩展字段。"""

        duration_seconds = int(
            source.get(
                LOAD_DURATION_SECONDS_ENVIRONMENT_VARIABLE,
                str(DEFAULT_DURATION_SECONDS),
            )
        )
        if scenario_kind == LoadScenarioKind.STEADY:
            return SteadyLoadScenarioDetail(
                users=int(source.get(LOAD_USERS_ENVIRONMENT_VARIABLE, str(DEFAULT_USERS))),
                spawn_rate=int(
                    source.get(
                        LOAD_SPAWN_RATE_ENVIRONMENT_VARIABLE,
                        str(DEFAULT_SPAWN_RATE),
                    )
                ),
                duration_seconds=duration_seconds,
            )
        if scenario_kind == LoadScenarioKind.BURST:
            return BurstLoadScenarioDetail(
                baseline_users=int(
                    source.get(
                        LOAD_BASELINE_USERS_ENVIRONMENT_VARIABLE,
                        str(DEFAULT_BASELINE_USERS),
                    )
                ),
                peak_users=int(
                    source.get(
                        LOAD_PEAK_USERS_ENVIRONMENT_VARIABLE,
                        str(DEFAULT_PEAK_USERS),
                    )
                ),
                burst_seconds=int(
                    source.get(
                        LOAD_BURST_SECONDS_ENVIRONMENT_VARIABLE,
                        str(DEFAULT_BURST_SECONDS),
                    )
                ),
            )
        if scenario_kind == LoadScenarioKind.OVERLOAD:
            return OverloadScenarioDetail(
                users=int(source.get(LOAD_USERS_ENVIRONMENT_VARIABLE, str(DEFAULT_PEAK_USERS))),
                expected_status_code=int(
                    source.get(
                        LOAD_EXPECTED_STATUS_CODE_ENVIRONMENT_VARIABLE,
                        str(DEFAULT_OVERLOAD_STATUS_CODE),
                    )
                ),
                duration_seconds=duration_seconds,
            )
        if scenario_kind == LoadScenarioKind.MULTI_INSTANCE:
            return MultiInstanceScenarioDetail(
                users=int(source.get(LOAD_USERS_ENVIRONMENT_VARIABLE, str(DEFAULT_USERS))),
                instance_count=int(
                    source.get(
                        LOAD_INSTANCE_COUNT_ENVIRONMENT_VARIABLE,
                        str(DEFAULT_INSTANCE_COUNT),
                    )
                ),
                duration_seconds=duration_seconds,
            )
        return DependencyDegradedScenarioDetail(
            users=int(source.get(LOAD_USERS_ENVIRONMENT_VARIABLE, str(DEFAULT_USERS))),
            injected_latency_milliseconds=int(
                source.get(
                    LOAD_INJECTED_LATENCY_MILLISECONDS_ENVIRONMENT_VARIABLE,
                    str(DEFAULT_INJECTED_LATENCY_MILLISECONDS),
                )
            ),
            duration_seconds=duration_seconds,
        )
