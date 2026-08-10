"""原子生成、审核准备并发布 Codex App Server schema 快照。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from src.core.codex_contract.app_server_schema_manifest_contract import (
    AppServerApprovalResponseRequirement,
    AppServerDefaultCatalog,
    AppServerMethodName,
    AppServerSchemaManifestEnvelope,
    AppServerSchemaManifestHeader,
    AppServerSchemaReviewStatus,
    AppServerSchemaSnapshotDetail,
)
from src.infrastructure.codex_agent.app_server_approval_protocol_probe import (
    AppServerApprovalProtocolProbe,
)
from src.infrastructure.codex_agent.app_server_manifest_registry import (
    AppServerManifestRegistry,
)
from src.infrastructure.codex_agent.app_server_process_supervisor import CodexProcessSupport

DEFAULT_CODEX_EXECUTABLE: Final = "codex"
DEFAULT_PROTOCOL_ROOT: Final = Path("protocol/codex_app_server")
DEFAULT_LICENSE_NOTICE_PATH: Final = "../THIRD_PARTY_NOTICES.md"
MANIFEST_FILENAME: Final = "manifest.json"
MANIFEST_SCHEMA_FILENAME: Final = "manifest.schema.json"
JSON_SCHEMA_DIRECTORY_NAME: Final = "json-schema"
TYPESCRIPT_DIRECTORY_NAME: Final = "typescript"
REQUIRED_SCHEMA_FILENAMES: Final = frozenset(
    {"ClientRequest.json", "ServerRequest.json", "ServerNotification.json"}
)


class AppServerSchemaGenerationCommand(BaseModel):
    """schema 生成命令的强类型输入。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    codex_binary: str = Field(min_length=1)
    protocol_root: Path
    expected_version: str | None = Field(default=None, min_length=1, max_length=64)
    target_platform: str = Field(min_length=1, max_length=128)
    license_notice_path: str = Field(min_length=1, max_length=512)


class AppServerSchemaSnapshotGenerator:
    """使用本机固定 Codex artifact 生成不可覆盖的版本快照。"""

    def execute(self, command: AppServerSchemaGenerationCommand) -> Path:
        """生成 JSON Schema、TypeScript、manifest 与 manifest schema。"""

        codex_command = CodexProcessSupport.resolve_command(command.codex_binary)
        codex_version = self._read_version(codex_command)
        if command.expected_version is not None and codex_version != command.expected_version:
            raise ValueError(
                f"Codex版本不匹配：actual={codex_version} expected={command.expected_version}。"
            )
        command.protocol_root.mkdir(parents=True, exist_ok=True)
        destination = command.protocol_root / codex_version
        if destination.exists():
            raise FileExistsError("目标Codex版本快照已经存在，禁止覆盖。")
        staging_root = Path(
            tempfile.mkdtemp(prefix=f".{codex_version}-", dir=command.protocol_root)
        )
        staging_release = staging_root / codex_version
        try:
            staging_release.mkdir()
            json_schema_directory = staging_release / JSON_SCHEMA_DIRECTORY_NAME
            typescript_directory = staging_release / TYPESCRIPT_DIRECTORY_NAME
            self._run_generator(
                codex_command,
                generator_name="generate-json-schema",
                destination=json_schema_directory,
            )
            self._run_generator(
                codex_command,
                generator_name="generate-ts",
                destination=typescript_directory,
            )
            self._verify_required_schema(json_schema_directory)
            manifest = self._build_manifest(
                codex_version=codex_version,
                target_platform=command.target_platform,
                license_notice_path=command.license_notice_path,
                json_schema_directory=json_schema_directory,
                typescript_directory=typescript_directory,
            )
            (staging_release / MANIFEST_FILENAME).write_text(
                manifest.model_dump_json(indent=2),
                encoding="utf-8",
            )
            (staging_release / MANIFEST_SCHEMA_FILENAME).write_text(
                json.dumps(
                    AppServerSchemaManifestEnvelope.model_json_schema(),
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            os.replace(staging_release, destination)
            logger.info("Codex App Server schema快照已发布：{}", destination)
            return destination
        finally:
            shutil.rmtree(staging_root, ignore_errors=True)

    def _read_version(self, codex_command: tuple[str, ...]) -> str:
        completed = subprocess.run(
            [*codex_command, "--version"],
            check=True,
            capture_output=True,
            text=True,
            env=CodexProcessSupport.build_standalone_environment(),
        )
        tokens = completed.stdout.strip().split()
        if not tokens:
            raise RuntimeError("Codex CLI未返回版本。")
        return tokens[-1]

    def _run_generator(
        self,
        codex_command: tuple[str, ...],
        *,
        generator_name: str,
        destination: Path,
    ) -> None:
        completed = subprocess.run(
            [*codex_command, "app-server", generator_name, "--out", str(destination)],
            check=False,
            capture_output=True,
            text=True,
            env=CodexProcessSupport.build_standalone_environment(),
        )
        if completed.returncode != 0:
            raise RuntimeError(f"Codex App Server {generator_name}命令失败。")
        if not destination.is_dir():
            raise RuntimeError(f"Codex App Server {generator_name}未生成目标目录。")

    def _verify_required_schema(self, schema_directory: Path) -> None:
        actual_names = {path.name for path in schema_directory.iterdir() if path.is_file()}
        missing = REQUIRED_SCHEMA_FILENAMES - actual_names
        if missing:
            raise RuntimeError(f"App Server schema缺少必要文件：{sorted(missing)}。")

    def _build_manifest(
        self,
        *,
        codex_version: str,
        target_platform: str,
        license_notice_path: str,
        json_schema_directory: Path,
        typescript_directory: Path,
    ) -> AppServerSchemaManifestEnvelope:
        approval_probe = AppServerApprovalProtocolProbe().run(
            schema_directory=json_schema_directory,
            codex_version=codex_version,
        )
        registry = AppServerManifestRegistry(json_schema_directory.parent)
        return AppServerSchemaManifestEnvelope(
            header=AppServerSchemaManifestHeader(
                codex_version=codex_version,
                review_status=AppServerSchemaReviewStatus.BLOCKED,
            ),
            detail=AppServerSchemaSnapshotDetail(
                generated_at=datetime.now(UTC),
                target_platform=target_platform,
                generator_commands=(
                    "codex app-server generate-json-schema",
                    "codex app-server generate-ts",
                ),
                json_schema_file_count=self._count_files(json_schema_directory),
                json_schema_bundle_sha256=registry.calculate_directory_digest(
                    json_schema_directory
                ),
                typescript_file_count=self._count_files(typescript_directory),
                typescript_bundle_sha256=self._calculate_directory_digest(
                    typescript_directory
                ),
                approval_schema_digest_sha256=(
                    approval_probe.approval_schema_digest_sha256
                ),
                approval_server_request_methods=tuple(
                    AppServerMethodName(method.value)
                    for method in approval_probe.approval_server_request_methods
                ),
                approval_response_requirements=tuple(
                    AppServerApprovalResponseRequirement(
                        schema_filename=filename,
                        required_fields=tuple(fields),
                    )
                    for filename, fields in sorted(
                        approval_probe.response_required_fields.items()
                    )
                ),
                confirmation_response_expected=(
                    approval_probe.confirmation_response_expected
                ),
                supported_agent_protocol_versions=("1.0", "2.0"),
                capabilities=AppServerDefaultCatalog().build_capabilities(),
                method_catalog=AppServerDefaultCatalog().build_method_catalog(),
                license_notice_path=license_notice_path,
            ),
        )

    def _count_files(self, directory: Path) -> int:
        return sum(1 for path in directory.rglob("*") if path.is_file())

    def _calculate_directory_digest(self, directory: Path) -> str:
        files = sorted(
            (path for path in directory.rglob("*") if path.is_file()),
            key=lambda path: path.relative_to(directory).as_posix(),
        )
        if not files:
            raise RuntimeError("生成目录为空，无法计算digest。")
        digest = hashlib.sha256()
        for path in files:
            digest.update(path.relative_to(directory).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
        return digest.hexdigest()


class AppServerSchemaGenerationCli:
    """schema 生成脚本入口。"""

    def execute(self, argv: Sequence[str] | None = None) -> int:
        parser = argparse.ArgumentParser(description="生成Codex App Server schema快照")
        parser.add_argument("--codex-bin", default=DEFAULT_CODEX_EXECUTABLE)
        parser.add_argument("--protocol-root", type=Path, default=DEFAULT_PROTOCOL_ROOT)
        parser.add_argument("--expected-version")
        parser.add_argument("--target-platform", default=os.name)
        parser.add_argument("--license-notice", default=DEFAULT_LICENSE_NOTICE_PATH)
        arguments = parser.parse_args(argv)
        command = AppServerSchemaGenerationCommand(
            codex_binary=str(arguments.codex_bin),
            protocol_root=arguments.protocol_root,
            expected_version=arguments.expected_version,
            target_platform=str(arguments.target_platform),
            license_notice_path=str(arguments.license_notice),
        )
        AppServerSchemaSnapshotGenerator().execute(command)
        return 0


if __name__ == "__main__":
    raise SystemExit(AppServerSchemaGenerationCli().execute())
