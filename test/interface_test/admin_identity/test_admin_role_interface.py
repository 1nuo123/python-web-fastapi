"""
管理员角色接口测试模块。
"""

from __future__ import annotations

from http import HTTPStatus
from uuid import uuid4

from fastapi.testclient import TestClient

from src.api.endpoint_admin_identity.contract_admin_identity_common import (
    ADMIN_IDENTITY_GRANT_CONFIRMATION_PHRASE,
    ADMIN_IDENTITY_SCHEMA_VERSION,
    AdminIdentityOperationName,
    AdminIdentityPayloadKind,
)
from src.api.endpoint_admin_identity.route_admin_identity_common import (
    ADMIN_BUSINESS_ROLES_PATH,
    ADMIN_ROLE_DETAIL_PATH,
    ADMIN_ROLE_SCOPES_PATH,
    ADMIN_ROLES_PATH,
    ADMIN_SCOPE_DETAIL_PATH,
    ADMIN_SCOPES_PATH,
)
from src.api.testing.test_app_factory import TestAppFactory
from src.application.ports.admin_identity_port import BusinessAdminRoleKey
from src.domain.auth.auth_role_key import AuthRoleKey

AUTH_TOKEN_PATH = "/auth/token"
AUTHORIZATION_HEADER = "Authorization"
BEARER_PREFIX = "Bearer"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin"
DATA_FIELD = "data"
DETAIL_FIELD = "detail"
DELETE_METHOD = "delete"
GET_METHOD = "get"
APPLICATION_JSON_MEDIA_TYPE = "application/json"
ADMIN_IDENTITY_ENVELOPE_SCHEMA_REF = "#/components/schemas/AdminIdentityEnvelope"
ADMIN_IDENTITY_RESPONSE_SCHEMA_REF = "#/components/schemas/ResponseEnvelope_AdminIdentityEnvelope_"
ADMIN_SCOPE_CREATE_SCHEMA_REF = "#/components/schemas/AdminScopeCreateRequest"
ADMIN_SCOPE_UPDATE_SCHEMA_REF = "#/components/schemas/AdminScopeUpdateRequest"
ADMIN_ROLE_CREATE_SCHEMA_REF = "#/components/schemas/AdminRoleCreateRequest"
ADMIN_ROLE_LIST_PAYLOAD_SCHEMA_NAME = "AdminRoleListPayload"
ADMIN_ROLE_UPDATE_SCHEMA_REF = "#/components/schemas/AdminRoleUpdateRequest"
ADMIN_ROLE_SCOPE_REPLACE_SCHEMA_REF = "#/components/schemas/AdminRoleScopeReplaceRequest"
OPENAPI_COMPONENTS_FIELD = "components"
OPENAPI_SCHEMAS_FIELD = "schemas"
OPENAPI_PATHS_FIELD = "paths"
PATCH_METHOD = "patch"
POST_METHOD = "post"
PUT_METHOD = "put"
REQUEST_BODY_FIELD = "requestBody"
RESPONSES_FIELD = "responses"
CONTENT_FIELD = "content"
SCHEMA_FIELD = "schema"
REF_FIELD = "$ref"
HTTP_OK_RESPONSE_FIELD = "200"
PROPERTIES_FIELD = "properties"
DISCRIMINATOR_FIELD = "discriminator"
PROPERTY_NAME_FIELD = "propertyName"
MAPPING_FIELD = "mapping"
DETAIL_DISCRIMINATOR_PROPERTY = "kind"
ROLE_KEY_FIELD = "role_key"
ROLES_FIELD = "roles"
PAGE_SIZE_FIELD = "page_size"
OFFSET_FIELD = "offset"
TOTAL_FIELD = "total"
SCOPE_CODES_FIELD = "scope_codes"
DELETED_FIELD = "deleted"
UNKNOWN_FIELD_NAME = "unknown"
CONFIRMATION_FIELD_NAME = "confirmation"
AUTH_READ_SCOPE = "auth:read"
ROLE_INTERFACE_NAME = "接口角色"
ROLE_INTERFACE_UPDATED_NAME = "接口角色更新"
INVALID_PAGE_SIZE = 0
ROLE_LIST_PAGE_SIZE = 10
ROLE_PAGINATION_PAGE_SIZE = 1
ROLE_PAGINATION_OFFSET = 0
CUSTOMER_SERVICE_ROLE = BusinessAdminRoleKey.CUSTOMER_SERVICE.value
BUSINESS_OPERATOR_ROLE = BusinessAdminRoleKey.BUSINESS_OPERATOR.value
ROLE_CREATE_KIND = AdminIdentityPayloadKind.ROLE_CREATE.value
ROLE_SCOPE_REPLACE_KIND = AdminIdentityPayloadKind.ROLE_SCOPE_REPLACE.value
ROLE_UPDATE_KIND = AdminIdentityPayloadKind.ROLE_UPDATE.value
SCOPE_CREATE_KIND = AdminIdentityPayloadKind.SCOPE_CREATE.value
SCOPE_UPDATE_KIND = AdminIdentityPayloadKind.SCOPE_UPDATE.value
ADMIN_GRANT_INVALID_CONFIRMATION = "invalid-admin-grant-confirmation"


class TestAdminRoleInterface:
    """
    管理员角色接口测试集合。
    """

    def test_role_query_should_require_admin_token(self) -> None:
        """
        验证角色查询需要管理员访问令牌。
        """

        app = TestAppFactory().create()
        with TestClient(app) as client:
            unauthorized_response = client.get(ADMIN_ROLES_PATH)
            access_token = self._issue_admin_token(client)
            authorized_response = client.get(
                ADMIN_ROLES_PATH,
                headers=self._build_auth_header(access_token),
            )

        assert unauthorized_response.status_code == HTTPStatus.UNAUTHORIZED
        assert authorized_response.status_code == HTTPStatus.OK

    def test_role_crud_routes_should_match_contract(self) -> None:
        """
        验证角色写接口完整挂载并返回强类型契约。
        """

        role_key = self._build_role_key("write")
        app = TestAppFactory().create()

        with TestClient(app) as client:
            access_token = self._issue_admin_token(client)
            auth_header = self._build_auth_header(access_token)
            create_response = client.post(
                ADMIN_ROLES_PATH,
                headers=auth_header,
                json=self._build_raw_role_create_body(role_key),
            )
            update_response = client.patch(
                ADMIN_ROLE_DETAIL_PATH.format(role_key=role_key),
                headers=auth_header,
                json=self._build_raw_role_update_body(),
            )
            replace_response = client.put(
                ADMIN_ROLE_SCOPES_PATH.format(role_key=role_key),
                headers=auth_header,
                json=self._build_raw_role_scope_replace_body(),
            )
            detail_response = client.get(
                ADMIN_ROLE_DETAIL_PATH.format(role_key=role_key),
                headers=auth_header,
            )
            delete_response = client.delete(
                ADMIN_ROLE_DETAIL_PATH.format(role_key=role_key),
                headers=auth_header,
            )

        assert create_response.status_code == HTTPStatus.OK
        assert update_response.status_code == HTTPStatus.OK
        assert replace_response.status_code == HTTPStatus.OK
        assert detail_response.status_code == HTTPStatus.OK
        assert detail_response.json()[DATA_FIELD][DETAIL_FIELD][ROLE_KEY_FIELD] == role_key
        assert delete_response.status_code == HTTPStatus.OK
        assert delete_response.json()[DATA_FIELD][DETAIL_FIELD][DELETED_FIELD] is True

    def test_role_list_and_business_dropdown_should_use_separate_contracts(self) -> None:
        """
        验证完整角色列表和业务角色下拉使用独立接口。
        """

        app = TestAppFactory().create()
        with TestClient(app) as client:
            access_token = self._issue_admin_token(client)
            auth_header = self._build_auth_header(access_token)
            list_response = client.get(
                ADMIN_ROLES_PATH,
                headers=auth_header,
                params={PAGE_SIZE_FIELD: ROLE_LIST_PAGE_SIZE},
            )
            pagination_response = client.get(
                ADMIN_ROLES_PATH,
                headers=auth_header,
                params={
                    PAGE_SIZE_FIELD: ROLE_PAGINATION_PAGE_SIZE,
                    OFFSET_FIELD: ROLE_PAGINATION_OFFSET,
                },
            )
            business_response = client.get(
                ADMIN_BUSINESS_ROLES_PATH,
                headers=auth_header,
                params={PAGE_SIZE_FIELD: ROLE_LIST_PAGE_SIZE},
            )
            filtered_response = client.get(
                ADMIN_BUSINESS_ROLES_PATH,
                headers=auth_header,
                params={"keyword": CUSTOMER_SERVICE_ROLE, PAGE_SIZE_FIELD: ROLE_LIST_PAGE_SIZE},
            )
            detail_response = client.get(
                ADMIN_ROLE_DETAIL_PATH.format(role_key=CUSTOMER_SERVICE_ROLE),
                headers=auth_header,
            )
            invalid_page_size_response = client.get(
                ADMIN_ROLES_PATH,
                headers=auth_header,
                params={"page_size": INVALID_PAGE_SIZE},
            )

        assert list_response.status_code == HTTPStatus.OK
        assert pagination_response.status_code == HTTPStatus.OK
        list_detail = list_response.json()[DATA_FIELD][DETAIL_FIELD]
        pagination_detail = pagination_response.json()[DATA_FIELD][DETAIL_FIELD]
        roles = list_detail[ROLES_FIELD]
        role_keys = {role[ROLE_KEY_FIELD] for role in roles}
        business_roles = business_response.json()[DATA_FIELD][DETAIL_FIELD][ROLES_FIELD]
        business_role_keys = {role[ROLE_KEY_FIELD] for role in business_roles}
        assert list_detail[PAGE_SIZE_FIELD] == ROLE_LIST_PAGE_SIZE
        assert list_detail[OFFSET_FIELD] == ROLE_PAGINATION_OFFSET
        assert list_detail[TOTAL_FIELD] >= len(roles)
        assert pagination_detail[PAGE_SIZE_FIELD] == ROLE_PAGINATION_PAGE_SIZE
        assert pagination_detail[OFFSET_FIELD] == ROLE_PAGINATION_OFFSET
        assert len(pagination_detail[ROLES_FIELD]) <= ROLE_PAGINATION_PAGE_SIZE
        assert pagination_detail[TOTAL_FIELD] >= len(pagination_detail[ROLES_FIELD])
        assert CUSTOMER_SERVICE_ROLE in role_keys
        assert BUSINESS_OPERATOR_ROLE in role_keys
        assert AuthRoleKey.ADMIN.value in role_keys
        assert all(SCOPE_CODES_FIELD in role for role in roles)
        assert CUSTOMER_SERVICE_ROLE in business_role_keys
        assert BUSINESS_OPERATOR_ROLE in business_role_keys
        assert AuthRoleKey.ADMIN.value not in business_role_keys
        assert all(SCOPE_CODES_FIELD not in role for role in business_roles)
        assert filtered_response.status_code == HTTPStatus.OK
        assert [
            role[ROLE_KEY_FIELD]
            for role in filtered_response.json()[DATA_FIELD][DETAIL_FIELD][ROLES_FIELD]
        ] == [CUSTOMER_SERVICE_ROLE]
        assert detail_response.status_code == HTTPStatus.OK
        assert invalid_page_size_response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_openapi_should_expose_scope_role_write_contracts(self) -> None:
        """
        验证 OpenAPI 暴露 scope/role 写请求和判别联合组件。
        """

        app = TestAppFactory().create()

        openapi_schema = app.openapi()
        paths = openapi_schema[OPENAPI_PATHS_FIELD]
        admin_identity_schema = openapi_schema[OPENAPI_COMPONENTS_FIELD][OPENAPI_SCHEMAS_FIELD][
            "AdminIdentityEnvelope"
        ]
        role_list_payload_schema = openapi_schema[OPENAPI_COMPONENTS_FIELD][OPENAPI_SCHEMAS_FIELD][
            ADMIN_ROLE_LIST_PAYLOAD_SCHEMA_NAME
        ]
        detail_schema = admin_identity_schema[PROPERTIES_FIELD][DETAIL_FIELD]
        discriminator = detail_schema[DISCRIMINATOR_FIELD]
        discriminator_mapping = discriminator[MAPPING_FIELD]

        for path, method in [
            (ADMIN_ROLES_PATH, POST_METHOD),
            (ADMIN_ROLE_DETAIL_PATH, PATCH_METHOD),
            (ADMIN_ROLE_SCOPES_PATH, PUT_METHOD),
            (ADMIN_SCOPES_PATH, POST_METHOD),
            (ADMIN_SCOPE_DETAIL_PATH, PATCH_METHOD),
        ]:
            operation = paths[path][method]
            assert (
                operation[REQUEST_BODY_FIELD][CONTENT_FIELD][APPLICATION_JSON_MEDIA_TYPE][
                    SCHEMA_FIELD
                ][REF_FIELD]
                == ADMIN_IDENTITY_ENVELOPE_SCHEMA_REF
            )
            assert (
                operation[RESPONSES_FIELD][HTTP_OK_RESPONSE_FIELD][CONTENT_FIELD][
                    APPLICATION_JSON_MEDIA_TYPE
                ][SCHEMA_FIELD][REF_FIELD]
                == ADMIN_IDENTITY_RESPONSE_SCHEMA_REF
            )
        for path, method in [
            (ADMIN_ROLE_DETAIL_PATH, GET_METHOD),
            (ADMIN_ROLE_DETAIL_PATH, DELETE_METHOD),
        ]:
            assert (
                paths[path][method][RESPONSES_FIELD][HTTP_OK_RESPONSE_FIELD][CONTENT_FIELD][
                    APPLICATION_JSON_MEDIA_TYPE
                ][SCHEMA_FIELD][REF_FIELD]
                == ADMIN_IDENTITY_RESPONSE_SCHEMA_REF
            )
        assert discriminator[PROPERTY_NAME_FIELD] == DETAIL_DISCRIMINATOR_PROPERTY
        assert discriminator_mapping[SCOPE_CREATE_KIND] == ADMIN_SCOPE_CREATE_SCHEMA_REF
        assert discriminator_mapping[SCOPE_UPDATE_KIND] == ADMIN_SCOPE_UPDATE_SCHEMA_REF
        assert discriminator_mapping[ROLE_CREATE_KIND] == ADMIN_ROLE_CREATE_SCHEMA_REF
        assert discriminator_mapping[ROLE_UPDATE_KIND] == ADMIN_ROLE_UPDATE_SCHEMA_REF
        assert discriminator_mapping[ROLE_SCOPE_REPLACE_KIND] == ADMIN_ROLE_SCOPE_REPLACE_SCHEMA_REF
        for field_name in [PAGE_SIZE_FIELD, OFFSET_FIELD, TOTAL_FIELD]:
            assert field_name in role_list_payload_schema[PROPERTIES_FIELD]

    def test_role_write_when_unknown_field_should_return_422(self) -> None:
        """
        楠岃瘉 role 鍐欐帴鍙?HTTP 灞傛嫆缁濇湭鐭ュ瓧娈点€?"""

        role_key = self._build_role_key("unknown")
        app = TestAppFactory().create()

        with TestClient(app) as client:
            access_token = self._issue_admin_token(client)
            auth_header = self._build_auth_header(access_token)
            create_response = client.post(
                ADMIN_ROLES_PATH,
                headers=auth_header,
                json=self._with_unknown_detail_field(self._build_raw_role_create_body(role_key)),
            )
            update_response = client.patch(
                ADMIN_ROLE_DETAIL_PATH.format(role_key=role_key),
                headers=auth_header,
                json=self._with_unknown_detail_field(self._build_raw_role_update_body()),
            )
            replace_response = client.put(
                ADMIN_ROLE_SCOPES_PATH.format(role_key=role_key),
                headers=auth_header,
                json=self._with_unknown_detail_field(self._build_raw_role_scope_replace_body()),
            )

        assert create_response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert update_response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert replace_response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_role_scope_replace_when_confirmation_invalid_should_return_422(self) -> None:
        """
        验证角色授权变更缺少或错误二次确认短语时拒绝。
        """

        role_key = self._build_role_key("confirm")
        app = TestAppFactory().create()

        with TestClient(app) as client:
            access_token = self._issue_admin_token(client)
            auth_header = self._build_auth_header(access_token)
            create_response = client.post(
                ADMIN_ROLES_PATH,
                headers=auth_header,
                json=self._build_raw_role_create_body(role_key),
            )
            missing_confirmation_response = client.put(
                ADMIN_ROLE_SCOPES_PATH.format(role_key=role_key),
                headers=auth_header,
                json=self._without_detail_field(
                    self._build_raw_role_scope_replace_body(),
                    CONFIRMATION_FIELD_NAME,
                ),
            )
            invalid_confirmation_body = self._build_raw_role_scope_replace_body()
            detail = invalid_confirmation_body[DETAIL_FIELD]
            if not isinstance(detail, dict):
                raise TypeError("身份管理请求 detail 必须是映射。")
            detail[CONFIRMATION_FIELD_NAME] = ADMIN_GRANT_INVALID_CONFIRMATION
            invalid_confirmation_response = client.put(
                ADMIN_ROLE_SCOPES_PATH.format(role_key=role_key),
                headers=auth_header,
                json=invalid_confirmation_body,
            )
            delete_response = client.delete(
                ADMIN_ROLE_DETAIL_PATH.format(role_key=role_key),
                headers=auth_header,
            )

        assert create_response.status_code == HTTPStatus.OK
        assert missing_confirmation_response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert invalid_confirmation_response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert delete_response.status_code == HTTPStatus.OK

    def test_registered_user_role_should_reject_privilege_or_lifecycle_changes(self) -> None:
        """验证公开注册固定角色不可改名、授权或删除。"""

        role_key = AuthRoleKey.REGISTERED_USER.value
        app = TestAppFactory().create()
        with TestClient(app) as client:
            access_token = self._issue_admin_token(client)
            auth_header = self._build_auth_header(access_token)
            update_response = client.patch(
                ADMIN_ROLE_DETAIL_PATH.format(role_key=role_key),
                headers=auth_header,
                json=self._build_raw_role_update_body(),
            )
            replace_response = client.put(
                ADMIN_ROLE_SCOPES_PATH.format(role_key=role_key),
                headers=auth_header,
                json=self._build_raw_role_scope_replace_body(),
            )
            delete_response = client.delete(
                ADMIN_ROLE_DETAIL_PATH.format(role_key=role_key),
                headers=auth_header,
            )

        assert update_response.status_code == HTTPStatus.CONFLICT
        assert replace_response.status_code == HTTPStatus.CONFLICT
        assert delete_response.status_code == HTTPStatus.CONFLICT

    def _build_role_key(self, suffix: str) -> str:
        """
        构建角色键。
        """

        return f"interface_role_{suffix}_{uuid4().hex}"

    def _build_raw_role_create_body(self, role_key: str) -> dict[str, object]:
        """
        构建角色创建请求体。
        """

        return {
            "header": {
                "kind": AdminIdentityPayloadKind.ROLE_CREATE.value,
                "schema_version": ADMIN_IDENTITY_SCHEMA_VERSION,
                "operation_name": AdminIdentityOperationName.ROLE_CREATE.value,
            },
            "detail": {
                "kind": AdminIdentityPayloadKind.ROLE_CREATE.value,
                "schema_version": ADMIN_IDENTITY_SCHEMA_VERSION,
                "role_key": role_key,
                "role_name": ROLE_INTERFACE_NAME,
                "scope_codes": [AUTH_READ_SCOPE],
                CONFIRMATION_FIELD_NAME: ADMIN_IDENTITY_GRANT_CONFIRMATION_PHRASE,
            },
        }

    def _build_raw_role_update_body(self) -> dict[str, object]:
        """
        构建角色更新请求体。
        """

        return {
            "header": {
                "kind": AdminIdentityPayloadKind.ROLE_UPDATE.value,
                "schema_version": ADMIN_IDENTITY_SCHEMA_VERSION,
                "operation_name": AdminIdentityOperationName.ROLE_UPDATE.value,
            },
            "detail": {
                "kind": AdminIdentityPayloadKind.ROLE_UPDATE.value,
                "schema_version": ADMIN_IDENTITY_SCHEMA_VERSION,
                "role_name": ROLE_INTERFACE_UPDATED_NAME,
            },
        }

    def _build_raw_role_scope_replace_body(self) -> dict[str, object]:
        """
        构建角色 scope 替换请求体。
        """

        return {
            "header": {
                "kind": AdminIdentityPayloadKind.ROLE_SCOPE_REPLACE.value,
                "schema_version": ADMIN_IDENTITY_SCHEMA_VERSION,
                "operation_name": AdminIdentityOperationName.ROLE_SCOPE_REPLACE.value,
            },
            "detail": {
                "kind": AdminIdentityPayloadKind.ROLE_SCOPE_REPLACE.value,
                "schema_version": ADMIN_IDENTITY_SCHEMA_VERSION,
                "scope_codes": [AUTH_READ_SCOPE],
                CONFIRMATION_FIELD_NAME: ADMIN_IDENTITY_GRANT_CONFIRMATION_PHRASE,
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

    def _without_detail_field(
        self,
        body: dict[str, object],
        field_name: str,
    ) -> dict[str, object]:
        """
        从身份管理请求扩展中移除字段。
        """

        detail = body[DETAIL_FIELD]
        if not isinstance(detail, dict):
            raise TypeError("身份管理请求 detail 必须是映射。")
        next_detail = dict(detail)
        next_detail.pop(field_name, None)
        body[DETAIL_FIELD] = next_detail
        return body
