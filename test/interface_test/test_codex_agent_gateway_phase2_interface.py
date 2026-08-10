"""Phase 2 Codex Agent WSS 设备认证接口测试。"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.api.testing.test_app_factory import TestAppFactory
from src.core.codex_contract.agent_protocol_contract import CodexAgentHello, CodexAgentHelloAck
from src.core.codex_contract.app_server_schema_manifest_contract import (
    AppServerCapabilityCode,
    AppServerCapabilityDetail,
)
from src.core.codex_contract.connection_session_contract import CodexConnectionFrame
from src.core.codex_contract.host_contract import (
    CodexHostCapabilities,
    CodexHostCompatibilityState,
)
from src.infrastructure.persistence.orm_model.codex_control_operation_orm_model import (
    CodexControlOperationOrmModel,
)
from src.infrastructure.persistence.orm_model.codex_host_orm_model import CodexHostOrmModel
from src.infrastructure.persistence.orm_model.codex_thread_index_orm_model import (
    CodexThreadIndexOrmModel,
)
from src.infrastructure.persistence.orm_model.codex_workspace_orm_model import (
    CodexWorkspaceOrmModel,
)
from test.fixtures.codex_device_authorization_test_support import (
    FROZEN_APP_SERVER_SCHEMA_DIGEST,
    FROZEN_CODEX_VERSION,
    CodexDeviceAuthorizationTestSupport,
)


def test_connect_when_device_token_invalid_should_reject_before_accept() -> None:
    with TestClient(TestAppFactory().create()) as client:
        with pytest.raises(WebSocketDisconnect) as captured:
            with client.websocket_connect(
                "/internal/codex-agents/connect",
            ):
                pass

    assert captured.value.code == 4401


def test_connect_when_device_valid_should_accept_hello_and_return_epoch() -> None:
    app = TestAppFactory().create()
    with TestClient(app) as client:
        device = CodexDeviceAuthorizationTestSupport.authorize_device(client)
        ticket = CodexDeviceAuthorizationTestSupport.issue_connection_ticket(
            client,
            device,
        )

        hello = CodexAgentHello(
            host_id=device.host_id,
            agent_version="1.0.0",
            codex_version=FROZEN_CODEX_VERSION,
            agent_protocol_version="1.0",
            app_server_schema_digest=FROZEN_APP_SERVER_SCHEMA_DIGEST,
            capabilities={"thread": ["list", "start"]},
        )
        frame = CodexConnectionFrame(
            message_id="hello-1",
            message_type="hello",
            payload=hello.model_dump(mode="json"),
        )
        with client.websocket_connect(
            f"/internal/codex-agents/connect?ticket={ticket.ticket}",
        ) as websocket:
            websocket.send_text(frame.model_dump_json())
            response = CodexConnectionFrame.model_validate_json(websocket.receive_text())
            ack = CodexAgentHelloAck.model_validate(response.payload)
            websocket.close()
            with pytest.raises(WebSocketDisconnect) as closed:
                websocket.receive_text()

        assert response.message_type == "hello_ack"
        assert ack.host_id == device.host_id
        assert ack.connection_epoch == 1
        assert closed.value.code == 1000


def test_create_thread_when_agent_offline_should_queue_one_stable_command_for_retries() -> None:
    app = TestAppFactory().create()
    host_id = uuid4()
    workspace_id = uuid4()
    with TestClient(app) as client:
        access_token = client.post(
            "/auth/token",
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
                    display_name="Offline host",
                    platform="windows",
                    status="online",
                    capabilities=CodexHostCapabilities(
                        items=(
                            AppServerCapabilityDetail(
                                code=AppServerCapabilityCode.THREAD_START,
                                version=1,
                            ),
                        ),
                        model_ids=("gpt-5", "gpt-5-mini"),
                    ).model_dump(mode="json"),
                    compatibility_state=CodexHostCompatibilityState.COMPATIBLE.value,
                    compatibility_reason_code="supported",
                    last_seen_at=datetime.now(UTC),
                    version=1,
                )
            )
            session.add(
                CodexWorkspaceOrmModel(
                    workspace_id=workspace_id,
                    host_id=host_id,
                    owner_subject_id="user-admin",
                    agent_workspace_key="work",
                    display_name="Work",
                    enabled=True,
                    version=1,
                )
            )
            unit_of_work.commit()
        finally:
            unit_of_work.dispose()
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Idempotency-Key": "phase2-offline-retry",
        }
        hosts_response = client.get("/codex/hosts", headers=headers)
        first = client.post(
            f"/codex/hosts/{host_id}/threads",
            headers=headers,
            json={
                "workspace_id": str(workspace_id),
                "execution": {
                    "model": "gpt-5",
                    "reasoning_effort": None,
                    "sandbox_mode": "workspace-write",
                    "approval_policy": "untrusted",
                },
            },
        )
        second = client.post(
            f"/codex/hosts/{host_id}/threads",
            headers=headers,
            json={
                "workspace_id": str(workspace_id),
                "execution": {
                    "model": "gpt-5",
                    "reasoning_effort": None,
                    "sandbox_mode": "workspace-write",
                    "approval_policy": "untrusted",
                },
            },
        )
        conflict = client.post(
            f"/codex/hosts/{host_id}/threads",
            headers=headers,
            json={
                "workspace_id": str(workspace_id),
                "execution": {
                    "model": "gpt-5-mini",
                    "reasoning_effort": None,
                    "sandbox_mode": "workspace-write",
                    "approval_policy": "untrusted",
                },
            },
        )
        check_uow = resource_mount.create_unit_of_work()
        try:
            operations = (
                check_uow.get_session()
                .query(CodexControlOperationOrmModel)
                .filter_by(idempotency_key="phase2-offline-retry")
                .all()
            )
        finally:
            check_uow.dispose()

    assert hosts_response.status_code == 200
    assert hosts_response.json()["data"]["items"][0]["status"] == "offline"
    assert first.status_code == 202
    assert second.status_code == 202
    assert conflict.status_code == 409
    assert first.json()["data"]["operation_id"] == second.json()["data"]["operation_id"]
    assert first.json()["data"]["command_id"] == second.json()["data"]["command_id"]
    assert conflict.json()["header"]["code"] == "codex.operation.idempotency_conflict"
    assert len(operations) == 1
    assert operations[0].status == "dispatched"
    assert operations[0].error_code is None
    assert operations[0].dispatch_attempt == 2


def test_read_thread_snapshot_when_agent_offline_should_return_index_fallback() -> None:
    app = TestAppFactory().create()
    host_id = uuid4()
    workspace_id = uuid4()
    thread_index_id = uuid4()
    thread_id = "019-phase2-offline-thread"
    now = datetime.now(UTC)
    with TestClient(app) as client:
        access_token = client.post(
            "/auth/token",
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
                    display_name="Offline host",
                    platform="windows",
                    status="online",
                    capabilities={},
                    last_seen_at=now,
                    version=1,
                )
            )
            session.add(
                CodexWorkspaceOrmModel(
                    workspace_id=workspace_id,
                    host_id=host_id,
                    owner_subject_id="user-admin",
                    agent_workspace_key="work",
                    display_name="Work",
                    enabled=True,
                    version=1,
                )
            )
            session.add(
                CodexThreadIndexOrmModel(
                    thread_index_id=thread_index_id,
                    host_id=host_id,
                    workspace_id=workspace_id,
                    owner_subject_id="user-admin",
                    upstream_thread_id=thread_id,
                    display_name="Indexed thread",
                    model="gpt-5",
                    status="notLoaded",
                    archived=False,
                    source_kind=None,
                    updated_at=now,
                    last_synced_at=now,
                )
            )
            unit_of_work.commit()
        finally:
            unit_of_work.dispose()

        response = client.get(
            f"/codex/hosts/{host_id}/threads/{thread_id}",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    assert response.status_code == 200
    snapshot = response.json()["data"]
    assert snapshot["history_status"] == "not_available_yet"
    assert snapshot["thread"]["upstream_thread_id"] == thread_id
    assert snapshot["thread"]["display_name"] == "Indexed thread"
    assert snapshot["thread"]["status"] == "notLoaded"
    assert snapshot["turns"] == []
    assert snapshot["items"] == []
