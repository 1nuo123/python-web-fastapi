"""Locust 场景运行时配置测试。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from test.performance.scenarios.load_runtime_settings import (
    LOAD_EXPECTED_STATUS_CODES_ENVIRONMENT_VARIABLE,
    LOAD_MAXIMUM_WAIT_SECONDS_ENVIRONMENT_VARIABLE,
    LOAD_MINIMUM_WAIT_SECONDS_ENVIRONMENT_VARIABLE,
    LOAD_SCENARIO_KIND_ENVIRONMENT_VARIABLE,
    LOAD_USERS_ENVIRONMENT_VARIABLE,
    LoadScenarioRuntimeSettings,
)
from test.performance.scenarios.load_scenario_contract import (
    LOAD_SCENARIO_SCHEMA_VERSION,
    BurstLoadScenarioDetail,
    DependencyDegradedScenarioDetail,
    LoadScenarioEnvelope,
    LoadScenarioHeader,
    LoadScenarioKind,
    MultiInstanceScenarioDetail,
    OverloadScenarioDetail,
    SteadyLoadScenarioDetail,
)

MINIMUM_WAIT_SECONDS = "0.25"
MAXIMUM_WAIT_SECONDS = "0.75"
EXPECTED_STATUS_CODES = "200,429"
OVERLOAD_USERS = "128"


class TestLoadScenarioRuntimeSettings:
    """验证负载场景环境输入的强类型边界。"""

    def test_from_environment_should_parse_wait_range_and_status_codes(self) -> None:
        """验证显式环境映射会被解析为强类型配置。"""

        settings = LoadScenarioRuntimeSettings.from_environment(
            {
                LOAD_MINIMUM_WAIT_SECONDS_ENVIRONMENT_VARIABLE: MINIMUM_WAIT_SECONDS,
                LOAD_MAXIMUM_WAIT_SECONDS_ENVIRONMENT_VARIABLE: MAXIMUM_WAIT_SECONDS,
                LOAD_EXPECTED_STATUS_CODES_ENVIRONMENT_VARIABLE: EXPECTED_STATUS_CODES,
            }
        )

        assert settings.minimum_wait_seconds == float(MINIMUM_WAIT_SECONDS)
        assert settings.maximum_wait_seconds == float(MAXIMUM_WAIT_SECONDS)
        assert settings.expected_status_codes == frozenset({200, 429})
        assert settings.scenario.header.scenario_kind == LoadScenarioKind.STEADY
        assert isinstance(settings.scenario.detail, SteadyLoadScenarioDetail)

    def test_from_environment_when_overload_selected_should_build_overload_contract(self) -> None:
        """验证 Locust 运行设置由强类型过载场景驱动。"""

        settings = LoadScenarioRuntimeSettings.from_environment(
            {
                LOAD_SCENARIO_KIND_ENVIRONMENT_VARIABLE: LoadScenarioKind.OVERLOAD.value,
                LOAD_USERS_ENVIRONMENT_VARIABLE: OVERLOAD_USERS,
                LOAD_EXPECTED_STATUS_CODES_ENVIRONMENT_VARIABLE: EXPECTED_STATUS_CODES,
            }
        )

        assert settings.scenario.header.scenario_kind == LoadScenarioKind.OVERLOAD
        assert isinstance(settings.scenario.detail, OverloadScenarioDetail)
        assert settings.scenario.detail.users == int(OVERLOAD_USERS)

    def test_from_environment_when_wait_range_reversed_should_fail(self) -> None:
        """验证反向等待区间会被拒绝。"""

        with pytest.raises(ValidationError, match="最小等待时间不得大于最大等待时间"):
            LoadScenarioRuntimeSettings.from_environment(
                {
                    LOAD_MINIMUM_WAIT_SECONDS_ENVIRONMENT_VARIABLE: MAXIMUM_WAIT_SECONDS,
                    LOAD_MAXIMUM_WAIT_SECONDS_ENVIRONMENT_VARIABLE: MINIMUM_WAIT_SECONDS,
                }
            )

    def test_from_environment_when_status_code_invalid_should_fail(self) -> None:
        """验证非整数状态码会被拒绝。"""

        with pytest.raises(ValueError, match="预期状态码必须是逗号分隔的整数"):
            LoadScenarioRuntimeSettings.from_environment(
                {LOAD_EXPECTED_STATUS_CODES_ENVIRONMENT_VARIABLE: "200,invalid"}
            )

    @pytest.mark.parametrize(
        ("kind", "detail"),
        (
            (
                LoadScenarioKind.STEADY,
                SteadyLoadScenarioDetail(users=2, spawn_rate=1, duration_seconds=5),
            ),
            (
                LoadScenarioKind.BURST,
                BurstLoadScenarioDetail(baseline_users=2, peak_users=4, burst_seconds=2),
            ),
            (
                LoadScenarioKind.OVERLOAD,
                OverloadScenarioDetail(users=8, expected_status_code=429, duration_seconds=5),
            ),
            (
                LoadScenarioKind.DEPENDENCY_DEGRADED,
                DependencyDegradedScenarioDetail(
                    users=2,
                    injected_latency_milliseconds=200,
                    duration_seconds=5,
                ),
            ),
            (
                LoadScenarioKind.MULTI_INSTANCE,
                MultiInstanceScenarioDetail(users=4, instance_count=2, duration_seconds=5),
            ),
        ),
    )
    def test_load_scenario_contract_when_valid_should_round_trip(
        self,
        kind: LoadScenarioKind,
        detail: (
            SteadyLoadScenarioDetail
            | BurstLoadScenarioDetail
            | OverloadScenarioDetail
            | DependencyDegradedScenarioDetail
            | MultiInstanceScenarioDetail
        ),
    ) -> None:
        """验证全部负载场景强类型扩展可稳定序列化往返。"""

        envelope = LoadScenarioEnvelope(
            header=LoadScenarioHeader(scenario_name=f"{kind.value}-test", scenario_kind=kind),
            detail=detail,
        )

        restored = LoadScenarioEnvelope.model_validate_json(envelope.model_dump_json())

        assert restored == envelope
        assert restored.detail.schema_version == LOAD_SCENARIO_SCHEMA_VERSION

    def test_load_scenario_contract_when_unknown_kind_should_reject(self) -> None:
        """验证负载场景拒绝未知判别值。"""

        payload = self._build_steady_envelope().model_dump(mode="python")
        payload["detail"]["kind"] = "unknown"

        with pytest.raises(ValidationError):
            LoadScenarioEnvelope.model_validate(payload)

    def test_load_scenario_contract_when_extra_field_should_reject(self) -> None:
        """验证负载场景拒绝扩展未知字段。"""

        payload = self._build_steady_envelope().model_dump(mode="python")
        payload["detail"]["unexpected"] = True

        with pytest.raises(ValidationError):
            LoadScenarioEnvelope.model_validate(payload)

    def test_load_scenario_contract_when_schema_version_invalid_should_reject(self) -> None:
        """验证负载场景拒绝错误契约版本。"""

        payload = self._build_steady_envelope().model_dump(mode="python")
        payload["detail"]["schema_version"] = "2.0"

        with pytest.raises(ValidationError):
            LoadScenarioEnvelope.model_validate(payload)

    def test_load_scenario_contract_when_outer_kind_mismatch_should_reject(self) -> None:
        """验证公共头与扩展类型不一致时拒绝。"""

        payload = self._build_steady_envelope().model_dump(mode="python")
        payload["header"]["scenario_kind"] = LoadScenarioKind.BURST.value

        with pytest.raises(ValidationError, match="类型不一致"):
            LoadScenarioEnvelope.model_validate(payload)

    @staticmethod
    def _build_steady_envelope() -> LoadScenarioEnvelope:
        """构建稳定负载强类型信封。"""

        return LoadScenarioEnvelope(
            header=LoadScenarioHeader(
                scenario_name="steady-contract-test",
                scenario_kind=LoadScenarioKind.STEADY,
            ),
            detail=SteadyLoadScenarioDetail(users=2, spawn_rate=1, duration_seconds=5),
        )
