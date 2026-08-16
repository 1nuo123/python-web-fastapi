"""Codex 高风险执行参数 scope 授权接口测试。"""

from __future__ import annotations

from http import HTTPStatus
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.testing.test_app_factory import TestAppFactory
from src.domain.auth.auth_scope_code import AuthScopeCode
from src.infrastructure.persistence.orm_model.auth_user_orm_model import AuthUserOrmModel
from src.infrastructure.persistence.orm_model.auth_user_scope_orm_model import (
    AuthUserScopeOrmModel,
)

TEST_PASSWORD = "CodexScopeAuth-123!"


class TestCodexScopeAuthorizationInterface:
    """验证具体执行能力只由有效 scope 放行。"""

    def test_thread_start_should_require_tool_and_full_access_scopes(self) -> None:
        app = TestAppFactory().create()
        with TestClient(app) as client:
            cases = (
                (
                    {AuthScopeCode.CODEX_OPERATE.value},
                    "workspace-write",
                    HTTPStatus.FORBIDDEN,
                ),
                (
                    {
                        AuthScopeCode.CODEX_OPERATE.value,
                        AuthScopeCode.CODEX_FILES.value,
                        AuthScopeCode.CODEX_TERMINAL.value,
                    },
                    "workspace-write",
                    HTTPStatus.NOT_FOUND,
                ),
                (
                    {
                        AuthScopeCode.CODEX_OPERATE.value,
                        AuthScopeCode.CODEX_FILES.value,
                        AuthScopeCode.CODEX_TERMINAL.value,
                    },
                    "danger-full-access",
                    HTTPStatus.FORBIDDEN,
                ),
                (
                    {
                        AuthScopeCode.CODEX_OPERATE.value,
                        AuthScopeCode.CODEX_FILES.value,
                        AuthScopeCode.CODEX_TERMINAL.value,
                        AuthScopeCode.CODEX_FULL_ACCESS.value,
                    },
                    "danger-full-access",
                    HTTPStatus.NOT_FOUND,
                ),
            )
            for index, (scope_codes, sandbox_mode, expected_status) in enumerate(cases):
                username = f"codex-scope-user-{index}-{uuid4()}"
                self._create_user_with_scopes(
                    app=app,
                    username=username,
                    scope_codes=scope_codes,
                )
                access_token = client.post(
                    "/auth/token",
                    json={"username": username, "password": TEST_PASSWORD},
                ).json()["data"]["access_token"]

                response = client.post(
                    f"/codex/hosts/{uuid4()}/threads",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Idempotency-Key": f"scope-check-{uuid4()}",
                    },
                    json={
                        "workspace_id": str(uuid4()),
                        "execution": {
                            "model": None,
                            "reasoning_effort": None,
                            "sandbox_mode": sandbox_mode,
                            "approval_policy": "untrusted",
                        },
                    },
                )

                assert response.status_code == expected_status

    def _create_user_with_scopes(
        self,
        *,
        app: FastAPI,
        username: str,
        scope_codes: set[str],
    ) -> None:
        resource_mount = app.state.container.resource_mount
        unit_of_work = resource_mount.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            user_id = uuid4()
            session.add(
                AuthUserOrmModel(
                    user_id=user_id,
                    subject_id=f"subject-{username}",
                    username=username,
                    password_hash=resource_mount.get_password_hasher().hash_password(TEST_PASSWORD),
                    is_active=True,
                )
            )
            session.add_all(
                AuthUserScopeOrmModel(user_id=user_id, scope_code=scope_code)
                for scope_code in sorted(scope_codes)
            )
            unit_of_work.commit()
        except BaseException:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()
