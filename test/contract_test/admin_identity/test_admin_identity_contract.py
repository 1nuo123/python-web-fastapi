"""
管理员身份契约测试模块。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.api.endpoint_admin_identity.contract_admin_identity_common import (
    ADMIN_IDENTITY_DISABLED_STATUS,
    ADMIN_IDENTITY_ENABLED_STATUS,
    ADMIN_IDENTITY_GRANT_CONFIRMATION_PHRASE,
    ADMIN_IDENTITY_SCHEMA_VERSION,
    AdminIdentityHeader,
    AdminIdentityOperationName,
    AdminIdentityPayloadKind,
)
from src.api.endpoint_admin_identity.contract_admin_identity_envelope import (
    AdminIdentityEnvelope,
)
from src.api.endpoint_admin_identity.contract_admin_role import (
    AdminBusinessRoleListPayload,
    AdminRoleCreateRequest,
    AdminRoleListPayload,
    AdminRoleScopeReplaceRequest,
    AdminRoleUpdateRequest,
)
from src.api.endpoint_admin_identity.contract_admin_scope import (
    AdminScopeCreateRequest,
    AdminScopeListPayload,
    AdminScopeUpdateRequest,
)
from src.api.endpoint_admin_identity.contract_admin_user import (
    AdminUserCreateRequest,
    AdminUserDisableRequest,
    AdminUserEnableRequest,
    AdminUserListPayload,
    AdminUserPayload,
    AdminUserStatusResultPayload,
    AdminUserUpdateRequest,
)
from src.application.ports.admin_identity_port import (
    AdminIdentityDeleteResult,
    AdminRolePage,
    AdminRoleSnapshot,
    AdminUserPage,
    AdminUserSnapshot,
    BusinessAdminRoleKey,
)
from src.domain.auth.admin_route_authorization_policy import PROTECTED_ADMIN_SCOPE_CODES
from src.domain.auth.auth_scope_code import AuthScopeCode

CONTRACT_PASSWORD = "contract-password"
CONTRACT_USERNAME = "contract-user"
CONTRACT_UPDATED_USERNAME = "contract-user-updated"
CONTRACT_SUBJECT_ID = "contract-user-subject"
CONTRACT_DISABLE_REASON = "业务停用"
CONTRACT_ENABLE_REASON = "业务启用"
CONTRACT_PAGE_SIZE = 50
CONTRACT_OFFSET = 0
CONTRACT_TOTAL = 1
CONTRACT_SCOPE_CODE = "contract:scope:read"
CONTRACT_SCOPE_NAME = "契约 scope"
CONTRACT_ROLE_KEY = "contract_identity_role"
CONTRACT_ROLE_NAME = "契约角色"
CONTRACT_ROLE_UPDATED_NAME = "契约角色更新"
PASSWORD_FIELD_NAME = "password"
PASSWORD_HASH_FIELD_NAME = "password_hash"
IS_ACTIVE_FIELD_NAME = "is_active"
SCOPE_CODES_FIELD_NAME = "scope_codes"
PAGE_SIZE_FIELD_NAME = "page_size"
OFFSET_FIELD_NAME = "offset"
TOTAL_FIELD_NAME = "total"
UNKNOWN_FIELD_NAME = "unknown"
SCOPE_KIND_FIELD_NAME = "scope_kind"


class TestAdminIdentityContract:
    """
    管理员身份契约测试集合。
    """

    def test_business_role_list_envelope_should_validate_contract(self) -> None:
        """
        验证只读业务角色列表信封保持公共头与扩展字段一致。
        """

        page = AdminRolePage(
            roles=[
                AdminRoleSnapshot(
                    role_key=BusinessAdminRoleKey.CUSTOMER_SERVICE.value,
                    role_name="customer_service",
                    scope_codes=["auth:read"],
                    user_count=0,
                )
            ],
            page_size=CONTRACT_PAGE_SIZE,
            offset=CONTRACT_OFFSET,
            total=CONTRACT_TOTAL,
        )
        detail = AdminBusinessRoleListPayload.from_page(page)
        envelope = AdminIdentityEnvelope(
            header=AdminIdentityHeader(
                kind=AdminIdentityPayloadKind.BUSINESS_ROLE_LIST,
                operation_name=AdminIdentityOperationName.ROLE_LIST,
            ),
            detail=detail,
        )

        dumped_role = envelope.model_dump(mode="json")["detail"]["roles"][0]
        assert envelope.header.schema_version == ADMIN_IDENTITY_SCHEMA_VERSION
        assert detail.roles[0].role_key == BusinessAdminRoleKey.CUSTOMER_SERVICE
        assert SCOPE_CODES_FIELD_NAME not in dumped_role

    def test_role_list_envelope_should_include_pagination_metadata(self) -> None:
        """
        验证管理员角色列表契约包含分页元数据。
        """

        page = AdminRolePage(
            roles=[
                AdminRoleSnapshot(
                    role_key=CONTRACT_ROLE_KEY,
                    role_name=CONTRACT_ROLE_NAME,
                    scope_codes=[CONTRACT_SCOPE_CODE],
                    user_count=0,
                )
            ],
            page_size=CONTRACT_PAGE_SIZE,
            offset=CONTRACT_OFFSET,
            total=CONTRACT_TOTAL,
        )
        detail = AdminRoleListPayload.from_page(page)
        envelope = AdminIdentityEnvelope(
            header=AdminIdentityHeader(
                kind=AdminIdentityPayloadKind.ROLE_LIST,
                operation_name=AdminIdentityOperationName.ROLE_LIST,
            ),
            detail=detail,
        )
        dumped_detail = envelope.model_dump(mode="json")["detail"]

        assert envelope.header.schema_version == ADMIN_IDENTITY_SCHEMA_VERSION
        assert detail.page_size == CONTRACT_PAGE_SIZE
        assert detail.offset == CONTRACT_OFFSET
        assert detail.total == CONTRACT_TOTAL
        assert PAGE_SIZE_FIELD_NAME in dumped_detail
        assert OFFSET_FIELD_NAME in dumped_detail
        assert TOTAL_FIELD_NAME in dumped_detail

    def test_business_role_list_when_unknown_field_should_fail(self) -> None:
        """
        验证业务角色列表未知字段会被拒绝。
        """

        with pytest.raises(ValidationError):
            AdminIdentityEnvelope.model_validate(
                {
                    "header": {
                        "kind": AdminIdentityPayloadKind.BUSINESS_ROLE_LIST.value,
                        "schema_version": ADMIN_IDENTITY_SCHEMA_VERSION,
                        "operation_name": AdminIdentityOperationName.ROLE_LIST.value,
                    },
                    "detail": {
                        "kind": AdminIdentityPayloadKind.BUSINESS_ROLE_LIST.value,
                        "schema_version": ADMIN_IDENTITY_SCHEMA_VERSION,
                        "roles": [],
                        "page_size": CONTRACT_PAGE_SIZE,
                        "offset": CONTRACT_OFFSET,
                        "total": CONTRACT_TOTAL,
                        "unknown": True,
                    },
                }
            )

    def test_user_response_payloads_should_validate_without_password(self) -> None:
        """
        验证用户详情与列表响应不包含密码字段。
        """

        snapshot = AdminUserSnapshot(
            subject_id=CONTRACT_SUBJECT_ID,
            username=CONTRACT_USERNAME,
            is_active=True,
            role_keys=[BusinessAdminRoleKey.CUSTOMER_SERVICE.value],
            direct_scope_codes=[AuthScopeCode.CODEX_READ.value],
            effective_scope_codes=["auth:read", AuthScopeCode.CODEX_READ.value],
        )
        payload = AdminUserPayload.from_snapshot(snapshot)
        list_payload = AdminUserListPayload.from_page(
            AdminUserPage(
                users=[snapshot],
                page_size=CONTRACT_PAGE_SIZE,
                offset=CONTRACT_OFFSET,
                total=CONTRACT_TOTAL,
            )
        )
        dumped_payload = payload.model_dump()
        dumped_json = list_payload.model_dump_json()

        assert payload.subject_id == CONTRACT_SUBJECT_ID
        assert list_payload.users[0].role_keys == [BusinessAdminRoleKey.CUSTOMER_SERVICE.value]
        assert payload.direct_scope_codes == [AuthScopeCode.CODEX_READ.value]
        assert payload.effective_scope_codes == ["auth:read", AuthScopeCode.CODEX_READ.value]
        assert PASSWORD_FIELD_NAME not in dumped_payload
        assert PASSWORD_HASH_FIELD_NAME not in dumped_payload
        assert CONTRACT_PASSWORD not in dumped_json

    def test_user_create_password_should_not_dump_plain_text(self) -> None:
        """
        验证用户创建契约序列化不泄漏密码原文。
        """

        envelope = AdminIdentityEnvelope(
            header=AdminIdentityHeader(
                kind=AdminIdentityPayloadKind.USER_CREATE,
                operation_name=AdminIdentityOperationName.USER_CREATE,
            ),
            detail=AdminUserCreateRequest(
                username=CONTRACT_USERNAME,
                password=CONTRACT_PASSWORD,
                role_keys=[BusinessAdminRoleKey.CUSTOMER_SERVICE.value],
                subject_id=CONTRACT_SUBJECT_ID,
            ),
        )

        dumped_json = envelope.model_dump_json()

        assert CONTRACT_PASSWORD not in dumped_json

    def test_scope_and_role_write_requests_should_validate_union(self) -> None:
        """
        验证 scope 和 role 写请求进入身份管理判别联合。
        """

        envelopes = [
            AdminIdentityEnvelope(
                header=AdminIdentityHeader(
                    kind=AdminIdentityPayloadKind.SCOPE_CREATE,
                    operation_name=AdminIdentityOperationName.SCOPE_CREATE,
                ),
                detail=AdminScopeCreateRequest(
                    scope_code=CONTRACT_SCOPE_CODE,
                    scope_name=CONTRACT_SCOPE_NAME,
                ),
            ),
            AdminIdentityEnvelope(
                header=AdminIdentityHeader(
                    kind=AdminIdentityPayloadKind.SCOPE_UPDATE,
                    operation_name=AdminIdentityOperationName.SCOPE_UPDATE,
                ),
                detail=AdminScopeUpdateRequest(scope_name=CONTRACT_SCOPE_NAME),
            ),
            AdminIdentityEnvelope(
                header=AdminIdentityHeader(
                    kind=AdminIdentityPayloadKind.ROLE_CREATE,
                    operation_name=AdminIdentityOperationName.ROLE_CREATE,
                ),
                detail=AdminRoleCreateRequest(
                    role_key=CONTRACT_ROLE_KEY,
                    role_name=CONTRACT_ROLE_NAME,
                    scope_codes=[CONTRACT_SCOPE_CODE],
                ),
            ),
            AdminIdentityEnvelope(
                header=AdminIdentityHeader(
                    kind=AdminIdentityPayloadKind.ROLE_UPDATE,
                    operation_name=AdminIdentityOperationName.ROLE_UPDATE,
                ),
                detail=AdminRoleUpdateRequest(role_name=CONTRACT_ROLE_UPDATED_NAME),
            ),
            AdminIdentityEnvelope(
                header=AdminIdentityHeader(
                    kind=AdminIdentityPayloadKind.ROLE_SCOPE_REPLACE,
                    operation_name=AdminIdentityOperationName.ROLE_SCOPE_REPLACE,
                ),
                detail=AdminRoleScopeReplaceRequest(
                    scope_codes=[CONTRACT_SCOPE_CODE],
                    confirmation=ADMIN_IDENTITY_GRANT_CONFIRMATION_PHRASE,
                ),
            ),
        ]

        assert [envelope.header.kind.value for envelope in envelopes] == [
            envelope.detail.kind for envelope in envelopes
        ]

    def test_scope_write_when_unknown_field_should_fail(self) -> None:
        """
        验证 scope 写请求未知字段会被拒绝。
        """

        with pytest.raises(ValidationError):
            AdminScopeCreateRequest.model_validate(
                {
                    "kind": AdminIdentityPayloadKind.SCOPE_CREATE.value,
                    "schema_version": ADMIN_IDENTITY_SCHEMA_VERSION,
                    "scope_code": CONTRACT_SCOPE_CODE,
                    "scope_name": CONTRACT_SCOPE_NAME,
                    UNKNOWN_FIELD_NAME: True,
                }
            )

    def test_role_write_when_unknown_field_should_fail(self) -> None:
        """
        验证 role 写请求未知字段会被拒绝。
        """

        with pytest.raises(ValidationError):
            AdminRoleCreateRequest.model_validate(
                {
                    "kind": AdminIdentityPayloadKind.ROLE_CREATE.value,
                    "schema_version": ADMIN_IDENTITY_SCHEMA_VERSION,
                    "role_key": CONTRACT_ROLE_KEY,
                    "role_name": CONTRACT_ROLE_NAME,
                    "scope_codes": [CONTRACT_SCOPE_CODE],
                    UNKNOWN_FIELD_NAME: True,
                }
            )

    def test_scope_create_when_scope_kind_present_should_fail_current_contract(
        self,
    ) -> None:
        """
        验证当前 scope 创建契约由服务端派生 scope_kind，不接收客户端字段。
        """

        with pytest.raises(ValidationError):
            AdminScopeCreateRequest.model_validate(
                {
                    "kind": AdminIdentityPayloadKind.SCOPE_CREATE.value,
                    "schema_version": ADMIN_IDENTITY_SCHEMA_VERSION,
                    "scope_code": CONTRACT_SCOPE_CODE,
                    "scope_name": CONTRACT_SCOPE_NAME,
                    SCOPE_KIND_FIELD_NAME: "custom",
                }
            )

    def test_protected_admin_scope_registry_should_include_security_manage(self) -> None:
        """
        验证后台受保护 scope 契约包含 security:manage。
        """

        assert AuthScopeCode.SECURITY_MANAGE.value in PROTECTED_ADMIN_SCOPE_CODES

    def test_operation_name_when_detail_kind_mismatch_should_fail(self) -> None:
        """
        验证 operation_name 与扩展类型不匹配时拒绝信封。
        """

        with pytest.raises(ValidationError):
            AdminIdentityEnvelope(
                header=AdminIdentityHeader(
                    kind=AdminIdentityPayloadKind.SCOPE_LIST,
                    operation_name=AdminIdentityOperationName.SCOPE_DELETE,
                ),
                detail=AdminScopeListPayload(scopes=[]),
            )

    def test_user_update_when_is_active_present_should_fail(self) -> None:
        """
        验证用户更新契约不再承载启停状态。
        """

        with pytest.raises(ValidationError):
            AdminUserUpdateRequest.model_validate(
                {
                    "kind": AdminIdentityPayloadKind.USER_UPDATE.value,
                    "schema_version": ADMIN_IDENTITY_SCHEMA_VERSION,
                    "username": CONTRACT_UPDATED_USERNAME,
                    IS_ACTIVE_FIELD_NAME: True,
                }
            )

    def test_user_disable_enable_status_payloads_should_not_express_physical_delete(
        self,
    ) -> None:
        """
        验证停用与启用契约返回状态语义而非物理删除语义。
        """

        disabled = AdminUserStatusResultPayload.from_disabled_result(
            AdminIdentityDeleteResult(
                target_id=CONTRACT_SUBJECT_ID,
                deleted=True,
                reason=CONTRACT_DISABLE_REASON,
            )
        )
        enabled = AdminUserStatusResultPayload.from_enabled_snapshot(
            AdminUserSnapshot(
                subject_id=CONTRACT_SUBJECT_ID,
                username=CONTRACT_USERNAME,
                is_active=True,
                role_keys=[BusinessAdminRoleKey.CUSTOMER_SERVICE.value],
                direct_scope_codes=[],
                effective_scope_codes=["auth:read"],
            ),
            reason=CONTRACT_ENABLE_REASON,
        )

        assert AdminUserDisableRequest(reason=CONTRACT_DISABLE_REASON).reason
        assert AdminUserEnableRequest(reason=CONTRACT_ENABLE_REASON).reason
        assert disabled.status == ADMIN_IDENTITY_DISABLED_STATUS
        assert disabled.is_active is False
        assert enabled.status == ADMIN_IDENTITY_ENABLED_STATUS
        assert enabled.is_active is True
        assert "deleted" not in disabled.model_dump()

    def test_user_disable_when_reason_missing_or_blank_should_fail(self) -> None:
        """
        验证停用用户请求必须携带非空原因。
        """

        with pytest.raises(ValidationError):
            AdminUserDisableRequest.model_validate(
                {
                    "kind": AdminIdentityPayloadKind.USER_DISABLE.value,
                    "schema_version": ADMIN_IDENTITY_SCHEMA_VERSION,
                }
            )
        with pytest.raises(ValidationError):
            AdminUserDisableRequest.model_validate(
                {
                    "kind": AdminIdentityPayloadKind.USER_DISABLE.value,
                    "schema_version": ADMIN_IDENTITY_SCHEMA_VERSION,
                    "reason": "",
                }
            )

    def test_header_detail_mismatch_should_fail(self) -> None:
        """
        验证公共头与扩展字段类型不一致时拒绝。
        """

        with pytest.raises(ValidationError):
            AdminIdentityEnvelope(
                header=AdminIdentityHeader(
                    kind=AdminIdentityPayloadKind.USER_LIST,
                    operation_name=AdminIdentityOperationName.USER_LIST,
                ),
                detail=AdminUserDisableRequest(reason=CONTRACT_DISABLE_REASON),
            )
