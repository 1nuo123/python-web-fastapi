"""
Prometheus metrics HTTP 接口测试模块。
"""

from __future__ import annotations

import os
import subprocess
import sys
from http import HTTPStatus

from fastapi.testclient import TestClient

from src.api.testing.test_app_factory import TestAppFactory

HEALTH_LIVE_PATH = "/health/live"
METRICS_PATH = "/metrics"
OPENAPI_PATH = "/openapi.json"
USER_DETAIL_ROUTE_TEMPLATE = "/users/{subject_id}"
USER_DETAIL_REQUEST_PATH = "/users/123"
RUNTIME_SECTION = "runtime"
METRICS_SECTION = "metrics"
HEADER_SECTION = "header"
ENABLED_FIELD = "enabled"
REQUEST_TOTAL_METRIC_NAME = "fastapi_request_total"
RUNTIME_READY_METRIC_NAME = "fastapi_runtime_ready"
HTTP_GET_METHOD = "GET"
AUTHORIZATION_TEXT = "Authorization"
JWT_TEXT = "JWT"
PASSWORD_TEXT = "password"
SECRET_TEXT = "secret"
TOKEN_TEXT = "token"
PATHS_FIELD = "paths"
SUBJECT_ID_FIELD = "subject_id"
CURRENT_WORKDIR = "."
PYTHON_EXECUTE_CODE_ARGUMENT = "-c"
PYTHONPATH_ENV_NAME = "PYTHONPATH"
SUBPROCESS_TIMEOUT_SECONDS = 30
FUNBOOST_BOOTSTRAPPER_MODULE = "src.infrastructure.task.funboost_task_bootstrapper"
FUNBOOST_IMPORT_FAILURE_MESSAGE = "指标应用装配不应导入 Funboost 启动器。"


class TestMetricsHttpInterface:
    """
    Prometheus metrics HTTP 接口测试集合。
    """

    def test_metrics_when_enabled_should_return_prometheus_text(self) -> None:
        """
        验证 metrics 开启时应返回 Prometheus 文本。
        """

        app = TestAppFactory().create(overrides=self._build_metrics_override(True))
        with TestClient(app) as client:
            client.get(HEALTH_LIVE_PATH)
            response = client.get(METRICS_PATH)

        metrics_text = response.text
        assert response.status_code == HTTPStatus.OK
        assert REQUEST_TOTAL_METRIC_NAME in metrics_text
        assert RUNTIME_READY_METRIC_NAME in metrics_text
        assert HEALTH_LIVE_PATH in metrics_text
        assert AUTHORIZATION_TEXT not in metrics_text
        assert JWT_TEXT not in metrics_text
        assert PASSWORD_TEXT not in metrics_text
        assert SECRET_TEXT not in metrics_text
        assert TOKEN_TEXT not in metrics_text

    def test_metrics_when_disabled_should_return_404(self) -> None:
        """
        验证 metrics 关闭时应返回 404。
        """

        app = TestAppFactory().create(overrides=self._build_metrics_override(False))
        with TestClient(app) as client:
            response = client.get(METRICS_PATH)

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_metrics_should_not_be_exposed_in_openapi(self) -> None:
        """
        验证 metrics 路由不进入 OpenAPI。
        """

        app = TestAppFactory().create(overrides=self._build_metrics_override(True))
        with TestClient(app) as client:
            response = client.get(OPENAPI_PATH)

        assert response.status_code == HTTPStatus.OK
        assert METRICS_PATH not in response.json()[PATHS_FIELD]

    def test_metrics_when_dynamic_route_should_use_route_template(self) -> None:
        """
        验证动态路由指标应使用 FastAPI route template。
        """

        app = TestAppFactory().create(overrides=self._build_metrics_override(True))
        app.add_api_route(
            USER_DETAIL_ROUTE_TEMPLATE,
            self._read_user,
            methods=[HTTP_GET_METHOD],
        )
        with TestClient(app) as client:
            user_response = client.get(USER_DETAIL_REQUEST_PATH)
            metrics_response = client.get(METRICS_PATH)

        metrics_text = metrics_response.text
        assert user_response.status_code == HTTPStatus.OK
        assert metrics_response.status_code == HTTPStatus.OK
        assert f'path="{USER_DETAIL_ROUTE_TEMPLATE}"' in metrics_text
        assert USER_DETAIL_REQUEST_PATH not in metrics_text

    def test_metrics_app_assembly_should_not_import_funboost_bootstrapper(self) -> None:
        """
        验证指标应用装配路径不应急切导入 Funboost 启动器。
        """

        environment = os.environ.copy()
        environment[PYTHONPATH_ENV_NAME] = CURRENT_WORKDIR
        completed_process = subprocess.run(
            [
                sys.executable,
                PYTHON_EXECUTE_CODE_ARGUMENT,
                self._build_funboost_import_isolation_script(),
            ],
            cwd=CURRENT_WORKDIR,
            env=environment,
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
            check=False,
        )

        assert completed_process.returncode == 0, (
            completed_process.stderr or completed_process.stdout
        )

    def _build_metrics_override(self, enabled: bool) -> dict[str, object]:
        """
        构建 metrics 开关覆盖配置。

        :param enabled: 是否启用 metrics。
        :type enabled: bool
        :returns: 配置覆盖映射。
        :rtype: dict[str, object]
        """

        return {
            RUNTIME_SECTION: {
                METRICS_SECTION: {
                    HEADER_SECTION: {
                        ENABLED_FIELD: enabled,
                    }
                }
            }
        }

    def _read_user(self, subject_id: str) -> dict[str, str]:
        """
        读取测试用户响应。

        :param subject_id: 测试主体标识。
        :type subject_id: str
        :returns: 测试响应体。
        :rtype: dict[str, str]
        """

        return {SUBJECT_ID_FIELD: subject_id}

    def _build_funboost_import_isolation_script(self) -> str:
        """
        构建 Funboost 导入隔离校验脚本。

        :returns: 可由 Python 子进程执行的隔离校验脚本。
        :rtype: str
        """

        overrides_literal = repr(self._build_metrics_override(True))
        return "\n".join(
            [
                "import sys",
                "from src.api.testing.test_app_factory import TestAppFactory",
                f"TestAppFactory().create(overrides={overrides_literal})",
                f"if {FUNBOOST_BOOTSTRAPPER_MODULE!r} in sys.modules:",
                f"    raise SystemExit({FUNBOOST_IMPORT_FAILURE_MESSAGE!r})",
            ]
        )
