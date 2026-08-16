"""Codex 远程连接产品 OpenAPI 契约测试。"""

from __future__ import annotations

from http import HTTPStatus

from fastapi.testclient import TestClient

from src.api.testing.test_app_factory import TestAppFactory

OPENAPI_PATH = "/openapi.json"
ENROLLMENT_ISSUED_SCHEMA_NAME = "CodexEnrollmentIntentIssuedDetail"
LAUNCH_URI_FIELD = "launch_uri"
EXPECTED_LAUNCH_URI_PATTERN = r"^codexremote://enroll\?token="
REQUIRED_CODEX_PATHS = frozenset(
    {
        "/admin/codex/hosts",
        "/codex/agent-release/current",
        "/codex/enrollment-intents",
        "/codex/enrollment-intents/{intent_id}",
        "/internal/codex-agents/enrollment-intents/consume",
    }
)
REMOVED_CODEX_PATHS = frozenset(
    {
        "/admin/codex/" + "access-" + "profiles",
        "/admin/codex/users/{subject_id}/" + "access",
        "/codex/access/" + "effective",
    }
)
FORBIDDEN_SHARED_HOST_PATH_TOKENS = ("transfer", "share", "member", "collaborator")


class TestCodexRemoteProductContract:
    """验证保留路由、注册契约和个人设备独占边界。"""

    def test_openapi_should_expose_codex_admin_enrollment_and_release_contracts(self) -> None:
        with TestClient(TestAppFactory().create()) as client:
            response = client.get(OPENAPI_PATH)

        assert response.status_code == HTTPStatus.OK
        openapi = response.json()
        paths = openapi["paths"]
        schemas = openapi["components"]["schemas"]
        assert REQUIRED_CODEX_PATHS.issubset(paths)
        assert REMOVED_CODEX_PATHS.isdisjoint(paths)
        assert (
            schemas[ENROLLMENT_ISSUED_SCHEMA_NAME]["properties"][LAUNCH_URI_FIELD]["pattern"]
            == EXPECTED_LAUNCH_URI_PATTERN
        )

    def test_openapi_should_not_expose_shared_host_management_paths(self) -> None:
        with TestClient(TestAppFactory().create()) as client:
            paths = client.get(OPENAPI_PATH).json()["paths"]

        codex_paths = tuple(path.lower() for path in paths if "codex" in path.lower())
        assert all(
            token not in path for path in codex_paths for token in FORBIDDEN_SHARED_HOST_PATH_TOKENS
        )
