"""
业务审计接口测试模块。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from src.api.endpoint_admin_audit.route_admin_audit import ADMIN_AUDIT_EVENTS_PATH
from src.api.endpoint_admin_identity.contract_admin_identity_common import (
    ADMIN_IDENTITY_GRANT_CONFIRMATION_PHRASE,
)
from src.api.endpoint_admin_identity.route_admin_identity_common import (
    ADMIN_USER_DETAIL_PATH,
    ADMIN_USER_DISABLE_PATH,
    ADMIN_USER_ENABLE_PATH,
    ADMIN_USER_PASSWORD_PATH,
    ADMIN_USER_ROLES_PATH,
    ADMIN_USERS_PATH,
)
from src.api.testing.test_app_factory import TestAppFactory
from src.application.ports.admin_audit_query_port import AdminAuditAction
from src.application.ports.admin_identity_port import BusinessAdminRoleKey
from src.core.logging_contract.log_writer_contract import LogWriteReason
from src.infrastructure.persistence.orm_model.auth_user_orm_model import AuthUserOrmModel
from src.infrastructure.security.security_event_builder import SecurityEventBuilder

AUTH_TOKEN_PATH = "/auth/token"
AUTHORIZATION_HEADER = "Authorization"
BEARER_PREFIX = "Bearer"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin"
DATA_FIELD = "data"
DETAIL_FIELD = "detail"
EVENTS_FIELD = "events"
ACTION_FIELD = "action"
TARGET_ID_FIELD = "target_id"
TARGET_KIND_FIELD = "target_kind"
PAGE_SIZE_FIELD = "page_size"
OFFSET_FIELD = "offset"
IS_ACTIVE_FIELD = "is_active"
AUDIT_INTERFACE_PASSWORD = "audit-interface-password"
AUDIT_INTERFACE_NEW_PASSWORD = "audit-interface-new-password"
CUSTOMER_SERVICE_ROLE = BusinessAdminRoleKey.CUSTOMER_SERVICE.value
BUSINESS_OPERATOR_ROLE = BusinessAdminRoleKey.BUSINESS_OPERATOR.value
AUDIT_PAGE_SIZE = 10
AUDIT_OFFSET = 0
DEFAULT_ADMIN_SUBJECT_ID = "user-admin"
OCCURRED_WINDOW_SECONDS = 60
BUSINESS_AUDIT_TARGET_KIND = "user"
NON_BUSINESS_OPERATION_NAME = "admin_identity_security_event"
NON_BUSINESS_TARGET_KIND = "user"
NON_BUSINESS_TARGET_ID = "non-business-audit-target"
FAKE_REQUEST_PATH = "/admin/audit-events"
FAKE_REQUEST_METHOD = "POST"
FAKE_REQUEST_SCHEME = "http"
FAKE_SERVER_HOST = "testserver"
FAKE_SERVER_PORT = 80
FAKE_CLIENT_HOST = "127.0.0.1"
FAKE_CLIENT_PORT = 10001
SENSITIVE_TEXTS = (
    AUDIT_INTERFACE_PASSWORD,
    AUDIT_INTERFACE_NEW_PASSWORD,
    "refresh_token",
    "access_token",
    "user-agent",
    "ip_address",
)


class TestAdminAuditInterface:
    """
    业务审计接口测试集合。
    """

    def test_audit_events_should_require_admin_token(self) -> None:
        """
        验证业务审计查询需要管理员访问令牌。
        """

        with TestClient(TestAppFactory().create()) as client:
            unauthorized_response = client.get(ADMIN_AUDIT_EVENTS_PATH)
            access_token = self._issue_admin_token(client)
            authorized_response = client.get(
                ADMIN_AUDIT_EVENTS_PATH,
                headers=self._build_auth_header(access_token),
            )

        assert unauthorized_response.status_code == HTTPStatus.UNAUTHORIZED
        assert authorized_response.status_code == HTTPStatus.OK

    def test_audit_events_should_filter_paginate_and_redact(self) -> None:
        """
        验证业务审计查询支持过滤、分页和脱敏。
        """

        username = self._build_username()
        subject_id = self._build_subject_id()
        app = TestAppFactory().create()
        with TestClient(app) as client:
            access_token = self._issue_admin_token(client)
            auth_header = self._build_auth_header(access_token)
            try:
                create_response = client.post(
                    ADMIN_USERS_PATH,
                    headers=auth_header,
                    json=self._build_user_create_body(username, subject_id),
                )
                reset_response = client.post(
                    ADMIN_USER_PASSWORD_PATH.format(subject_id=subject_id),
                    headers=auth_header,
                    json=self._build_password_reset_body(),
                )
                role_response = client.post(
                    ADMIN_USER_ROLES_PATH.format(subject_id=subject_id),
                    headers=auth_header,
                    json=self._build_role_replace_body(),
                )
                disable_response = client.post(
                    ADMIN_USER_DISABLE_PATH.format(subject_id=subject_id),
                    headers=auth_header,
                    json=self._build_disable_body(),
                )
                disabled_user_response = client.get(
                    ADMIN_USER_DETAIL_PATH.format(subject_id=subject_id),
                    headers=auth_header,
                )
                enable_response = client.post(
                    ADMIN_USER_ENABLE_PATH.format(subject_id=subject_id),
                    headers=auth_header,
                    json=self._build_enable_body(),
                )
                app.state.container.resource_mount.flush_runtime_logs(reason=LogWriteReason.MANUAL)
                audit_response = client.get(
                    ADMIN_AUDIT_EVENTS_PATH,
                    headers=auth_header,
                    params={
                        TARGET_ID_FIELD: subject_id,
                        "page_size": AUDIT_PAGE_SIZE,
                        "offset": AUDIT_OFFSET,
                    },
                )
                disabled_response = client.get(
                    ADMIN_AUDIT_EVENTS_PATH,
                    headers=auth_header,
                    params={
                        TARGET_ID_FIELD: subject_id,
                        ACTION_FIELD: AdminAuditAction.USER_DISABLED.value,
                    },
                )
                enabled_response = client.get(
                    ADMIN_AUDIT_EVENTS_PATH,
                    headers=auth_header,
                    params={
                        TARGET_ID_FIELD: subject_id,
                        ACTION_FIELD: AdminAuditAction.USER_ENABLED.value,
                    },
                )
                target_combo_response = client.get(
                    ADMIN_AUDIT_EVENTS_PATH,
                    headers=auth_header,
                    params={
                        TARGET_KIND_FIELD: BUSINESS_AUDIT_TARGET_KIND,
                        TARGET_ID_FIELD: subject_id,
                    },
                )
                occurred_from = datetime.now(UTC) - timedelta(seconds=OCCURRED_WINDOW_SECONDS)
                occurred_to = datetime.now(UTC) + timedelta(seconds=OCCURRED_WINDOW_SECONDS)
                actor_time_response = client.get(
                    ADMIN_AUDIT_EVENTS_PATH,
                    headers=auth_header,
                    params={
                        TARGET_ID_FIELD: subject_id,
                        "actor_subject_id": DEFAULT_ADMIN_SUBJECT_ID,
                        "occurred_from": occurred_from.isoformat(),
                        "occurred_to": occurred_to.isoformat(),
                    },
                )
            finally:
                self._cleanup(app=app, subject_ids=[subject_id])

        audit_detail = audit_response.json()[DATA_FIELD][DETAIL_FIELD]
        disabled_events = disabled_response.json()[DATA_FIELD][DETAIL_FIELD][EVENTS_FIELD]
        enabled_events = enabled_response.json()[DATA_FIELD][DETAIL_FIELD][EVENTS_FIELD]
        target_combo_events = target_combo_response.json()[DATA_FIELD][DETAIL_FIELD][EVENTS_FIELD]
        actor_time_events = actor_time_response.json()[DATA_FIELD][DETAIL_FIELD][EVENTS_FIELD]
        serialized_response = audit_response.text.lower()

        assert create_response.status_code == HTTPStatus.OK
        assert reset_response.status_code == HTTPStatus.OK
        assert role_response.status_code == HTTPStatus.OK
        assert disable_response.status_code == HTTPStatus.OK
        assert disabled_user_response.status_code == HTTPStatus.OK
        assert disabled_user_response.json()[DATA_FIELD][DETAIL_FIELD][IS_ACTIVE_FIELD] is False
        assert enable_response.status_code == HTTPStatus.OK
        assert audit_response.status_code == HTTPStatus.OK
        assert audit_detail[PAGE_SIZE_FIELD] == AUDIT_PAGE_SIZE
        assert audit_detail[OFFSET_FIELD] == AUDIT_OFFSET
        assert len(audit_detail[EVENTS_FIELD]) >= 5
        assert disabled_response.status_code == HTTPStatus.OK
        assert [event[ACTION_FIELD] for event in disabled_events] == [
            AdminAuditAction.USER_DISABLED.value
        ]
        assert all(event[TARGET_ID_FIELD] == subject_id for event in disabled_events)
        assert enabled_response.status_code == HTTPStatus.OK
        assert [event[ACTION_FIELD] for event in enabled_events] == [
            AdminAuditAction.USER_ENABLED.value
        ]
        assert all(event[TARGET_ID_FIELD] == subject_id for event in enabled_events)
        assert target_combo_response.status_code == HTTPStatus.OK
        assert len(target_combo_events) >= 5
        assert all(
            event[TARGET_KIND_FIELD] == BUSINESS_AUDIT_TARGET_KIND
            and event[TARGET_ID_FIELD] == subject_id
            for event in target_combo_events
        )
        assert actor_time_response.status_code == HTTPStatus.OK
        assert len(actor_time_events) >= 1
        assert all(
            event["actor_subject_id"] == DEFAULT_ADMIN_SUBJECT_ID for event in actor_time_events
        )
        for sensitive_text in SENSITIVE_TEXTS:
            assert sensitive_text.lower() not in serialized_response

    def test_audit_events_should_ignore_non_business_identity_event(self) -> None:
        """
        验证非业务白名单身份安全事件不会进入业务审计响应。
        """

        app = TestAppFactory().create()
        with TestClient(app) as client:
            access_token = self._issue_admin_token(client)
            auth_header = self._build_auth_header(access_token)
            self._emit_non_business_identity_event(app)
            app.state.container.resource_mount.flush_runtime_logs(reason=LogWriteReason.MANUAL)
            response = client.get(
                ADMIN_AUDIT_EVENTS_PATH,
                headers=auth_header,
                params={TARGET_ID_FIELD: NON_BUSINESS_TARGET_ID},
            )

        events = response.json()[DATA_FIELD][DETAIL_FIELD][EVENTS_FIELD]

        assert response.status_code == HTTPStatus.OK
        assert events == []

    def _build_username(self) -> str:
        """
        构建测试用户名。
        """

        return f"audit_interface_{uuid4().hex}"

    def _build_subject_id(self) -> str:
        """
        构建测试主体标识。
        """

        return f"audit-interface-{uuid4()}"

    def _build_user_create_body(
        self,
        username: str,
        subject_id: str,
    ) -> dict[str, object]:
        """
        构建用户创建请求体。
        """

        return {
            "header": {
                "kind": "admin_user_create",
                "schema_version": "1.0",
                "operation_name": "user_create",
            },
            "detail": {
                "kind": "admin_user_create",
                "schema_version": "1.0",
                "username": username,
                "password": AUDIT_INTERFACE_PASSWORD,
                "role_keys": [CUSTOMER_SERVICE_ROLE],
                "subject_id": subject_id,
            },
        }

    def _build_password_reset_body(self) -> dict[str, object]:
        """
        构建密码重置请求体。
        """

        return {
            "header": {
                "kind": "admin_user_password_reset",
                "schema_version": "1.0",
                "operation_name": "user_password_reset",
            },
            "detail": {
                "kind": "admin_user_password_reset",
                "schema_version": "1.0",
                "password": AUDIT_INTERFACE_NEW_PASSWORD,
            },
        }

    def _build_role_replace_body(self) -> dict[str, object]:
        """
        构建角色替换请求体。
        """

        return {
            "header": {
                "kind": "admin_user_role_replace",
                "schema_version": "1.0",
                "operation_name": "user_role_replace",
            },
            "detail": {
                "kind": "admin_user_role_replace",
                "schema_version": "1.0",
                "role_keys": [BUSINESS_OPERATOR_ROLE],
                "confirmation": ADMIN_IDENTITY_GRANT_CONFIRMATION_PHRASE,
            },
        }

    def _build_disable_body(self) -> dict[str, object]:
        """
        构建停用请求体。
        """

        return {
            "header": {
                "kind": "admin_user_disable",
                "schema_version": "1.0",
                "operation_name": "user_disable",
            },
            "detail": {
                "kind": "admin_user_disable",
                "schema_version": "1.0",
                "reason": "业务审计接口测试停用",
            },
        }

    def _build_enable_body(self) -> dict[str, object]:
        """
        构建启用请求体。
        """

        return {
            "header": {
                "kind": "admin_user_enable",
                "schema_version": "1.0",
                "operation_name": "user_enable",
            },
            "detail": {
                "kind": "admin_user_enable",
                "schema_version": "1.0",
                "reason": "业务审计接口测试启用",
            },
        }

    def _issue_admin_token(self, client: TestClient) -> str:
        """
        签发管理员访问令牌。
        """

        response = client.post(
            AUTH_TOKEN_PATH,
            json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        )
        return str(response.json()[DATA_FIELD]["access_token"])

    def _build_auth_header(self, access_token: str) -> dict[str, str]:
        """
        构建认证请求头。
        """

        return {AUTHORIZATION_HEADER: f"{BEARER_PREFIX} {access_token}"}

    def _emit_non_business_identity_event(self, app: FastAPI) -> None:
        """
        写入非业务白名单身份安全事件。
        """

        request = Request(
            {
                "type": "http",
                "method": FAKE_REQUEST_METHOD,
                "path": FAKE_REQUEST_PATH,
                "scheme": FAKE_REQUEST_SCHEME,
                "server": (FAKE_SERVER_HOST, FAKE_SERVER_PORT),
                "query_string": b"",
                "headers": [],
                "client": (FAKE_CLIENT_HOST, FAKE_CLIENT_PORT),
            }
        )
        app.state.container.resource_mount.emit_security_event(
            SecurityEventBuilder().build_admin_identity_changed_event(
                request=request,
                actor_subject_id=DEFAULT_ADMIN_SUBJECT_ID,
                operation_name=NON_BUSINESS_OPERATION_NAME,
                target_kind=NON_BUSINESS_TARGET_KIND,
                target_id=NON_BUSINESS_TARGET_ID,
                status_code=HTTPStatus.OK,
            )
        )

    def _cleanup(self, *, app: FastAPI, subject_ids: list[str]) -> None:
        """
        清理测试用户。
        """

        resource_mount = app.state.container.resource_mount
        unit_of_work = resource_mount.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            users = (
                session.query(AuthUserOrmModel)
                .filter(AuthUserOrmModel.subject_id.in_(subject_ids))
                .all()
            )
            for user in users:
                session.delete(user)
            unit_of_work.commit()
        finally:
            unit_of_work.dispose()
