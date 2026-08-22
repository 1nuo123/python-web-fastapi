"""基础审批打开、CAS 决定和浏览器终态推送集成测试。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.endpoint_auth_access.contract_auth_access import StepUpGrantPayload
from src.api.testing.test_app_factory import TestAppFactory
from src.core.auth_contract.step_up_grant_contract import StepUpGrantPurpose
from src.core.codex_contract.agent_protocol_v2_contract import (
    AgentApprovalOpenedEventDetail,
    AgentApprovalReplyCommandDetail,
    AgentPendingApprovalSnapshot,
)
from src.core.codex_contract.approval_contract import (
    CodexApprovalDecision,
    CodexApprovalDisplaySummary,
    CodexApprovalRiskLevel,
)
from src.core.codex_contract.device_key_contract import DeviceKeyState
from src.core.codex_contract.host_contract import CodexHostCollection, CodexHostSnapshot
from src.core.codex_contract.realtime_event_contract import (
    CodexApprovalEventDetail,
    CodexRealtimeEvent,
    CodexRealtimeEventType,
    CodexThreadUpdatedDetail,
)
from src.core.codex_contract.thread_contract import (
    CodexThreadStatus,
    CodexThreadTitleSource,
)
from src.core.http_contract.response_envelope_contract import ResponseEnvelope
from src.domain.codex.host_status import CodexApprovalState, CodexHostStatus
from src.infrastructure.persistence.orm_model.codex_device_authorization_audit_orm_model import (
    CodexDeviceAuthorizationAuditOrmModel,
)
from src.infrastructure.persistence.orm_model.codex_host_device_key_orm_model import (
    CodexHostDeviceKeyOrmModel,
)
from src.infrastructure.persistence.orm_model.codex_host_orm_model import CodexHostOrmModel
from src.infrastructure.persistence.orm_model.codex_thread_index_orm_model import (
    CodexThreadIndexOrmModel,
)
from src.infrastructure.persistence.orm_model.codex_workspace_orm_model import (
    CodexWorkspaceOrmModel,
)
from test.fixtures.codex_device_authorization_test_support import (
    TEST_ADMIN_PASSWORD,
    TEST_BROWSER_ORIGIN,
    CodexDeviceAuthorizationTestSupport,
)

ORIGIN = "http://testserver"
AUTH_STEP_UP_PATH = "/auth/step-up"
CODEX_HOST_COLLECTION_PATH = "/codex/hosts"


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.docker
@pytest.mark.usefixtures("integration_database")
def test_device_authorization_approval_should_persist_host_key_and_audit_atomically() -> None:
    app = TestAppFactory().create()
    with TestClient(app) as client:
        device = CodexDeviceAuthorizationTestSupport.authorize_device(client)
        unit_of_work = app.state.container.resource_mount.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            host = session.get(CodexHostOrmModel, device.host_id)
            key = session.get(CodexHostDeviceKeyOrmModel, device.key_id)
            assert host is not None
            assert key is not None
            audit = (
                session.query(CodexDeviceAuthorizationAuditOrmModel)
                .filter_by(
                    host_id=device.host_id,
                )
                .one()
            )
            assert key.host_id == device.host_id
            assert audit.host_id == device.host_id
        finally:
            unit_of_work.dispose()


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.docker
@pytest.mark.usefixtures("integration_database")
def test_host_revoke_should_atomically_revoke_host_and_device_key() -> None:
    app = TestAppFactory().create()
    with TestClient(app) as client:
        device = CodexDeviceAuthorizationTestSupport.authorize_device(client)
        access_token = CodexDeviceAuthorizationTestSupport.issue_browser_access_token(client)
        authorization_headers = {"Authorization": f"Bearer {access_token}"}
        hosts_response = client.get(
            CODEX_HOST_COLLECTION_PATH,
            headers=authorization_headers,
        )
        hosts_response.raise_for_status()
        hosts = ResponseEnvelope[CodexHostCollection].model_validate(hosts_response.json())
        host = next(item for item in hosts.data.items if item.host_id == device.host_id)
        grant_response = client.post(
            AUTH_STEP_UP_PATH,
            headers={
                **authorization_headers,
                "Origin": TEST_BROWSER_ORIGIN,
            },
            json={
                "password": TEST_ADMIN_PASSWORD,
                "purpose": StepUpGrantPurpose.CODEX_HOST_REVOKE.value,
            },
        )
        grant_response.raise_for_status()
        grant = ResponseEnvelope[StepUpGrantPayload].model_validate(grant_response.json())
        revoke_response = client.post(
            f"{CODEX_HOST_COLLECTION_PATH}/{device.host_id}/revoke",
            headers={
                **authorization_headers,
                "If-Match": str(host.version),
            },
            json={"step_up_token": grant.data.grant_token},
        )
        revoke_response.raise_for_status()
        revoked = ResponseEnvelope[CodexHostSnapshot].model_validate(revoke_response.json())

        unit_of_work = app.state.container.resource_mount.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            persisted_host = session.get(CodexHostOrmModel, device.host_id)
            persisted_key = session.get(CodexHostDeviceKeyOrmModel, device.key_id)
            assert persisted_host is not None
            assert persisted_key is not None
            assert persisted_host.status == CodexHostStatus.REVOKED.value
            assert persisted_host.revoked_at is not None
            assert persisted_key.state == DeviceKeyState.REVOKED.value
            assert persisted_key.revoked_at is not None
        finally:
            unit_of_work.dispose()

    assert revoked.data.status == CodexHostStatus.REVOKED.value
    assert revoked.data.revoked_at is not None


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.docker
@pytest.mark.usefixtures("integration_database")
def test_high_risk_approval_should_require_one_time_step_up_and_publish_terminal_decision() -> None:
    app = TestAppFactory().create()
    host_id = uuid4()
    workspace_id = uuid4()
    approval_id = uuid4()
    thread_id = "019-approval-thread"
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
                    display_name="Approval host",
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
                    display_name="Approval conversation",
                    title_source=CodexThreadTitleSource.APP_SERVER.value,
                    status=CodexThreadStatus.ACTIVE.value,
                    active_turn_id="019-approval-turn",
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
        ticket = client.post(
            "/codex/realtime-tickets",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Origin": ORIGIN,
            },
        ).json()["data"]["ticket"]
        with client.websocket_connect(
            f"/internal/codex-agents/connect?ticket={agent_ticket.ticket}",
        ) as agent_websocket:
            connection = CodexDeviceAuthorizationTestSupport.connect_v2(
                agent_websocket,
                device,
            )
            with client.websocket_connect(
                f"/codex/events?ticket={ticket}",
                headers={"Origin": ORIGIN},
            ) as browser_websocket:
                for _ in range(3):
                    browser_websocket.receive_text()
                CodexDeviceAuthorizationTestSupport.send_v2_event(
                    agent_websocket,
                    connection,
                    AgentApprovalOpenedEventDetail(
                        approval=AgentPendingApprovalSnapshot(
                            approval_id=approval_id,
                            app_server_instance_id=uuid4(),
                            approval_kind="command",
                            thread_id=thread_id,
                            turn_id="019-approval-turn",
                            item_id="019-approval-item",
                            payload_digest="b" * 64,
                            version=1,
                            expires_at=datetime.now(UTC) + timedelta(minutes=5),
                            display=CodexApprovalDisplaySummary(
                                title="命令审批",
                                reason="需要运行测试",
                                risk_level=CodexApprovalRiskLevel.HIGH,
                                # 浏览器只能提交 Agent 按冻结 schema 明确广告的官方动作。
                                allowed_actions=(CodexApprovalDecision.ACCEPT,),
                            ),
                        )
                    ),
                    sequence=1,
                    app_server_instance_id=uuid4(),
                )
                opened_event = CodexRealtimeEvent.model_validate_json(
                    browser_websocket.receive_text()
                )
                opened_thread_event = CodexRealtimeEvent.model_validate_json(
                    browser_websocket.receive_text()
                )
                approvals = client.get(
                    "/codex/approvals",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                missing_step_up = client.post(
                    f"/codex/approvals/{approval_id}/decision",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Idempotency-Key": "approval-without-step-up",
                    },
                    json={"decision": "accept", "approval_version": 1},
                )
                step_up = client.post(
                    "/auth/step-up",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Origin": ORIGIN,
                    },
                    json={
                        "password": "admin",
                        "purpose": "codex.high_risk_approval",
                    },
                )
                grant_token = step_up.json()["data"]["grant_token"]
                with ThreadPoolExecutor(max_workers=1) as executor:
                    decision_future = executor.submit(
                        client.post,
                        f"/codex/approvals/{approval_id}/decision",
                        headers={
                            "Authorization": f"Bearer {access_token}",
                            "Idempotency-Key": "approval-once",
                            "X-Step-Up-Token": grant_token,
                        },
                        json={"decision": "accept", "approval_version": 1},
                    )
                    command = CodexDeviceAuthorizationTestSupport.receive_v2_command(
                        agent_websocket
                    )
                    CodexDeviceAuthorizationTestSupport.acknowledge_v2_command(
                        agent_websocket,
                        connection,
                        command,
                    )
                    decision_response = decision_future.result(timeout=5)
                resolved_event = CodexRealtimeEvent.model_validate_json(
                    browser_websocket.receive_text()
                )
                grant_reuse_response = client.post(
                    f"/codex/approvals/{approval_id}/decision",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Idempotency-Key": "approval-reused-step-up",
                        "X-Step-Up-Token": grant_token,
                    },
                    json={"decision": "accept", "approval_version": 2},
                )
                browser_websocket.close()
            CodexDeviceAuthorizationTestSupport.close_websocket(agent_websocket)

    assert opened_event.header.detail_kind == CodexRealtimeEventType.APPROVAL_OPENED
    assert isinstance(opened_event.detail, CodexApprovalEventDetail)
    assert opened_thread_event.header.detail_kind == CodexRealtimeEventType.THREAD_UPDATED
    assert isinstance(opened_thread_event.detail, CodexThreadUpdatedDetail)
    assert opened_thread_event.detail.thread.upstream_thread_id == thread_id
    assert opened_thread_event.detail.thread.recency_at is not None
    assert approvals.status_code == HTTPStatus.OK
    persisted = approvals.json()["data"]["items"][0]
    assert persisted["display_summary"] == {
        "title": "命令审批",
        "reason": "需要运行测试",
        "workspace_name": None,
        "risk_level": "high",
        "command_summary": None,
        "command": None,
        "command_actions": [],
        "working_directory": None,
        "read_only": False,
        "file_scope": [],
        "file_changes": [],
        "permission_names": [],
        "network_requested": False,
        "extra_root_requested": False,
        "risk_reason": None,
        "allowed_actions": ["accept"],
    }
    opened_approval = opened_event.detail.approval.model_dump(mode="json")
    assert opened_approval == persisted
    assert missing_step_up.status_code == HTTPStatus.FORBIDDEN
    assert step_up.status_code == HTTPStatus.OK
    assert grant_reuse_response.status_code == HTTPStatus.FORBIDDEN
    assert decision_response.status_code == HTTPStatus.ACCEPTED
    assert isinstance(command.detail, AgentApprovalReplyCommandDetail)
    assert command.detail.approval_id == approval_id
    assert command.detail.decision == "accept"
    assert command.detail.approval_version == 1
    assert resolved_event.header.detail_kind == CodexRealtimeEventType.APPROVAL_RESOLVED
    assert isinstance(resolved_event.detail, CodexApprovalEventDetail)
    assert resolved_event.detail.approval.state == CodexApprovalState.APPLIED
