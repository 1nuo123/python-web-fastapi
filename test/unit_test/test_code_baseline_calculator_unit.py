"""源码基线摘要稳定性单元测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.infrastructure.evidence import code_baseline_calculator
from src.infrastructure.evidence.code_baseline_calculator import CodeBaselineCalculator


class TestCodeBaselineCalculatorUnit:
    """验证运行证据不会污染源码基线。"""

    def test_calculate_when_autotuner_artifact_changes_should_keep_baseline(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """验证调参运行 JSON 变化不会改变代码摘要。"""

        source_root = tmp_path / "src"
        run_root = tmp_path / "test" / "performance" / "autotuner" / "runs"
        source_root.mkdir()
        run_root.mkdir(parents=True)
        source_path = source_root / "module.py"
        run_path = run_root / "run.json"
        source_path.write_text("class StableSource:\n    pass\n", encoding="utf-8")
        run_path.write_text('{"round": 1}\n', encoding="utf-8")
        monkeypatch.setattr(
            code_baseline_calculator,
            "BASELINE_DIRECTORY_ROOTS",
            (source_root, tmp_path / "test"),
        )
        monkeypatch.setattr(code_baseline_calculator, "BASELINE_FIXED_FILES", ())
        monkeypatch.setattr(
            code_baseline_calculator,
            "IGNORED_BASELINE_PATHS",
            (run_root,),
        )

        first = CodeBaselineCalculator.calculate()
        run_path.write_text('{"round": 2}\n', encoding="utf-8")
        second = CodeBaselineCalculator.calculate()

        assert first == second
