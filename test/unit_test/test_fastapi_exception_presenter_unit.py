"""
FastAPI 异常呈现器单元测试模块。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.testing.test_app_factory import TestAppFactory
from src.api.testing.test_route_binder import TestRouteBinder as ExceptionTestRouteBinder

VALIDATION_PATH = "/auth/token"
UNEXPECTED_EXCEPTION_PATH = "/exception-presenter-test"
SECRET_TEXT = "postgresql+psycopg://user:password@db:5432/app"
DETAIL_FIELD = "detail"
LOGGER_EXCEPTION_CALLED_MESSAGE = "异常呈现器不应调用 logger.exception。"


class TestFastApiExceptionPresenterUnit:
    """
    FastAPI 异常呈现器单元测试集合。
    """

    def test_validation_error_should_not_return_internal_detail(self) -> None:
        """
        验证请求校验错误不向客户端返回内部 detail 字段。
        """

        app = TestAppFactory().create()

        with TestClient(app) as client:
            response = client.post(VALIDATION_PATH, json={"username": "admin"})

        response_payload = response.json()
        assert response.status_code == 422
        assert DETAIL_FIELD not in response_payload["data"]

    def test_unexpected_exception_should_not_return_raw_exception(self) -> None:
        """
        验证未预期异常不向客户端返回原始异常详情。
        """

        app = TestAppFactory().create()
        ExceptionTestRouteBinder(app).bind_unexpected_exception_route(
            path=UNEXPECTED_EXCEPTION_PATH,
            message=SECRET_TEXT,
        )

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(UNEXPECTED_EXCEPTION_PATH)

        response_text = response.text
        assert response.status_code == 500
        assert SECRET_TEXT not in response_text
        assert DETAIL_FIELD not in response.json()["data"]

    def test_unexpected_exception_should_not_call_plain_exception_logger(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        验证未预期异常不调用普通 ``logger.exception`` 明文路径。
        """

        app = TestAppFactory().create()
        ExceptionTestRouteBinder(app).bind_unexpected_exception_route(
            path=UNEXPECTED_EXCEPTION_PATH,
            message=SECRET_TEXT,
        )
        logger = app.state.container.resource_mount._logger  # noqa: SLF001
        exception_called = False

        def capture_exception_call(*_arguments: object, **_keywords: object) -> None:
            nonlocal exception_called
            exception_called = True

        monkeypatch.setattr(logger, "exception", capture_exception_call)

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(UNEXPECTED_EXCEPTION_PATH)

        assert response.status_code == 500
        assert exception_called is False, LOGGER_EXCEPTION_CALLED_MESSAGE
