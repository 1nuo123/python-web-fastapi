"""
测试数据库日志集成测试模块。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.testing.test_app_factory import TestAppFactory

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.usefixtures("integration_database"),
]


class TestDatabaseLoggingIntegration:
    """
    测试数据库日志集成测试集合，用于组织同一主题下的测试场景。
    """

    def test_app_request_should_emit_access_logging_event(self) -> None:
        """
        验证应用请求应发送访问日志事件。
        """

        app = TestAppFactory().create()
        with TestClient(app) as client:
            response = client.get("/health/live")
            assert response.status_code == 200
