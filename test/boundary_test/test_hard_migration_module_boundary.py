"""热点模块硬迁移边界测试模块。"""

from __future__ import annotations

from pathlib import Path

from src.api.endpoint_admin_identity.route_admin_identity import AdminIdentityRouteCatalog
from src.api.endpoint_admin_identity.route_admin_role import AdminRoleRouteCatalog
from src.api.endpoint_admin_identity.route_admin_scope import AdminScopeRouteCatalog
from src.api.endpoint_admin_identity.route_admin_user import AdminUserRouteCatalog
from src.infrastructure.persistence.repository_impl.admin_identity_repository_impl import (
    AdminIdentityRepositoryImpl,
)
from src.infrastructure.persistence.repository_impl.admin_role_repository import (
    AdminRoleRepository,
)
from src.infrastructure.persistence.repository_impl.admin_scope_repository import (
    AdminScopeRepository,
)
from src.infrastructure.persistence.repository_impl.admin_user_repository import (
    AdminUserRepository,
)
from src.infrastructure.resource_mount.admin_identity_resource_facade import (
    AdminIdentityResourceFacade,
)
from src.infrastructure.resource_mount.admin_security_resource_facade import (
    AdminSecurityResourceFacade,
)
from src.infrastructure.resource_mount.logging_resource_facade import LoggingResourceFacade
from src.infrastructure.resource_mount.shared_resource_accessor import SharedResourceAccessor
from src.infrastructure.resource_mount.task_resource_facade import TaskResourceFacade
from src.infrastructure.settings.app_settings_loader import AppSettingsLoader
from src.infrastructure.shared_resource_mount import SharedResourceMount

LEGACY_ADMIN_IDENTITY_CONTRACT_PATH = Path(
    "src/api/endpoint_admin_identity/contract_admin_identity.py"
)
LEGACY_SETTINGS_ROUTE_METHOD_NAME = "_route_file_content"


class TestHardMigrationModuleBoundary:
    """热点模块硬迁移边界测试集合。"""

    def test_admin_identity_when_split_should_not_keep_legacy_contract(self) -> None:
        """验证身份契约完成硬切换且路由按三个资源域组合。"""

        assert LEGACY_ADMIN_IDENTITY_CONTRACT_PATH.exists() is False
        assert issubclass(AdminIdentityRouteCatalog, AdminScopeRouteCatalog)
        assert issubclass(AdminIdentityRouteCatalog, AdminRoleRouteCatalog)
        assert issubclass(AdminIdentityRouteCatalog, AdminUserRouteCatalog)

    def test_admin_identity_repository_should_compose_three_domain_repositories(
        self,
    ) -> None:
        """验证管理员身份仓储仅组合 scope、role 和 user 职责。"""

        assert issubclass(AdminIdentityRepositoryImpl, AdminScopeRepository)
        assert issubclass(AdminIdentityRepositoryImpl, AdminRoleRepository)
        assert issubclass(AdminIdentityRepositoryImpl, AdminUserRepository)

    def test_shared_resource_mount_should_remain_thin_composition_entry(self) -> None:
        """验证共享资源挂载入口只组合稳定资源门面。"""

        assert SharedResourceMount.__bases__ == (
            SharedResourceAccessor,
            AdminIdentityResourceFacade,
            AdminSecurityResourceFacade,
            TaskResourceFacade,
            LoggingResourceFacade,
        )
        assert set(SharedResourceMount.__dict__) == {
            "__module__",
            "__doc__",
        }

    def test_settings_loader_should_not_keep_legacy_routing_method(self) -> None:
        """验证配置加载器只保留统一解析入口。"""

        assert not hasattr(AppSettingsLoader, LEGACY_SETTINGS_ROUTE_METHOD_NAME)
