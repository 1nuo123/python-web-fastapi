"""
FastAPI生命周期编排器基础设施模块。
"""

from __future__ import annotations

from types import TracebackType

from fastapi import FastAPI

from src.infrastructure.shared_resource_mount import SharedResourceMount


class ApplicationLifespanContext:
    """
    应用生命周期上下文对象，用于承载上下文状态。
    """

    def __init__(self, *, app: FastAPI, resource_mount: SharedResourceMount) -> None:
        """
        初始化应用生命周期上下文。

        :param app: 当前 FastAPI 或 ASGI 应用实例。约束：需符合 ``FastAPI`` 注解。
        :type app: FastAPI
        :param resource_mount: 共享资源挂载点，用于访问数据库、缓存、消息和鉴权能力。约束：需符合 ``SharedResourceMount`` 注解。
        :type resource_mount: SharedResourceMount
        :returns: 无返回值。
        :rtype: None
        """

        self._app = app
        self._resource_mount = resource_mount

    async def __aenter__(self) -> None:
        """
        执行异步上下文生命周期步骤。

        :returns: 无返回值。
        :rtype: None
        """

        try:
            self._resource_mount.startup()
            await self._resource_mount.startup_streaming()
        except Exception:
            self._app.state.ready = False
            await self._resource_mount.shutdown_streaming()
            self._resource_mount.shutdown()
            raise
        self._app.state.ready = True
        return None

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        """
        执行异步上下文生命周期步骤。

        :param exc_type: 异步上下文退出时的异常类型。
        :type exc_type: type[BaseException] | None
        :param exc: 当前捕获到的异常对象。
        :type exc: BaseException | None
        :param traceback: 异步上下文退出时的异常回溯对象。
        :type traceback: TracebackType | None
        :returns: 返回布尔判断结果。
        :rtype: bool
        """

        self._app.state.ready = False
        await self._resource_mount.shutdown_streaming()
        self._resource_mount.shutdown()
        return False


class FastApiLifespanOrchestrator:
    """
    FastAPI生命周期编排器类型，用于封装当前模块中的相关行为或状态。
    """

    def __init__(self, resource_mount: SharedResourceMount) -> None:
        """
        初始化FastAPI生命周期编排器。

        :param resource_mount: 共享资源挂载点，用于访问数据库、缓存、消息和鉴权能力。约束：需符合 ``SharedResourceMount`` 注解。
        :type resource_mount: SharedResourceMount
        :returns: 无返回值。
        :rtype: None
        """

        self._resource_mount = resource_mount

    def __call__(self, app: FastAPI) -> ApplicationLifespanContext:
        """
        执行当前可调用对象。

        :param app: 当前 FastAPI 或 ASGI 应用实例。约束：需符合 ``FastAPI`` 注解。
        :type app: FastAPI
        :returns: 返回当前操作结果。
        :rtype: ApplicationLifespanContext
        """

        return ApplicationLifespanContext(app=app, resource_mount=self._resource_mount)
