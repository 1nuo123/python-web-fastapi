"""turn/steer 与 turn/interrupt 的 REST→Agent 幂等链路集成测试。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from http import HTTPStatus
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.testing.test_app_factory import TestAppFactory
from src.core.codex_contract.agent_protocol_contract import (
    CodexAgentCommandAck,
    CodexAgentCommandResult,
    CodexAgentHello,
)
from src.core.codex_contract.agent_protocol_v2_contract import (
    AgentThreadChangedEventDetail,
    AgentTurnChangedEventDetail,
    AgentTurnInterruptCommandDetail,
    AgentTurnSteerCommandDetail,
)
from src.core.codex_contract.app_server_product_contract import (
    AppServerThreadProductSnapshot,
)
from src.core.codex_contract.app_server_schema_manifest_contract import (
    AppServerNotificationName,
)
from src.core.codex_contract.thread_contract import CodexThreadTitleSource
from src.domain.codex.host_status import CodexThreadStatus
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

APP_SERVER_ACTIVE_TURN_STATUS = "inProgress"


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.docker
@pytest.mark.usefixtures("integration_database")
def test_active_turn_event_order_should_preserve_turn_and_allow_commands() -> None:
    app = TestAppFactory().create()
    host_id = uuid4()
    workspace_id = uuid4()
    thread_index_id = uuid4()
    thread_id = "019-control-thread"
    active_turn_id = "019-control-turn"
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
                    display_name="Control host",
                    platform="windows",
                    status="online",
                    capabilities={},
                    version=1,
                )
            )
            unit_of_work.flush()
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
            unit_of_work.flush()
            now = datetime.now(UTC)
            session.add(
                CodexThreadIndexOrmModel(
                    thread_index_id=thread_index_id,
                    host_id=host_id,
                    workspace_id=workspace_id,
                    owner_subject_id="user-admin",
                    upstream_thread_id=thread_id,
                    display_name="Control thread",
                    title_source=CodexThreadTitleSource.APP_SERVER.value,
                    status=CodexThreadStatus.IDLE.value,
                    active_turn_id=None,
                    archived=False,
                    created_at=now,
                    recency_at=now,
                    updated_at=now,
                    last_synced_at=now,
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
        headers = {"Authorization": f"Bearer {access_token}"}
        with client.websocket_connect(
            f"/internal/codex-agents/connect?ticket={agent_ticket.ticket}",
        ) as agent_websocket:
            connection = CodexDeviceAuthorizationTestSupport.connect_v2(
                agent_websocket,
                device,
            )
            app_server_instance_id = uuid4()
            CodexDeviceAuthorizationTestSupport.send_v2_event(
                agent_websocket,
                connection,
                AgentTurnChangedEventDetail(
                    method=AppServerNotificationName.TURN_STARTED,
                    thread_id=thread_id,
                    turn_id=active_turn_id,
                    status=APP_SERVER_ACTIVE_TURN_STATUS,
                ),
                sequence=1,
                app_server_instance_id=app_server_instance_id,
            )
            CodexDeviceAuthorizationTestSupport.send_v2_event(
                agent_websocket,
                connection,
                AgentThreadChangedEventDetail(
                    method=AppServerNotificationName.THREAD_STATUS_CHANGED,
                    thread=AppServerThreadProductSnapshot(
                        thread_id=thread_id,
                        display_name="Control thread",
                        status=CodexThreadStatus.ACTIVE.value,
                    ),
                ),
                sequence=2,
                app_server_instance_id=app_server_instance_id,
            )
            with ThreadPoolExecutor(max_workers=1) as executor:
                steer_future = executor.submit(
                    client.post,
                    f"/codex/hosts/{host_id}/threads/{thread_id}/steer",
                    headers={**headers, "Idempotency-Key": "steer-once"},
                    json={"message": "追加约束"},
                )
                steer_command = CodexDeviceAuthorizationTestSupport.receive_v2_command(
                    agent_websocket
                )
                CodexDeviceAuthorizationTestSupport.acknowledge_v2_command(
                    agent_websocket,
                    connection,
                    steer_command,
                )
                steer_response = steer_future.result(timeout=5)

                interrupt_future = executor.submit(
                    client.post,
                    f"/codex/hosts/{host_id}/threads/{thread_id}/interrupt",
                    headers={**headers, "Idempotency-Key": "interrupt-once"},
                )
                interrupt_command = CodexDeviceAuthorizationTestSupport.receive_v2_command(
                    agent_websocket
                )
                CodexDeviceAuthorizationTestSupport.acknowledge_v2_command(
                    agent_websocket,
                    connection,
                    interrupt_command,
                )
                interrupt_response = interrupt_future.result(timeout=5)

            CodexDeviceAuthorizationTestSupport.close_websocket(agent_websocket)

        check_uow = resource_mount.create_unit_of_work()
        try:
            check_session = check_uow.get_session()
            operations = (
                check_session.query(CodexControlOperationOrmModel)
                .filter_by(host_id=host_id, thread_id=thread_id)
                .all()
            )
            thread = check_session.get(CodexThreadIndexOrmModel, thread_index_id)
        finally:
            check_uow.dispose()

    assert steer_response.status_code == HTTPStatus.ACCEPTED
    assert interrupt_response.status_code == HTTPStatus.ACCEPTED
    assert isinstance(steer_command.detail, AgentTurnSteerCommandDetail)
    assert steer_command.detail.turn_id == active_turn_id
    assert isinstance(interrupt_command.detail, AgentTurnInterruptCommandDetail)
    assert interrupt_command.detail.turn_id == active_turn_id
    assert thread is not None
    assert thread.status == CodexThreadStatus.ACTIVE.value
    assert thread.active_turn_id == active_turn_id
    assert steer_command.header.command_id != interrupt_command.header.command_id
    assert {operation.operation_type for operation in operations} == {
        "turn.steer",
        "turn.interrupt",
    }
    assert all(not hasattr(operation, "message") for operation in operations)


def test_thread_read_should_restore_authoritative_turn_and_final_item_without_path_leak() -> None:
    app = TestAppFactory().create()
    host_id = uuid4()
    workspace_id = uuid4()
    thread_id = "019-snapshot-thread"
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
                    display_name="Snapshot host",
                    platform="windows",
                    status="online",
                    capabilities={},
                    version=1,
                )
            )
            unit_of_work.flush()
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
            unit_of_work.flush()
            now = datetime.now(UTC)
            session.add(
                CodexThreadIndexOrmModel(
                    thread_index_id=uuid4(),
                    host_id=host_id,
                    workspace_id=workspace_id,
                    owner_subject_id="user-admin",
                    upstream_thread_id=thread_id,
                    display_name="Snapshot",
                    title_source=CodexThreadTitleSource.APP_SERVER.value,
                    status="active",
                    active_turn_id="019-stale-active-turn",
                    archived=False,
                    created_at=now,
                    recency_at=now,
                    updated_at=now,
                    last_synced_at=now,
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
        with client.websocket_connect(
            f"/internal/codex-agents/connect?ticket={agent_ticket.ticket}",
        ) as agent_websocket:
            hello = CodexAgentHello(
                host_id=host_id,
                agent_version="1.0.0",
                codex_version=FROZEN_CODEX_VERSION,
                agent_protocol_version="1.0",
                app_server_schema_digest=FROZEN_APP_SERVER_SCHEMA_DIGEST,
                capabilities={"thread": ["read"]},
            )
            agent_websocket.send_text(CodexDeviceAuthorizationTestSupport.frame_v1("hello", hello))
            agent_websocket.receive_text()
            with ThreadPoolExecutor(max_workers=1) as executor:
                response_future = executor.submit(
                    client.get,
                    f"/codex/hosts/{host_id}/threads/{thread_id}?include_history=true",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                command = CodexDeviceAuthorizationTestSupport.receive_v1_command(agent_websocket)
                CodexDeviceAuthorizationTestSupport.acknowledge_v1_command(
                    agent_websocket,
                    command,
                )
                result = CodexAgentCommandResult(
                    command_id=command.command_id,
                    operation_id=command.operation_id,
                    outcome="completed",
                    result={
                        "thread": {
                            "id": thread_id,
                            "name": "Snapshot",
                            "preview": "Snapshot",
                            "modelProvider": "openai",
                            "status": {"type": "notLoaded"},
                            "createdAt": 1_700_000_000,
                            "updatedAt": 1_700_000_001,
                            "cwd": "C:\\private\\workspace",
                            "turns": [
                                {
                                    "id": "019-snapshot-turn",
                                    "status": "completed",
                                    "startedAt": 1_700_000_000,
                                    "completedAt": 1_700_000_001,
                                    "error": None,
                                    "items": [
                                        {
                                            "type": "agentMessage",
                                            "id": "019-snapshot-item",
                                            "text": "final answer",
                                        }
                                    ],
                                },
                                {
                                    "id": "019-interrupted-turn",
                                    "status": "interrupted",
                                    "startedAt": 1_700_000_002,
                                    "completedAt": 1_700_000_003,
                                    "error": None,
                                    "items": [],
                                },
                            ],
                        }
                    },
                )
                agent_websocket.send_text(
                    CodexDeviceAuthorizationTestSupport.frame_v1("command.result", result)
                )
                response = response_future.result(timeout=5)

            with ThreadPoolExecutor(max_workers=1) as executor:
                omitted_response_future = executor.submit(
                    client.get,
                    f"/codex/hosts/{host_id}/threads/{thread_id}?include_history=true",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                omitted_command = CodexDeviceAuthorizationTestSupport.receive_v1_command(
                    agent_websocket
                )
                CodexDeviceAuthorizationTestSupport.acknowledge_v1_command(
                    agent_websocket,
                    omitted_command,
                )
                agent_websocket.send_text(
                    CodexDeviceAuthorizationTestSupport.frame_v1(
                        "command.result",
                        CodexAgentCommandResult(
                            command_id=omitted_command.command_id,
                            operation_id=omitted_command.operation_id,
                            outcome="completed",
                            result={
                                "thread": {
                                    "id": thread_id,
                                    "name": "Snapshot",
                                    "modelProvider": "openai",
                                    "status": {"type": "notLoaded"},
                                    "createdAt": 1_700_000_000,
                                    "updatedAt": 1_700_000_001,
                                    "turns": [],
                                },
                                "historyStatus": "omitted_too_large",
                            },
                        ),
                    )
                )
                omitted_response = omitted_response_future.result(timeout=5)

            with ThreadPoolExecutor(max_workers=1) as executor:
                overflow_response_future = executor.submit(
                    client.get,
                    f"/codex/hosts/{host_id}/threads/{thread_id}?include_history=true",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                overflow_command = CodexDeviceAuthorizationTestSupport.receive_v1_command(
                    agent_websocket
                )
                agent_websocket.send_text(
                    CodexDeviceAuthorizationTestSupport.frame_v1(
                        "command.ack",
                        CodexAgentCommandAck(
                            command_id=overflow_command.command_id,
                            operation_id=overflow_command.operation_id,
                            state="failed",
                            replayed=False,
                        ),
                    )
                )
                agent_websocket.send_text(
                    CodexDeviceAuthorizationTestSupport.frame_v1(
                        "command.result",
                        CodexAgentCommandResult(
                            command_id=overflow_command.command_id,
                            operation_id=overflow_command.operation_id,
                            outcome="failed",
                            error_code="response_too_large",
                            error_message="App Server响应超过4 MiB，历史正文已省略。",
                        ),
                    )
                )
                overflow_response = overflow_response_future.result(timeout=5)

            with ThreadPoolExecutor(max_workers=1) as executor:
                metadata_response_future = executor.submit(
                    client.get,
                    f"/codex/hosts/{host_id}/threads/{thread_id}",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                metadata_command = CodexDeviceAuthorizationTestSupport.receive_v1_command(
                    agent_websocket
                )
                assert metadata_command.params["includeTurns"] is False
                CodexDeviceAuthorizationTestSupport.acknowledge_v1_command(
                    agent_websocket,
                    metadata_command,
                )
                agent_websocket.send_text(
                    CodexDeviceAuthorizationTestSupport.frame_v1(
                        "command.result",
                        CodexAgentCommandResult(
                            command_id=metadata_command.command_id,
                            operation_id=metadata_command.operation_id,
                            outcome="completed",
                            result={
                                "thread": {
                                    "id": thread_id,
                                    "name": "Snapshot",
                                    "modelProvider": "openai",
                                    "status": {"type": "notLoaded"},
                                    "createdAt": 1_700_000_000,
                                    "updatedAt": 1_700_000_001,
                                    "turns": [],
                                }
                            },
                        ),
                    )
                )
                metadata_response = metadata_response_future.result(timeout=5)

            CodexDeviceAuthorizationTestSupport.close_websocket(agent_websocket)

    assert response.status_code == HTTPStatus.OK
    snapshot = response.json()["data"]
    assert snapshot["history_status"] == "complete"
    assert snapshot["thread"]["upstream_thread_id"] == thread_id
    assert snapshot["thread"]["status"] == "interrupted"
    assert snapshot["thread"]["active_turn_id"] is None
    assert snapshot["turns"][0]["status"] == "completed"
    assert snapshot["turns"][1]["status"] == "interrupted"
    assert snapshot["items"][0]["header"]["detail_kind"] == "agent_message"
    assert snapshot["items"][0]["detail"]["text"] == "final answer"
    assert "cwd" not in response.text
    assert "C:\\private\\workspace" not in response.text
    assert omitted_response.status_code == HTTPStatus.OK
    omitted_snapshot = omitted_response.json()["data"]
    assert omitted_snapshot["history_status"] == "omitted_too_large"
    assert omitted_snapshot["turns"] == []
    assert omitted_snapshot["items"] == []
    assert overflow_response.status_code == HTTPStatus.OK
    assert overflow_response.json()["data"]["history_status"] == "omitted_too_large"
    assert metadata_response.status_code == HTTPStatus.OK
    assert metadata_response.json()["data"]["history_status"] == "not_requested"
