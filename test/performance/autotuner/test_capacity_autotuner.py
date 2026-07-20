"""容量自动搜索器测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from test.performance.autotuner import capacity_autotuner
from test.performance.autotuner.capacity_autotuner import (
    CapacityAutotuner,
    CapacityAutotunerCli,
    CapacitySearchSpace,
    DeterministicDryRunEvaluator,
    TrialPromotion,
    TuningCampaignReport,
    TuningEvaluationMode,
    TuningLoadProfile,
    TuningReport,
)

AUTOTUNER_TEST_RUN_ID = "autotuner-test-run"
AUTOTUNER_TEST_SEED = 17
AUTOTUNER_TEST_ENVIRONMENT = "test-environment"
AUTOTUNER_TEST_BASELINE = "baseline-test"


class TestCapacityAutotuner:
    """验证自动搜索的记录和晋升规则。"""

    def test_search_when_multiple_candidates_should_compare_best_and_failed(self) -> None:
        """验证搜索会保留全部轮次并输出最优与失败配置。"""

        report = CapacityAutotuner().search(
            search_space=CapacitySearchSpace(
                max_workers=(1, 2),
                max_pending_requests=(1,),
                queue_wait_timeout_seconds=(1,),
            ),
            evaluator=DeterministicDryRunEvaluator(),
            run_id=AUTOTUNER_TEST_RUN_ID,
            seed=AUTOTUNER_TEST_SEED,
            environment_summary=AUTOTUNER_TEST_ENVIRONMENT,
            code_baseline=AUTOTUNER_TEST_BASELINE,
            load_profile=TuningLoadProfile.STEADY,
            evaluation_mode=TuningEvaluationMode.DRY_RUN,
        )

        promotions = {trial.detail.promotion for trial in report.trials}
        assert len(report.trials) == 2
        assert report.best_trial_id != report.failed_trial_id
        assert TrialPromotion.CANDIDATE in promotions
        assert TrialPromotion.REJECTED in promotions
        assert report.should_continue is True
        assert report.header.run_id == AUTOTUNER_TEST_RUN_ID
        for trial in report.trials:
            assert trial.detail.metrics.peak_cpu_percent >= 0
            assert trial.detail.metrics.peak_memory_mebibytes > 0
            assert trial.detail.metrics.peak_thread_count > 0
            assert trial.detail.metrics.peak_connection_count >= 0

    def test_search_when_run_ids_differ_should_keep_independent_trial_ids(self) -> None:
        """验证不同运行不会覆盖或复用候选标识。"""

        search_space = CapacitySearchSpace(
            max_workers=(1,),
            max_pending_requests=(1,),
            queue_wait_timeout_seconds=(1,),
        )
        first = CapacityAutotuner().search(
            search_space=search_space,
            evaluator=DeterministicDryRunEvaluator(),
            run_id="first-run",
            seed=1,
            environment_summary=AUTOTUNER_TEST_ENVIRONMENT,
            code_baseline=AUTOTUNER_TEST_BASELINE,
            load_profile=TuningLoadProfile.STEADY,
            evaluation_mode=TuningEvaluationMode.DRY_RUN,
        )
        second = CapacityAutotuner().search(
            search_space=search_space,
            evaluator=DeterministicDryRunEvaluator(),
            run_id="second-run",
            seed=2,
            environment_summary=AUTOTUNER_TEST_ENVIRONMENT,
            code_baseline=AUTOTUNER_TEST_BASELINE,
            load_profile=TuningLoadProfile.BURST,
            evaluation_mode=TuningEvaluationMode.DRY_RUN,
        )

        assert first.trials[0].header.trial_id != second.trials[0].header.trial_id

    def test_cli_should_generate_campaign_from_exact_persisted_runs(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """验证活动报告只引用本轮原始 JSON 并据此计算晋升结论。"""

        run_directory = tmp_path / "runs"
        report_path = tmp_path / "capacity_tuning_report.json"
        monkeypatch.setattr(capacity_autotuner, "TUNING_RUN_DIRECTORY", run_directory)
        monkeypatch.setattr(capacity_autotuner, "TUNING_REPORT_FILE", report_path)

        CapacityAutotunerCli.execute()

        campaign = TuningCampaignReport.model_validate_json(report_path.read_text(encoding="utf-8"))
        reports = [
            TuningReport.model_validate_json(path.read_text(encoding="utf-8"))
            for path in campaign.run_paths
        ]
        stable = CapacityAutotunerCli._has_stable_best_parameters(reports)  # noqa: SLF001
        stable_metrics = CapacityAutotunerCli._has_stable_metrics(reports)  # noqa: SLF001
        resources_satisfied = CapacityAutotunerCli._resource_limits_satisfied(  # noqa: SLF001
            reports
        )
        eligible = False

        assert len(campaign.run_paths) == capacity_autotuner.TUNING_DRY_RUN_ROUND_COUNT
        assert all(path.parent == run_directory for path in campaign.run_paths)
        assert campaign.stable_best_parameters is stable
        assert campaign.stable_across_loads is stable_metrics
        assert campaign.resource_limits_satisfied is resources_satisfied
        assert campaign.eligible_for_promotion is False
        assert campaign.best_parameters is not None
        assert campaign.best_metrics is not None
        assert campaign.promotion == (
            TrialPromotion.CANDIDATE if eligible else TrialPromotion.REJECTED
        )
        assert campaign.should_continue is eligible
