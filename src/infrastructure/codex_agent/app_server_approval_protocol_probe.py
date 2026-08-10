"""从本机生成schema验证App Server 0.145.0稳定审批协议。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final, cast

from src.core.codex_contract.app_server_approval_contract import (
    AppServerApprovalMethod,
    AppServerApprovalProtocolProbeResult,
)

SERVER_REQUEST_SCHEMA: Final = "ServerRequest.json"
CLIENT_REQUEST_SCHEMA: Final = "ClientRequest.json"
SERVER_NOTIFICATION_SCHEMA: Final = "ServerNotification.json"
APPROVAL_RESPONSE_SCHEMA_REQUIREMENTS: Final = {
    "CommandExecutionRequestApprovalResponse.json": frozenset({"decision"}),
    "FileChangeRequestApprovalResponse.json": frozenset({"decision"}),
    "PermissionsRequestApprovalResponse.json": frozenset({"permissions"}),
}
PROBE_SCHEMA_FILENAMES: Final = (
    SERVER_REQUEST_SCHEMA,
    CLIENT_REQUEST_SCHEMA,
    SERVER_NOTIFICATION_SCHEMA,
    *APPROVAL_RESPONSE_SCHEMA_REQUIREMENTS.keys(),
)


class AppServerApprovalProtocolMismatchError(ValueError):
    """生成schema与Phase 0冻结的稳定审批协议不一致。"""


class AppServerApprovalProtocolProbe:
    """验证审批只由App Server发起，客户端只回复原JSON-RPC id。"""

    def run(
        self,
        *,
        schema_directory: str | Path,
        codex_version: str,
    ) -> AppServerApprovalProtocolProbeResult:
        """读取生成schema、校验方向与响应字段并计算稳定digest。"""

        root = Path(schema_directory)
        documents = {
            filename: self._read_document(root / filename) for filename in PROBE_SCHEMA_FILENAMES
        }
        server_methods = self._collect_top_level_methods(documents[SERVER_REQUEST_SCHEMA])
        client_methods = self._collect_top_level_methods(documents[CLIENT_REQUEST_SCHEMA])
        notification_methods = self._collect_top_level_methods(
            documents[SERVER_NOTIFICATION_SCHEMA]
        )
        required_methods = {method.value for method in AppServerApprovalMethod}
        missing_methods = required_methods - server_methods
        if missing_methods:
            raise AppServerApprovalProtocolMismatchError(
                f"App Server缺少稳定审批server request: {sorted(missing_methods)}"
            )
        wrong_direction = required_methods & (client_methods | notification_methods)
        if wrong_direction:
            raise AppServerApprovalProtocolMismatchError(
                f"审批方法出现在错误的协议方向: {sorted(wrong_direction)}"
            )
        required_fields: dict[str, list[str]] = {}
        for filename, expected_fields in APPROVAL_RESPONSE_SCHEMA_REQUIREMENTS.items():
            actual_fields = self._read_required_fields(documents[filename])
            if not expected_fields.issubset(actual_fields):
                raise AppServerApprovalProtocolMismatchError(
                    f"审批响应{filename}缺少字段: {sorted(expected_fields - actual_fields)}"
                )
            required_fields[filename] = sorted(actual_fields)
        return AppServerApprovalProtocolProbeResult(
            codex_version=codex_version,
            approval_schema_digest_sha256=self._calculate_digest(root),
            approval_server_request_methods=sorted(
                AppServerApprovalMethod(method) for method in required_methods
            ),
            response_required_fields=required_fields,
            confirmation_response_expected=False,
        )

    def _read_document(self, path: Path) -> Mapping[str, object]:
        """读取并验证schema根必须是JSON对象。"""

        if not path.is_file():
            raise AppServerApprovalProtocolMismatchError(f"缺少App Server schema: {path.name}")
        payload = cast(object, json.loads(path.read_text(encoding="utf-8")))
        if not isinstance(payload, dict):
            raise AppServerApprovalProtocolMismatchError(
                f"App Server schema根不是对象: {path.name}"
            )
        return cast(dict[str, object], payload)

    def _collect_top_level_methods(self, document: Mapping[str, object]) -> set[str]:
        """收集JSON-RPC联合契约各顶层变体中的method枚举。"""

        methods: set[str] = set()
        for variant_value in self._as_sequence(document.get("oneOf")):
            variant = self._as_mapping(variant_value)
            properties = self._as_mapping(variant.get("properties"))
            method_property = self._as_mapping(properties.get("method"))
            for method in self._as_sequence(method_property.get("enum")):
                if isinstance(method, str):
                    methods.add(method)
        return methods

    def _read_required_fields(self, document: Mapping[str, object]) -> set[str]:
        """读取响应payload的required字段。"""

        return {
            value for value in self._as_sequence(document.get("required")) if isinstance(value, str)
        }

    def _calculate_digest(self, root: Path) -> str:
        """按文件名和原始字节冻结本次审批协议子集。"""

        digest = hashlib.sha256()
        for filename in sorted(PROBE_SCHEMA_FILENAMES):
            digest.update(filename.encode("utf-8"))
            digest.update(b"\0")
            digest.update((root / filename).read_bytes())
            digest.update(b"\0")
        return digest.hexdigest()

    def _as_mapping(self, value: object) -> Mapping[str, object]:
        """把未知JSON节点安全收窄为对象。"""

        if isinstance(value, dict):
            return cast(dict[str, object], value)
        return {}

    def _as_sequence(self, value: object) -> Sequence[object]:
        """把未知JSON节点安全收窄为数组。"""

        if isinstance(value, list):
            return cast(list[object], value)
        return ()
