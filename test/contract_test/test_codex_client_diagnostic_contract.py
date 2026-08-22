"""Codex 客户端诊断信封的边界契约测试。"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from src.core.codex_contract.client_diagnostic_contract import (
    CodexClientDiagnosticDetail,
    CodexClientDiagnosticEnvelope,
    CodexClientDiagnosticHeader,
    CodexClientDiagnosticSource,
    CodexClientDiagnosticSummary,
)


def _build_header() -> CodexClientDiagnosticHeader:
    """构造不含用户内容的确定性诊断头。"""

    return CodexClientDiagnosticHeader(
        event_id="event-1",
        source=CodexClientDiagnosticSource.VUE,
        occurred_at=datetime(2026, 8, 19, tzinfo=UTC),
    )


def _build_detail() -> CodexClientDiagnosticDetail:
    """构造只含白名单字段的确定性诊断详情。"""

    return CodexClientDiagnosticDetail(
        summary=CodexClientDiagnosticSummary.VUE_ERROR,
        error_code="client.vue.render_failed",
        fingerprint="vue:client.vue.render_failed",
    )


def test_client_diagnostic_contract_accepts_only_structured_metadata() -> None:
    """合法信封只能暴露版本、枚举、代码和派生指纹。"""

    envelope = CodexClientDiagnosticEnvelope(
        header=_build_header(),
        detail=_build_detail(),
    )

    assert envelope.header.source is CodexClientDiagnosticSource.VUE
    assert envelope.detail.error_code == "client.vue.render_failed"


@pytest.mark.parametrize(
    "error_code",
    [
        "Bearer access-token-value",
        "../workspace/private.txt",
        "client.error with space",
    ],
)
def test_client_diagnostic_contract_rejects_free_text_error_codes(
    error_code: str,
) -> None:
    """错误码不能承载 token、路径或自由文本。"""

    with pytest.raises(ValidationError):
        CodexClientDiagnosticDetail(
            summary=CodexClientDiagnosticSummary.VUE_ERROR,
            error_code=error_code,
            fingerprint="vue:client.runtime.unclassified",
        )


def test_client_diagnostic_contract_forbids_unknown_sensitive_fields() -> None:
    """额外字段必须在协议边界拒绝，防止正文绕过客户端约束。"""

    with pytest.raises(ValidationError):
        CodexClientDiagnosticEnvelope.model_validate(
            {
                "header": _build_header().model_dump(mode="json"),
                "detail": {
                    **_build_detail().model_dump(mode="json"),
                    "message": "secret conversation content",
                },
            }
        )
