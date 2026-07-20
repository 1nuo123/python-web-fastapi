"""
FastAPI路由组装器基础设施模块。
"""

from __future__ import annotations

from fastapi import FastAPI

from src.core.http_contract.web_bundle_contract import WebBundle

ROOT_API_PREFIX = ""
MODULE_NAME_LIST_SEPARATOR = ", "
ENABLED_MODULE_NOT_MOUNTED_MESSAGE_TEMPLATE = "启用的 Web 模块未完成路由挂载: {module_names}。"


class FastApiRouteComposer:
    """
    FastAPI路由组装器类型，用于封装当前模块中的相关行为或状态。
    """

    def compose(
        self,
        *,
        app: FastAPI,
        bundles: list[WebBundle],
        enabled_modules: list[str],
        api_prefix: str,
    ) -> list[str]:
        """
        处理组装。

        :param app: 当前 FastAPI 或 ASGI 应用实例。约束：需符合 ``FastAPI`` 注解。
        :type app: FastAPI
        :param bundles: 待挂载的 Web 资源集合。约束：需符合 ``list[WebBundle]`` 注解。
        :type bundles: list[WebBundle]
        :param enabled_modules: 需要启用的模块名列表。约束：需符合 ``list[str]`` 注解。
        :type enabled_modules: list[str]
        :param api_prefix: 接口统一前缀。约束：需符合 ``str`` 注解。
        :type api_prefix: str
        :returns: 返回按实现构造的列表结果。
        :rtype: list[str]
        """

        mounted_modules: list[str] = []
        enabled_module_set = set(enabled_modules)
        for bundle in bundles:
            module_name = str(bundle.module_name)
            if module_name not in enabled_module_set:
                continue
            app.include_router(bundle.router, prefix=api_prefix or ROOT_API_PREFIX)
            mounted_modules.append(module_name)
        missing_module_names = [
            module_name
            for module_name in enabled_modules
            if module_name not in set(mounted_modules)
        ]
        if len(missing_module_names) > 0:
            raise ValueError(
                ENABLED_MODULE_NOT_MOUNTED_MESSAGE_TEMPLATE.format(
                    module_names=MODULE_NAME_LIST_SEPARATOR.join(missing_module_names)
                )
            )
        return mounted_modules
