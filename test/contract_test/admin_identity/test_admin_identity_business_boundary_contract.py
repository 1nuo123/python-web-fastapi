"""
管理员身份业务边界契约测试模块。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.api.admin_list_page_contract import (
    ADMIN_LIST_PAGE_SCHEMA_VERSION,
    AdminListPageEnvelope,
    AdminListPageHeader,
    AdminListPageOperationName,
    AdminListPagePayload,
    AdminListPagePayloadKind,
    AdminListPageQuery,
)
from src.api.endpoint_admin_identity.contract_admin_identity_common import (
    ADMIN_IDENTITY_DISABLED_STATUS,
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
    AdminRoleScopeReplaceRequest,
    AdminRoleUpdateRequest,
)
from src.api.endpoint_admin_identity.contract_admin_scope import (
    AdminScopeCreateRequest,
    AdminScopeUpdateRequest,
)
from src.api.endpoint_admin_identity.contract_admin_user import (
    AdminUserDisableRequest,
    AdminUserStatusResultPayload,
    AdminUserUpdateRequest,
)
from src.application.ports.admin_identity_port import (
    AdminIdentityDeleteResult,
    AdminRolePage,
    AdminRoleSnapshot,
    BusinessAdminRoleKey,
)
from src.application.ports.admin_regression_result import (
    ADMIN_REGRESSION_SCHEMA_VERSION,
    AdminRegressionHeader,
    AdminRegressionResult,
    AdminRegressionResultPayload,
    AdminRegressionStatus,
)

CONTRACT_ROLE_NAME = "customer_service"
CONTRACT_PAGE_SIZE = 50
CONTRACT_OFFSET = 0
CONTRACT_TOTAL = 1
CONTRACT_SUBJECT_ID = "contract-business-user"
CONTRACT_DISABLE_REASON = "业务边界停用"
UNKNOWN_FIELD_NAME = "unknown"
IS_ACTIVE_FIELD_NAME = "is_active"
DELETED_FIELD_NAME = "deleted"
SCOPE_CODES_FIELD_NAME = "scope_codes"
DESCRIPTION_FIELD_NAME = "description"
CONTRACT_NEXT_CURSOR = "next-page"
CONTRACT_PAGE_ITEM = "item-1"
CONTRACT_TEST_ENTRY = "pytest"
CONTRACT_REGRESSION_NOTE = "业务后台回归契约测试。"
CONTRACT_SCOPE_CODE = "contract:identity:read"
CONTRACT_SCOPE_NAME = "契约 scope"
CONTRACT_ROLE_KEY = "contract_identity_role"
CONTRACT_ROLE_NAME_UPDATED = "契约角色更新"


class TestAdminIdentityBusinessBoundaryContract:
    """
    管理员身份业务边界契约测试集合。
    """

    def test_business_role_list_should_not_expose_scope_codes(self) -> None:
        """
        验证只读业务角色列表不暴露 scope 组合。
        """

        detail = AdminBusinessRoleListPayload.from_page(
            AdminRolePage(
                roles=[
                    AdminRoleSnapshot(
                        role_key=BusinessAdminRoleKey.CUSTOMER_SERVICE.value,
                        role_name=CONTRACT_ROLE_NAME,
                        scope_codes=["auth:read"],
                        user_count=0,
                    )
                ],
                page_size=CONTRACT_PAGE_SIZE,
                offset=CONTRACT_OFFSET,
                total=CONTRACT_TOTAL,
            )
        )
        envelope = AdminIdentityEnvelope(
            header=AdminIdentityHeader(
                kind=AdminIdentityPayloadKind.BUSINESS_ROLE_LIST,
                operation_name=AdminIdentityOperationName.ROLE_LIST,
            ),
            detail=detail,
        )

        dumped_role = envelope.model_dump(mode="json")["detail"]["roles"][0]

        assert dumped_role["role_key"] == BusinessAdminRoleKey.CUSTOMER_SERVICE.value
        assert SCOPE_CODES_FIELD_NAME not in dumped_role
        assert DESCRIPTION_FIELD_NAME not in dumped_role

    def test_scope_and_role_write_detail_should_join_identity_union(self) -> None:
        """
        验证 scope 与 role 写请求属于完整身份管理契约联合。
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
                    scope_codes=[SCOPE_CODES_FIELD_NAME],
                    confirmation=ADMIN_IDENTITY_GRANT_CONFIRMATION_PHRASE,
                ),
            ),
            AdminIdentityEnvelope(
                header=AdminIdentityHeader(
                    kind=AdminIdentityPayloadKind.ROLE_UPDATE,
                    operation_name=AdminIdentityOperationName.ROLE_UPDATE,
                ),
                detail=AdminRoleUpdateRequest(role_name=CONTRACT_ROLE_NAME_UPDATED),
            ),
            AdminIdentityEnvelope(
                header=AdminIdentityHeader(
                    kind=AdminIdentityPayloadKind.ROLE_SCOPE_REPLACE,
                    operation_name=AdminIdentityOperationName.ROLE_SCOPE_REPLACE,
                ),
                detail=AdminRoleScopeReplaceRequest(
                    scope_codes=[SCOPE_CODES_FIELD_NAME],
                    confirmation=ADMIN_IDENTITY_GRANT_CONFIRMATION_PHRASE,
                ),
            ),
        ]

        assert all(
            envelope.header.schema_version == ADMIN_IDENTITY_SCHEMA_VERSION
            for envelope in envelopes
        )

    def test_user_status_contract_should_use_status_not_physical_delete(self) -> None:
        """
        验证用户停用响应表达状态，不表达物理删除。
        """

        status_payload = AdminUserStatusResultPayload.from_disabled_result(
            AdminIdentityDeleteResult(
                target_id=CONTRACT_SUBJECT_ID,
                deleted=True,
                reason=CONTRACT_DISABLE_REASON,
            )
        )

        dumped = status_payload.model_dump()

        assert status_payload.status == ADMIN_IDENTITY_DISABLED_STATUS
        assert status_payload.is_active is False
        assert DELETED_FIELD_NAME not in dumped

    def test_user_update_and_disable_should_reject_unknown_fields(self) -> None:
        """
        验证用户更新与停用契约拒绝未知字段。
        """

        with pytest.raises(ValidationError):
            AdminUserUpdateRequest.model_validate(
                {
                    "kind": AdminIdentityPayloadKind.USER_UPDATE.value,
                    "schema_version": ADMIN_IDENTITY_SCHEMA_VERSION,
                    IS_ACTIVE_FIELD_NAME: True,
                }
            )
        with pytest.raises(ValidationError):
            AdminUserDisableRequest.model_validate(
                {
                    "kind": AdminIdentityPayloadKind.USER_DISABLE.value,
                    "schema_version": ADMIN_IDENTITY_SCHEMA_VERSION,
                    "reason": CONTRACT_DISABLE_REASON,
                    UNKNOWN_FIELD_NAME: True,
                }
            )

    def test_admin_list_page_contract_should_validate_header_and_detail(self) -> None:
        """
        验证统一后台分页契约公共头与扩展字段一致。
        """

        query_envelope = AdminListPageEnvelope(
            header=AdminListPageHeader(
                kind=AdminListPagePayloadKind.QUERY,
                operation_name=AdminListPageOperationName.QUERY,
            ),
            detail=AdminListPageQuery(
                page_size=CONTRACT_PAGE_SIZE,
                offset=CONTRACT_OFFSET,
            ),
        )
        payload_envelope = AdminListPageEnvelope(
            header=AdminListPageHeader(
                kind=AdminListPagePayloadKind.PAYLOAD,
                operation_name=AdminListPageOperationName.PAYLOAD,
            ),
            detail=AdminListPagePayload(
                page_size=CONTRACT_PAGE_SIZE,
                items=[CONTRACT_PAGE_ITEM],
                offset=CONTRACT_OFFSET,
                total=CONTRACT_TOTAL,
                next_cursor=CONTRACT_NEXT_CURSOR,
            ),
        )

        assert query_envelope.header.schema_version == ADMIN_LIST_PAGE_SCHEMA_VERSION
        assert payload_envelope.detail.items == [CONTRACT_PAGE_ITEM]
        assert payload_envelope.detail.total == CONTRACT_TOTAL
        assert payload_envelope.detail.next_cursor == CONTRACT_NEXT_CURSOR

    def test_admin_regression_result_contract_should_validate_result(self) -> None:
        """
        验证业务后台回归结果契约公共头与扩展字段一致。
        """

        result = AdminRegressionResult(
            header=AdminRegressionHeader(),
            detail=AdminRegressionResultPayload(
                status=AdminRegressionStatus.PASSED,
                test_entries=[CONTRACT_TEST_ENTRY],
                note=CONTRACT_REGRESSION_NOTE,
            ),
        )

        dumped = result.model_dump(mode="json")

        assert result.header.schema_version == ADMIN_REGRESSION_SCHEMA_VERSION
        assert dumped["detail"]["status"] == AdminRegressionStatus.PASSED.value
        assert dumped["detail"]["test_entries"] == [CONTRACT_TEST_ENTRY]
