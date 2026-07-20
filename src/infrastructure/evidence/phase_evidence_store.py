"""生产整改阶段证据持久化与索引模块。"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict

from src.core.phase_evidence_contract import (
    DocumentationRecord,
    RegressionRecord,
    RegressionStatus,
    TestRunRecord,
    TruthValidationStatus,
)
from src.infrastructure.evidence.code_baseline_calculator import CodeBaselineCalculator

EVIDENCE_ROOT_DIRECTORY: Final = Path("docs/evidence")
TEST_RUN_DIRECTORY_NAME: Final = "test-runs"
REGRESSION_DIRECTORY_NAME: Final = "regressions"
DOCUMENTATION_DIRECTORY_NAME: Final = "documentation"
PHASE_EVIDENCE_INDEX_FILE_NAME: Final = "phase_evidence_index.json"
EVIDENCE_FILE_SUFFIX: Final = ".json"
EVIDENCE_IDENTIFIER_PATTERN: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
EVIDENCE_INDEX_SCHEMA_VERSION: Final = "1.0"
REQUIRED_LOCAL_TEST_RUN_IDS: Final = frozenset(
    {
        "phase3-final-static",
        "phase3-final-offline",
        "phase3-final-regression",
        "phase3-final-security",
        "phase3-final-migration",
        "phase3-final-image",
        "phase3-final-load",
    }
)


class PhaseEvidenceIndex(BaseModel):
    """阶段证据索引。

    :ivar schema_version: 索引契约版本。
    :ivar generated_at: 索引生成时间。
    :ivar test_runs: 测试运行证据路径。
    :ivar regressions: 回归证据路径。
    :ivar documentation: 文档事实证据路径。
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = EVIDENCE_INDEX_SCHEMA_VERSION
    generated_at: datetime
    test_runs: list[Path]
    regressions: list[Path]
    documentation: list[Path]
    blocked_documentation: list[Path]
    open_regressions: list[Path]
    fixed_regressions: list[Path]
    verified_regressions: list[Path]
    rejected_regressions: list[Path]
    code_baseline: str
    current_test_runs: list[Path]
    stale_test_runs: list[Path]
    missing_required_test_run_ids: list[str]


class PhaseEvidenceStore:
    """以强类型 JSON 文件持久化阶段证据。"""

    def __init__(self, root_directory: Path = EVIDENCE_ROOT_DIRECTORY) -> None:
        """初始化证据根目录。"""

        self._root_directory = root_directory

    def save_test_run(self, record: TestRunRecord) -> Path:
        """持久化测试运行记录。"""

        return self._save_record(
            directory_name=TEST_RUN_DIRECTORY_NAME,
            identifier=record.header.run_id,
            payload=record.model_dump_json(indent=2),
        )

    def save_regression(self, record: RegressionRecord) -> Path:
        """持久化真实失败回归记录。"""

        return self._save_record(
            directory_name=REGRESSION_DIRECTORY_NAME,
            identifier=record.header.finding_id,
            payload=record.model_dump_json(indent=2),
        )

    def save_documentation(self, record: DocumentationRecord) -> Path:
        """持久化文档事实记录。"""

        identifier = record.header.topic.replace("/", "__").replace("\\", "__")
        if EVIDENCE_IDENTIFIER_PATTERN.fullmatch(identifier) is None:
            topic_digest = sha256(record.header.topic.encode("utf-8")).hexdigest()
            identifier = f"documentation-{topic_digest}"
        return self._save_record(
            directory_name=DOCUMENTATION_DIRECTORY_NAME,
            identifier=identifier,
            payload=record.model_dump_json(indent=2),
        )

    def build_index(self) -> PhaseEvidenceIndex:
        """校验全部证据并生成可检索索引。"""

        test_run_paths = self._validated_paths(
            directory_name=TEST_RUN_DIRECTORY_NAME,
            model_type=TestRunRecord,
        )
        current_baseline = CodeBaselineCalculator.calculate()
        test_run_records = {
            path: TestRunRecord.model_validate_json(path.read_text(encoding="utf-8"))
            for path in test_run_paths
        }
        regression_paths = self._validated_paths(
            directory_name=REGRESSION_DIRECTORY_NAME,
            model_type=RegressionRecord,
        )
        regression_records = {
            path: RegressionRecord.model_validate_json(path.read_text(encoding="utf-8"))
            for path in regression_paths
        }
        documentation_paths = self._validated_paths(
            directory_name=DOCUMENTATION_DIRECTORY_NAME,
            model_type=DocumentationRecord,
        )
        blocked_documentation_paths = [
            path
            for path in documentation_paths
            if DocumentationRecord.model_validate_json(
                path.read_text(encoding="utf-8")
            ).detail.validation_status
            == TruthValidationStatus.BLOCKED
        ]
        index = PhaseEvidenceIndex(
            generated_at=datetime.now(UTC),
            test_runs=test_run_paths,
            regressions=regression_paths,
            documentation=documentation_paths,
            blocked_documentation=blocked_documentation_paths,
            open_regressions=[
                path
                for path, record in regression_records.items()
                if record.status == RegressionStatus.OPEN
            ],
            fixed_regressions=[
                path
                for path, record in regression_records.items()
                if record.status == RegressionStatus.FIXED
            ],
            verified_regressions=[
                path
                for path, record in regression_records.items()
                if record.status == RegressionStatus.VERIFIED
            ],
            rejected_regressions=[
                path
                for path, record in regression_records.items()
                if record.status == RegressionStatus.REJECTED
            ],
            code_baseline=current_baseline,
            current_test_runs=[
                path
                for path, record in test_run_records.items()
                if record.header.code_baseline == current_baseline
            ],
            stale_test_runs=[
                path
                for path, record in test_run_records.items()
                if record.header.code_baseline != current_baseline
            ],
            missing_required_test_run_ids=sorted(
                REQUIRED_LOCAL_TEST_RUN_IDS
                - {
                    record.header.run_id
                    for record in test_run_records.values()
                    if record.header.code_baseline == current_baseline
                    and record.detail.status.value == "passed"
                }
            ),
        )
        self._write_atomically(
            path=self._root_directory / PHASE_EVIDENCE_INDEX_FILE_NAME,
            payload=index.model_dump_json(indent=2),
        )
        return index

    def _save_record(self, *, directory_name: str, identifier: str, payload: str) -> Path:
        """校验记录标识并原子写入 JSON。"""

        if EVIDENCE_IDENTIFIER_PATTERN.fullmatch(identifier) is None:
            raise ValueError(f"阶段证据标识不合法：{identifier}。")
        path = self._root_directory / directory_name / f"{identifier}{EVIDENCE_FILE_SUFFIX}"
        self._write_atomically(path=path, payload=payload)
        return path

    def _validated_paths(
        self,
        *,
        directory_name: str,
        model_type: type[TestRunRecord] | type[RegressionRecord] | type[DocumentationRecord],
    ) -> list[Path]:
        """反序列化目录内全部记录并返回稳定排序路径。"""

        directory = self._root_directory / directory_name
        if not directory.exists():
            return []
        paths = sorted(directory.glob(f"*{EVIDENCE_FILE_SUFFIX}"))
        for path in paths:
            model_type.model_validate_json(path.read_text(encoding="utf-8"))
        return paths

    @staticmethod
    def _write_atomically(*, path: Path, payload: str) -> None:
        """通过同目录临时文件原子替换目标记录。"""

        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_suffix(f"{path.suffix}.tmp")
        temporary_path.write_text(payload + "\n", encoding="utf-8")
        temporary_path.replace(path)
