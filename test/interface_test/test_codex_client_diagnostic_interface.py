"""Codex 客户端诊断 HTTP 接口测试。"""

from __future__ import annotations

from http import HTTPStatus

from fastapi.testclient import TestClient

from src.api.testing.test_app_factory import TestAppFactory
from src.infrastructure.codex.codex_client_diagnostic_recorder import (
    CODEX_CLIENT_DIAGNOSTIC_RATE_LIMIT_PER_MINUTE,
)

ORIGIN = "http://testserver"
DIAGNOSTIC_PATH = "/codex/diagnostics"
PERFORMANCE_DIAGNOSTIC_PATH = "/codex/diagnostics/performance"


def issue_access_token(client: TestClient) -> str:
    """签发拥有默认 Codex 读取权限的测试访问令牌。"""

    response = client.post(
        "/auth/browser/token",
        headers={"Origin": ORIGIN},
        json={"username": "admin", "password": "admin"},
    )
    assert response.status_code == HTTPStatus.OK
    return str(response.json()["data"]["access_token"])


def build_diagnostic_payload(event_id: str) -> dict[str, object]:
    """构建 API 契约中的最小安全诊断载荷。"""

    return {
        "header": {
            "kind": "client_diagnostic",
            "schema_version": "1.0",
            "event_id": event_id,
            "source": "window",
            "occurred_at": "2026-08-19T00:00:00Z",
        },
        "detail": {
            "kind": "client_diagnostic_detail",
            "schema_version": "1.0",
            "summary": "window_error",
            "error_code": "client.window.error",
            "fingerprint": "window:client.window.error",
        },
    }


def build_performance_payload(event_id: str) -> dict[str, object]:
    """构建仅含固定枚举、单位和数值的性能诊断载荷。"""

    return {
        "header": {
            "kind": "client_performance",
            "schema_version": "1.0",
            "event_id": event_id,
            "occurred_at": "2026-08-19T00:00:00Z",
        },
        "detail": {
            "kind": "client_performance_detail",
            "schema_version": "1.0",
            "metric": "approximate_fps",
            "observation": "observed",
            "unit": "frames_per_second",
            "value": 58.0,
        },
    }


def test_diagnostic_endpoint_should_require_authentication_reject_unknown_fields_and_suppress_excess() -> (
    None
):
    """验证认证、严格契约和每用户每指纹 20 条的失败软降级。"""

    with TestClient(
        TestAppFactory().create(
            overrides={
                "runtime": {
                    "codex_control": {
                        "client_diagnostic_error_collection_enabled": True,
                    }
                }
            }
        )
    ) as client:
        unauthenticated = client.post(DIAGNOSTIC_PATH, json=build_diagnostic_payload("no-auth"))
        assert unauthenticated.status_code == HTTPStatus.UNAUTHORIZED

        access_token = issue_access_token(client)
        headers = {"Authorization": f"Bearer {access_token}"}
        invalid_payload = build_diagnostic_payload("invalid")
        invalid_payload["detail"] = {
            **invalid_payload["detail"],
            "message": "Bearer access-token-value must never be accepted",
        }
        invalid = client.post(DIAGNOSTIC_PATH, headers=headers, json=invalid_payload)
        assert invalid.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert "access-token-value" not in invalid.text

        responses = [
            client.post(
                DIAGNOSTIC_PATH,
                headers=headers,
                json=build_diagnostic_payload(f"accepted-{index}"),
            )
            for index in range(CODEX_CLIENT_DIAGNOSTIC_RATE_LIMIT_PER_MINUTE + 1)
        ]

    assert all(response.status_code == HTTPStatus.OK for response in responses)
    assert all(response.json()["data"]["recorded"] for response in responses[:-1])
    assert not responses[-1].json()["data"]["recorded"]


def test_diagnostic_endpoint_should_acknowledge_without_recording_when_collection_disabled() -> (
    None
):
    """默认关闭的采集开关不得写日志，也不得让浏览器对诊断重试。"""

    with TestClient(TestAppFactory().create()) as client:
        access_token = issue_access_token(client)
        response = client.post(
            DIAGNOSTIC_PATH,
            headers={"Authorization": f"Bearer {access_token}"},
            json=build_diagnostic_payload("collection-disabled"),
        )

    assert response.status_code == HTTPStatus.OK
    assert not response.json()["data"]["recorded"]


def test_diagnostic_endpoint_should_require_codex_read_scope() -> None:
    """已认证但未获 Codex 读取权限的主体不得上传诊断。"""

    app = TestAppFactory().create(
        overrides={
            "auth_module": {
                "bootstrap_admin": {
                    "enabled": True,
                    "username": "diagnostic-limited-admin",
                    "subject_id": "diagnostic-limited-subject",
                    "role_bindings": [
                        {
                            "kind": "bootstrap_role_binding",
                            "schema_version": "v1",
                            "role_key": "admin",
                            "scope_codes": ["auth:read"],
                        }
                    ],
                }
            }
        }
    )
    with TestClient(app) as client:
        token_response = client.post(
            "/auth/browser/token",
            headers={"Origin": ORIGIN},
            json={"username": "diagnostic-limited-admin", "password": "admin"},
        )
        assert token_response.status_code == HTTPStatus.OK
        access_token = str(token_response.json()["data"]["access_token"])
        diagnostic_response = client.post(
            DIAGNOSTIC_PATH,
            headers={"Authorization": f"Bearer {access_token}"},
            json=build_diagnostic_payload("missing-codex-read"),
        )

    assert diagnostic_response.status_code == HTTPStatus.FORBIDDEN


def test_performance_diagnostic_endpoint_should_remain_disabled_by_default_and_accept_only_contract() -> (
    None
):
    """性能端点默认不写入，启用后只接受封闭的数值词表。"""

    with TestClient(TestAppFactory().create()) as client:
        access_token = issue_access_token(client)
        headers = {"Authorization": f"Bearer {access_token}"}
        disabled = client.post(
            PERFORMANCE_DIAGNOSTIC_PATH,
            headers=headers,
            json=build_performance_payload("performance-disabled"),
        )

    assert disabled.status_code == HTTPStatus.OK
    assert not disabled.json()["data"]["recorded"]

    with TestClient(
        TestAppFactory().create(
            overrides={
                "runtime": {
                    "codex_control": {
                        "client_diagnostic_performance_collection_enabled": True,
                    }
                }
            }
        )
    ) as client:
        access_token = issue_access_token(client)
        headers = {"Authorization": f"Bearer {access_token}"}
        enabled = client.post(
            PERFORMANCE_DIAGNOSTIC_PATH,
            headers=headers,
            json=build_performance_payload("performance-enabled"),
        )
        invalid_payload = build_performance_payload("performance-invalid")
        invalid_payload["detail"] = {
            **invalid_payload["detail"],
            "path": "/secret/thread/body",
        }
        invalid = client.post(
            PERFORMANCE_DIAGNOSTIC_PATH,
            headers=headers,
            json=invalid_payload,
        )

    assert enabled.status_code == HTTPStatus.OK
    assert enabled.json()["data"]["recorded"]
    assert invalid.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert "/secret/thread/body" not in invalid.text
