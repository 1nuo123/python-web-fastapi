"""冻结Codex App Server 0.145.0审批协议契约测试。"""

from __future__ import annotations

import hashlib
from pathlib import Path

from src.core.codex_contract.app_server_schema_manifest_contract import (
    AppServerSchemaManifestEnvelope,
)
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
