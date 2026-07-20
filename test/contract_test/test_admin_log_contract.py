"""
管理员日志 HTTP 契约测试模块。
"""

from __future__ import annotations

from datetime import UTC, datetime

from src.api.endpoint_admin_log.contract_admin_log import (
    AdminLogRecordPayload,
    AdminSecurityEventPayload,
)
from src.application.ports.admin_log_query_port import (
    AdminLogRecordSnapshot,
    AdminUnparsedLogDetail,
)
from src.core.logging_contract.log_event_contract import (
    AccessLogDetail,
    LogEventKind,
    LogLevel,
    SecurityLogDetail,
)
from src.core.security_contract.security_event_contract import (
    AUTH_FAILURE_EVENT_KIND,
    AuthFailureSecurityEventDetail,
    SecurityEventDecision,
    SecurityEventEnvelope,
    SecurityEventHeader,
    SecurityEventSeverity,
    SecurityEventType,
)

TEST_EVENT_ID = "event-admin-log-1"
TEST_SECURITY_EVENT_ID = "event-admin-security-1"
TEST_REQUEST_ID = "request-admin-log-1"
TEST_TRACE_ID = "trace-admin-log-1"
TEST_SUBJECT_ID = "subject-admin-log-1"
TEST_SOURCE_MODULE = "test_module"
TEST_SOURCE_COMPONENT = "test_component"
TEST_MESSAGE = "测试日志"
TEST_PATH = "/auth/token"
TEST_METHOD = "POST"
TEST_ROUTE_NAME = "issue_access_token"
TEST_CLIENT_IP = "198.51.100.10"
TEST_USER_AGENT = "AdminLogContractTest/1.0"
TEST_OCCURRED_EPOCH = 1700000000
TEST_STATUS_CODE = 401
TEST_ELAPSED_MILLISECONDS = 2.5
TEST_POLICY_NAME = "auth"
TEST_REASON_CODE = "auth.failure"
TEST_IP_DIGEST = "0123456789abcdef"
TEST_SUBJECT_DIGEST = "abcdef0123456789"
UNPARSED_SUMMARY = "历史日志详情无法按当前强类型契约解析。"


class TestAdminLogContract:
    """
    管理员日志 HTTP 契约测试集合。
    """

    def test_access_log_payload_should_remove_plain_client_identity(self) -> None:
        """
        验证访问日志载荷不会暴露完整客户端 IP 与 user-agent。
        """

        payload = AdminLogRecordPayload.from_snapshot(self._build_access_log_snapshot())
        serialized_payload = payload.model_dump_json()

        assert TEST_CLIENT_IP not in serialized_payload
        assert TEST_USER_AGENT not in serialized_payload
        assert payload.detail.request_path == TEST_PATH

    def test_unparsed_log_payload_should_return_summary_only(self) -> None:
        """
        验证不可解析日志详情只返回摘要。
        """

        payload = AdminLogRecordPayload.from_snapshot(
            AdminLogRecordSnapshot(
                event_id=TEST_EVENT_ID,
                event_kind=LogEventKind.EXCEPTION,
                schema_version="0.1",
                level=LogLevel.ERROR,
                message=TEST_MESSAGE,
                occurred_at=self._build_occurred_at(),
                request_id=TEST_REQUEST_ID,
                trace_id=TEST_TRACE_ID,
                authenticated_subject_id=TEST_SUBJECT_ID,
                source_module=TEST_SOURCE_MODULE,
                source_component=TEST_SOURCE_COMPONENT,
                detail=AdminUnparsedLogDetail(summary=UNPARSED_SUMMARY),
                security_event=None,
            )
        )

        assert payload.detail.summary == UNPARSED_SUMMARY

    def test_security_event_payload_should_keep_structured_event(self) -> None:
        """
        验证安全事件载荷保留强类型安全事件。
        """

        snapshot = self._build_security_log_snapshot()
        payload = AdminSecurityEventPayload.from_snapshot(snapshot)

        assert payload.security_event.header.event_type == (
            SecurityEventType.AUTH_LOGIN_FAILURE.value
        )
        assert payload.security_event.header.ip_digest == TEST_IP_DIGEST
        assert TEST_USER_AGENT not in payload.model_dump_json()

    def _build_access_log_snapshot(self) -> AdminLogRecordSnapshot:
        """
        构建访问日志快照。
        """

        return AdminLogRecordSnapshot(
            event_id=TEST_EVENT_ID,
            event_kind=LogEventKind.ACCESS,
            schema_version="1.0",
            level=LogLevel.INFO,
            message=TEST_MESSAGE,
            occurred_at=self._build_occurred_at(),
            request_id=TEST_REQUEST_ID,
            trace_id=TEST_TRACE_ID,
            authenticated_subject_id=TEST_SUBJECT_ID,
            source_module=TEST_SOURCE_MODULE,
            source_component=TEST_SOURCE_COMPONENT,
            detail=AccessLogDetail(
                request_path=TEST_PATH,
                request_method=TEST_METHOD,
                status_code=TEST_STATUS_CODE,
                elapsed_milliseconds=TEST_ELAPSED_MILLISECONDS,
                client_ip=TEST_CLIENT_IP,
                user_agent=TEST_USER_AGENT,
                route_name=TEST_ROUTE_NAME,
            ),
            security_event=None,
        )

    def _build_security_log_snapshot(self) -> AdminLogRecordSnapshot:
        """
        构建安全日志快照。
        """

        security_event = self._build_security_event()
        return AdminLogRecordSnapshot(
            event_id=TEST_SECURITY_EVENT_ID,
            event_kind=LogEventKind.SECURITY,
            schema_version="1.0",
            level=LogLevel.WARNING,
            message=TEST_MESSAGE,
            occurred_at=self._build_occurred_at(),
            request_id=TEST_REQUEST_ID,
            trace_id=TEST_TRACE_ID,
            authenticated_subject_id=TEST_SUBJECT_ID,
            source_module=TEST_SOURCE_MODULE,
            source_component=TEST_SOURCE_COMPONENT,
            detail=SecurityLogDetail(security_event=security_event),
            security_event=security_event,
        )

    def _build_security_event(self) -> SecurityEventEnvelope:
        """
        构建安全事件信封。
        """

        return SecurityEventEnvelope(
            header=SecurityEventHeader(
                event_type=SecurityEventType.AUTH_LOGIN_FAILURE.value,
                detail_kind=AUTH_FAILURE_EVENT_KIND,
                severity=SecurityEventSeverity.WARNING,
                decision=SecurityEventDecision.DENY,
                reason_code=TEST_REASON_CODE,
                request_id=TEST_REQUEST_ID,
                trace_id=TEST_TRACE_ID,
                path=TEST_PATH,
                method=TEST_METHOD,
                status_code=TEST_STATUS_CODE,
                subject_id=TEST_SUBJECT_ID,
                ip_digest=TEST_IP_DIGEST,
                user_agent_digest=TEST_IP_DIGEST,
                policy_name=TEST_POLICY_NAME,
                occurred_at_epoch=TEST_OCCURRED_EPOCH,
            ),
            detail=AuthFailureSecurityEventDetail(
                subject_digest=TEST_SUBJECT_DIGEST,
                ip_digest=TEST_IP_DIGEST,
                reason_code=TEST_REASON_CODE,
            ),
        )

    def _build_occurred_at(self) -> datetime:
        """
        构建发生时间。
        """

        return datetime.fromtimestamp(TEST_OCCURRED_EPOCH, UTC)
