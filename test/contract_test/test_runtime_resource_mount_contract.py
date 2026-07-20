"""
运行时资源挂载契约测试模块。
"""

from __future__ import annotations

import pytest

from src.core.http_contract.runtime_resource_contract import RuntimeResourceStatus
from src.infrastructure.resource_mount.runtime_resource_mount_contract import (
    HTTP_RUNTIME_ATTACHED_KIND,
    RESOURCE_MOUNT_TARGET_RESOURCE,
    RUNTIME_RESOURCE_MOUNT_SCHEMA_VERSION,
    RUNTIME_RESOURCE_STATE_CHANGED_KIND,
    HttpRuntimeAttachedDetail,
    RuntimeResourceMountOperationEnvelope,
    RuntimeResourceMountOperationHeader,
    RuntimeResourceStateChangedDetail,
)
from src.infrastructure.resource_mount.shared_resource_constants import RESOURCE_HTTP_CLIENT

ATTACH_HTTP_OPERATION_NAME = "attach_http_runtime"
MARK_STATE_OPERATION_NAME = "mark_runtime_resource_state"
UNEXPECTED_FIELD_NAME = "unexpected"
UNEXPECTED_FIELD_VALUE = "value"
MISMATCH_SCHEMA_VERSION = "2.0"


class TestRuntimeResourceMountContract:
    """
    运行时资源挂载契约测试集合。
    """

    def test_mount_operation_envelope_should_accept_http_detail(self) -> None:
        """
        验证挂载操作信封应接受 HTTP 运行时扩展。
        """

        envelope = RuntimeResourceMountOperationEnvelope(
            header=RuntimeResourceMountOperationHeader(
                kind=HTTP_RUNTIME_ATTACHED_KIND,
                operation_name=ATTACH_HTTP_OPERATION_NAME,
                target_resource=RESOURCE_MOUNT_TARGET_RESOURCE,
                resource_name=RESOURCE_HTTP_CLIENT,
            ),
            detail=HttpRuntimeAttachedDetail(
                sync_status=RuntimeResourceStatus.READY,
                async_status=RuntimeResourceStatus.STOPPED,
            ),
        )

        assert envelope.header.schema_version == RUNTIME_RESOURCE_MOUNT_SCHEMA_VERSION
        assert envelope.detail.kind == HTTP_RUNTIME_ATTACHED_KIND

    def test_mount_operation_when_detail_extra_field_should_fail(self) -> None:
        """
        验证挂载操作扩展字段禁止额外字段。
        """

        with pytest.raises(ValueError):
            HttpRuntimeAttachedDetail.model_validate(
                {
                    "kind": HTTP_RUNTIME_ATTACHED_KIND,
                    "schema_version": RUNTIME_RESOURCE_MOUNT_SCHEMA_VERSION,
                    "sync_status": RuntimeResourceStatus.READY.value,
                    "async_status": RuntimeResourceStatus.STOPPED.value,
                    UNEXPECTED_FIELD_NAME: UNEXPECTED_FIELD_VALUE,
                }
            )

    def test_mount_operation_when_kind_mismatch_should_fail(self) -> None:
        """
        验证挂载操作当公共头与扩展类型不一致应失败。
        """

        with pytest.raises(ValueError):
            RuntimeResourceMountOperationEnvelope(
                header=RuntimeResourceMountOperationHeader(
                    kind=RUNTIME_RESOURCE_STATE_CHANGED_KIND,
                    operation_name=ATTACH_HTTP_OPERATION_NAME,
                    resource_name=RESOURCE_HTTP_CLIENT,
                ),
                detail=HttpRuntimeAttachedDetail(
                    sync_status=RuntimeResourceStatus.READY,
                    async_status=RuntimeResourceStatus.STOPPED,
                ),
            )

    def test_mount_operation_when_schema_version_mismatch_should_fail(self) -> None:
        """
        验证挂载操作当公共头与扩展版本不一致应失败。
        """

        with pytest.raises(ValueError):
            RuntimeResourceMountOperationEnvelope(
                header=RuntimeResourceMountOperationHeader.model_validate(
                    {
                        "kind": RUNTIME_RESOURCE_STATE_CHANGED_KIND,
                        "schema_version": MISMATCH_SCHEMA_VERSION,
                        "operation_name": MARK_STATE_OPERATION_NAME,
                        "target_resource": RESOURCE_MOUNT_TARGET_RESOURCE,
                        "resource_name": RESOURCE_HTTP_CLIENT,
                    }
                ),
                detail=RuntimeResourceStateChangedDetail(
                    status=RuntimeResourceStatus.READY,
                ),
            )
