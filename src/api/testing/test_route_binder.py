"""
API 测试路由绑定工具模块。
"""

from __future__ import annotations

from fastapi import FastAPI


class TestRouteBinder:
    """
    测试路由绑定器，集中提供测试专用的路由挂载能力。
    """

    def __init__(self, app: FastAPI) -> None:
        """
        初始化测试路由绑定器。

        :param app: 当前 FastAPI 应用。
        :type app: FastAPI
        """

        self._app = app

    def bind_unexpected_exception_route(self, *, path: str, message: str) -> None:
        """
        绑定触发未预期异常的测试路由。

        :param path: 测试路由路径。
        :type path: str
        :param message: 异常消息。
        :type message: str
        """

        def raise_unexpected_exception() -> None:
            raise RuntimeError(message)

        self._app.add_api_route(
            path,
            raise_unexpected_exception,
            methods=["GET"],
        )
