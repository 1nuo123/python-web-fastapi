"""Codex Phase 1 浏览器认证与所有权接口测试。"""

from http import HTTPStatus
from uuid import uuid4

from fastapi.testclient import TestClient

from src.api.testing.test_app_factory import TestAppFactory
from src.infrastructure.persistence.orm_model.auth_user_orm_model import AuthUserOrmModel
from src.infrastructure.persistence.orm_model.codex_host_orm_model import CodexHostOrmModel

ORIGIN = "http://testserver"


class TestCodexPhase1Interface:
    def test_browser_token_when_origin_allowed_should_set_httponly_cookie_without_refresh_body(
        self,
    ) -> None:
        with TestClient(TestAppFactory().create()) as client:
            response = client.post(
                "/auth/browser/token",
                headers={"Origin": ORIGIN},
                json={"username": "admin", "password": "admin"},
            )

        assert response.status_code == HTTPStatus.OK
        assert "refresh_token" not in response.json()["data"]
        cookie = response.headers["set-cookie"]
        assert "HttpOnly" in cookie
        assert "SameSite=strict" in cookie
        assert "Path=/auth/browser" in cookie

    def test_browser_token_when_origin_missing_should_return_forbidden(self) -> None:
        with TestClient(TestAppFactory().create()) as client:
            response = client.post(
                "/auth/browser/token",
                json={"username": "admin", "password": "admin"},
            )

        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_browser_token_when_trusted_proxy_origin_should_set_cookie(self) -> None:
        with TestClient(
            TestAppFactory().create(),
            base_url="http://backend.internal",
            client=("127.0.0.1", 50000),
        ) as client:
            response = client.post(
                "/auth/browser/token",
                headers={
                    "Origin": "https://console.example.test",
                    "X-Forwarded-For": "203.0.113.10",
                    "X-Forwarded-Host": "console.example.test",
                    "X-Forwarded-Proto": "https",
                },
                json={"username": "admin", "password": "admin"},
            )

        assert response.status_code == HTTPStatus.OK
        assert "HttpOnly" in response.headers["set-cookie"]

    def test_browser_refresh_and_revoke_should_use_cookie_only(self) -> None:
        with TestClient(TestAppFactory().create()) as client:
            issue_response = client.post(
                "/auth/browser/token",
                headers={"Origin": ORIGIN},
                json={"username": "admin", "password": "admin"},
            )
            refresh_response = client.post(
                "/auth/browser/refresh",
                headers={"Origin": ORIGIN},
            )
            revoke_response = client.post(
                "/auth/browser/revoke",
                headers={"Origin": ORIGIN},
            )

        assert issue_response.status_code == HTTPStatus.OK
        assert refresh_response.status_code == HTTPStatus.OK
        assert "refresh_token" not in refresh_response.json()["data"]
        assert revoke_response.status_code == HTTPStatus.OK
        assert "Max-Age=0" in revoke_response.headers["set-cookie"]

    def test_codex_interfaces_when_other_owner_host_should_hide_resource(self) -> None:
        app = TestAppFactory().create()
        other_host_id = uuid4()
        own_host_id = uuid4()
        with TestClient(app) as client:
            token_response = client.post(
                "/auth/token",
                json={"username": "admin", "password": "admin"},
            )
            access_token = token_response.json()["data"]["access_token"]
            resource_mount = app.state.container.resource_mount
            unit_of_work = resource_mount.create_unit_of_work()
            try:
                session = unit_of_work.get_session()
                session.add(
                    AuthUserOrmModel(
                        subject_id="other-owner",
                        username="other-owner",
                        password_hash=resource_mount.get_password_hasher().hash_password("unused"),
                        is_active=True,
                    )
                )
                session.add(
                    CodexHostOrmModel(
                        host_id=other_host_id,
                        owner_subject_id="other-owner",
                        display_name="其他电脑",
                        platform="windows",
                        status="offline",
                        capabilities={},
                        version=1,
                    )
                )
                session.add(
                    CodexHostOrmModel(
                        host_id=own_host_id,
                        owner_subject_id="user-admin",
                        display_name="我的电脑",
                        platform="windows",
                        status="offline",
                        capabilities={},
                        version=1,
                    )
                )
                unit_of_work.commit()
            finally:
                unit_of_work.dispose()

            headers = {"Authorization": f"Bearer {access_token}"}
            hosts_response = client.get("/codex/hosts", headers=headers)
            hidden_response = client.get(
                f"/codex/hosts/{other_host_id}/workspaces",
                headers=headers,
            )

        visible_ids = {item["host_id"] for item in hosts_response.json()["data"]["items"]}
        assert hosts_response.status_code == HTTPStatus.OK
        assert str(own_host_id) in visible_ids
        assert str(other_host_id) not in visible_ids
        assert hidden_response.status_code == HTTPStatus.NOT_FOUND
