"""Codex 客户端性能诊断的边界契约测试。"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from src.core.codex_contract.client_performance_contract import (
    CodexClientPerformanceDetail,
    CodexClientPerformanceEnvelope,
    CodexClientPerformanceHeader,
    CodexClientPerformanceMetric,
    CodexClientPerformanceObservation,
    CodexClientPerformanceUnit,
)


def build_header() -> CodexClientPerformanceHeader:
    """构建无用户身份和会话信息的确定性性能头。"""

    return CodexClientPerformanceHeader(
        event_id="performance-event-1",
        occurred_at=datetime(2026, 8, 19, tzinfo=UTC),
    )


def build_detail() -> CodexClientPerformanceDetail:
    """构建一个受限的 reducer 耗时样本。"""

    return CodexClientPerformanceDetail(
        metric=CodexClientPerformanceMetric.REDUCER_DURATION_MILLISECONDS,
        observation=CodexClientPerformanceObservation.OBSERVED,
        unit=CodexClientPerformanceUnit.MILLISECONDS,
        value=7.5,
    )


def test_performance_contract_should_accept_only_fixed_numeric_measurement() -> None:
    """合法性能信封只包含固定枚举、单位和有限数值。"""

    envelope = CodexClientPerformanceEnvelope(header=build_header(), detail=build_detail())

    assert envelope.detail.metric is CodexClientPerformanceMetric.REDUCER_DURATION_MILLISECONDS
    assert envelope.detail.value == 7.5


@pytest.mark.parametrize(
    ("observation", "unit", "value"),
    [
        (
            CodexClientPerformanceObservation.SOCKET_CLOSED,
            CodexClientPerformanceUnit.MILLISECONDS,
            7.5,
        ),
        (
            CodexClientPerformanceObservation.OBSERVED,
            CodexClientPerformanceUnit.BYTES,
            7.5,
        ),
        (
            CodexClientPerformanceObservation.OBSERVED,
            CodexClientPerformanceUnit.MILLISECONDS,
            60_001.0,
        ),
    ],
)
def test_performance_contract_should_reject_invalid_metric_combinations(
    observation: CodexClientPerformanceObservation,
    unit: CodexClientPerformanceUnit,
    value: float,
) -> None:
    """观测、单位和数值上限必须与固定测量词表一致。"""

    with pytest.raises(ValidationError):
        CodexClientPerformanceDetail(
            metric=CodexClientPerformanceMetric.REDUCER_DURATION_MILLISECONDS,
            observation=observation,
            unit=unit,
            value=value,
        )


def test_performance_contract_should_reject_free_text_and_unknown_fields() -> None:
    """性能边界不得接收 URL、异常或任意额外字段。"""

    with pytest.raises(ValidationError):
        CodexClientPerformanceEnvelope.model_validate(
            {
                "header": build_header().model_dump(mode="json"),
                "detail": {
                    **build_detail().model_dump(mode="json"),
                    "url": "https://private.example.test/thread/secret",
                },
            }
        )


def test_performance_contract_accepts_fixed_pwa_legacy_cache_measurement() -> None:
    """PWA 清理只允许固定的已知缓存发现样本。"""

    detail = CodexClientPerformanceDetail(
        metric=CodexClientPerformanceMetric.PWA_LEGACY_CACHE,
        observation=CodexClientPerformanceObservation.LEGACY_CACHE_DETECTED,
        unit=CodexClientPerformanceUnit.COUNT,
        value=1,
    )

    assert detail.metric is CodexClientPerformanceMetric.PWA_LEGACY_CACHE
