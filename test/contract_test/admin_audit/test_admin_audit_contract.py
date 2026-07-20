"""
业务审计契约测试模块。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from src.api.endpoint_admin_audit.contract_admin_audit import (
    ADMIN_AUDIT_SCHEMA_VERSION,
    AdminAuditEnvelope,
    AdminAuditEventListPayload,
    AdminAuditEventPayload,
    AdminAuditHeader,
    AdminAuditOperationName,
    AdminAuditPayloadKind,
)
from src.application.ports.admin_audit_query_port import (
    AdminAuditAction,
    AdminAuditEventPage,
    AdminAuditEventSnapshot,
    AdminAuditResult,
)

AUDIT_EVENT_ID = "audit-contract-event"
AUDIT_ACTOR_SUBJECT_ID = "actor-contract"
AUDIT_TARGET_KIND = "user"
AUDIT_TARGET_ID = "target-contract"
AUDIT_SUMMARY = "业务审计契约测试摘要。"
AUDIT_OCCURRED_AT = datetime(2026, 5, 28, 10, 55, tzinfo=UTC)
AUDIT_PAGE_SIZE = 50
AUDIT_OFFSET = 0
AUDIT_TOTAL = 1
UNKNOWN_FIELD_NAME = "unknown"
SENSITIVE_TEXTS = ("password", "token", "secret", "user-agent", "ip_address")


class TestAdminAuditContract:
    """
    业务审计契约测试集合。
    """

    def test_audit_event_list_envelope_should_validate_contract(self) -> None:
        """
        验证业务审计列表信封公共头与扩展字段一致。
        """

        envelope = AdminAuditEnvelope(
            header=AdminAuditHeader(
                kind=AdminAuditPayloadKind.EVENT_LIST,
                operation_name=AdminAuditOperationName.EVENT_LIST,
            ),
            detail=AdminAuditEventListPayload.from_page(self._build_page()),
        )

        dumped = envelope.model_dump(mode="json")

        assert envelope.header.schema_version == ADMIN_AUDIT_SCHEMA_VERSION
        assert dumped["detail"]["events"][0]["action"] == AdminAuditAction.USER_DISABLED.value
        assert dumped["detail"]["page_size"] == AUDIT_PAGE_SIZE
        assert dumped["detail"]["total"] == AUDIT_TOTAL

    def test_audit_event_envelope_should_validate_single_event_branch(self) -> None:
        """
        验证业务审计单事件扩展字段判别联合分支。
        """

        payload = AdminAuditEventPayload.from_snapshot(self._build_page().events[0])
        envelope = AdminAuditEnvelope(
            header=AdminAuditHeader(
                kind=AdminAuditPayloadKind.EVENT,
                operation_name=AdminAuditOperationName.EVENT_LIST,
            ),
            detail=payload,
        )

        dumped = envelope.model_dump(mode="json")

        assert dumped["header"]["kind"] == AdminAuditPayloadKind.EVENT.value
        assert dumped["detail"]["kind"] == AdminAuditPayloadKind.EVENT.value
        assert dumped["detail"]["event_id"] == AUDIT_EVENT_ID

    def test_audit_event_list_when_unknown_field_should_fail(self) -> None:
        """
        验证业务审计契约拒绝未知字段。
        """

        with pytest.raises(ValidationError):
            AdminAuditEnvelope.model_validate(
                {
                    "header": {
                        "kind": AdminAuditPayloadKind.EVENT_LIST.value,
                        "schema_version": ADMIN_AUDIT_SCHEMA_VERSION,
                        "operation_name": AdminAuditOperationName.EVENT_LIST.value,
                    },
                    "detail": {
                        "kind": AdminAuditPayloadKind.EVENT_LIST.value,
                        "schema_version": ADMIN_AUDIT_SCHEMA_VERSION,
                        "events": [],
                        "page_size": AUDIT_PAGE_SIZE,
                        "offset": AUDIT_OFFSET,
                        "total": AUDIT_TOTAL,
                        UNKNOWN_FIELD_NAME: True,
                    },
                }
            )

    def test_audit_header_detail_mismatch_should_fail(self) -> None:
        """
        验证业务审计公共头与扩展字段不一致时拒绝。
        """

        with pytest.raises(ValidationError):
            AdminAuditEnvelope(
                header=AdminAuditHeader(
                    kind=AdminAuditPayloadKind.EVENT,
                    operation_name=AdminAuditOperationName.EVENT_LIST,
                ),
                detail=AdminAuditEventListPayload.from_page(self._build_page()),
            )

    def test_audit_contract_should_not_include_sensitive_fields(self) -> None:
        """
        验证业务审计序列化结果不包含敏感字段。
        """

        envelope = AdminAuditEnvelope(
            header=AdminAuditHeader(
                kind=AdminAuditPayloadKind.EVENT_LIST,
                operation_name=AdminAuditOperationName.EVENT_LIST,
            ),
            detail=AdminAuditEventListPayload.from_page(self._build_page()),
        )

        serialized = envelope.model_dump_json().lower()

        for sensitive_text in SENSITIVE_TEXTS:
            assert sensitive_text not in serialized

    def _build_page(self) -> AdminAuditEventPage:
        """
        构建业务审计分页结果。
        """

        return AdminAuditEventPage(
            events=[
                AdminAuditEventSnapshot(
                    event_id=AUDIT_EVENT_ID,
                    action=AdminAuditAction.USER_DISABLED,
                    actor_subject_id=AUDIT_ACTOR_SUBJECT_ID,
                    target_kind=AUDIT_TARGET_KIND,
                    target_id=AUDIT_TARGET_ID,
                    result=AdminAuditResult.SUCCESS,
                    occurred_at=AUDIT_OCCURRED_AT,
                    summary=AUDIT_SUMMARY,
                )
            ],
            page_size=AUDIT_PAGE_SIZE,
            offset=AUDIT_OFFSET,
            total=AUDIT_TOTAL,
        )
