"""
管理员配置热更新 HTTP 契约测试模块。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.api.endpoint_admin_settings.contract_admin_settings import (
    ADMIN_SETTINGS_RELOAD_REQUEST_KIND,
    ADMIN_SETTINGS_RELOAD_SCHEMA_VERSION,
    AdminSettingsReloadCandidatePayload,
    AdminSettingsReloadHeader,
    AdminSettingsReloadKind,
    AdminSettingsReloadOperationName,
    AdminSettingsReloadRequestEnvelope,
    AdminSettingsReloadResultPayload,
)
from src.application.ports.admin_settings_reload_port import (
    AdminSettingsReloadCandidateSnapshot,
    AdminSettingsReloadResultSnapshot,
)

TEST_CANDIDATE_VERSION = "candidate001"
TEST_DIGEST = "0123456789abcdef"
TEST_ACTIVE_SNAPSHOT_ID = "snapshot001"
UNKNOWN_FIELD_NAME = "overrides"


class TestAdminSettingsContract:
    """
    管理员配置热更新 HTTP 契约测试集合。
    """

    def test_candidate_payload_should_map_candidate_fields(self) -> None:
        """
        验证候选载荷会映射候选版本与摘要。
        """

        payload = AdminSettingsReloadCandidatePayload.from_candidate(
            AdminSettingsReloadCandidateSnapshot(
                candidate_version=TEST_CANDIDATE_VERSION,
                digest=TEST_DIGEST,
            )
        )

        assert payload.candidate_version == TEST_CANDIDATE_VERSION
        assert payload.digest == TEST_DIGEST

    def test_reload_result_payload_should_map_result_fields(self) -> None:
        """
        验证热更新结果载荷会映射执行结果字段。
        """

        payload = AdminSettingsReloadResultPayload.from_result(
            AdminSettingsReloadResultSnapshot(
                success=True,
                rolled_back=False,
                reason=None,
                candidate_version=TEST_CANDIDATE_VERSION,
                restored_resources=[],
                active_snapshot_id=TEST_ACTIVE_SNAPSHOT_ID,
            )
        )

        assert payload.success is True
        assert payload.rolled_back is False
        assert payload.active_snapshot_id == TEST_ACTIVE_SNAPSHOT_ID

    def test_reload_request_should_reject_overrides(self) -> None:
        """
        验证热更新请求拒绝任意配置覆盖字段。
        """

        with pytest.raises(ValidationError):
            AdminSettingsReloadRequestEnvelope.model_validate(
                {
                    "header": {
                        "kind": AdminSettingsReloadKind.REQUEST.value,
                        "schema_version": ADMIN_SETTINGS_RELOAD_SCHEMA_VERSION,
                        "operation_name": (AdminSettingsReloadOperationName.APPLY_RELOAD.value),
                    },
                    "detail": {
                        "kind": ADMIN_SETTINGS_RELOAD_REQUEST_KIND,
                        "schema_version": ADMIN_SETTINGS_RELOAD_SCHEMA_VERSION,
                        UNKNOWN_FIELD_NAME: {"runtime": {"logging": {"level": "INFO"}}},
                    },
                }
            )

    def test_reload_request_should_validate_header_detail_kind(self) -> None:
        """
        验证热更新请求会校验公共头与扩展字段类型一致。
        """

        with pytest.raises(ValidationError):
            AdminSettingsReloadRequestEnvelope.model_validate(
                {
                    "header": AdminSettingsReloadHeader(
                        kind=AdminSettingsReloadKind.CANDIDATE,
                        operation_name=AdminSettingsReloadOperationName.APPLY_RELOAD,
                    ).model_dump(mode="json"),
                    "detail": {
                        "kind": ADMIN_SETTINGS_RELOAD_REQUEST_KIND,
                        "schema_version": ADMIN_SETTINGS_RELOAD_SCHEMA_VERSION,
                    },
                }
            )
