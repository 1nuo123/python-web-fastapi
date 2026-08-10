"""Codex 浏览器实时票据与产品事件接口测试。"""

from __future__ import annotations

from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.api.testing.test_app_factory import TestAppFactory
from src.core.codex_contract.realtime_event_contract import CodexRealtimeEvent

ORIGIN = "http://testserver"


def _issue_access_token(client: TestClient) -> str:
    response = client.post(
        "/auth/browser/token",
        headers={"Origin": ORIGIN},
        json={"username": "admin", "password": "admin"},
    )
    assert response.status_code == HTTPStatus.OK
    return str(response.json()["data"]["access_token"])


def test_realtime_ticket_when_consumed_should_emit_new_epoch_and_authority_snapshots() -> None:
    with TestClient(TestAppFactory().create()) as client:
        access_token = _issue_access_token(client)
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
            f"/codex/events?ticket={ticket}",
            headers={"Origin": ORIGIN},
        ) as websocket:
            events = [
                CodexRealtimeEvent.model_validate_json(websocket.receive_text()) for _ in range(3)
            ]
            websocket.close()

    assert len({event.stream_epoch for event in events}) == 1
    assert [event.cursor for event in events] == [None, None, None]
    assert len({event.event_id for event in events}) == len(events)
    assert [event.type.value for event in events] == [
        "connection.ready",
        "host.snapshot",
        "workspace.snapshot",
    ]
    assert all("jsonrpc" not in event.model_dump() for event in events)


def test_realtime_ticket_when_reused_or_origin_missing_should_reject_before_accept() -> None:
    with TestClient(TestAppFactory().create()) as client:
        access_token = _issue_access_token(client)
        missing_origin = client.post(
            "/codex/realtime-tickets",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        ticket = client.post(
            "/codex/realtime-tickets",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Origin": ORIGIN,
            },
        ).json()["data"]["ticket"]
        with client.websocket_connect(
            f"/codex/events?ticket={ticket}",
            headers={"Origin": ORIGIN},
        ) as websocket:
            websocket.receive_text()
            websocket.close()
        with pytest.raises(WebSocketDisconnect) as captured:
            with client.websocket_connect(
                f"/codex/events?ticket={ticket}",
                headers={"Origin": ORIGIN},
            ):
                pass

    assert missing_origin.status_code == HTTPStatus.FORBIDDEN
    assert captured.value.code == 4403


def test_thread_snapshot_interface_should_publish_history_capacity_status() -> None:
    app = TestAppFactory().create()
    schema = app.openapi()["components"]["schemas"]["CodexThreadAuthoritySnapshot"]

    assert schema["properties"]["history_status"]["default"] == "complete"
    assert schema["properties"]["history_status"]["enum"] == [
        "complete",
        "not_requested",
        "omitted_too_large",
        "not_available_yet",
    ]
