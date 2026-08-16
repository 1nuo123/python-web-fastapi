"""Codex Agent v2 事件累计 ACK 跨连接集成测试。"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession

from src.api.testing.test_app_factory import TestAppFactory
from src.core.codex_contract.agent_protocol_v2_contract import (
    AgentEventAckV2Detail,
    AgentEventBatchV2Detail,
    AgentEventRecord,
    AgentHelloAckV2Detail,
    AgentHelloV2Detail,
    AgentProtocolWarningEventDetail,
)
from src.infrastructure.persistence.orm_model.codex_host_orm_model import CodexHostOrmModel
from test.fixtures.codex_device_authorization_test_support import (
    FROZEN_APP_SERVER_SCHEMA_DIGEST,
    FROZEN_CODEX_VERSION,
    AuthorizedAgentDevice,
    CodexDeviceAuthorizationTestSupport,
)

TEST_OWNER_SUBJECT_ID = "user-admin"
TEST_EVENT_SEQUENCE = 1


class TestCodexAgentEventCursorIntegration:
    """验证服务端事件游标在 Agent 连接代次之间保持累计状态。"""

    def test_v2_event_ack_should_survive_agent_reconnect(self) -> None:
        """验证相同 Agent epoch 重连后从服务端累计 ACK 继续发送。"""

        app = TestAppFactory().create()
        host_id = uuid4()
        event_epoch = uuid4()
        with TestClient(app) as client:
            device = self._provision_host_and_key(app, host_id)
            first_ticket = CodexDeviceAuthorizationTestSupport.issue_connection_ticket(
                client,
                device,
            )
            with client.websocket_connect(
                f"/internal/codex-agents/connect?ticket={first_ticket.ticket}"
            ) as first_websocket:
                first_ack = self._send_hello(first_websocket, device, event_epoch)
                assert first_ack.after_seq == 0
                self._send_event(first_websocket, device, event_epoch, TEST_EVENT_SEQUENCE)
                first_event_ack = CodexDeviceAuthorizationTestSupport.receive_v2_envelope(
                    first_websocket
                )
                assert isinstance(first_event_ack.detail, AgentEventAckV2Detail)
                assert first_event_ack.detail.after_seq == TEST_EVENT_SEQUENCE
                CodexDeviceAuthorizationTestSupport.close_websocket(first_websocket)

            second_ticket = CodexDeviceAuthorizationTestSupport.issue_connection_ticket(
                client,
                device,
            )
            with client.websocket_connect(
                f"/internal/codex-agents/connect?ticket={second_ticket.ticket}"
            ) as second_websocket:
                second_ack = self._send_hello(second_websocket, device, event_epoch)
                assert second_ack.after_seq == TEST_EVENT_SEQUENCE
                CodexDeviceAuthorizationTestSupport.close_websocket(second_websocket)

    def _provision_host_and_key(
        self,
        app: FastAPI,
        host_id: UUID,
    ) -> AuthorizedAgentDevice:
        """创建测试主机并签发活跃设备 key。"""

        unit_of_work = app.state.container.resource_mount.create_unit_of_work()
        try:
            unit_of_work.get_session().add(
                CodexHostOrmModel(
                    host_id=host_id,
                    owner_subject_id=TEST_OWNER_SUBJECT_ID,
                    display_name="事件游标主机",
                    platform="windows",
                    status="offline",
                    capabilities={},
                    version=1,
                )
            )
            unit_of_work.commit()
        finally:
            unit_of_work.dispose()
        return CodexDeviceAuthorizationTestSupport.provision_active_key(
            app=app,
            host_id=host_id,
            owner_subject_id=TEST_OWNER_SUBJECT_ID,
        )

    def _send_hello(
        self,
        websocket: WebSocketTestSession,
        device: AuthorizedAgentDevice,
        event_epoch: UUID,
    ) -> AgentHelloAckV2Detail:
        """发送指定事件 epoch 的 v2 hello。"""

        websocket.send_text(
            CodexDeviceAuthorizationTestSupport.frame_v2(
                device=device,
                detail=AgentHelloV2Detail(
                    agent_version="2.0.0",
                    codex_version=FROZEN_CODEX_VERSION,
                    app_server_schema_digest=FROZEN_APP_SERVER_SCHEMA_DIGEST,
                    capabilities=(),
                    agent_event_epoch=event_epoch,
                ),
            )
        )
        envelope = CodexDeviceAuthorizationTestSupport.receive_v2_envelope(websocket)
        assert isinstance(envelope.detail, AgentHelloAckV2Detail)
        return envelope.detail

    def _send_event(
        self,
        websocket: WebSocketTestSession,
        device: AuthorizedAgentDevice,
        event_epoch: UUID,
        sequence: int,
    ) -> None:
        """发送一个稳定 v2 协议告警事件。"""

        record = AgentEventRecord(
            agent_event_epoch=event_epoch,
            seq=sequence,
            event_id=uuid4(),
            app_server_instance_id=uuid4(),
            occurred_at=datetime.now(UTC),
            detail=AgentProtocolWarningEventDetail(
                reason_code="event_cursor_integration",
                method="test/event",
            ),
        )
        websocket.send_text(
            CodexDeviceAuthorizationTestSupport.frame_v2(
                device=device,
                detail=AgentEventBatchV2Detail(
                    agent_event_epoch=event_epoch,
                    first_seq=sequence,
                    last_seq=sequence,
                    events=(record,),
                ),
            )
        )
