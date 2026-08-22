"""Codex 管理、发布与注册意图接口测试。"""

from __future__ import annotations

import asyncio
from http import HTTPStatus
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.testing.test_app_factory import TestAppFactory
from src.core.codex_contract.agent_release_manifest_contract import (
    CodexAgentReleaseDownloadEnvelope,
)
from src.core.codex_contract.enrollment_intent_contract import (
    CodexEnrollmentIntentCreateDetail,
    CodexEnrollmentIntentCreateRequestEnvelope,
    CodexEnrollmentIntentEnvelope,
    CodexEnrollmentIntentIssuedDetail,
    CodexEnrollmentIntentRequestHeader,
    CodexEnrollmentIntentStatusDetail,
)
from src.core.codex_contract.host_contract import CodexHostCollection
from src.core.http_contract.response_envelope_contract import ResponseEnvelope
from src.infrastructure.codex.codex_enrollment_intent_store import (
    CODEX_ENROLLMENT_INTENT_KEY_NAMESPACE,
    CODEX_ENROLLMENT_INTENT_TOKEN_NAMESPACE,
)
from src.infrastructure.settings.raw_application_settings import SettingsOverrideMapping
from test.fixtures.codex_device_authorization_test_support import (
    CodexDeviceAuthorizationTestSupport,
)

AUTHORIZATION_HEADER = "Authorization"
BEARER_TOKEN_PREFIX = "Bearer"
ORIGIN_HEADER = "Origin"
ACCESS_CONTROL_REQUEST_METHOD_HEADER = "Access-Control-Request-Method"
ACCESS_CONTROL_ALLOW_ORIGIN_HEADER = "Access-Control-Allow-Origin"
ACCESS_CONTROL_ALLOW_METHODS_HEADER = "Access-Control-Allow-Methods"
DEVELOPMENT_BROWSER_ORIGIN = "http://127.0.0.1:3000"
HTTP_PUT_METHOD = "PUT"
CODEX_ENROLLMENT_INTENT_PATH = "/codex/enrollment-intents"
CODEX_AGENT_RELEASE_PATH = "/codex/agent-release/current"
CODEX_ADMIN_HOSTS_PATH = "/admin/codex/hosts"
ADMIN_USER_SCOPES_PATH = "/admin/users/test-subject/scopes"
INTENT_TOKEN_QUERY_FIELD = "token"


class TestCodexAdminEnrollmentInterface:
    """验证浏览器管理接口和会话绑定的一次性注册流程。"""

    def test_admin_user_scope_preflight_should_allow_put_method(self) -> None:
        """验证分离部署的管理页可通过直接 scope 更新预检。"""

        with TestClient(TestAppFactory().create()) as client:
            response = client.options(
                ADMIN_USER_SCOPES_PATH,
                headers={
                    ORIGIN_HEADER: DEVELOPMENT_BROWSER_ORIGIN,
                    ACCESS_CONTROL_REQUEST_METHOD_HEADER: HTTP_PUT_METHOD,
                },
            )

        assert response.status_code == HTTPStatus.OK
        assert response.headers[ACCESS_CONTROL_ALLOW_ORIGIN_HEADER] == DEVELOPMENT_BROWSER_ORIGIN
        allowed_methods = {
            method.strip()
            for method in response.headers[ACCESS_CONTROL_ALLOW_METHODS_HEADER].split(",")
        }
        assert HTTP_PUT_METHOD in allowed_methods

    def test_authenticated_codex_admin_interfaces_should_keep_hosts_and_release_only(self) -> None:
        app = TestAppFactory().create()
        with TestClient(app) as client:
            access_token = CodexDeviceAuthorizationTestSupport.issue_browser_access_token(client)
            headers = self._authorization_headers(access_token)

            hosts_response = client.get(CODEX_ADMIN_HOSTS_PATH, headers=headers)
            release_response = client.get(CODEX_AGENT_RELEASE_PATH, headers=headers)
            removed_responses = [
                client.request(method, path, headers=headers)
                for method, path in (
                    ("GET", "/admin/codex/" + "access-" + "profiles"),
                    ("GET", "/codex/access/" + "effective"),
                    ("PUT", "/admin/codex/users/test-subject/" + "access"),
                    ("DELETE", "/admin/codex/users/test-subject/" + "access"),
                )
            ]

        assert hosts_response.status_code == HTTPStatus.OK
        ResponseEnvelope[CodexHostCollection].model_validate(hosts_response.json())
        assert all(response.status_code == HTTPStatus.NOT_FOUND for response in removed_responses)
        assert release_response.status_code == HTTPStatus.OK
        release = ResponseEnvelope[CodexAgentReleaseDownloadEnvelope].model_validate(
            release_response.json()
        )
        assert release.data.detail.download_url.startswith("https://")
        assert release.data.detail.manifest_url.startswith("https://")
        assert release.data.detail.distribution_mode.value == "verified"
        assert len(release.data.detail.artifact_sha256) == 64
        assert release.data.detail.automatic_updates_enabled is True

    def test_enrollment_intent_should_bind_token_session_and_hide_browser_token(self) -> None:
        app = TestAppFactory().create()
        intent_token = ""
        intent_id: UUID | None = None
        record_version = 1
        with TestClient(app) as client:
            try:
                first_access_token = CodexDeviceAuthorizationTestSupport.issue_browser_access_token(
                    client
                )
                create_response = client.post(
                    CODEX_ENROLLMENT_INTENT_PATH,
                    headers=self._authorization_headers(first_access_token),
                    json=CodexEnrollmentIntentCreateRequestEnvelope(
                        header=CodexEnrollmentIntentRequestHeader(request_id=uuid4()),
                        detail=CodexEnrollmentIntentCreateDetail(),
                    ).model_dump(mode="json"),
                )
                create_response.raise_for_status()
                created = ResponseEnvelope[CodexEnrollmentIntentEnvelope].model_validate(
                    create_response.json()
                )
                assert isinstance(created.data.detail, CodexEnrollmentIntentIssuedDetail)
                intent_id = created.data.header.intent_id
                parsed_launch_uri = urlparse(created.data.detail.launch_uri)
                query = parse_qs(parsed_launch_uri.query)
                intent_tokens = query.get(INTENT_TOKEN_QUERY_FIELD, [])
                assert parsed_launch_uri.scheme == "codexremote"
                assert parsed_launch_uri.netloc == "enroll"
                assert set(query) == {INTENT_TOKEN_QUERY_FIELD}
                assert len(intent_tokens) == 1
                intent_token = intent_tokens[0]
                assert first_access_token not in created.data.detail.launch_uri

                read_response = client.get(
                    f"{CODEX_ENROLLMENT_INTENT_PATH}/{intent_id}",
                    headers=self._authorization_headers(first_access_token),
                )
                read_response.raise_for_status()
                read_envelope = ResponseEnvelope[CodexEnrollmentIntentEnvelope].model_validate(
                    read_response.json()
                )
                assert isinstance(
                    read_envelope.data.detail,
                    CodexEnrollmentIntentStatusDetail,
                )

                second_access_token = (
                    CodexDeviceAuthorizationTestSupport.issue_browser_access_token(client)
                )
                cross_session_response = client.get(
                    f"{CODEX_ENROLLMENT_INTENT_PATH}/{intent_id}",
                    headers=self._authorization_headers(second_access_token),
                )

                record = asyncio.run(
                    app.state.container.resource_mount.get_codex_control_runtime().enrollment_intent_store.read_by_id(
                        intent_id
                    )
                )
                if record is not None:
                    record_version = record.version
                assert cross_session_response.status_code == HTTPStatus.NOT_FOUND
            finally:
                if intent_id is not None and intent_token:
                    self._delete_enrollment_intent(
                        app=app,
                        intent_id=intent_id,
                        intent_token=intent_token,
                        record_version=record_version,
                    )

    def test_development_enrollment_intent_should_launch_development_agent(self) -> None:
        """开发控制面只能返回 Development MSI 注册的独立 URI。"""

        overrides: SettingsOverrideMapping = {
            "runtime": {"codex_control": {"agent_deployment_profile": "development"}}
        }
        app = TestAppFactory().create(overrides=overrides)
        intent_token = ""
        intent_id: UUID | None = None
        record_version = 1
        with TestClient(app) as client:
            try:
                access_token = CodexDeviceAuthorizationTestSupport.issue_browser_access_token(
                    client
                )
                response = client.post(
                    CODEX_ENROLLMENT_INTENT_PATH,
                    headers=self._authorization_headers(access_token),
                    json=CodexEnrollmentIntentCreateRequestEnvelope(
                        header=CodexEnrollmentIntentRequestHeader(request_id=uuid4()),
                        detail=CodexEnrollmentIntentCreateDetail(),
                    ).model_dump(mode="json"),
                )
                response.raise_for_status()
                created = ResponseEnvelope[CodexEnrollmentIntentEnvelope].model_validate(
                    response.json()
                )
                assert isinstance(created.data.detail, CodexEnrollmentIntentIssuedDetail)
                intent_id = created.data.header.intent_id
                parsed_launch_uri = urlparse(created.data.detail.launch_uri)
                intent_token = parse_qs(parsed_launch_uri.query)[INTENT_TOKEN_QUERY_FIELD][0]
                assert parsed_launch_uri.scheme == "codexremote-dev"
                assert parsed_launch_uri.netloc == "enroll"
            finally:
                if intent_id is not None and intent_token:
                    self._delete_enrollment_intent(
                        app=app,
                        intent_id=intent_id,
                        intent_token=intent_token,
                        record_version=record_version,
                    )

    def _authorization_headers(self, access_token: str) -> dict[str, str]:
        return {AUTHORIZATION_HEADER: f"{BEARER_TOKEN_PREFIX} {access_token}"}

    def _delete_enrollment_intent(
        self,
        *,
        app: FastAPI,
        intent_id: UUID,
        intent_token: str,
        record_version: int,
    ) -> None:
        """删除测试创建的注册意图主记录和 token 索引。"""

        mount = app.state.container.resource_mount
        digest = mount.get_sensitive_digest_service().digest(intent_token)
        state = mount.get_atomic_state()
        asyncio.run(
            state.delete(
                key=f"{CODEX_ENROLLMENT_INTENT_KEY_NAMESPACE}:{intent_id}",
                expected_version=record_version,
            )
        )
        asyncio.run(
            state.delete(
                key=f"{CODEX_ENROLLMENT_INTENT_TOKEN_NAMESPACE}:{digest}",
                expected_version=1,
            )
        )
