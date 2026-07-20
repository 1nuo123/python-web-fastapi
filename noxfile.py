"""统一质量与测试入口。"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from subprocess import list2cmdline
from time import perf_counter
from typing import Final, Literal, TypedDict, cast

import nox
from defusedxml import ElementTree
from nox.command import CommandFailed

QUALITY_LOCATIONS = ("src", "test", "noxfile.py")
WINDOWS_EXECUTABLE_SUFFIX = ".exe"
PROJECT_PYTHON_EXECUTABLE = Path(sys.executable).as_posix()
IMPORT_LINTER_EXECUTABLE = (
    Path(sys.executable)
    .with_name(f"lint-imports{WINDOWS_EXECUTABLE_SUFFIX if os.name == 'nt' else ''}")
    .as_posix()
)
OFFLINE_MARKER_EXPRESSION = (
    "not postgres and not redis and not rabbitmq and not docker "
    "and not public_network and not integration and not performance"
)
OFFLINE_TEST_PATHS = (
    "test/unit_test",
    "test/contract_test",
    "test/boundary_test",
    "test/interface_test",
    "test/exception_test",
    "test/path_test",
    "test/initialization_test",
    "test/class_inheritance_test",
    "test/convention_usage_test",
)
PERSISTED_TEST_ARTIFACT_DIRECTORY = Path("docs/evidence/test-artifacts")
COVERAGE_REPORT_PATH = PERSISTED_TEST_ARTIFACT_DIRECTORY / "phase3-final-coverage.json"
DOMAIN_COVERAGE_MINIMUM_PERCENT = 90.0
PERCENT_MULTIPLIER = 100.0
TEST_RESULT_DIRECTORY = PERSISTED_TEST_ARTIFACT_DIRECTORY
STATIC_RESULT_DIRECTORY = Path(".tmp/static-results")
STATIC_COMMAND_MANIFEST_PATH = STATIC_RESULT_DIRECTORY / "commands.json"
OFFLINE_JUNIT_PATH = TEST_RESULT_DIRECTORY / "phase3-final-offline.xml"
REGRESSION_JUNIT_PATH = TEST_RESULT_DIRECTORY / "phase3-final-regression.xml"
REGRESSION_ARTIFACT_MANIFEST_PATH = TEST_RESULT_DIRECTORY / "phase3-artifacts.json"
NOX_SUCCESS_EXIT_CODE = 0
NOX_FAILURE_EXIT_CODE = 1
TEST_RUN_STATUS_PASSED = "passed"
TEST_RUN_STATUS_FAILED = "failed"
STATIC_COMMAND_ENTRY = "nox -s static"
OFFLINE_COMMAND_ENTRY = "nox -s offline"
REGRESSION_COMMAND_ENTRY = "nox -s regression"
STATIC_RUN_ID = "phase3-final-static"
OFFLINE_RUN_ID = "phase3-final-offline"
REGRESSION_RUN_ID = "phase3-final-regression"
PYTEST_WARNING_SUMMARY_PATTERN: Final = re.compile(r"(\d+) warnings?")
COMPOSE_VALIDATION_ENV: Final = {
    "POSTGRES_DB": "fastapi_web_skeleton_validation",
    "POSTGRES_USER": "validation_user",
    "POSTGRES_PASSWORD": "validation-postgres-password",
    "REDIS_PASSWORD": "validation-redis-password",
    "JWT_SECRET": "validation-jwt-secret-minimum-32-characters",
    "AUTH_BOOTSTRAP_ADMIN_PASSWORD": "validation-bootstrap-admin-password",
    "RABBITMQ_DEFAULT_USER": "validation_user",
    "RABBITMQ_DEFAULT_PASS": "validation-rabbitmq-password",
}
DOMAIN_COVERAGE_PREFIXES: Final = {
    "auth": (
        "src/application/issue_access_token_usecase.py",
        "src/application/refresh_access_token_usecase.py",
        "src/application/revoke_access_token_usecase.py",
        "src/core/auth_contract/",
        "src/domain/auth/",
        "src/infrastructure/auth/",
    ),
    "security": (
        "src/core/security_contract/",
        "src/infrastructure/security/",
    ),
    "task": (
        "src/application/task/",
        "src/core/task_contract/",
        "src/infrastructure/task/",
    ),
    "persistence": (
        "src/core/persistence_contract/",
        "src/infrastructure/persistence/",
    ),
}


class CoverageFileSummary(TypedDict):
    """覆盖率文件摘要映射。"""

    num_statements: int
    covered_lines: int
    num_branches: int
    covered_branches: int
    percent_covered: float


class CoverageFileRecord(TypedDict):
    """覆盖率文件记录映射。"""

    summary: CoverageFileSummary


class CoverageReport(TypedDict):
    """覆盖率 JSON 报告映射。"""

    files: dict[str, CoverageFileRecord]
    totals: CoverageFileSummary


@dataclass(frozen=True, slots=True)
class DomainCoverageResult:
    """四个关键业务域组合覆盖率。"""

    auth: float
    security: float
    task: float
    persistence: float


@dataclass(frozen=True, slots=True)
class JunitTestSummary:
    """JUnit 测试计数摘要。"""

    test_count: int
    failure_count: int
    error_count: int
    skipped_count: int


@dataclass(frozen=True, slots=True)
class StaticCommandResult:
    """静态门禁单条命令的结构化结果。"""

    command: str
    tool_version: str
    exit_code: int
    finding_count: int
    evidence_path: str
    started_at: str
    finished_at: str
    duration_seconds: float


class StaticQualityRunner:
    """顺序执行静态门禁并保存逐命令原始输出。"""

    def __init__(self, session: nox.Session) -> None:
        """保存 Nox 会话和当前命令结果。"""

        self._session = session
        self._results: list[StaticCommandResult] = []
        STATIC_RESULT_DIRECTORY.mkdir(parents=True, exist_ok=True)

    def run(
        self,
        *command: str,
        evidence_name: str,
        tool_distribution: str,
        env: dict[str, str] | None = None,
    ) -> None:
        """执行一条门禁命令并持久化完整输出。"""

        started_at = datetime.now(UTC)
        started_counter = perf_counter()
        output = self._session.run(*command, env=env, silent=True)
        finished_at = datetime.now(UTC)
        evidence_path = STATIC_RESULT_DIRECTORY / f"{evidence_name}.log"
        evidence_path.write_text(output or "命令成功且没有标准输出。\n", encoding="utf-8")
        self._results.append(
            StaticCommandResult(
                command=list2cmdline(command),
                tool_version=self._resolve_version(tool_distribution),
                exit_code=NOX_SUCCESS_EXIT_CODE,
                finding_count=0,
                evidence_path=evidence_path.as_posix(),
                started_at=started_at.isoformat(),
                finished_at=finished_at.isoformat(),
                duration_seconds=perf_counter() - started_counter,
            )
        )

    def save_manifest(self) -> None:
        """保存供 TestRun 契约消费的逐命令清单。"""

        STATIC_COMMAND_MANIFEST_PATH.write_text(
            json.dumps(
                [asdict(result) for result in self._results],
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def _resolve_version(self, distribution: str) -> str:
        """读取当前项目解释器中的真实工具版本。"""

        if distribution == "python":
            return sys.version.split()[0]
        if distribution == "uv":
            return self._session.run("uv", "--version", silent=True).strip()
        if distribution == "docker":
            return self._session.run(
                "docker",
                "version",
                "--format",
                "{{.Client.Version}}",
                silent=True,
            ).strip()
        return version(distribution)


class JunitReportReader:
    """读取 pytest JUnit XML 的稳定计数。"""

    @staticmethod
    def read(path: Path) -> JunitTestSummary:
        """解析单测试套件或聚合测试套件。"""

        root = ElementTree.parse(path).getroot()  # noqa: S314
        suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
        return JunitTestSummary(
            test_count=sum(int(suite.attrib.get("tests", "0")) for suite in suites),
            failure_count=sum(int(suite.attrib.get("failures", "0")) for suite in suites),
            error_count=sum(int(suite.attrib.get("errors", "0")) for suite in suites),
            skipped_count=sum(int(suite.attrib.get("skipped", "0")) for suite in suites),
        )


class NoxArtifactManifest:
    """生成 TestRun 可消费的持久化产物摘要清单。"""

    @staticmethod
    def save(path: Path, artifacts: tuple[tuple[str, Path], ...]) -> Path:
        """保存产物类型、路径和 SHA-256 摘要。"""

        path.write_text(
            json.dumps(
                [
                    {
                        "kind": kind,
                        "path": artifact_path.as_posix(),
                        "sha256": sha256(artifact_path.read_bytes()).hexdigest(),
                        "command_index": 0,
                    }
                    for kind, artifact_path in artifacts
                ],
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return path


class NoxEvidenceRun:
    """记录一个 Nox 会话的真实命令结果。"""

    def __init__(
        self,
        *,
        kind: Literal["static", "unit", "integration"],
        command_entry: str,
        run_id: str,
    ) -> None:
        """冻结运行标识、环境和开始时间。"""

        self._kind = kind
        self._command_entry = command_entry
        self._run_id = run_id
        self._started_at = datetime.now(UTC)
        self._started_counter = perf_counter()

    def save_passed(
        self,
        *,
        session: nox.Session,
        test_count: int | None,
        warning_count: int = 0,
        artifact_manifest_path: Path | None = None,
        coverage: tuple[float, DomainCoverageResult, Path] | None = None,
    ) -> None:
        """持久化通过记录。"""

        self._save(
            session=session,
            status=TEST_RUN_STATUS_PASSED,
            exit_code=NOX_SUCCESS_EXIT_CODE,
            test_count=test_count,
            failure_summary=None,
            warning_count=warning_count,
            artifact_manifest_path=artifact_manifest_path,
            coverage=coverage,
        )

    def save_failed(self, *, session: nox.Session, failure_summary: str) -> None:
        """持久化失败记录。"""

        self._save(
            session=session,
            status=TEST_RUN_STATUS_FAILED,
            exit_code=NOX_FAILURE_EXIT_CODE,
            test_count=None,
            failure_summary=failure_summary,
            warning_count=0,
            artifact_manifest_path=None,
            coverage=None,
        )

    def _save(
        self,
        *,
        session: nox.Session,
        status: str,
        exit_code: int,
        test_count: int | None,
        failure_summary: str | None,
        warning_count: int,
        artifact_manifest_path: Path | None,
        coverage: tuple[float, DomainCoverageResult, Path] | None,
    ) -> None:
        """调用项目证据入口写入统一强类型记录。"""

        duration_seconds = perf_counter() - self._started_counter
        arguments = [
            PROJECT_PYTHON_EXECUTABLE,
            "-m",
            "src.cli.record_phase_test_run",
            "--run-id",
            self._run_id,
            "--kind",
            self._kind,
            "--status",
            status,
            "--command-entry",
            self._command_entry,
            "--started-at",
            self._started_at.isoformat(),
            "--duration-seconds",
            str(duration_seconds),
            "--exit-code",
            str(exit_code),
            "--warning-count",
            str(warning_count),
        ]
        if test_count is not None:
            arguments.extend(("--test-count", str(test_count)))
        if failure_summary is not None:
            arguments.extend(("--failure-summary", failure_summary))
        if self._kind == "static" and STATIC_COMMAND_MANIFEST_PATH.is_file():
            arguments.extend(("--command-manifest-path", STATIC_COMMAND_MANIFEST_PATH.as_posix()))
        if artifact_manifest_path is not None:
            arguments.extend(("--artifact-manifest-path", artifact_manifest_path.as_posix()))
        if coverage is not None:
            total_percent, domains, report_path = coverage
            arguments.extend(
                (
                    "--coverage-total-percent",
                    str(total_percent),
                    "--coverage-auth-percent",
                    str(domains.auth),
                    "--coverage-security-percent",
                    str(domains.security),
                    "--coverage-task-percent",
                    str(domains.task),
                    "--coverage-persistence-percent",
                    str(domains.persistence),
                    "--coverage-report-path",
                    report_path.as_posix(),
                )
            )
        session.run(*arguments, env={"PYTHONPATH": "."})


class NoxSessions:
    """集中声明可复现的 Nox 会话。"""

    @staticmethod
    @nox.session(name="static", venv_backend="none")
    def static(session: nox.Session) -> None:
        """执行格式、静态、类型、架构和安全检查。"""

        evidence = NoxEvidenceRun(
            kind="static",
            command_entry=STATIC_COMMAND_ENTRY,
            run_id=STATIC_RUN_ID,
        )
        runner = StaticQualityRunner(session)
        try:
            runner.run(
                PROJECT_PYTHON_EXECUTABLE,
                "-m",
                "compileall",
                "-q",
                "src",
                evidence_name="compileall",
                tool_distribution="python",
            )
            runner.run(
                PROJECT_PYTHON_EXECUTABLE,
                "-m",
                "ruff",
                "format",
                "--check",
                *QUALITY_LOCATIONS,
                evidence_name="ruff-format",
                tool_distribution="ruff",
            )
            runner.run(
                PROJECT_PYTHON_EXECUTABLE,
                "-m",
                "ruff",
                "check",
                *QUALITY_LOCATIONS,
                evidence_name="ruff-check",
                tool_distribution="ruff",
            )
            runner.run(
                PROJECT_PYTHON_EXECUTABLE,
                "-m",
                "mypy",
                "src",
                evidence_name="mypy",
                tool_distribution="mypy",
            )
            runner.run(
                IMPORT_LINTER_EXECUTABLE,
                evidence_name="import-linter",
                tool_distribution="import-linter",
            )
            runner.run(
                PROJECT_PYTHON_EXECUTABLE,
                "-m",
                "bandit",
                "-c",
                "pyproject.toml",
                "-r",
                "src",
                "--severity-level",
                "medium",
                evidence_name="bandit",
                tool_distribution="bandit",
            )
            runner.run(
                PROJECT_PYTHON_EXECUTABLE,
                "-m",
                "pip_audit",
                evidence_name="pip-audit",
                tool_distribution="pip-audit",
            )
            runner.run(
                PROJECT_PYTHON_EXECUTABLE,
                "-m",
                "detect_secrets",
                "scan",
                "src",
                "config",
                "compose.yml",
                "compose.production.yml",
                "Dockerfile",
                evidence_name="detect-secrets",
                tool_distribution="detect-secrets",
            )
            runner.run(
                "uv",
                "lock",
                "--check",
                evidence_name="uv-lock",
                tool_distribution="uv",
            )
            runner.run(
                "docker",
                "compose",
                "-f",
                "compose.yml",
                "config",
                "-q",
                env=COMPOSE_VALIDATION_ENV,
                evidence_name="compose-local",
                tool_distribution="docker",
            )
            runner.run(
                "docker",
                "compose",
                "-f",
                "compose.yml",
                "-f",
                "compose.production.yml",
                "config",
                "-q",
                env=COMPOSE_VALIDATION_ENV,
                evidence_name="compose-production",
                tool_distribution="docker",
            )
        except CommandFailed:
            evidence.save_failed(
                session=session,
                failure_summary="静态质量会话存在失败命令。",
            )
            raise
        runner.save_manifest()
        evidence.save_passed(session=session, test_count=None)

    @staticmethod
    @nox.session(name="offline", venv_backend="none")
    def offline(session: nox.Session) -> None:
        """执行不依赖外部服务的快速测试层。"""

        TEST_RESULT_DIRECTORY.mkdir(parents=True, exist_ok=True)
        evidence = NoxEvidenceRun(
            kind="unit",
            command_entry=OFFLINE_COMMAND_ENTRY,
            run_id=OFFLINE_RUN_ID,
        )
        try:
            output = session.run(
                PROJECT_PYTHON_EXECUTABLE,
                "-m",
                "pytest",
                "-q",
                "-m",
                OFFLINE_MARKER_EXPRESSION,
                f"--junitxml={OFFLINE_JUNIT_PATH.as_posix()}",
                *OFFLINE_TEST_PATHS,
                silent=True,
            )
        except CommandFailed:
            evidence.save_failed(
                session=session,
                failure_summary="离线测试会话存在失败用例。",
            )
            raise
        summary = JunitReportReader.read(OFFLINE_JUNIT_PATH)
        session.log(output)
        artifact_manifest_path = NoxArtifactManifest.save(
            TEST_RESULT_DIRECTORY / "phase3-offline-artifacts.json",
            (("junit", OFFLINE_JUNIT_PATH),),
        )
        evidence.save_passed(
            session=session,
            test_count=summary.test_count,
            warning_count=NoxSessions._read_warning_count(output),
            artifact_manifest_path=artifact_manifest_path,
        )

    @staticmethod
    @nox.session(name="regression", venv_backend="none")
    def regression(session: nox.Session) -> None:
        """执行全量回归与总体、关键域覆盖率门禁。"""

        COVERAGE_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        TEST_RESULT_DIRECTORY.mkdir(parents=True, exist_ok=True)
        evidence = NoxEvidenceRun(
            kind="integration",
            command_entry=REGRESSION_COMMAND_ENTRY,
            run_id=REGRESSION_RUN_ID,
        )
        try:
            output = session.run(
                PROJECT_PYTHON_EXECUTABLE,
                "-m",
                "pytest",
                "-q",
                "--cov=src",
                "--cov-branch",
                "--cov-report=term-missing",
                f"--cov-report=json:{COVERAGE_REPORT_PATH.as_posix()}",
                "--cov-fail-under=85",
                f"--junitxml={REGRESSION_JUNIT_PATH.as_posix()}",
                silent=True,
            )
        except CommandFailed:
            evidence.save_failed(
                session=session,
                failure_summary="全量回归存在失败用例或覆盖率未达标。",
            )
            raise
        summary = JunitReportReader.read(REGRESSION_JUNIT_PATH)
        if summary.skipped_count > 0:
            evidence.save_failed(
                session=session,
                failure_summary=f"全量回归存在 {summary.skipped_count} 个 skip 或 xfail。",
            )
            session.error("全量回归不允许存在 skip 或 xfail。")
        session.log(output)
        domains = NoxSessions._enforce_domain_coverage(session)
        report = cast(
            CoverageReport,
            json.loads(COVERAGE_REPORT_PATH.read_text(encoding="utf-8")),
        )
        artifact_manifest_path = NoxArtifactManifest.save(
            REGRESSION_ARTIFACT_MANIFEST_PATH,
            (
                ("junit", REGRESSION_JUNIT_PATH),
                ("coverage", COVERAGE_REPORT_PATH),
            ),
        )
        evidence.save_passed(
            session=session,
            test_count=summary.test_count,
            warning_count=NoxSessions._read_warning_count(output),
            artifact_manifest_path=artifact_manifest_path,
            coverage=(report["totals"]["percent_covered"], domains, COVERAGE_REPORT_PATH),
        )

    @staticmethod
    def _enforce_domain_coverage(session: nox.Session) -> DomainCoverageResult:
        """按语义域汇总语句与分支覆盖率并执行 90% 门禁。"""

        report = cast(
            CoverageReport,
            json.loads(COVERAGE_REPORT_PATH.read_text(encoding="utf-8")),
        )
        failures: list[str] = []
        percentages: dict[str, float] = {}
        for domain_name, prefixes in DOMAIN_COVERAGE_PREFIXES.items():
            covered = 0
            total = 0
            for file_name, record in report["files"].items():
                normalized_name = file_name.replace("\\", "/")
                if not normalized_name.startswith(prefixes):
                    continue
                summary = record["summary"]
                covered += summary["covered_lines"] + summary["covered_branches"]
                total += summary["num_statements"] + summary["num_branches"]
            percentage = PERCENT_MULTIPLIER * covered / total if total else 0.0
            percentages[domain_name] = percentage
            session.log("关键域 %s 组合覆盖率：%.2f%%", domain_name, percentage)
            if percentage < DOMAIN_COVERAGE_MINIMUM_PERCENT:
                failures.append(f"{domain_name}={percentage:.2f}%")
        if failures:
            session.error("关键域覆盖率未达到 90%：" + "、".join(failures))
        return DomainCoverageResult(
            auth=percentages["auth"],
            security=percentages["security"],
            task=percentages["task"],
            persistence=percentages["persistence"],
        )

    @staticmethod
    def _read_warning_count(output: str) -> int:
        """从 pytest 终态摘要读取警告数量。"""

        matches = PYTEST_WARNING_SUMMARY_PATTERN.findall(output)
        return int(matches[-1]) if matches else 0
