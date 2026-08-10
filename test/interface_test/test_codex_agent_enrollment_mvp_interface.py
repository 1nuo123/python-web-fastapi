"""Codex Agent v2 设备注册、批准与一次性票据接口测试。"""

from __future__ import annotations

from http import HTTPStatus
from uuid import uuid4

from fastapi.testclient import TestClient

from src.api.endpoint_auth_access.contract_auth_access import StepUpGrantPayload
from src.api.testing.test_app_factory import TestAppFactory
from src.core.auth_contract.step_up_grant_contract import StepUpGrantPurpose
from src.core.codex_contract.device_key_contract import (
    AgentConnectionTicketResponse,
    DeviceChallengeIssueRequest,
    DeviceChallengeIssueRequestEnvelope,
    DeviceChallengeRequestHeader,
)
from src.core.codex_contract.host_contract import CodexHostCollection, CodexHostSnapshot
from src.core.http_contract.response_envelope_contract import ResponseEnvelope
from src.domain.codex.host_status import CodexHostStatus
from test.fixtures.codex_device_authorization_test_support import (
    TEST_ADMIN_PASSWORD,
    TEST_BROWSER_ORIGIN,
    CodexDeviceAuthorizationTestSupport,
)

AUTH_STEP_UP_PATH = "/auth/step-up"
CODEX_HOST_COLLECTION_PATH = "/codex/hosts"
CODEX_DEVICE_CHALLENGE_PATH = "/internal/codex-agents/device-challenges"


class TestCodexAgentEnrollmentV2Interface:
    """验证旧 bearer 注册停用且 v2 设备身份可完成授权。"""

    def test_legacy_pairing_should_be_gone_and_v2_device_should_be_authorized(self) -> None:
        app = TestAppFactory().create()
        with TestClient(app) as client:
            legacy_response = client.post(
                "/internal/codex-agents/enroll",
                json={
                    "host_id": "00000000-0000-0000-0000-000000000001",
                    "pairing_code": "expired-pairing-code-000000000000",
                },
            )
            assert legacy_response.status_code == HTTPStatus.GONE

            device = CodexDeviceAuthorizationTestSupport.authorize_device(client)
            ticket = CodexDeviceAuthorizationTestSupport.issue_connection_ticket(
                client,
                device,
            )

        assert device.host_id
        assert device.key_id
        assert isinstance(ticket, AgentConnectionTicketResponse)

    def test_revoke_host_should_require_bound_step_up_and_disable_device_key(self) -> None:
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

            approval_grant_response = client.post(
                AUTH_STEP_UP_PATH,
                headers={
                    **authorization_headers,
                    "Origin": TEST_BROWSER_ORIGIN,
                },
                json={
                    "password": TEST_ADMIN_PASSWORD,
                    "purpose": StepUpGrantPurpose.CODEX_HIGH_RISK_APPROVAL.value,
                },
            )
            approval_grant_response.raise_for_status()
            approval_grant = ResponseEnvelope[StepUpGrantPayload].model_validate(
                approval_grant_response.json()
            )
            wrong_purpose_response = client.post(
                f"{CODEX_HOST_COLLECTION_PATH}/{device.host_id}/revoke",
                headers={
                    **authorization_headers,
                    "If-Match": str(host.version),
                },
                json={"step_up_token": approval_grant.data.grant_token},
            )

            revoke_grant_response = client.post(
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
            revoke_grant_response.raise_for_status()
            revoke_grant = ResponseEnvelope[StepUpGrantPayload].model_validate(
                revoke_grant_response.json()
            )
            revoke_response = client.post(
                f"{CODEX_HOST_COLLECTION_PATH}/{device.host_id}/revoke",
                headers={
                    **authorization_headers,
                    "If-Match": str(host.version),
                },
                json={"step_up_token": revoke_grant.data.grant_token},
            )
            revoke_response.raise_for_status()
            revoked = ResponseEnvelope[CodexHostSnapshot].model_validate(revoke_response.json())

            challenge_response = client.post(
                CODEX_DEVICE_CHALLENGE_PATH,
                json=DeviceChallengeIssueRequestEnvelope(
                    header=DeviceChallengeRequestHeader(request_id=uuid4()),
                    detail=DeviceChallengeIssueRequest(
                        host_id=device.host_id,
                        key_id=device.key_id,
                    ),
                ).model_dump(mode="json"),
            )

        assert wrong_purpose_response.status_code == HTTPStatus.FORBIDDEN
        assert revoked.data.status == CodexHostStatus.REVOKED.value
        assert revoked.data.revoked_at is not None
        assert challenge_response.status_code == HTTPStatus.NOT_FOUND
