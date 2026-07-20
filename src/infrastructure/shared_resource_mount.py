"""共享资源挂载点组合入口。"""

from __future__ import annotations

from src.infrastructure.resource_mount.admin_identity_resource_facade import (
    AdminIdentityResourceFacade,
)
from src.infrastructure.resource_mount.admin_security_resource_facade import (
    AdminSecurityResourceFacade,
)
from src.infrastructure.resource_mount.logging_resource_facade import LoggingResourceFacade
from src.infrastructure.resource_mount.shared_resource_accessor import SharedResourceAccessor
from src.infrastructure.resource_mount.task_resource_facade import TaskResourceFacade


class SharedResourceMount(
    SharedResourceAccessor,
    AdminIdentityResourceFacade,
    AdminSecurityResourceFacade,
    TaskResourceFacade,
    LoggingResourceFacade,
):
    """组合各资源域门面的稳定挂载入口。"""
