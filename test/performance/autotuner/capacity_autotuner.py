"""容量参数自动搜索器。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from itertools import product
from pathlib import Path
from platform import machine, python_version, system
from threading import active_count
from time import perf_counter, sleep
from typing import Literal
from uuid import uuid4

from loguru import logger
from psutil import AccessDenied, NoSuchProcess, Process, ZombieProcess
from pydantic import BaseModel, ConfigDict, Field

from src.infrastructure.evidence.code_baseline_calculator import CodeBaselineCalculator

TUNING_SCHEMA_VERSION = "1.0"
TUNING_TRIAL_HEADER_KIND = "tuning_trial_header"
TUNING_TRIAL_DETAIL_KIND = "capacity_tuning_trial"
TUNING_REPORT_FILE = Path("test/performance/autotuner/capacity_tuning_report.json")
TUNING_RUN_DIRECTORY = Path("test/performance/autotuner/runs")
TUNING_DRY_RUN_ROUND_COUNT = 3
DRY_RUN_REQUEST_COUNT = 24
DRY_RUN_WORK_SECONDS = 0.002
MILLISECONDS_PER_SECOND = 1000.0
PERCENTILE_P50_INDEX = 0.50
PERCENTILE_P95_INDEX = 0.95
PERCENTILE_P99_INDEX = 0.99
BYTES_PER_MEBIBYTE = 1024 * 1024
MAXIMUM_P95_RELATIVE_SPREAD = 0.10
MAXIMUM_THROUGHPUT_RELATIVE_SPREAD = 0.10
MAXIMUM_PEAK_CPU_PERCENT = 90.0
MAXIMUM_PEAK_MEMORY_MEBIBYTES = 1024.0
MAXIMUM_PEAK_THREAD_COUNT = 128
MAXIMUM_PEAK_CONNECTION_COUNT = 256


class TrialPromotion(StrEnum):
    """调参轮次晋升状态。"""

    PROMOTED = "promoted"
    REJECTED = "rejected"
    CANDIDATE = "candidate"


class TuningEvaluationMode(StrEnum):
    """调参评估模式，决定结果是否具备生产晋升资格。"""

    DRY_RUN = "dry_run"
    REAL_LOAD = "real_load"


class TuningLoadProfile(StrEnum):
    """调参活动必须覆盖的负载轮廓。"""

    STEADY = "steady"
    BURST = "burst"
    DEPENDENCY_DEGRADED = "dependency_degraded"


class TuningTrialHeader(BaseModel):
    """调参轮次公共头。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["tuning_trial_header"] = TUNING_TRIAL_HEADER_KIND
    schema_version: Literal["1.0"] = TUNING_SCHEMA_VERSION
    trial_id: str = Field(min_length=1)
    seed: int


class TuningRunHeader(BaseModel):
    """调参运行公共头。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["capacity_tuning_run"] = "capacity_tuning_run"
    schema_version: Literal["1.0"] = TUNING_SCHEMA_VERSION
    run_id: str = Field(min_length=1)
    seed: int
    environment_summary: str = Field(min_length=1)
    code_baseline: str = Field(min_length=1)
    load_profile: TuningLoadProfile
    evaluation_mode: TuningEvaluationMode


class CapacityParameters(BaseModel):
    """候选容量参数。"""

    model_config = ConfigDict(extra="forbid")

    max_workers: int = Field(ge=1)
    max_pending_requests: int = Field(ge=1)
    queue_wait_timeout_seconds: int = Field(ge=1)


class TrialMetrics(BaseModel):
    """调参轮次指标。"""

    model_config = ConfigDict(extra="forbid")

    throughput_per_second: float = Field(ge=0)
    p50_milliseconds: float = Field(ge=0)
    p95_milliseconds: float = Field(ge=0)
    p99_milliseconds: float = Field(ge=0)
    error_rate: float = Field(ge=0, le=1)
    peak_workers: int = Field(ge=0)
    peak_cpu_percent: float = Field(ge=0)
    peak_memory_mebibytes: float = Field(ge=0)
    peak_thread_count: int = Field(ge=0)
    peak_connection_count: int = Field(ge=0)


class TuningTrialDetail(BaseModel):
    """调参轮次强类型扩展字段。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["capacity_tuning_trial"] = TUNING_TRIAL_DETAIL_KIND
    schema_version: Literal["1.0"] = TUNING_SCHEMA_VERSION
    parameters: CapacityParameters
    metrics: TrialMetrics
    conclusion: str = Field(min_length=1)
    promotion: TrialPromotion


class TuningTrialEnvelope(BaseModel):
    """调参轮次信封。"""

    model_config = ConfigDict(extra="forbid")

    header: TuningTrialHeader
    detail: TuningTrialDetail


class TuningReport(BaseModel):
    """自动搜索结构化报告。"""

    model_config = ConfigDict(extra="forbid")

    header: TuningRunHeader
    trials: list[TuningTrialEnvelope]
    best_trial_id: str
    failed_trial_id: str
    should_continue: bool
    conclusion: str


class TuningCampaignReport(BaseModel):
    """三轮调参活动索引报告。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = TUNING_SCHEMA_VERSION
    run_paths: list[Path] = Field(min_length=TUNING_DRY_RUN_ROUND_COUNT)
    code_baseline: str = Field(min_length=1)
    stable_best_parameters: bool
    stable_across_loads: bool
    resource_limits_satisfied: bool
    eligible_for_promotion: bool
    best_parameters: CapacityParameters
    best_metrics: TrialMetrics
    failed_parameters: CapacityParameters
    failed_metrics: TrialMetrics
    promotion: TrialPromotion
    should_continue: bool
    conclusion: str = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class CapacitySearchSpace:
    """容量参数离散搜索空间。"""

    max_workers: tuple[int, ...]
    max_pending_requests: tuple[int, ...]
    queue_wait_timeout_seconds: tuple[int, ...]


@dataclass(slots=True)
class ResourcePeakSnapshot:
    """调参轮次进程资源峰值。"""

    cpu_percent: float = 0.0
    memory_mebibytes: float = 0.0
    thread_count: int = 0
    connection_count: int = 0


class ProcessResourceSampler:
    """使用进程级采样收集 dry-run 资源峰值。"""

    def __init__(self) -> None:
        """初始化当前进程采样器。"""

        self._process = Process()
        self._peaks = ResourcePeakSnapshot()
        self._process.cpu_percent(interval=None)

    def sample(self) -> None:
        """采集一次 CPU、内存、线程和网络连接数量。"""

        try:
            connection_count = len(self._process.net_connections(kind="inet"))
            memory_mebibytes = self._process.memory_info().rss / BYTES_PER_MEBIBYTE
            cpu_percent = self._process.cpu_percent(interval=None)
        except (AccessDenied, NoSuchProcess, ZombieProcess) as exc:
            raise RuntimeError("容量调参资源峰值采集失败。") from exc
        self._peaks.cpu_percent = max(self._peaks.cpu_percent, cpu_percent)
        self._peaks.memory_mebibytes = max(
            self._peaks.memory_mebibytes,
            memory_mebibytes,
        )
        self._peaks.thread_count = max(self._peaks.thread_count, active_count())
        self._peaks.connection_count = max(
            self._peaks.connection_count,
            connection_count,
        )

    def get_peaks(self) -> ResourcePeakSnapshot:
        """返回当前轮次的资源峰值快照。"""

        return self._peaks


class CapacityAutotuner:
    """基于结构化指标自动评估候选容量。"""

    def search(
        self,
        *,
        search_space: CapacitySearchSpace,
        evaluator: Callable[[CapacityParameters], TrialMetrics],
        run_id: str,
        seed: int,
        environment_summary: str,
        code_baseline: str,
        load_profile: TuningLoadProfile,
        evaluation_mode: TuningEvaluationMode,
    ) -> TuningReport:
        """遍历搜索空间并生成最优、失败配置对比。"""

        trials: list[TuningTrialEnvelope] = []
        candidates = product(
            search_space.max_workers,
            search_space.max_pending_requests,
            search_space.queue_wait_timeout_seconds,
        )
        for index, values in enumerate(candidates, start=1):
            parameters = CapacityParameters(
                max_workers=values[0],
                max_pending_requests=values[1],
                queue_wait_timeout_seconds=values[2],
            )
            metrics = evaluator(parameters)
            trials.append(
                TuningTrialEnvelope(
                    header=TuningTrialHeader(
                        trial_id=f"{run_id}-trial-{index}",
                        seed=seed + index,
                    ),
                    detail=TuningTrialDetail(
                        parameters=parameters,
                        metrics=metrics,
                        conclusion="候选配置完成自动测量，等待跨负载复验。",
                        promotion=TrialPromotion.CANDIDATE,
                    ),
                )
            )
        ranked = sorted(
            trials,
            key=lambda trial: (
                trial.detail.metrics.error_rate,
                -trial.detail.metrics.throughput_per_second,
                trial.detail.metrics.p95_milliseconds,
            ),
        )
        best = ranked[0]
        failed = ranked[-1]
        best.detail.promotion = TrialPromotion.CANDIDATE
        failed.detail.promotion = TrialPromotion.REJECTED
        return TuningReport(
            header=TuningRunHeader(
                run_id=run_id,
                seed=seed,
                environment_summary=environment_summary,
                code_baseline=code_baseline,
                load_profile=load_profile,
                evaluation_mode=evaluation_mode,
            ),
            trials=trials,
            best_trial_id=best.header.trial_id,
            failed_trial_id=failed.header.trial_id,
            should_continue=len(trials) > 1 and best.detail.metrics.error_rate == 0,
            conclusion="最优配置仅列为 dry-run 候选；真实多轮负载复验通过前不得晋升。",
        )


class DeterministicDryRunEvaluator:
    """使用可复现轻量工作负载验证 autotuner 数据链路。"""

    def __call__(self, parameters: CapacityParameters) -> TrialMetrics:
        """测量确定性任务并返回延迟分位数。"""

        latencies: list[float] = []
        sampler = ProcessResourceSampler()
        started_at = perf_counter()
        for _request_index in range(DRY_RUN_REQUEST_COUNT):
            request_started_at = perf_counter()
            sleep(DRY_RUN_WORK_SECONDS / parameters.max_workers)
            latencies.append((perf_counter() - request_started_at) * MILLISECONDS_PER_SECOND)
            sampler.sample()
        elapsed = perf_counter() - started_at
        ordered = sorted(latencies)
        peaks = sampler.get_peaks()
        return TrialMetrics(
            throughput_per_second=DRY_RUN_REQUEST_COUNT / elapsed,
            p50_milliseconds=self._percentile(ordered, PERCENTILE_P50_INDEX),
            p95_milliseconds=self._percentile(ordered, PERCENTILE_P95_INDEX),
            p99_milliseconds=self._percentile(ordered, PERCENTILE_P99_INDEX),
            error_rate=0,
            peak_workers=parameters.max_workers,
            peak_cpu_percent=peaks.cpu_percent,
            peak_memory_mebibytes=peaks.memory_mebibytes,
            peak_thread_count=peaks.thread_count,
            peak_connection_count=peaks.connection_count,
        )

    @staticmethod
    def _percentile(values: list[float], ratio: float) -> float:
        """读取离散样本分位数。"""

        if len(values) == 1:
            return values[0]
        index = round((len(values) - 1) * ratio)
        return values[index]


class CapacityAutotunerCli:
    """执行 dry-run 并持久化结构化报告。"""

    @classmethod
    def execute(cls) -> None:
        """运行自动搜索并写入报告。"""

        TUNING_RUN_DIRECTORY.mkdir(parents=True, exist_ok=True)
        reports: list[TuningReport] = []
        run_paths: list[Path] = []
        environment_summary = f"system={system()};machine={machine()};python={python_version()}"
        code_baseline = CodeBaselineCalculator.calculate()
        for round_index, load_profile in enumerate(TuningLoadProfile, start=1):
            run_id = f"capacity-{uuid4().hex}"
            report = CapacityAutotuner().search(
                search_space=CapacitySearchSpace(
                    max_workers=(2, 4, 8),
                    max_pending_requests=(4, 8),
                    queue_wait_timeout_seconds=(1, 2),
                ),
                evaluator=DeterministicDryRunEvaluator(),
                run_id=run_id,
                seed=round_index,
                environment_summary=environment_summary,
                code_baseline=code_baseline,
                load_profile=load_profile,
                evaluation_mode=TuningEvaluationMode.DRY_RUN,
            )
            report_path = TUNING_RUN_DIRECTORY / f"{run_id}.json"
            report_path.write_text(
                report.model_dump_json(indent=2),
                encoding="utf-8",
            )
            reports.append(report)
            run_paths.append(report_path)
        stable_best_parameters = CapacityAutotunerCli._has_stable_best_parameters(reports)
        stable_across_loads = CapacityAutotunerCli._has_stable_metrics(reports)
        resource_limits_satisfied = CapacityAutotunerCli._resource_limits_satisfied(reports)
        campaign_eligible = (
            stable_best_parameters
            and stable_across_loads
            and resource_limits_satisfied
            and all(
                report.header.evaluation_mode == TuningEvaluationMode.REAL_LOAD
                for report in reports
            )
        )
        representative_best = CapacityAutotunerCli._resolve_trial(
            reports[0], reports[0].best_trial_id
        )
        representative_failed = CapacityAutotunerCli._resolve_trial(
            reports[0], reports[0].failed_trial_id
        )
        campaign = TuningCampaignReport(
            run_paths=run_paths,
            code_baseline=code_baseline,
            stable_best_parameters=stable_best_parameters,
            stable_across_loads=stable_across_loads,
            resource_limits_satisfied=resource_limits_satisfied,
            eligible_for_promotion=campaign_eligible,
            best_parameters=representative_best.detail.parameters,
            best_metrics=representative_best.detail.metrics,
            failed_parameters=representative_failed.detail.parameters,
            failed_metrics=representative_failed.detail.metrics,
            promotion=(TrialPromotion.CANDIDATE if campaign_eligible else TrialPromotion.REJECTED),
            should_continue=campaign_eligible,
            conclusion=(
                "跨负载 dry-run 的参数、指标和资源风险均稳定，保留为真实负载候选，尚不晋升。"
                if campaign_eligible
                else "当前活动属于 dry-run，或跨负载稳定性、资源风险未通过；"
                "保留最优/失败对比，淘汰晋升路线并保持冻结配置。"
            ),
        )
        TUNING_REPORT_FILE.write_text(
            campaign.model_dump_json(indent=2),
            encoding="utf-8",
        )
        logger.info(
            "容量自动搜索完成：运行轮数={}，最优参数稳定={}，是否继续={}",
            len(reports),
            campaign.stable_best_parameters,
            campaign.should_continue,
        )

    @staticmethod
    def _has_stable_best_parameters(reports: list[TuningReport]) -> bool:
        """判断三轮最优参数是否一致。"""

        best_parameters = []
        for report in reports:
            best_trial = next(
                trial for trial in report.trials if trial.header.trial_id == report.best_trial_id
            )
            best_parameters.append(best_trial.detail.parameters)
        return all(parameters == best_parameters[0] for parameters in best_parameters[1:])

    @staticmethod
    def _has_stable_metrics(reports: list[TuningReport]) -> bool:
        """校验不同负载轮廓下吞吐与 p95 波动均在冻结阈值内。"""

        best_metrics = [
            CapacityAutotunerCli._resolve_trial(report, report.best_trial_id).detail.metrics
            for report in reports
        ]
        throughput_values = [metrics.throughput_per_second for metrics in best_metrics]
        p95_values = [metrics.p95_milliseconds for metrics in best_metrics]
        return (
            CapacityAutotunerCli._relative_spread(throughput_values)
            <= MAXIMUM_THROUGHPUT_RELATIVE_SPREAD
            and CapacityAutotunerCli._relative_spread(p95_values) <= MAXIMUM_P95_RELATIVE_SPREAD
            and all(metrics.error_rate == 0 for metrics in best_metrics)
        )

    @staticmethod
    def _resource_limits_satisfied(reports: list[TuningReport]) -> bool:
        """校验最优候选未超过 CPU、内存、线程和连接风险阈值。"""

        metrics = [
            CapacityAutotunerCli._resolve_trial(report, report.best_trial_id).detail.metrics
            for report in reports
        ]
        return all(
            item.peak_cpu_percent <= MAXIMUM_PEAK_CPU_PERCENT
            and item.peak_memory_mebibytes <= MAXIMUM_PEAK_MEMORY_MEBIBYTES
            and item.peak_thread_count <= MAXIMUM_PEAK_THREAD_COUNT
            and item.peak_connection_count <= MAXIMUM_PEAK_CONNECTION_COUNT
            for item in metrics
        )

    @staticmethod
    def _relative_spread(values: list[float]) -> float:
        """计算跨负载最大相对波动，零基线仅允许全零。"""

        minimum = min(values)
        maximum = max(values)
        if minimum == 0:
            return 0 if maximum == 0 else float("inf")
        return (maximum - minimum) / minimum

    @staticmethod
    def _resolve_trial(report: TuningReport, trial_id: str) -> TuningTrialEnvelope:
        """按稳定标识读取调参轮次。"""

        return next(trial for trial in report.trials if trial.header.trial_id == trial_id)


if __name__ == "__main__":
    CapacityAutotunerCli.execute()
