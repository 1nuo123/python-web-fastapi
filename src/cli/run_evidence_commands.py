"""逐命令执行并保存真实起止时间、返回码和原始日志的命令行入口。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from subprocess import list2cmdline
from time import perf_counter

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from src.core.phase_evidence_contract import CommandExecutionEvidence

COMMAND_SUCCESS_EXIT_CODE = 0
COMMAND_TIMEOUT_EXIT_CODE = 124


class EvidenceEnvironmentVariable(BaseModel):
    """单个命令环境变量。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    value: str


class EvidenceCommandStep(BaseModel):
    """待执行的单个证据命令。"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    argv: tuple[str, ...] = Field(min_length=1)
    timeout_seconds: float = Field(gt=0)
    environment: tuple[EvidenceEnvironmentVariable, ...] = ()


class EvidenceCommandPlan(BaseModel):
    """可复现命令执行计划。"""

    model_config = ConfigDict(extra="forbid")

    output_directory: Path
    stop_on_failure: bool = True
    steps: tuple[EvidenceCommandStep, ...] = Field(min_length=1)


class EvidenceCommandRunner:
    """不经 shell 执行结构化命令计划并持久化完整原始输出。"""

    def run(self, plan_path: Path, manifest_path: Path) -> int:
        """执行计划并写入 ``CommandExecutionEvidence`` 清单。"""

        plan = EvidenceCommandPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
        plan.output_directory.mkdir(parents=True, exist_ok=True)
        results: list[CommandExecutionEvidence] = []
        final_exit_code = COMMAND_SUCCESS_EXIT_CODE
        for step in plan.steps:
            result = self._run_step(step=step, output_directory=plan.output_directory)
            results.append(result)
            if result.exit_code != COMMAND_SUCCESS_EXIT_CODE:
                final_exit_code = result.exit_code
                if plan.stop_on_failure:
                    break
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = manifest_path.with_suffix(f"{manifest_path.suffix}.tmp")
        temporary_path.write_text(
            json.dumps(
                [result.model_dump(mode="json") for result in results],
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(manifest_path)
        return final_exit_code

    @staticmethod
    def _run_step(
        *,
        step: EvidenceCommandStep,
        output_directory: Path,
    ) -> CommandExecutionEvidence:
        """执行一条命令并保存 stdout、stderr 和真实时间窗口。"""

        evidence_path = output_directory / f"{step.name}.log"
        environment = os.environ.copy()
        environment.update({item.name: item.value for item in step.environment})
        started_at = datetime.now(UTC)
        started_counter = perf_counter()
        try:
            completed = subprocess.run(
                step.argv,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=step.timeout_seconds,
                env=environment,
            )
            exit_code = completed.returncode
            output = completed.stdout + completed.stderr
        except subprocess.TimeoutExpired as exc:
            exit_code = COMMAND_TIMEOUT_EXIT_CODE
            standard_output = exc.stdout if isinstance(exc.stdout, str) else ""
            standard_error = exc.stderr if isinstance(exc.stderr, str) else ""
            output = standard_output + standard_error + "\n命令执行超时。\n"
        finished_at = datetime.now(UTC)
        duration_seconds = perf_counter() - started_counter
        evidence_path.write_text(output or "命令成功且没有标准输出。\n", encoding="utf-8")
        logger.info("证据命令完成：名称={}，返回码={}。", step.name, exit_code)
        return CommandExecutionEvidence(
            command=list2cmdline(step.argv),
            tool_version="由原始日志中的版本命令记录",
            exit_code=exit_code,
            finding_count=0,
            evidence_path=evidence_path,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=duration_seconds,
        )


class EvidenceCommandRunnerCli:
    """结构化证据命令执行入口。"""

    def run(self) -> int:
        """解析参数并执行命令计划。"""

        parser = argparse.ArgumentParser(description="执行结构化证据命令计划。")
        parser.add_argument("--plan", required=True, type=Path)
        parser.add_argument("--manifest", required=True, type=Path)
        arguments = parser.parse_args()
        return EvidenceCommandRunner().run(arguments.plan, arguments.manifest)


if __name__ == "__main__":
    raise SystemExit(EvidenceCommandRunnerCli().run())
