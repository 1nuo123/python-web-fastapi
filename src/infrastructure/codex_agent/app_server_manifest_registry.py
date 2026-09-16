"""已审核 App Server schema manifest 目录加载器。"""

from __future__ import annotations

import hashlib
from pathlib import Path

from src.core.codex_contract.app_server_schema_manifest_contract import (
    AppServerSchemaManifestEnvelope,
)
from src.domain.codex.codex_compatibility_policy import CodexCompatibilityPolicy


class AppServerManifestValidationError(ValueError):
    """schema manifest 与目录中的官方生成物不一致。"""


class AppServerManifestRegistry:
    """加载、校验并向运行时提供只读兼容矩阵。"""

    def __init__(self, protocol_root: str | Path) -> None:
        self._protocol_root = Path(protocol_root)

    def load_manifests(self) -> tuple[AppServerSchemaManifestEnvelope, ...]:
        """读取所有版本目录并验证精确版本与 schema digest。"""

        manifests: list[AppServerSchemaManifestEnvelope] = []
        if not self._protocol_root.is_dir():
            raise AppServerManifestValidationError("App Server协议根目录不存在。")
        for manifest_path in sorted(self._protocol_root.glob("*/manifest.json")):
            manifest = AppServerSchemaManifestEnvelope.model_validate_json(
                manifest_path.read_text(encoding="utf-8")
            )
            version_directory = manifest_path.parent
            if version_directory.name != manifest.header.codex_version:
                raise AppServerManifestValidationError("App Server manifest版本与目录名不一致。")
            schema_directory = version_directory / "json-schema"
            actual_digest = self.calculate_directory_digest(schema_directory)
            if actual_digest != manifest.detail.json_schema_bundle_sha256:
                raise AppServerManifestValidationError(
                    f"App Server schema digest不匹配：{manifest.header.codex_version}。"
                )
            manifests.append(manifest)
        if not manifests:
            raise AppServerManifestValidationError("没有可加载的App Server manifest。")
        return tuple(manifests)

    def build_policy(
        self,
        *,
        minimum_codex_version: str,
        blocked_codex_versions: list[str],
    ) -> CodexCompatibilityPolicy:
        """使用已验证 manifest 和运行时版本边界构造兼容策略。"""

        return CodexCompatibilityPolicy(
            self.load_manifests(),
            minimum_codex_version=minimum_codex_version,
            blocked_codex_versions=tuple(blocked_codex_versions),
        )

    def calculate_directory_digest(self, directory: str | Path) -> str:
        """按相对 POSIX 路径和原始字节计算稳定 SHA-256。"""

        root = Path(directory)
        if not root.is_dir():
            raise AppServerManifestValidationError("App Server schema目录不存在。")
        files = sorted(
            (path for path in root.rglob("*") if path.is_file()),
            key=lambda path: path.relative_to(root).as_posix(),
        )
        if not files:
            raise AppServerManifestValidationError("App Server schema目录为空。")
        digest = hashlib.sha256()
        for path in files:
            digest.update(path.relative_to(root).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
        return digest.hexdigest()
