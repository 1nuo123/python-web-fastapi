"""测试运行阶段证据写入命令行入口。"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from platform import platform, python_version
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from src.core.phase_evidence_contract import (
    BenchmarkPromotion,
    CommandExecutionEvidence,
    CoverageEvidence,
    EvidenceArtifact,
    EvidenceArtifactKind,
    ImageRunDetail,
    IntegrationRunDetail,
    LoadRunDetail,
    MigrationRunDetail,
    SecurityRunDetail,
    StaticRunDetail,
    TestRunHeader,
    TestRunRecord,
    TestRunStatus,
    UnitRunDetail,
)
from src.infrastructure.evidence.code_baseline_calculator import CodeBaselineCalculator
from src.infrastructure.evidence.phase_evidence_store import (
    EVIDENCE_ROOT_DIRECTORY,
    TEST_RUN_DIRECTORY_NAME,
    PhaseEvidenceStore,
)


class TestRunEvidenceCommand(BaseModel):
    """命令行解析后的测试运行证据输入。"""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    kind: Literal["static", "unit", "integration", "security", "migration", "image", "load"]
    status: TestRunStatus
    command_entry: str = Field(min_length=1)
    started_at: datetime
    duration_seconds: float = Field(ge=0)
    exit_code: int
    test_count: int | None = Field(default=None, ge=0)
    failure_summary: str | None = None
    tool_version: str = Field(min_length=1)
    finding_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    skipped_count: int = Field(ge=0)
    xfailed_count: int = Field(ge=0)
    artifact_path: Path | None = None
    artifact_kind: EvidenceArtifactKind | None = None
    promotion: BenchmarkPromotion
    stable_across_runs: bool
    peak_cpu_percent: float = Field(ge=0)
    peak_memory_mebibytes: float = Field(ge=0)
    peak_thread_count: int = Field(ge=0)
    peak_connection_count: int = Field(ge=0)
    coverage_total_percent: float | None = Field(default=None, ge=0, le=100)
    coverage_auth_percent: float | None = Field(default=None, ge=0, le=100)
    coverage_security_percent: float | None = Field(default=None, ge=0, le=100)
    coverage_task_percent: float | None = Field(default=None, ge=0, le=100)
    coverage_persistence_percent: float | None = Field(default=None, ge=0, le=100)
    coverage_report_path: Path | None = None
    command_manifest_path: Path | None = None
    artifact_manifest_path: Path | None = None


class TestRunEvidenceCli:
    """把 Nox 会话结果写入统一强类型证据存储。"""

    def run(self) -> int:
        """解析命令行输入并持久化测试运行记录。"""

        command = TestRunEvidenceCommand.model_validate(vars(self._build_parser().parse_args()))
        evidence_path = EVIDENCE_ROOT_DIRECTORY / TEST_RUN_DIRECTORY_NAME / f"{command.run_id}.json"
        environment_summary = f"python={python_version()};platform={platform()}"
        detail = self._build_detail(
            command=command,
            evidence_path=evidence_path,
            environment_summary=environment_summary,
        )
        record = TestRunRecord(
            header=TestRunHeader(
                run_id=command.run_id,
                code_baseline=CodeBaselineCalculator.calculate(),
                environment=environment_summary,
                started_at=command.started_at,
                command_entry=command.command_entry,
            ),
            kind=command.kind,
            detail=detail,
        )
        PhaseEvidenceStore().save_test_run(record)
        return 0

    @staticmethod
    def _build_parser() -> argparse.ArgumentParser:
        """构建测试运行证据命令行协议。"""

        parser = argparse.ArgumentParser(description="写入测试运行阶段证据。")
        parser.add_argument("--run-id", required=True)
        parser.add_argument("--kind", required=True)
        parser.add_argument("--status", required=True)
        parser.add_argument("--command-entry", required=True)
        parser.add_argument("--started-at", required=True)
        parser.add_argument("--duration-seconds", required=True, type=float)
        parser.add_argument("--exit-code", required=True, type=int)
        parser.add_argument("--test-count", type=int)
        parser.add_argument("--failure-summary")
        parser.add_argument("--tool-version", default=f"python-{python_version()}")
        parser.add_argument("--finding-count", type=int, default=0)
        parser.add_argument("--warning-count", type=int, default=0)
        parser.add_argument("--skipped-count", type=int, default=0)
        parser.add_argument("--xfailed-count", type=int, default=0)
        parser.add_argument("--artifact-path", type=Path)
        parser.add_argument("--artifact-kind")
        parser.add_argument("--promotion", default=BenchmarkPromotion.CANDIDATE.value)
        parser.add_argument("--stable-across-runs", action="store_true")
        parser.add_argument("--peak-cpu-percent", type=float, default=0)
        parser.add_argument("--peak-memory-mebibytes", type=float, default=0)
        parser.add_argument("--peak-thread-count", type=int, default=0)
        parser.add_argument("--peak-connection-count", type=int, default=0)
        parser.add_argument("--coverage-total-percent", type=float)
        parser.add_argument("--coverage-auth-percent", type=float)
        parser.add_argument("--coverage-security-percent", type=float)
        parser.add_argument("--coverage-task-percent", type=float)
        parser.add_argument("--coverage-persistence-percent", type=float)
        parser.add_argument("--coverage-report-path", type=Path)
        parser.add_argument("--command-manifest-path", type=Path)
        parser.add_argument("--artifact-manifest-path", type=Path)
        return parser

    @staticmethod
    def _build_detail(
        *,
        command: TestRunEvidenceCommand,
        evidence_path: Path,
        environment_summary: str,
    ) -> (
        StaticRunDetail
        | UnitRunDetail
        | IntegrationRunDetail
        | SecurityRunDetail
        | MigrationRunDetail
        | ImageRunDetail
        | LoadRunDetail
    ):
        """按判别值构造测试运行强类型扩展。"""

        artifacts = TestRunEvidenceCli._build_artifacts(command)
        detail_values = {
            "status": command.status,
            "command": command.command_entry,
            "exit_code": command.exit_code,
            "test_count": command.test_count,
            "duration_seconds": command.duration_seconds,
            "environment_summary": environment_summary,
            "failure_summary": command.failure_summary,
            "evidence_path": evidence_path,
            "commands": TestRunEvidenceCli._build_commands(command, evidence_path),
            "artifacts": artifacts,
            "warning_count": command.warning_count,
            "skipped_count": command.skipped_count,
            "xfailed_count": command.xfailed_count,
            "coverage": TestRunEvidenceCli._build_coverage(command),
        }
        if command.kind == "static":
            return StaticRunDetail.model_validate(detail_values)
        if command.kind == "unit":
            return UnitRunDetail.model_validate(detail_values)
        if command.kind == "integration":
            return IntegrationRunDetail.model_validate(detail_values)
        if command.kind == "security":
            return SecurityRunDetail.model_validate(detail_values)
        if command.kind == "migration":
            return MigrationRunDetail.model_validate(detail_values)
        if command.kind == "image":
            return ImageRunDetail.model_validate(detail_values)
        detail_values.update(
            {
                "promotion": command.promotion,
                "stable_across_runs": command.stable_across_runs,
                "peak_cpu_percent": command.peak_cpu_percent,
                "peak_memory_mebibytes": command.peak_memory_mebibytes,
                "peak_thread_count": command.peak_thread_count,
                "peak_connection_count": command.peak_connection_count,
            }
        )
        return LoadRunDetail.model_validate(detail_values)

    @staticmethod
    def _build_commands(
        command: TestRunEvidenceCommand,
        evidence_path: Path,
    ) -> tuple[CommandExecutionEvidence, ...]:
        """优先读取逐命令清单，否则记录聚合入口。"""

        if command.command_manifest_path is None:
            return (
                CommandExecutionEvidence(
                    command=command.command_entry,
                    tool_version=command.tool_version,
                    exit_code=command.exit_code,
                    finding_count=command.finding_count,
                    evidence_path=command.artifact_path or evidence_path,
                    started_at=command.started_at,
                    finished_at=command.started_at + timedelta(seconds=command.duration_seconds),
                    duration_seconds=command.duration_seconds,
                ),
            )
        if not command.command_manifest_path.is_file():
            raise ValueError(f"逐命令证据清单不存在：{command.command_manifest_path}。")
        adapter = TypeAdapter(tuple[CommandExecutionEvidence, ...])
        return adapter.validate_json(command.command_manifest_path.read_text(encoding="utf-8"))

    @staticmethod
    def _build_coverage(command: TestRunEvidenceCommand) -> CoverageEvidence | None:
        """仅在六个覆盖率字段完整时构建覆盖率证据。"""

        coverage_values = (
            command.coverage_total_percent,
            command.coverage_auth_percent,
            command.coverage_security_percent,
            command.coverage_task_percent,
            command.coverage_persistence_percent,
            command.coverage_report_path,
        )
        if all(value is None for value in coverage_values):
            return None
        if (
            command.coverage_total_percent is None
            or command.coverage_auth_percent is None
            or command.coverage_security_percent is None
            or command.coverage_task_percent is None
            or command.coverage_persistence_percent is None
            or command.coverage_report_path is None
        ):
            raise ValueError("总体、四个关键域和报告路径必须一起提供。")
        return CoverageEvidence(
            total_percent=command.coverage_total_percent,
            auth_percent=command.coverage_auth_percent,
            security_percent=command.coverage_security_percent,
            task_percent=command.coverage_task_percent,
            persistence_percent=command.coverage_persistence_percent,
            report_path=command.coverage_report_path,
        )

    @staticmethod
    def _build_artifacts(command: TestRunEvidenceCommand) -> tuple[EvidenceArtifact, ...]:
        """校验并摘要单个产物或逐产物清单。"""

        if command.artifact_manifest_path is not None:
            if command.artifact_path is not None or command.artifact_kind is not None:
                raise ValueError("产物清单与单产物参数不能同时提供。")
            if not command.artifact_manifest_path.is_file():
                raise ValueError(f"产物证据清单不存在：{command.artifact_manifest_path}。")
            adapter = TypeAdapter(tuple[EvidenceArtifact, ...])
            artifacts = adapter.validate_json(
                command.artifact_manifest_path.read_text(encoding="utf-8")
            )
            for artifact in artifacts:
                if not artifact.path.is_file():
                    raise ValueError(f"阶段证据产物不存在：{artifact.path}。")
                actual_sha256 = sha256(artifact.path.read_bytes()).hexdigest()
                if actual_sha256 != artifact.sha256:
                    raise ValueError(f"阶段证据产物摘要不匹配：{artifact.path}。")
            return artifacts

        if command.artifact_path is None and command.artifact_kind is None:
            return ()
        if command.artifact_path is None or command.artifact_kind is None:
            raise ValueError("产物路径与产物类型必须同时提供。")
        if not command.artifact_path.is_file():
            raise ValueError(f"阶段证据产物不存在：{command.artifact_path}。")
        return (
            EvidenceArtifact(
                kind=command.artifact_kind,
                path=command.artifact_path,
                sha256=sha256(command.artifact_path.read_bytes()).hexdigest(),
            ),
        )


if __name__ == "__main__":
    raise SystemExit(TestRunEvidenceCli().run())
