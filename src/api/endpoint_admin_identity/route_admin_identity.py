"""管理员身份路由组合入口。"""

from __future__ import annotations

from src.api.endpoint_admin_identity.route_admin_identity_common import AdminIdentityRouteSupport
from src.api.endpoint_admin_identity.route_admin_role import AdminRoleRouteCatalog
from src.api.endpoint_admin_identity.route_admin_scope import AdminScopeRouteCatalog
from src.api.endpoint_admin_identity.route_admin_user import AdminUserRouteCatalog
from src.api.web_bundle_catalog import (
    WebBundleProvider,
    WebBundleProviderDetail,
    WebBundleProviderEnvelope,
    WebBundleProviderHeader,
)
from src.core.http_contract.web_bundle_contract import ApplicationModuleName, WebBundle


class AdminIdentityRouteCatalog(
    AdminScopeRouteCatalog,
    AdminRoleRouteCatalog,
    AdminUserRouteCatalog,
):
    """管理员身份路由组合目录。"""

    def __init__(self) -> None:
        """初始化路由组合目录。

        :returns: 无返回值。
        :rtype: None
        """

        AdminIdentityRouteSupport.__init__(self)
        self._bind_scope_routes()
        self._bind_role_routes()
        self._bind_user_routes()


class AdminIdentityBundleProvider(WebBundleProvider):
    """
    管理员身份模块提供者。
    """

    module_name = ApplicationModuleName.ADMIN_IDENTITY.value

    def provide(self) -> WebBundleProviderEnvelope:
        """
        提供管理员身份模块信封。
        """

        return WebBundleProviderEnvelope(
            header=WebBundleProviderHeader(module_name=self.module_name),
            detail=WebBundleProviderDetail(provider_name=self.__class__.__name__),
            bundle=WebBundle(
                module_name=self.module_name,
                router=AdminIdentityRouteCatalog().router,
            ),
        )
