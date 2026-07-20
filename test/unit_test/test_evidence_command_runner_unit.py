"""证据命令与多产物清单单元测试。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import TypeAdapter

from src.cli.build_evidence_artifact_manifest import EvidenceArtifactManifestBuilder
from src.cli.run_evidence_commands import EvidenceCommandRunner
from src.core.phase_evidence_contract import CommandExecutionEvidence, EvidenceArtifact


class TestEvidenceCommandRunnerUnit:
    """验证逐命令时间窗、返回码、日志和多产物摘要。"""

    def test_runner_when_plan_valid_should_persist_real_command_window(
        self,
        tmp_path: Path,
    ) -> None:
        """验证命令执行清单包含真实时间窗与原始输出。"""

        plan_path = tmp_path / "plan.json"
        manifest_path = tmp_path / "commands.json"
        plan_path.write_text(
            json.dumps(
                {
                    "output_directory": str(tmp_path / "logs"),
                    "steps": [
                        {
                            "name": "python-version",
                            "argv": [sys.executable, "--version"],
                            "timeout_seconds": 10,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        exit_code = EvidenceCommandRunner().run(plan_path, manifest_path)
        records = TypeAdapter(tuple[CommandExecutionEvidence, ...]).validate_json(
            manifest_path.read_text(encoding="utf-8")
        )

        assert exit_code == 0
        assert len(records) == 1
        assert records[0].finished_at >= records[0].started_at
        assert records[0].duration_seconds >= 0
        assert records[0].evidence_path.read_text(encoding="utf-8").startswith("Python")

    def test_artifact_builder_when_multiple_files_should_hash_and_link_command(
        self,
        tmp_path: Path,
    ) -> None:
        """验证一个 TestRun 可关联多个逐命令原始产物。"""

        first_artifact = tmp_path / "first.log"
        second_artifact = tmp_path / "second.csv"
        first_artifact.write_text("第一条证据\n", encoding="utf-8")
        second_artifact.write_text("name,value\nresult,1\n", encoding="utf-8")
        plan_path = tmp_path / "artifact-plan.json"
        manifest_path = tmp_path / "artifacts.json"
        plan_path.write_text(
            json.dumps(
                {
                    "artifacts": [
                        {"kind": "log", "path": str(first_artifact), "command_index": 0},
                        {"kind": "load_stats", "path": str(second_artifact), "command_index": 1},
                    ]
                }
            ),
            encoding="utf-8",
        )

        EvidenceArtifactManifestBuilder.build(plan_path, manifest_path)
        artifacts = TypeAdapter(tuple[EvidenceArtifact, ...]).validate_json(
            manifest_path.read_text(encoding="utf-8")
        )

        assert len(artifacts) == 2
        assert artifacts[0].command_index == 0
        assert artifacts[1].command_index == 1
        assert all(len(artifact.sha256) == 64 for artifact in artifacts)
