"""
测试结束到结束用法测试模块。
"""

from __future__ import annotations

from http import HTTPStatus

from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict

from src.api.testing.test_app_factory import TestAppFactory
from src.application.dispatch_background_job_usecase import TaskDispatchCommand
from src.core.task_contract.task_handler_contract import TaskHandler
from src.core.task_contract.task_invocation_contract import TypedTaskInvocation
from src.domain.auth.auth_error_code import AuthErrorCode
from src.domain.auth.auth_scope_code import AuthScopeCode
from src.infrastructure.persistence.orm_model.auth_role_scope_orm_model import (
    AuthRoleScopeOrmModel,
)
from src.infrastructure.persistence.orm_model.auth_user_orm_model import AuthUserOrmModel
from src.infrastructure.task.task_registration_registry import RegisteredTaskBinding

API_PREFIX = "/api/v1"
AUTHORIZATION_HEADER = "Authorization"
AUTH_ME_PATH = "/auth/me"
AUTH_REFRESH_PATH = "/auth/refresh"
AUTH_REVOKE_PATH = "/auth/revoke"
AUTH_TOKEN_PATH = "/auth/token"
AUTH_READ_SCOPE_CODE = AuthScopeCode.AUTH_READ.value
BEARER_PREFIX = "Bearer"
DATA_FIELD = "data"
ERROR_CODE_FIELD = "error_code"
ACCESS_TOKEN_FIELD = "access_token"
REFRESH_TOKEN_FIELD = "refresh_token"


class DemoTaskPayload(BaseModel):
    """
    示例任务Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar kind: 结构版本的具体类型标识。约束：需符合 ``str`` 注解。默认值：`'demo_task'`。取值语义：用于承载当前对象中的业务状态。
    :vartype kind: str
    :ivar schema_version: 结构模式版本。约束：需符合 ``str`` 注解。默认值：`'1.0'`。取值语义：用于承载当前对象中的业务状态。
    :vartype schema_version: str
    :ivar task_id: ``task_id`` 字段。约束：需符合 ``str`` 注解。默认值：`'usage-task'`。取值语义：用于唯一标识对应实体。
    :vartype task_id: str
    """

    model_config = ConfigDict(extra="forbid")

    kind: str = "demo_task"
    schema_version: str = "1.0"
    task_id: str = "usage-task"


class DemoTaskHandler(TaskHandler[DemoTaskPayload]):
    """
    示例任务处理器。
    """

    def handle(self, invocation: TypedTaskInvocation[DemoTaskPayload]) -> None:
        _ = invocation
        return None


class TestEndToEndUsage:
    """
    测试结束到结束用法测试集合，用于组织同一主题下的测试场景。
    """

    def test_issue_token_refresh_revoke_then_access_system_chain(self) -> None:
        """
        验证令牌刷新撤销随后访问系统链路。

        :returns: 无返回值。
        :rtype: None
        """

        with TestClient(
            TestAppFactory().create(
                task_bindings=[
                    RegisteredTaskBinding(
                        job_kind="demo_task",
                        payload_model=DemoTaskPayload,
                        handler=DemoTaskHandler(),
                    )
                ]
            )
        ) as client:
            token_response = client.post(
                AUTH_TOKEN_PATH,
                json={"username": "admin", "password": "admin"},
            )
            access_token = token_response.json()["data"]["access_token"]
            refresh_token = token_response.json()["data"]["refresh_token"]
            me_response = client.get(
                AUTH_ME_PATH,
                headers={"Authorization": f"bearer {access_token}"},
            )
            refresh_response = client.post(
                AUTH_REFRESH_PATH,
                json={"refresh_token": refresh_token},
            )
            refreshed_refresh_token = refresh_response.json()["data"]["refresh_token"]
            refreshed_access_token = refresh_response.json()["data"]["access_token"]
            revoke_response = client.post(
                AUTH_REVOKE_PATH,
                json={"refresh_token": refreshed_refresh_token},
            )
            revoked_refresh_response = client.post(
                AUTH_REFRESH_PATH,
                json={"refresh_token": refreshed_refresh_token},
            )
            revoked_access_response = client.get(
                AUTH_ME_PATH,
                headers={"Authorization": f"Bearer {refreshed_access_token}"},
            )
            dispatch_result = client.app.state.container.dispatch_background_job_usecase.execute(
                TaskDispatchCommand(payload=DemoTaskPayload())
            )
            assert token_response.status_code == 200
            assert me_response.status_code == 200
            assert refresh_response.status_code == 200
            assert revoke_response.status_code == 200
            assert revoked_refresh_response.status_code == 401
            assert revoked_access_response.status_code == 401
            assert me_response.json()["header"]["code"] == "system.success.ok"
            assert revoked_refresh_response.json()["data"]["error_code"] == "auth.token.revoked"
            assert revoked_access_response.json()["data"]["error_code"] == "auth.token.revoked"
            assert dispatch_result.dispatched is True
            assert dispatch_result.backend.value == "local"

    def test_refresh_reuse_should_revoke_session_in_usage_chain(self) -> None:
        """
        验证用法链路中刷新令牌复用应撤销整个令牌会话。
        """

        with TestClient(TestAppFactory().create()) as client:
            token_response = client.post(
                AUTH_TOKEN_PATH,
                json={"username": "admin", "password": "admin"},
            )
            refresh_token = token_response.json()[DATA_FIELD][REFRESH_TOKEN_FIELD]
            refresh_response = client.post(
                AUTH_REFRESH_PATH,
                json={REFRESH_TOKEN_FIELD: refresh_token},
            )
            refreshed_payload = refresh_response.json()[DATA_FIELD]
            refreshed_access_token = refreshed_payload[ACCESS_TOKEN_FIELD]
            refreshed_refresh_token = refreshed_payload[REFRESH_TOKEN_FIELD]
            reused_response = client.post(
                AUTH_REFRESH_PATH,
                json={REFRESH_TOKEN_FIELD: refresh_token},
            )
            revoked_access_response = client.get(
                AUTH_ME_PATH,
                headers={AUTHORIZATION_HEADER: f"{BEARER_PREFIX} {refreshed_access_token}"},
            )
            revoked_refresh_response = client.post(
                AUTH_REFRESH_PATH,
                json={REFRESH_TOKEN_FIELD: refreshed_refresh_token},
            )

            assert token_response.status_code == HTTPStatus.OK
            assert refresh_response.status_code == HTTPStatus.OK
            assert reused_response.status_code == HTTPStatus.UNAUTHORIZED
            assert reused_response.json()[DATA_FIELD][ERROR_CODE_FIELD] == str(
                AuthErrorCode.TOKEN_REUSED
            )
            assert revoked_access_response.status_code == HTTPStatus.UNAUTHORIZED
            assert revoked_access_response.json()[DATA_FIELD][ERROR_CODE_FIELD] == str(
                AuthErrorCode.TOKEN_REVOKED
            )
            assert revoked_refresh_response.status_code == HTTPStatus.UNAUTHORIZED
            assert revoked_refresh_response.json()[DATA_FIELD][ERROR_CODE_FIELD] == str(
                AuthErrorCode.TOKEN_REVOKED
            )

    def test_usage_when_async_http_client_enabled_should_keep_sync_usecase_backbone(
        self,
    ) -> None:
        """
        验证用法规约当异步 HTTP 客户端启用应保持同步用例主干。
        """

        app = TestAppFactory().create(
            overrides={
                "runtime": {
                    "web": {
                        "outbound_http_client": {
                            "envelope_kind": "outbound_http_client_envelope",
                            "schema_version": "1.0",
                            "header": {
                                "kind": "outbound_http_client_header",
                                "schema_version": "1.0",
                                "client_name": "default_outbound_http",
                                "enabled": True,
                                "mode": "async_http",
                            },
                            "detail": {
                                "kind": "async_http",
                                "schema_version": "1.0",
                                "timeout_seconds": 5,
                                "max_connections": 20,
                                "max_keepalive_connections": 10,
                            },
                        }
                    }
                }
            }
        )

        with TestClient(app) as client:
            token_response = client.post(
                AUTH_TOKEN_PATH,
                json={"username": "admin", "password": "admin"},
            )
            system_response = client.get(
                "/auth/me",
                headers={
                    "Authorization": f"Bearer {token_response.json()['data']['access_token']}"
                },
            )
            async_http_client = client.app.state.container.resource_mount.get_async_http_client()

            assert token_response.status_code == 200
            assert system_response.status_code == 200
            assert async_http_client.get_client().is_closed is False

    def test_issue_token_refresh_revoke_then_access_system_chain_with_api_prefix(
        self,
    ) -> None:
        """
        验证令牌刷新撤销随后访问系统链路携带API前缀。

        :returns: 无返回值。
        :rtype: None
        """

        app = TestAppFactory().create(overrides={"runtime": {"web": {"api_prefix": API_PREFIX}}})
        with TestClient(app) as client:
            token_response = client.post(
                f"{API_PREFIX}{AUTH_TOKEN_PATH}",
                json={"username": "admin", "password": "admin"},
            )
            access_token = token_response.json()["data"]["access_token"]
            refresh_token = token_response.json()["data"]["refresh_token"]
            me_response = client.get(
                f"{API_PREFIX}{AUTH_ME_PATH}",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            refresh_response = client.post(
                f"{API_PREFIX}{AUTH_REFRESH_PATH}",
                json={"refresh_token": refresh_token},
            )
            refreshed_refresh_token = refresh_response.json()["data"]["refresh_token"]
            refreshed_access_token = refresh_response.json()["data"]["access_token"]
            revoke_response = client.post(
                f"{API_PREFIX}{AUTH_REVOKE_PATH}",
                json={"refresh_token": refreshed_refresh_token},
            )
            revoked_refresh_response = client.post(
                f"{API_PREFIX}{AUTH_REFRESH_PATH}",
                json={"refresh_token": refreshed_refresh_token},
            )
            revoked_access_response = client.get(
                f"{API_PREFIX}{AUTH_ME_PATH}",
                headers={"Authorization": f"Bearer {refreshed_access_token}"},
            )
            assert token_response.status_code == 200
            assert me_response.status_code == 200
            assert refresh_response.status_code == 200
            assert revoke_response.status_code == 200
            assert revoked_refresh_response.status_code == 401
            assert revoked_access_response.status_code == 401

    def test_issue_token_then_scope_revoked_should_keep_auth_me_self_inspection(
        self,
    ) -> None:
        """
        验证作用域撤销后当前主体自省仍返回真实授权快照。

        :returns: 无返回值。
        :rtype: None
        """

        app = TestAppFactory().create()
        with TestClient(app) as client:
            token_response = client.post(
                AUTH_TOKEN_PATH,
                json={"username": "admin", "password": "admin"},
            )
            access_token = token_response.json()["data"]["access_token"]
            me_response = client.get(
                AUTH_ME_PATH,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            assert me_response.status_code == 200

            self._revoke_admin_scope(app)
            try:
                self_inspection_response = client.get(
                    AUTH_ME_PATH,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                detail = self_inspection_response.json()["data"]
                assert self_inspection_response.status_code == HTTPStatus.OK
                assert AUTH_READ_SCOPE_CODE not in detail["scopes"]
            finally:
                self._restore_admin_scope(app)

    def _revoke_admin_scope(self, app) -> None:
        """
        撤销管理员作用域。

        :param app: 当前 FastAPI 或 ASGI 应用实例。
        :type app: Any
        :returns: 无返回值。
        :rtype: None
        """

        resource_mount = app.state.container.resource_mount
        unit_of_work = resource_mount.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            user = session.query(AuthUserOrmModel).filter_by(username="admin").one()
            admin_role = next(
                user_role.role
                for user_role in user.user_roles
                if user_role.role.role_key == "admin"
            )
            admin_role.role_scopes[:] = [
                role_scope
                for role_scope in admin_role.role_scopes
                if role_scope.scope_code != AUTH_READ_SCOPE_CODE
            ]
            unit_of_work.commit()
        finally:
            unit_of_work.dispose()

    def _restore_admin_scope(self, app) -> None:
        """
        处理恢复管理员作用域。

        :param app: 当前 FastAPI 或 ASGI 应用实例。
        :type app: Any
        :returns: 无返回值。
        :rtype: None
        """

        resource_mount = app.state.container.resource_mount
        unit_of_work = resource_mount.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            user = session.query(AuthUserOrmModel).filter_by(username="admin").one()
            admin_role = next(
                user_role.role
                for user_role in user.user_roles
                if user_role.role.role_key == "admin"
            )
            if (
                session.get(
                    AuthRoleScopeOrmModel,
                    (admin_role.role_id, AUTH_READ_SCOPE_CODE),
                )
                is not None
            ):
                return
            admin_role.role_scopes.append(AuthRoleScopeOrmModel(scope_code=AUTH_READ_SCOPE_CODE))
            unit_of_work.commit()
        finally:
            unit_of_work.dispose()
