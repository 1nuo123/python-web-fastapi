"""Locust 稳定、突发和过载 HTTP 场景入口。"""

from __future__ import annotations

from locust import HttpUser, between, task

from test.performance.scenarios.load_runtime_settings import LoadScenarioRuntimeSettings

HEALTH_LIVE_PATH = "/health/live"
HEALTH_READY_PATH = "/health/ready"
TOO_MANY_REQUESTS_STATUS_CODE = 429
BACKPRESSURE_STAT_NAME_SUFFIX = "backpressure_429"


LOAD_SCENARIO_RUNTIME_SETTINGS = LoadScenarioRuntimeSettings.from_environment()
LOAD_SCENARIO_STAT_NAME_PREFIX = LOAD_SCENARIO_RUNTIME_SETTINGS.scenario.detail.kind


class RuntimeProbeUser(HttpUser):
    """以健康探针验证运行时吞吐、背压与恢复。"""

    wait_time = between(
        LOAD_SCENARIO_RUNTIME_SETTINGS.minimum_wait_seconds,
        LOAD_SCENARIO_RUNTIME_SETTINGS.maximum_wait_seconds,
    )

    @task(4)
    def read_live_probe(self) -> None:
        """请求存活探针。"""

        self._read_probe(
            path=HEALTH_LIVE_PATH,
            name=f"{LOAD_SCENARIO_STAT_NAME_PREFIX}_health_live",
        )

    @task(1)
    def read_ready_probe(self) -> None:
        """请求就绪探针。"""

        self._read_probe(
            path=HEALTH_READY_PATH,
            name=f"{LOAD_SCENARIO_STAT_NAME_PREFIX}_health_ready",
        )

    def _read_probe(self, *, path: str, name: str) -> None:
        """请求探针并把契约内的限流拒绝记录为背压事件。"""

        with self.client.get(path, name=name, catch_response=True) as response:
            if response.status_code not in LOAD_SCENARIO_RUNTIME_SETTINGS.expected_status_codes:
                response.failure(f"收到未预期的 HTTP 状态码：{response.status_code}")
                return
            if response.status_code == TOO_MANY_REQUESTS_STATUS_CODE:
                response.request_meta["name"] = f"{name}_{BACKPRESSURE_STAT_NAME_SUFFIX}"
            response.success()
