"""
Web 模块集中清单。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.core.auth_contract.authorization_policy_contract import (
    RouteAuthorizationRequirement,
)
from src.core.http_contract.web_bundle_contract import ApplicationModuleName
from src.domain.auth.admin_route_authorization_policy import (
    BUSINESS_ADMIN_AUTHORIZATION_REQUIREMENTS,
    OPS_ONLY_AUTHORIZATION_REQUIREMENTS,
)

WEB_MODULE_MANIFEST_SCHEMA_VERSION: Final = "1.0"
ROUTER_PROVIDER_KIND: Final = "router_provider"
HEALTH_PROVIDER_IMPORT_PATH = (
    "src.api.endpoint_health_probe.route_health_probe.HealthProbeBundleProvider"
)
AUTH_PROVIDER_IMPORT_PATH = (
    "src.api.endpoint_auth_access.route_auth_access.AuthAccessBundleProvider"
)
SYSTEM_PROVIDER_IMPORT_PATH = (
    "src.api.endpoint_system_overview.route_system_overview.SystemOverviewBundleProvider"
)
SECURITY_PROTECTION_PROVIDER_IMPORT_PATH = "src.api.endpoint_security_protection.route_security_protection.SecurityProtectionBundleProvider"
ADMIN_TASK_PROVIDER_IMPORT_PATH = (
    "src.api.endpoint_admin_task.route_admin_task.AdminTaskBundleProvider"
)
ADMIN_SETTINGS_PROVIDER_IMPORT_PATH = (
    "src.api.endpoint_admin_settings.route_admin_settings.AdminSettingsBundleProvider"
)
ADMIN_LOG_PROVIDER_IMPORT_PATH = "src.api.endpoint_admin_log.route_admin_log.AdminLogBundleProvider"
ADMIN_IDENTITY_PROVIDER_IMPORT_PATH = (
    "src.api.endpoint_admin_identity.route_admin_identity.AdminIdentityBundleProvider"
)
ADMIN_AUDIT_PROVIDER_IMPORT_PATH = (
    "src.api.endpoint_admin_audit.route_admin_audit.AdminAuditBundleProvider"
)
CODEX_CONTROL_PROVIDER_IMPORT_PATH = (
    "src.api.endpoint_codex_control.route_codex_host.CodexControlBundleProvider"
)
CODEX_ADMIN_PROVIDER_IMPORT_PATH = (
    "src.api.endpoint_codex_admin.route_codex_admin.CodexAdminBundleProvider"
)
CODEX_AGENT_GATEWAY_PROVIDER_IMPORT_PATH = (
    "src.api.endpoint_codex_agent.route_codex_agent_connect.CodexAgentGatewayBundleProvider"
)
HEALTH_ROUTE_TAG = "health"
AUTH_ROUTE_TAG = "auth"
SYSTEM_ROUTE_TAG = "system"
SECURITY_PROTECTION_ROUTE_TAG = "security_protection"
ADMIN_TASK_ROUTE_TAG = "admin_task"
ADMIN_SETTINGS_ROUTE_TAG = "admin_settings"
ADMIN_LOG_ROUTE_TAG = "admin_log"
ADMIN_IDENTITY_ROUTE_TAG = "admin_identity"
ADMIN_AUDIT_ROUTE_TAG = "admin_audit"
CODEX_CONTROL_ROUTE_TAG = "codex"
CODEX_ADMIN_ROUTE_TAG = "codex_admin"
CODEX_AGENT_GATEWAY_ROUTE_TAG = "codex_agent_gateway"
ADMIN_BOUNDARY_POLICY_MISMATCH_MESSAGE = "Web 模块清单的后台边界策略与集中授权要求不一致。"


class AdminBoundaryPolicy(StrEnum):
    """
    后台边界策略枚举。
    """

    PUBLIC = "public"
    BUSINESS_ADMIN = "business_admin"
    OPS_ONLY = "ops_only"
    AUTHENTICATED_USER = "authenticated_user"


class AuthenticationMode(StrEnum):
    """Web 模块入口使用的认证链。"""

    NONE = "none"
    USER_BEARER = "user_bearer"
    AGENT_DEVICE = "agent_device"


BUSINESS_ADMIN_MODULE_NAMES: tuple[str, ...] = (
    ApplicationModuleName.ADMIN_IDENTITY.value,
    ApplicationModuleName.ADMIN_AUDIT.value,
)
OPS_ONLY_MODULE_NAMES: tuple[str, ...] = (
    ApplicationModuleName.ADMIN_TASK.value,
    ApplicationModuleName.ADMIN_SETTINGS.value,
    ApplicationModuleName.ADMIN_LOG.value,
    ApplicationModuleName.SECURITY_PROTECTION.value,
    ApplicationModuleName.SYSTEM_OVERVIEW.value,
)


class WebModuleHeader(BaseModel):
    """
    Web 模块公共头。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["router_provider"] = ROUTER_PROVIDER_KIND
    schema_version: Literal["1.0"] = WEB_MODULE_MANIFEST_SCHEMA_VERSION
    module_name: str
    enabled: bool = True


class RouterProviderDetail(BaseModel):
    """
    路由提供者扩展。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["router_provider"] = ROUTER_PROVIDER_KIND
    schema_version: Literal["1.0"] = WEB_MODULE_MANIFEST_SCHEMA_VERSION
    provider_import_path: str
    route_tags: list[str]
    admin_boundary_policy: AdminBoundaryPolicy = AdminBoundaryPolicy.PUBLIC
    authentication_mode: AuthenticationMode = AuthenticationMode.NONE


WebModuleManifestDetail = Annotated[
    RouterProviderDetail,
    Field(discriminator="kind"),
]


class WebModuleManifestEnvelope(BaseModel):
    """
    Web 模块清单信封。
    """

    model_config = ConfigDict(extra="forbid")

    header: WebModuleHeader
    detail: WebModuleManifestDetail

    @model_validator(mode="after")
    def validate_manifest_contract(self) -> WebModuleManifestEnvelope:
        """
        校验 Web 模块清单公共头与扩展字段一致。
        """

        if self.header.kind != self.detail.kind:
            raise ValueError("Web 模块 header.kind 必须与 detail.kind 一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("Web 模块 header.schema_version 必须与 detail.schema_version 一致。")
        return self


class WebModuleManifestRegistry:
    """
    Web 模块清单注册表。
    """

    def __init__(
        self,
        manifest_entries: list[WebModuleManifestEnvelope] | None = None,
    ) -> None:
        """
        初始化 Web 模块清单注册表。
        """

        self._manifest_entries = manifest_entries

    def list_entries(self) -> list[WebModuleManifestEnvelope]:
        """
        列出内置 Web 模块清单。
        """

        if self._manifest_entries is not None:
            return list(self._manifest_entries)
        return [
            WebModuleManifestEnvelope(
                header=WebModuleHeader(module_name=ApplicationModuleName.HEALTH_PROBE.value),
                detail=RouterProviderDetail(
                    provider_import_path=HEALTH_PROVIDER_IMPORT_PATH,
                    route_tags=[HEALTH_ROUTE_TAG],
                ),
            ),
            WebModuleManifestEnvelope(
                header=WebModuleHeader(module_name=ApplicationModuleName.CODEX_CONTROL.value),
                detail=RouterProviderDetail(
                    provider_import_path=CODEX_CONTROL_PROVIDER_IMPORT_PATH,
                    route_tags=[CODEX_CONTROL_ROUTE_TAG],
                    admin_boundary_policy=AdminBoundaryPolicy.AUTHENTICATED_USER,
                    authentication_mode=AuthenticationMode.USER_BEARER,
                ),
            ),
            WebModuleManifestEnvelope(
                header=WebModuleHeader(module_name=ApplicationModuleName.CODEX_ADMIN.value),
                detail=RouterProviderDetail(
                    provider_import_path=CODEX_ADMIN_PROVIDER_IMPORT_PATH,
                    route_tags=[CODEX_ADMIN_ROUTE_TAG],
                    admin_boundary_policy=AdminBoundaryPolicy.AUTHENTICATED_USER,
                    authentication_mode=AuthenticationMode.USER_BEARER,
                ),
            ),
            WebModuleManifestEnvelope(
                header=WebModuleHeader(module_name=ApplicationModuleName.CODEX_AGENT_GATEWAY.value),
                detail=RouterProviderDetail(
                    provider_import_path=CODEX_AGENT_GATEWAY_PROVIDER_IMPORT_PATH,
                    route_tags=[CODEX_AGENT_GATEWAY_ROUTE_TAG],
                    admin_boundary_policy=AdminBoundaryPolicy.PUBLIC,
                    authentication_mode=AuthenticationMode.AGENT_DEVICE,
                ),
            ),
            WebModuleManifestEnvelope(
                header=WebModuleHeader(module_name=ApplicationModuleName.AUTH_ACCESS.value),
                detail=RouterProviderDetail(
                    provider_import_path=AUTH_PROVIDER_IMPORT_PATH,
                    route_tags=[AUTH_ROUTE_TAG],
                ),
            ),
            WebModuleManifestEnvelope(
                header=WebModuleHeader(module_name=ApplicationModuleName.SYSTEM_OVERVIEW.value),
                detail=RouterProviderDetail(
                    provider_import_path=SYSTEM_PROVIDER_IMPORT_PATH,
                    route_tags=[SYSTEM_ROUTE_TAG],
                    admin_boundary_policy=AdminBoundaryPolicy.OPS_ONLY,
                ),
            ),
            WebModuleManifestEnvelope(
                header=WebModuleHeader(module_name=ApplicationModuleName.SECURITY_PROTECTION.value),
                detail=RouterProviderDetail(
                    provider_import_path=SECURITY_PROTECTION_PROVIDER_IMPORT_PATH,
                    route_tags=[SECURITY_PROTECTION_ROUTE_TAG],
                    admin_boundary_policy=AdminBoundaryPolicy.OPS_ONLY,
                ),
            ),
            WebModuleManifestEnvelope(
                header=WebModuleHeader(module_name=ApplicationModuleName.ADMIN_TASK.value),
                detail=RouterProviderDetail(
                    provider_import_path=ADMIN_TASK_PROVIDER_IMPORT_PATH,
                    route_tags=[ADMIN_TASK_ROUTE_TAG],
                    admin_boundary_policy=AdminBoundaryPolicy.OPS_ONLY,
                ),
            ),
            WebModuleManifestEnvelope(
                header=WebModuleHeader(module_name=ApplicationModuleName.ADMIN_SETTINGS.value),
                detail=RouterProviderDetail(
                    provider_import_path=ADMIN_SETTINGS_PROVIDER_IMPORT_PATH,
                    route_tags=[ADMIN_SETTINGS_ROUTE_TAG],
                    admin_boundary_policy=AdminBoundaryPolicy.OPS_ONLY,
                ),
            ),
            WebModuleManifestEnvelope(
                header=WebModuleHeader(module_name=ApplicationModuleName.ADMIN_LOG.value),
                detail=RouterProviderDetail(
                    provider_import_path=ADMIN_LOG_PROVIDER_IMPORT_PATH,
                    route_tags=[ADMIN_LOG_ROUTE_TAG],
                    admin_boundary_policy=AdminBoundaryPolicy.OPS_ONLY,
                ),
            ),
            WebModuleManifestEnvelope(
                header=WebModuleHeader(module_name=ApplicationModuleName.ADMIN_IDENTITY.value),
                detail=RouterProviderDetail(
                    provider_import_path=ADMIN_IDENTITY_PROVIDER_IMPORT_PATH,
                    route_tags=[ADMIN_IDENTITY_ROUTE_TAG],
                    admin_boundary_policy=AdminBoundaryPolicy.BUSINESS_ADMIN,
                ),
            ),
            WebModuleManifestEnvelope(
                header=WebModuleHeader(module_name=ApplicationModuleName.ADMIN_AUDIT.value),
                detail=RouterProviderDetail(
                    provider_import_path=ADMIN_AUDIT_PROVIDER_IMPORT_PATH,
                    route_tags=[ADMIN_AUDIT_ROUTE_TAG],
                    admin_boundary_policy=AdminBoundaryPolicy.BUSINESS_ADMIN,
                ),
            ),
        ]

    def list_business_admin_module_names(self) -> list[str]:
        """
        列出业务后台模块名。
        """

        return list(BUSINESS_ADMIN_MODULE_NAMES)

    def list_ops_only_module_names(self) -> list[str]:
        """
        列出运维控制面模块名。
        """

        return list(OPS_ONLY_MODULE_NAMES)

    def validate_admin_boundary_authorization(self) -> None:
        """
        校验后台边界策略与集中授权事实源一致。
        """

        if self._collect_module_names(AdminBoundaryPolicy.BUSINESS_ADMIN) != set(
            BUSINESS_ADMIN_MODULE_NAMES
        ):
            raise ValueError(ADMIN_BOUNDARY_POLICY_MISMATCH_MESSAGE)
        if self._collect_module_names(AdminBoundaryPolicy.OPS_ONLY) != set(OPS_ONLY_MODULE_NAMES):
            raise ValueError(ADMIN_BOUNDARY_POLICY_MISMATCH_MESSAGE)
        if len(BUSINESS_ADMIN_AUTHORIZATION_REQUIREMENTS) == 0:
            raise ValueError(ADMIN_BOUNDARY_POLICY_MISMATCH_MESSAGE)
        if len(OPS_ONLY_AUTHORIZATION_REQUIREMENTS) == 0:
            raise ValueError(ADMIN_BOUNDARY_POLICY_MISMATCH_MESSAGE)

    def list_admin_authorization_requirements(
        self,
    ) -> list[RouteAuthorizationRequirement]:
        """
        列出后台模块集中授权要求。
        """

        return [
            *BUSINESS_ADMIN_AUTHORIZATION_REQUIREMENTS,
            *OPS_ONLY_AUTHORIZATION_REQUIREMENTS,
        ]

    def _collect_module_names(self, policy: AdminBoundaryPolicy) -> set[str]:
        """
        收集指定后台边界策略下的模块名。
        """

        return {
            entry.header.module_name
            for entry in self.list_entries()
            if entry.detail.admin_boundary_policy == policy
        }
