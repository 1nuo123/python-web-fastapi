"""唯一调参入口：相同真实故障矩阵比较配置，不隐式修改运行时配置。"""

import argparse
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import rtoml

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from scripts.codex.autotuner.connection.evaluate import evaluate
from scripts.codex.autotuner.connection.report import source_digest, write_report
from scripts.codex.verify_compatibility_release import implementation_digest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--candidates", type=Path, default=Path(__file__).with_name("candidates.toml")
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--only")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    config = tomllib.loads(args.candidates.read_text(encoding="utf-8"))
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    runs = []
    for candidate in config["candidates"]:
        if args.only and candidate["name"] != args.only:
            continue
        for seed in config["seeds"]:
            directory = args.output / f"{candidate['name']}-{seed}"
            directory.mkdir(parents=True, exist_ok=True)
            candidate_file = directory / "candidate.toml"
            candidate_file.write_text(rtoml.dumps({**candidate, "seed": seed}), encoding="utf-8")
            digest = implementation_digest()
            connection_digest = source_digest(ROOT)
            result_file = directory / "acceptance.json"
            if result_file.exists():
                raise FileExistsError(
                    "Use a fresh output directory; prior evidence must not be mistaken for a new run"
                )
            timed_out = False
            returncode = None
            with (directory / "run.log").open("w", encoding="utf-8") as log:
                try:
                    process = subprocess.run(
                        [
                            sys.executable,
                            "-X",
                            "utf8",
                            "-B",
                            str(ROOT / "scripts/codex/acceptance/windows_connection.py"),
                            "--proxy=http",
                            f"--connection-candidate={candidate_file.resolve()}",
                            f"--acceptance-report={result_file.resolve()}",
                        ],
                        cwd=ROOT,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        timeout=600,
                        env={**os.environ, "PYTHONHASHSEED": str(seed)},
                    )
                    returncode = process.returncode
                except subprocess.TimeoutExpired:
                    timed_out = True
            result = (
                json.loads(result_file.read_text(encoding="utf-8"))
                if result_file.exists()
                else {"passed": False}
            )
            if returncode != 0:
                result["passed"] = False
            result["runner_timeout"] = timed_out
            result["runner_returncode"] = returncode
            if source_digest(ROOT) != connection_digest:
                result["passed"] = False
                result["source_changed_during_run"] = True
            runs.append(
                {
                    "candidate": candidate,
                    "seed": seed,
                    "revision": revision,
                    "source_digest": digest,
                    "connection_source_digest": connection_digest,
                    "evaluation": evaluate(result),
                    "result": result,
                }
            )
            write_report(args.output, runs)
            print(json.dumps(runs[-1]["evaluation"]), flush=True)


if __name__ == "__main__":
    main()
