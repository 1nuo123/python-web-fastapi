"""Codex 控制操作派生投影契约测试。"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from src.core.codex_contract.operation_contract import (
    CODEX_OPERATION_PROJECTION_KIND,
    CODEX_OPERATION_PROJECTION_SCHEMA_VERSION,
    CodexOperationProjection,
    CodexOperationProjectionHeader,
    CodexOperationProjectionKind,
    CodexTurnSubmissionProjectionDetail,
)


class TestCodexOperationProjectionContract:
    """验证公共头、强类型扩展与原始消息隔离。"""

    def test_turn_submission_projection_should_only_serialize_derived_title(self) -> None:
        """投影只允许短标题和发生时间，不得容纳原始消息字段。"""

        projection = CodexOperationProjection(
            header=CodexOperationProjectionHeader(
                detail_kind=CodexOperationProjectionKind.TURN_SUBMISSION,
            ),
            detail=CodexTurnSubmissionProjectionDetail(
                display_name="修复 Codex 会话标题",
                occurred_at=datetime(2026, 8, 16, 12, 30, tzinfo=UTC),
            ),
        )

        payload = projection.model_dump(mode="json")

        assert payload == {
            "header": {
                "kind": CODEX_OPERATION_PROJECTION_KIND,
                "schema_version": CODEX_OPERATION_PROJECTION_SCHEMA_VERSION,
                "detail_kind": CodexOperationProjectionKind.TURN_SUBMISSION.value,
            },
            "detail": {
                "kind": CodexOperationProjectionKind.TURN_SUBMISSION.value,
                "schema_version": CODEX_OPERATION_PROJECTION_SCHEMA_VERSION,
                "display_name": "修复 Codex 会话标题",
                "occurred_at": "2026-08-16T12:30:00Z",
            },
        }

    def test_projection_should_reject_raw_message_and_header_mismatch(self) -> None:
        """未知原始消息字段和外内类型不一致必须在契约层失败。"""

        with pytest.raises(ValidationError):
            CodexTurnSubmissionProjectionDetail.model_validate(
                {
                    "kind": CodexOperationProjectionKind.TURN_SUBMISSION.value,
                    "schema_version": CODEX_OPERATION_PROJECTION_SCHEMA_VERSION,
                    "display_name": "短标题",
                    "occurred_at": "2026-08-16T12:30:00Z",
                    "message": "不得持久化的原始消息",
                }
            )

        with pytest.raises(ValidationError):
            CodexOperationProjection.model_validate(
                {
                    "header": {
                        "kind": CODEX_OPERATION_PROJECTION_KIND,
                        "schema_version": CODEX_OPERATION_PROJECTION_SCHEMA_VERSION,
                        "detail_kind": "unknown_projection",
                    },
                    "detail": {
                        "kind": CodexOperationProjectionKind.TURN_SUBMISSION.value,
                        "schema_version": CODEX_OPERATION_PROJECTION_SCHEMA_VERSION,
                        "display_name": "短标题",
                        "occurred_at": "2026-08-16T12:30:00Z",
                    },
                }
            )
