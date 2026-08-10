"""Agent 通知到浏览器稳定产品事件的完整控制面集成测试。"""

from __future__ import annotations

from datetime import UTC, datetime
from http import HTTPStatus
from uuid import uuid4

from fastapi.testclient import TestClient

from src.api.testing.test_app_factory import TestAppFactory
from src.core.codex_contract.agent_protocol_contract import (
    CodexAgentHello,
    CodexAgentRealtimeEvent,
    CodexAgentStateSnapshot,
    CodexAgentWorkspaceSnapshot,
)
from src.core.codex_contract.realtime_event_contract import CodexRealtimeEvent
from src.infrastructure.persistence.orm_model.codex_host_orm_model import CodexHostOrmModel
from test.fixtures.codex_device_authorization_test_support import (
    FROZEN_APP_SERVER_SCHEMA_DIGEST,
    FROZEN_CODEX_VERSION,
    CodexDeviceAuthorizationTestSupport,
)

ORIGIN = "http://testserver"


def test_agent_notifications_should_map_to_ordered_browser_product_events() -> None:
    app = TestAppFactory().create()
    host_id = uuid4()
    thread_id = "019-pipeline-thread"
    turn_id = "019-pipeline-turn"
    item_id = "019-pipeline-item"
    with TestClient(app) as client:
        access_token = client.post(
            "/auth/browser/token",
            headers={"Origin": ORIGIN},
            json={"username": "admin", "password": "admin"},
        ).json()["data"]["access_token"]
        resource_mount = app.state.container.resource_mount
        unit_of_work = resource_mount.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            session.add(
                CodexHostOrmModel(
                    host_id=host_id,
                    owner_subject_id="user-admin",
                    display_name="Pipeline host",
                    platform="windows",
                    status="offline",
                    capabilities={},
                    version=1,
                )
            )
            unit_of_work.commit()
        finally:
            unit_of_work.dispose()
        device = CodexDeviceAuthorizationTestSupport.provision_active_key(
            app=app,
            host_id=host_id,
            owner_subject_id="user-admin",
        )
        agent_ticket = CodexDeviceAuthorizationTestSupport.issue_connection_ticket(
            client,
            device,
        )
        ticket_response = client.post(
            "/codex/realtime-tickets",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Origin": ORIGIN,
            },
        )
        assert ticket_response.status_code == HTTPStatus.OK
        ticket = ticket_response.json()["data"]["ticket"]
        with client.websocket_connect(
            f"/internal/codex-agents/connect?ticket={agent_ticket.ticket}",
        ) as agent_websocket:
            hello = CodexAgentHello(
                host_id=host_id,
                agent_version="1.0.0",
                codex_version=FROZEN_CODEX_VERSION,
                agent_protocol_version="1.0",
                app_server_schema_digest=FROZEN_APP_SERVER_SCHEMA_DIGEST,
                capabilities={"thread": ["list", "read", "start"]},
            )
            agent_websocket.send_text(CodexDeviceAuthorizationTestSupport.frame_v1("hello", hello))
            agent_websocket.receive_text()
            snapshot = CodexAgentStateSnapshot(
                host_id=host_id,
                app_server_instance_id="app-server-pipeline",
                workspaces=[
                    CodexAgentWorkspaceSnapshot(
                        key="work",
                        display_name="Work",
                        allow_write=True,
                    )
                ],
                threads=[
                    {
                        "id": thread_id,
                        "workspaceKey": "work",
                        "preview": "Pipeline",
                        "status": "active",
                        "createdAt": 1_700_000_000,
                        "updatedAt": 1_700_000_001,
                    }
                ],
                captured_at=datetime.now(UTC),
            )
            agent_websocket.send_text(
                CodexDeviceAuthorizationTestSupport.frame_v1("state.snapshot", snapshot)
            )
            with client.websocket_connect(
                f"/codex/events?ticket={ticket}",
                headers={"Origin": ORIGIN},
            ) as browser_websocket:
                for _ in range(3):
                    browser_websocket.receive_text()
                delta = CodexAgentRealtimeEvent(
                    host_id=host_id,
                    app_server_instance_id="app-server-pipeline",
                    method="item/agentMessage/delta",
                    params={
                        "threadId": thread_id,
                        "turnId": turn_id,
                        "itemId": item_id,
                        "delta": "hello",
                    },
                )
                agent_websocket.send_text(
                    CodexDeviceAuthorizationTestSupport.frame_v1("realtime.event", delta)
                )
                delta_event = CodexRealtimeEvent.model_validate_json(
                    browser_websocket.receive_text()
                )
                completed = CodexAgentRealtimeEvent(
                    host_id=host_id,
                    app_server_instance_id="app-server-pipeline",
                    method="item/completed",
                    params={
                        "threadId": thread_id,
                        "turnId": turn_id,
                        "item": {
                            "type": "agentMessage",
                            "id": item_id,
                            "text": "hello world",
                            "phase": None,
                            "memoryCitation": None,
                        },
                        "completedAtMs": 1_700_000_001_000,
                    },
                )
                agent_websocket.send_text(
                    CodexDeviceAuthorizationTestSupport.frame_v1(
                        "realtime.event",
                        completed,
                    )
                )
                completed_event = CodexRealtimeEvent.model_validate_json(
                    browser_websocket.receive_text()
                )

                browser_websocket.close()

            CodexDeviceAuthorizationTestSupport.close_websocket(agent_websocket)

    assert delta_event.type.value == "item.delta"
    assert delta_event.payload["delta"] == "hello"
    assert completed_event.type.value == "item.upsert"
    assert completed_event.payload["item"]["text"] == "hello world"
    assert completed_event.stream_epoch == delta_event.stream_epoch
    assert completed_event.event_id != delta_event.event_id
    assert "method" not in completed_event.model_dump()
    assert "params" not in completed_event.model_dump()
