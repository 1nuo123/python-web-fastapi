"""冻结Codex App Server 0.145.0审批协议契约测试。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from pydantic import JsonValue

from src.core.codex_contract.app_server_schema_manifest_contract import (
    AppServerSchemaManifestEnvelope,
)
from src.core.codex_contract.approval_contract import CodexApprovalDecision
from src.infrastructure.codex_agent.app_server_approval_protocol_probe import (
    AppServerApprovalProtocolProbe,
)

PROTOCOL_ROOT = Path("protocol/codex_app_server/0.145.0")


class TestCodexAppServerApprovalContract:
    """生成schema、manifest和稳定审批方向的一致性测试。"""

    def test_frozen_schema_should_match_manifest_and_have_no_confirmation_response(self) -> None:
        """验证审批是server request加client response，不存在第二确认response。"""

        manifest = AppServerSchemaManifestEnvelope.model_validate_json(
            (PROTOCOL_ROOT / "manifest.json").read_text(encoding="utf-8")
        )
        detail = manifest.detail

        result = AppServerApprovalProtocolProbe().run(
            schema_directory=PROTOCOL_ROOT / "json-schema",
            codex_version=manifest.header.codex_version,
        )

        assert result.approval_schema_digest_sha256 == detail.approval_schema_digest_sha256
        assert [method.value for method in result.approval_server_request_methods] == (
            [method.value for method in detail.approval_server_request_methods]
        )
        assert result.response_required_fields == {
            requirement.schema_filename: list(requirement.required_fields)
            for requirement in detail.approval_response_requirements
        }
        assert result.confirmation_response_expected is False
        assert detail.confirmation_response_expected is False

        json_count, json_digest = self._calculate_bundle(PROTOCOL_ROOT / "json-schema")
        typescript_count, typescript_digest = self._calculate_bundle(PROTOCOL_ROOT / "typescript")
        assert json_count == detail.json_schema_file_count
        assert json_digest == detail.json_schema_bundle_sha256
        assert typescript_count == detail.typescript_file_count
        assert typescript_digest == detail.typescript_bundle_sha256

    def test_official_approval_decisions_should_match_product_decision_enum(self) -> None:
        """产品枚举只能覆盖冻结 schema 中的三类官方响应分支。"""

        command_decisions = self._read_schema_decision_names(
            "CommandExecutionRequestApprovalResponse.json",
            "CommandExecutionApprovalDecision",
        )
        file_change_decisions = self._read_schema_decision_names(
            "FileChangeRequestApprovalResponse.json",
            "FileChangeApprovalDecision",
        )
        assert command_decisions == {decision.value for decision in CodexApprovalDecision}
        assert file_change_decisions == {
            CodexApprovalDecision.ACCEPT.value,
            CodexApprovalDecision.ACCEPT_FOR_SESSION.value,
            CodexApprovalDecision.DECLINE.value,
            CodexApprovalDecision.CANCEL.value,
        }

    def test_permissions_response_schema_should_keep_optional_strict_auto_review(self) -> None:
        """权限审批只由 profile、scope 与可选 strictAutoReview 构成。"""

        schema = self._read_schema("PermissionsRequestApprovalResponse.json")
        assert set(self._read_string_list_field(schema, "required")) == {"permissions"}
        assert set(self._read_object_field(schema, "properties")) == {
            "permissions",
            "scope",
            "strictAutoReview",
        }
        definitions = self._read_object_field(schema, "definitions")
        permission_grant_scope = self._read_object_field(
            definitions,
            "PermissionGrantScope",
        )
        assert self._read_string_list_field(permission_grant_scope, "enum") == [
            "turn",
            "session",
        ]

    def _calculate_bundle(self, root: Path) -> tuple[int, str]:
        """按相对路径和文件字节验证完整生成物未漂移。"""

        digest = hashlib.sha256()
        files = sorted(
            (path for path in root.rglob("*") if path.is_file()),
            key=lambda path: path.relative_to(root).as_posix(),
        )
        for path in files:
            digest.update(path.relative_to(root).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
        return len(files), digest.hexdigest()

    def _read_schema_decision_names(
        self,
        schema_filename: str,
        definition_name: str,
    ) -> set[str]:
        """从 string/object 判别式分支读取 schema 定义的官方 decision 名称。"""

        decisions: set[str] = set()
        definitions = self._read_object_field(
            self._read_schema(schema_filename),
            "definitions",
        )
        decision_definition = self._read_object_field(definitions, definition_name)
        variants = self._read_list_field(decision_definition, "oneOf")
        for variant in variants:
            variant_mapping = self._read_json_object(variant)
            if "enum" in variant_mapping:
                decisions.update(self._read_string_list_field(variant_mapping, "enum"))
                continue
            decisions.update(self._read_string_list_field(variant_mapping, "required"))
        return decisions

    def _read_schema(self, schema_filename: str) -> dict[str, JsonValue]:
        """读取冻结生成物，测试不得绕过 0.145.0 schema 自行定义协议。"""

        schema = json.loads(
            (PROTOCOL_ROOT / "json-schema" / schema_filename).read_text(encoding="utf-8")
        )
        return self._read_json_object(schema)

    def _read_object_field(
        self,
        schema: Mapping[str, JsonValue],
        field_name: str,
    ) -> dict[str, JsonValue]:
        """读取冻结 schema 必须存在的对象字段。"""

        return self._read_json_object(schema[field_name])

    def _read_list_field(
        self,
        schema: Mapping[str, JsonValue],
        field_name: str,
    ) -> list[JsonValue]:
        """读取冻结 schema 必须存在的列表字段。"""

        value = schema[field_name]
        assert isinstance(value, list)
        return value

    def _read_string_list_field(
        self,
        schema: Mapping[str, JsonValue],
        field_name: str,
    ) -> list[str]:
        """读取只允许字符串成员的冻结 schema 列表字段。"""

        values = self._read_list_field(schema, field_name)
        assert all(isinstance(value, str) for value in values)
        return [cast(str, value) for value in values]

    def _read_json_object(self, value: object) -> dict[str, JsonValue]:
        """把 json.loads 的动态边界收窄为 schema 所需对象。"""

        assert isinstance(value, dict)
        assert all(isinstance(key, str) for key in value)
        return cast(dict[str, JsonValue], value)
