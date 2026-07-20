"""
测试日志异常路径测试模块。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.testing.test_app_factory import TestAppFactory


class TestLoggingExceptionPath:
    """
    测试日志异常路径测试集合，用于组织同一主题下的测试场景。
    """

    def test_unexpected_exception_should_keep_http_semantics(self) -> None:
        """
        验证未预期异常应保持 HTTP 语义。
        """

        app = TestAppFactory().create()

        @app.get("/logging-exception-test")
        def logging_exception_test() -> None:
            raise RuntimeError("日志异常测试")

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/logging-exception-test")
            assert response.status_code == 500
            assert response.json()["header"]["code"] == "system.internal.unexpected"
