"""Codex 浏览器实时票据与产品事件接口测试。"""

from __future__ import annotations

from http import HTTPStatus
from itertools import product

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.api.testing.test_app_factory import TestAppFactory
from src.core.codex_contract.realtime_batch_contract import CodexRealtimeBatch
from src.core.codex_contract.realtime_event_contract import CodexRealtimeEvent
from src.core.logging_contract.log_event_contract import (
    CodexExperienceFeatureFlagsLogDetail,
    LogEventEnvelope,
    LogEventKind,
)
from src.infrastructure.settings.raw_application_settings import SettingsOverrideMapping

ORIGIN = "http://testserver"
FEATURE_FLAG_NAMES = (
    "codex_scroll_controller_v2",
    "codex_realtime_batch_v2",
    "codex_authority_recovery_v2",
)
FEATURE_FLAG_COMBINATIONS = tuple(product((False, True), repeat=3))


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

    assert len({event.header.stream_epoch for event in events}) == 1
    assert [event.header.cursor for event in events] == [None, None, None]
    assert len({event.header.event_id for event in events}) == len(events)
    assert [event.header.detail_kind.value for event in events] == [
        "connection.ready",
        "host.snapshot",
        "workspace.snapshot",
    ]
    assert all("jsonrpc" not in event.model_dump() for event in events)


def test_realtime_batch_request_when_server_flag_disabled_should_keep_legacy_events() -> None:
    """客户端不得通过 query 参数绕过默认关闭的服务器批次发布开关。"""

    with TestClient(TestAppFactory().create()) as client:
        access_token = _issue_access_token(client)
        ticket = client.post(
            "/codex/realtime-tickets",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Origin": ORIGIN,
            },
        ).json()["data"]["ticket"]
        with client.websocket_connect(
            f"/codex/events?ticket={ticket}&batch_version=2",
            headers={"Origin": ORIGIN},
        ) as websocket:
            payload = websocket.receive_text()
            websocket.close()

    assert (
        CodexRealtimeEvent.model_validate_json(payload).header.detail_kind.value
        == "connection.ready"
    )


def test_realtime_batch_request_when_server_flag_enabled_should_emit_batch() -> None:
    """浏览器请求和服务端开关同时开启后才允许 v2 批次输出。"""

    overrides: SettingsOverrideMapping = {
        "runtime": {"codex_control": {"codex_realtime_batch_v2": True}}
    }
    app = TestAppFactory().create(overrides=overrides)
    with TestClient(app) as client:
        access_token = _issue_access_token(client)
        ticket = client.post(
            "/codex/realtime-tickets",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Origin": ORIGIN,
            },
        ).json()["data"]["ticket"]
        with client.websocket_connect(
            f"/codex/events?ticket={ticket}&batch_version=2",
            headers={"Origin": ORIGIN},
        ) as websocket:
            payload = websocket.receive_text()
            websocket.close()

    batch = CodexRealtimeBatch.model_validate_json(payload)
    assert batch.events[0].header.detail_kind.value == "connection.ready"


def test_feature_flags_endpoint_returns_server_authority_and_requires_authentication() -> None:
    """接口返回服务器决定，并记录不含认证上下文的固定发布决策。"""

    overrides: SettingsOverrideMapping = {
        "runtime": {
            "codex_control": {
                "codex_scroll_controller_v2": True,
                "codex_realtime_batch_v2": True,
                "codex_authority_recovery_v2": False,
            }
        }
    }
    app = TestAppFactory().create(overrides=overrides)
    emitted_events: list[LogEventEnvelope] = []
    runtime = app.state.container.resource_mount.get_codex_control_runtime()
    runtime.feature_flag_log_event_emitter = emitted_events.append
    with TestClient(app) as client:
        unauthorized = client.get("/codex/experience/feature-flags")
        access_token = _issue_access_token(client)
        authorized = client.get(
            "/codex/experience/feature-flags",
            headers={"Authorization": f"Bearer {access_token}", "Origin": ORIGIN},
        )

    assert unauthorized.status_code in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}
    assert authorized.status_code == HTTPStatus.OK
    assert authorized.json()["data"] == {
        "codex_scroll_controller_v2": True,
        "codex_realtime_batch_v2": True,
        "codex_authority_recovery_v2": False,
    }
    assert len(emitted_events) == 1
    emitted_event = emitted_events[0]
    assert emitted_event.header.kind == LogEventKind.CODEX_EXPERIENCE_FEATURE_FLAGS
    assert emitted_event.header.authenticated_subject_id is None
    assert emitted_event.header.request_id is None
    assert isinstance(emitted_event.detail, CodexExperienceFeatureFlagsLogDetail)
    assert tuple(decision.enabled for decision in emitted_event.detail.decisions) == (
        True,
        True,
        False,
    )


@pytest.mark.parametrize("flag_values", FEATURE_FLAG_COMBINATIONS)
def test_feature_flag_combination_should_boot_and_return_exact_server_values(
    flag_values: tuple[bool, bool, bool],
) -> None:
    """八种服务端开关组合都必须能启动，并按原值返回权威配置。"""

    overrides: SettingsOverrideMapping = {
        "runtime": {"codex_control": dict(zip(FEATURE_FLAG_NAMES, flag_values, strict=True))}
    }
    app = TestAppFactory().create(overrides=overrides)
    with TestClient(app) as client:
        access_token = _issue_access_token(client)
        response = client.get(
            "/codex/experience/feature-flags",
            headers={"Authorization": f"Bearer {access_token}", "Origin": ORIGIN},
        )

    assert response.status_code == HTTPStatus.OK
    assert response.json()["data"] == dict(zip(FEATURE_FLAG_NAMES, flag_values, strict=True))


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
    openapi = app.openapi()
    schema = openapi["components"]["schemas"]["CodexThreadAuthoritySnapshot"]
    history_page_schema = openapi["components"]["schemas"]["CodexThreadHistoryPage"]
    history_item_reload_schema = openapi["components"]["schemas"]["CodexThreadHistoryItemReload"]
    history_status_schema = openapi["components"]["schemas"]["CodexThreadHistoryStatus"]

    assert schema["properties"]["history_status"]["default"] == "complete"
    assert {"history_before_cursor", "history_has_more", "history_revision"}.issubset(
        schema["properties"]
    )
    assert set(history_page_schema["required"]) == {
        "items",
        "has_more",
        "history_revision",
    }
    assert "/codex/hosts/{host_id}/threads/{thread_id}/history" in openapi["paths"]
    history_item_reload_path = "/codex/hosts/{host_id}/threads/{thread_id}/history/items"
    assert history_item_reload_path in openapi["paths"]
    assert set(history_item_reload_schema["properties"]) == {
        "items",
        "missing_item_ids",
    }
    item_id_parameter = openapi["paths"][history_item_reload_path]["get"]["parameters"][2]
    assert item_id_parameter["name"] == "item_id"
    assert item_id_parameter["in"] == "query"
    assert item_id_parameter["schema"]["maxItems"] == 50
    assert history_status_schema["enum"] == [
        "complete",
        "not_requested",
        "omitted_too_large",
        "not_available_yet",
    ]
