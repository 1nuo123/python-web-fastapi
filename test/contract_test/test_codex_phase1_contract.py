"""Codex Phase 1 公共契约测试。"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.api.endpoint_auth_access.contract_auth_access import (
    BrowserTokenIssuePayload,
    StepUpGrantRequest,
)
from src.core.auth_contract.step_up_grant_contract import StepUpGrantPurpose
from src.core.codex_contract.host_contract import CodexHostSnapshot
from src.core.codex_contract.realtime_event_contract import (
    CodexHostStatusChangedDetail,
    CodexRealtimeEvent,
    CodexRealtimeEventHeader,
    CodexRealtimeEventType,
)


class TestCodexPhase1Contract:
    def test_browser_token_payload_should_not_expose_refresh_token(self) -> None:
        payload = BrowserTokenIssuePayload(
            access_token="access-token",
            expires_in_seconds=900,
        )

        assert "refresh_token" not in payload.model_dump()
        assert "refresh_token" not in BrowserTokenIssuePayload.model_json_schema()["properties"]

    def test_step_up_grant_request_should_accept_only_closed_purposes(self) -> None:
        approval_request = StepUpGrantRequest(
            password="admin",
            purpose=StepUpGrantPurpose.CODEX_HIGH_RISK_APPROVAL,
        )
        revoke_request = StepUpGrantRequest(
            password="admin",
            purpose=StepUpGrantPurpose.CODEX_HOST_REVOKE,
        )

        assert approval_request.purpose is StepUpGrantPurpose.CODEX_HIGH_RISK_APPROVAL
        assert revoke_request.purpose is StepUpGrantPurpose.CODEX_HOST_REVOKE
        with pytest.raises(ValidationError):
            StepUpGrantRequest.model_validate(
                {
                    "password": "admin",
                    "purpose": "codex.unknown_operation",
                }
            )

    def test_host_contract_when_absolute_path_extra_present_should_fail(self) -> None:
        now = datetime.now(UTC)
        with pytest.raises(ValidationError):
            CodexHostSnapshot.model_validate(
                {
                    "host_id": uuid4(),
                    "owner_subject_id": "owner",
                    "display_name": "电脑",
                    "platform": "windows",
                    "status": "offline",
                    "capabilities": {},
                    "created_at": now,
                    "updated_at": now,
                    "version": 1,
                    "absolute_path": "C:/secret",
                }
            )

    def test_realtime_event_should_expose_product_event_without_jsonrpc_fields(self) -> None:
        host_id = uuid4()
        event = CodexRealtimeEvent(
            header=CodexRealtimeEventHeader(
                event_id="event-1",
                occurred_at=datetime.now(UTC),
                detail_kind=CodexRealtimeEventType.HOST_STATUS_CHANGED,
                host_id=host_id,
                stream_epoch="stream-epoch-1",
                cursor="1-0",
            ),
            detail=CodexHostStatusChangedDetail(
                host_id=host_id,
                status="online",
            ),
        )

        dumped = event.model_dump(mode="json")
        assert "jsonrpc" not in dumped
        assert "method" not in dumped
        assert "params" not in dumped
        assert dumped["header"]["kind"] == "codex_realtime_event"
        assert dumped["header"]["stream_epoch"] == "stream-epoch-1"
        assert dumped["header"]["cursor"] == "1-0"
        assert dumped["header"]["detail_kind"] == "host.status_changed"
        assert dumped["detail"]["kind"] == "host.status_changed"
