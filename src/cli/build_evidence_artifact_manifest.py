"""从结构化产物计划生成带摘要的 TestRun 产物清单。"""

from __future__ import annotations

import argparse
import json
from hashlib import sha256
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from src.core.phase_evidence_contract import EvidenceArtifact, EvidenceArtifactKind


class EvidenceArtifactInput(BaseModel):
    """待摘要的单个证据产物。"""

    model_config = ConfigDict(extra="forbid")

    kind: EvidenceArtifactKind
    path: Path
    command_index: int | None = Field(default=None, ge=0)


class EvidenceArtifactPlan(BaseModel):
    """待摘要的证据产物集合。"""

    model_config = ConfigDict(extra="forbid")

    artifacts: tuple[EvidenceArtifactInput, ...] = Field(min_length=1)


class EvidenceArtifactManifestBuilder:
    """校验产物存在并生成 SHA-256 清单。"""

    @staticmethod
    def build(plan_path: Path, manifest_path: Path) -> None:
        """生成 TestRun 可直接消费的产物清单。"""

        plan = EvidenceArtifactPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
        artifacts: list[EvidenceArtifact] = []
        for item in plan.artifacts:
            if not item.path.is_file():
                raise ValueError(f"阶段证据产物不存在：{item.path}。")
            artifacts.append(
                EvidenceArtifact(
                    kind=item.kind,
                    path=item.path,
                    sha256=sha256(item.path.read_bytes()).hexdigest(),
                    command_index=item.command_index,
                )
            )
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = manifest_path.with_suffix(f"{manifest_path.suffix}.tmp")
        temporary_path.write_text(
            json.dumps(
                [artifact.model_dump(mode="json") for artifact in artifacts],
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(manifest_path)


class EvidenceArtifactManifestCli:
    """证据产物清单命令行入口。"""

    def run(self) -> int:
        """解析参数并生成清单。"""

        parser = argparse.ArgumentParser(description="生成阶段证据产物摘要清单。")
        parser.add_argument("--plan", required=True, type=Path)
        parser.add_argument("--manifest", required=True, type=Path)
        arguments = parser.parse_args()
        EvidenceArtifactManifestBuilder.build(arguments.plan, arguments.manifest)
        return 0


if __name__ == "__main__":
    raise SystemExit(EvidenceArtifactManifestCli().run())
