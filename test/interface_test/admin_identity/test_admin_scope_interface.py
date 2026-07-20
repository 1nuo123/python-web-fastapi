"""
管理员 scope 接口测试模块。
"""

from __future__ import annotations

from http import HTTPStatus
from uuid import uuid4

from fastapi.testclient import TestClient

from src.api.endpoint_admin_identity.contract_admin_identity_common import (
    ADMIN_IDENTITY_SCHEMA_VERSION,
    AdminIdentityOperationName,
    AdminIdentityPayloadKind,
)
from src.api.endpoint_admin_identity.route_admin_identity_common import (
    ADMIN_SCOPE_DETAIL_PATH,
    ADMIN_SCOPES_PATH,
)
from src.api.testing.test_app_factory import TestAppFactory
from src.application.admin.identity.shared.admin_identity_command import (
    AdminScopeUpdateCommand,
)
from src.application.ports.admin_identity_port import (
    AdminScopeKind,
    AdminScopeSnapshot,
)
from src.domain.auth.auth_scope_code import AuthScopeCode

AUTH_TOKEN_PATH = "/auth/token"
AUTHORIZATION_HEADER = "Authorization"
BEARER_PREFIX = "Bearer"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin"
DATA_FIELD = "data"
DETAIL_FIELD = "detail"
SCOPE_CODE_FIELD = "scope_code"
DELETED_FIELD = "deleted"
UNKNOWN_FIELD_NAME = "unknown"
AUTH_READ_SCOPE = AuthScopeCode.AUTH_READ.value
DEFAULT_ADMIN_SUBJECT_ID = "user-admin"
SCOPE_INTERFACE_NAME = "接口 scope"
SCOPE_INTERFACE_UPDATED_NAME = "接口 scope 更新"


class AdminScopeUpdateUsecaseSpy:
    """
    管理员 scope 更新用例测试替身。
    """

    def __init__(self) -> None:
        """
        初始化测试替身。
        """

        self.command: AdminScopeUpdateCommand | None = None

    def execute(self, command: AdminScopeUpdateCommand) -> AdminScopeSnapshot:
        """
        记录路由传入的更新命令。
        """

        self.command = command
        return AdminScopeSnapshot(
            scope_code=command.scope_code,
            scope_name=command.scope_name or SCOPE_INTERFACE_UPDATED_NAME,
            description=command.description,
            scope_kind=AdminScopeKind.BUILTIN,
            enabled=command.enabled if command.enabled is not None else True,
        )


class TestAdminScopeInterface:
    """
    管理员 scope 接口测试集合。
    """

    def test_scope_crud_routes_should_require_admin_token_and_match_contract(
        self,
    ) -> None:
        """
        验证 scope 读取和写入路由完整挂载。
        """

        scope_code = self._build_scope_code("boundary")
        app = TestAppFactory().create()

        with TestClient(app) as client:
            unauthorized_response = client.get(ADMIN_SCOPES_PATH)
            access_token = self._issue_admin_token(client)
            auth_header = self._build_auth_header(access_token)
            list_response = client.get(ADMIN_SCOPES_PATH, headers=auth_header)
            detail_response = client.get(
                ADMIN_SCOPE_DETAIL_PATH.format(scope_code=AUTH_READ_SCOPE),
                headers=auth_header,
            )
            create_response = client.post(
                ADMIN_SCOPES_PATH,
                headers=auth_header,
                json=self._build_scope_create_body(scope_code),
            )
            update_response = client.patch(
                ADMIN_SCOPE_DETAIL_PATH.format(scope_code=scope_code),
                headers=auth_header,
                json=self._build_scope_update_body(),
            )
            delete_response = client.delete(
                ADMIN_SCOPE_DETAIL_PATH.format(scope_code=scope_code),
                headers=auth_header,
            )

        assert unauthorized_response.status_code == HTTPStatus.UNAUTHORIZED
        assert list_response.status_code == HTTPStatus.OK
        assert detail_response.status_code == HTTPStatus.OK
        assert create_response.status_code == HTTPStatus.OK
        assert create_response.json()[DATA_FIELD][DETAIL_FIELD][SCOPE_CODE_FIELD] == scope_code
        assert update_response.status_code == HTTPStatus.OK
        assert delete_response.status_code == HTTPStatus.OK
        assert delete_response.json()[DATA_FIELD][DETAIL_FIELD][DELETED_FIELD] is True

    def test_disabled_admin_identity_module_should_not_mount_scope_route(self) -> None:
        """
        验证禁用管理员身份模块后也不装配 scope 路由。
        """

        app = TestAppFactory().create(
            overrides={
                "app": {
                    "modules": {
                        "enabled": [
                            "health_probe",
                            "auth_access",
                        ],
                    }
                }
            }
        )

        with TestClient(app) as client:
            access_token = self._issue_admin_token(client)
            response = client.get(
                ADMIN_SCOPES_PATH,
                headers=self._build_auth_header(access_token),
            )

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_scope_write_when_unknown_field_should_return_422(self) -> None:
        """
        验证 scope 写接口 HTTP 层拒绝未知字段。
        """

        scope_code = self._build_scope_code("unknown")
        app = TestAppFactory().create()

        with TestClient(app) as client:
            access_token = self._issue_admin_token(client)
            auth_header = self._build_auth_header(access_token)
            create_response = client.post(
                ADMIN_SCOPES_PATH,
                headers=auth_header,
                json=self._with_unknown_detail_field(self._build_scope_create_body(scope_code)),
            )
            update_response = client.patch(
                ADMIN_SCOPE_DETAIL_PATH.format(scope_code=scope_code),
                headers=auth_header,
                json=self._with_unknown_detail_field(self._build_scope_update_body()),
            )

        assert create_response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert update_response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_scope_update_when_protected_builtin_disabled_should_return_conflict(
        self,
    ) -> None:
        """
        验证 HTTP 接口拒绝禁用受保护内置 scope。
        """

        app = TestAppFactory().create()

        with TestClient(app) as client:
            access_token = self._issue_admin_token(client)
            response = client.patch(
                ADMIN_SCOPE_DETAIL_PATH.format(scope_code=AuthScopeCode.AUTH_MANAGE.value),
                headers=self._build_auth_header(access_token),
                json=self._build_scope_update_body(enabled=False),
            )

        assert response.status_code == HTTPStatus.CONFLICT

    def test_scope_update_when_security_manage_disabled_should_return_conflict(
        self,
    ) -> None:
        """
        验证 HTTP 接口拒绝禁用 security:manage。
        """

        app = TestAppFactory().create()

        with TestClient(app) as client:
            access_token = self._issue_admin_token(client)
            response = client.patch(
                ADMIN_SCOPE_DETAIL_PATH.format(scope_code=AuthScopeCode.SECURITY_MANAGE.value),
                headers=self._build_auth_header(access_token),
                json=self._build_scope_update_body(enabled=False),
            )

        assert response.status_code == HTTPStatus.CONFLICT

    def test_scope_update_should_transmit_actor_subject_id(self) -> None:
        """
        验证 scope 更新路由会把当前 principal 主体标识传入命令。
        """

        app = TestAppFactory().create()
        usecase_spy = AdminScopeUpdateUsecaseSpy()
        app.state.container.update_admin_scope_usecase = usecase_spy

        with TestClient(app) as client:
            access_token = self._issue_admin_token(client)
            response = client.patch(
                ADMIN_SCOPE_DETAIL_PATH.format(scope_code=AuthScopeCode.AUTH_MANAGE.value),
                headers=self._build_auth_header(access_token),
                json=self._build_scope_update_body(enabled=True),
            )

        assert response.status_code == HTTPStatus.OK
        assert usecase_spy.command is not None
        assert usecase_spy.command.actor_subject_id == DEFAULT_ADMIN_SUBJECT_ID

    def test_scope_update_when_task_dispatch_disabled_should_return_conflict(
        self,
    ) -> None:
        """
        验证任务派发受保护 scope 也不允许通过接口禁用。
        """

        app = TestAppFactory().create()

        with TestClient(app) as client:
            access_token = self._issue_admin_token(client)
            response = client.patch(
                ADMIN_SCOPE_DETAIL_PATH.format(scope_code=AuthScopeCode.TASK_DISPATCH.value),
                headers=self._build_auth_header(access_token),
                json=self._build_scope_update_body(enabled=False),
            )

        assert response.status_code == HTTPStatus.CONFLICT

    def _build_scope_code(self, suffix: str) -> str:
        """
        构建 scope 编码。
        """

        return f"interface:{suffix}:{uuid4()}"

    def _build_scope_create_body(self, scope_code: str) -> dict[str, object]:
        """
        构建 scope 创建请求体。
        """

        return {
            "header": {
                "kind": AdminIdentityPayloadKind.SCOPE_CREATE.value,
                "schema_version": ADMIN_IDENTITY_SCHEMA_VERSION,
                "operation_name": AdminIdentityOperationName.SCOPE_CREATE.value,
            },
            "detail": {
                "kind": AdminIdentityPayloadKind.SCOPE_CREATE.value,
                "schema_version": ADMIN_IDENTITY_SCHEMA_VERSION,
                "scope_code": scope_code,
                "scope_name": SCOPE_INTERFACE_NAME,
                "description": None,
                "enabled": True,
            },
        }

    def _build_scope_update_body(
        self,
        *,
        enabled: bool | None = True,
    ) -> dict[str, object]:
        """
        构建 scope 更新请求体。
        """

        return {
            "header": {
                "kind": AdminIdentityPayloadKind.SCOPE_UPDATE.value,
                "schema_version": ADMIN_IDENTITY_SCHEMA_VERSION,
                "operation_name": AdminIdentityOperationName.SCOPE_UPDATE.value,
            },
            "detail": {
                "kind": AdminIdentityPayloadKind.SCOPE_UPDATE.value,
                "schema_version": ADMIN_IDENTITY_SCHEMA_VERSION,
                "scope_name": SCOPE_INTERFACE_UPDATED_NAME,
                "description": None,
                "enabled": enabled,
            },
        }

    def _issue_admin_token(self, client: TestClient) -> str:
        """
        签发管理员访问令牌。
        """

        token_response = client.post(
            AUTH_TOKEN_PATH,
            json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        )
        return str(token_response.json()[DATA_FIELD]["access_token"])

    def _build_auth_header(self, access_token: str) -> dict[str, str]:
        """
        构建认证请求头。
        """

        return {AUTHORIZATION_HEADER: f"{BEARER_PREFIX} {access_token}"}

    def _with_unknown_detail_field(
        self,
        body: dict[str, object],
    ) -> dict[str, object]:
        """
        在身份管理请求扩展中添加未知字段。
        """

        detail = body[DETAIL_FIELD]
        if not isinstance(detail, dict):
            raise TypeError("身份管理请求 detail 必须是映射。")
        body[DETAIL_FIELD] = {**detail, UNKNOWN_FIELD_NAME: True}
        return body
