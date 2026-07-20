"""
FastAPIOpenAPI表面基础设施模块。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

if TYPE_CHECKING:
    from src.infrastructure.shared_resource_mount import SharedResourceMount

OPENAPI_DESCRIPTION = "FastAPI Web 基础设施骨架。"
OpenApiDocumentValue = (
    str
    | int
    | float
    | bool
    | None
    | list["OpenApiDocumentValue"]
    | dict[str, "OpenApiDocumentValue"]
)
OpenApiDocument = dict[str, OpenApiDocumentValue]


class FastApiOpenApiSurface:
    """
    FastAPIOpenAPI表面类型，用于封装当前模块中的相关行为或状态。
    """

    def __init__(
        self,
        *,
        app: FastAPI,
        resource_mount: SharedResourceMount,
    ) -> None:
        """
        初始化FastAPIOpenAPI表面。

        :param app: 当前 FastAPI 或 ASGI 应用实例。约束：需符合 ``FastAPI`` 注解。
        :type app: FastAPI
        :param resource_mount: 共享资源挂载点。
        :type resource_mount: SharedResourceMount
        :returns: 无返回值。
        :rtype: None
        """

        self._app = app
        self._resource_mount = resource_mount

    def bind(self) -> None:
        """
        处理绑定。

        :returns: 无返回值。
        :rtype: None
        """

        if not self._resource_mount.read_runtime_bundle().settings.app.enable_openapi:
            return
        object.__setattr__(self._app, "openapi", self.build_openapi)

    def build_openapi(self) -> OpenApiDocument:
        """
        构建OpenAPI。

        :returns: 返回当前步骤新建的对象。
        :rtype: OpenApiDocument
        """

        if self._app.openapi_schema is not None:
            return self._app.openapi_schema
        settings = self._resource_mount.read_runtime_bundle().settings
        self._app.openapi_schema = get_openapi(
            title=settings.app.name,
            version=settings.app.version,
            description=OPENAPI_DESCRIPTION,
            routes=self._app.routes,
        )
        return self._app.openapi_schema
