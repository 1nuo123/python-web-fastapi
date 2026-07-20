"""
Web 模块清单单元测试。
"""

from __future__ import annotations

import pytest

from src.api.web_bundle_catalog import (
    ENABLED_MODULES_CONFIG_PATH,
    PROVIDER_ROUTE_TAGS_MISMATCH_MESSAGE,
    WebBundleCatalog,
)
from src.api.web_module_manifest import (
    ADMIN_AUDIT_PROVIDER_IMPORT_PATH,
    ADMIN_AUDIT_ROUTE_TAG,
    ADMIN_LOG_PROVIDER_IMPORT_PATH,
    ADMIN_LOG_ROUTE_TAG,
    ADMIN_SETTINGS_PROVIDER_IMPORT_PATH,
    ADMIN_SETTINGS_ROUTE_TAG,
    ADMIN_TASK_PROVIDER_IMPORT_PATH,
    ADMIN_TASK_ROUTE_TAG,
    BUSINESS_ADMIN_MODULE_NAMES,
    HEALTH_PROVIDER_IMPORT_PATH,
    OPS_ONLY_MODULE_NAMES,
    ROUTER_PROVIDER_KIND,
    AdminBoundaryPolicy,
    RouterProviderDetail,
    WebModuleHeader,
    WebModuleManifestEnvelope,
    WebModuleManifestRegistry,
)
from src.core.http_contract.web_bundle_contract import ApplicationModuleName
from src.domain.auth.admin_route_authorization_policy import (
    BUSINESS_ADMIN_AUTHORIZATION_REQUIREMENTS,
    OPS_ONLY_AUTHORIZATION_REQUIREMENTS,
)
from src.domain.auth.auth_scope_code import AuthScopeCode

UNKNOWN_MODULE_NAME = "unknown_module"
MISSING_PROVIDER_IMPORT_PATH = "src.api.missing_module.MissingProvider"
UNEXPECTED_ROUTE_TAG = "unexpected_route_tag"
OPS_ONLY_SCOPE_CODES = {
    AuthScopeCode.SYSTEM_READ,
    AuthScopeCode.TASK_DISPATCH,
}
ADMIN_MODULE_MANIFEST_EXPECTATIONS = {
    ApplicationModuleName.ADMIN_TASK.value: (
        ADMIN_TASK_PROVIDER_IMPORT_PATH,
        ADMIN_TASK_ROUTE_TAG,
    ),
    ApplicationModuleName.ADMIN_SETTINGS.value: (
        ADMIN_SETTINGS_PROVIDER_IMPORT_PATH,
        ADMIN_SETTINGS_ROUTE_TAG,
    ),
    ApplicationModuleName.ADMIN_LOG.value: (
        ADMIN_LOG_PROVIDER_IMPORT_PATH,
        ADMIN_LOG_ROUTE_TAG,
    ),
    ApplicationModuleName.ADMIN_AUDIT.value: (
        ADMIN_AUDIT_PROVIDER_IMPORT_PATH,
        ADMIN_AUDIT_ROUTE_TAG,
    ),
}


class TestWebModuleManifestUnit:
    """
    Web 模块清单单元测试集合。
    """

    def test_manifest_registry_should_list_builtin_modules(self) -> None:
        """
        验证内置模块应登记到集中清单。
        """

        module_names = [
            entry.header.module_name for entry in WebModuleManifestRegistry().list_entries()
        ]

        assert ApplicationModuleName.HEALTH_PROBE.value in module_names
        assert ApplicationModuleName.AUTH_ACCESS.value in module_names
        assert ApplicationModuleName.SYSTEM_OVERVIEW.value in module_names

    def test_manifest_registry_should_include_admin_module_entries(self) -> None:
        """
        验证管理员模块应登记明确 provider 与路由标签。
        """

        entries = {
            entry.header.module_name: entry for entry in WebModuleManifestRegistry().list_entries()
        }

        for module_name, (
            provider_import_path,
            route_tag,
        ) in ADMIN_MODULE_MANIFEST_EXPECTATIONS.items():
            entry = entries[module_name]
            assert entry.detail.provider_import_path == provider_import_path
            assert entry.detail.route_tags == [route_tag]

    def test_manifest_registry_should_mark_admin_boundary_policy(self) -> None:
        """
        验证 Web 模块清单明确业务后台与 ops-only 边界。
        """

        entries = {
            entry.header.module_name: entry for entry in WebModuleManifestRegistry().list_entries()
        }

        assert set(WebModuleManifestRegistry().list_business_admin_module_names()) == set(
            BUSINESS_ADMIN_MODULE_NAMES
        )
        assert set(WebModuleManifestRegistry().list_ops_only_module_names()) == set(
            OPS_ONLY_MODULE_NAMES
        )
        for module_name in BUSINESS_ADMIN_MODULE_NAMES:
            assert (
                entries[module_name].detail.admin_boundary_policy
                == AdminBoundaryPolicy.BUSINESS_ADMIN
            )
        for module_name in OPS_ONLY_MODULE_NAMES:
            assert entries[module_name].detail.admin_boundary_policy == AdminBoundaryPolicy.OPS_ONLY

    def test_business_authorization_should_not_use_ops_only_scopes(self) -> None:
        """
        验证业务后台页面入口权限不使用运维控制面 scope。
        """

        business_scope_codes = {
            scope
            for requirement in BUSINESS_ADMIN_AUTHORIZATION_REQUIREMENTS
            for scope in requirement.required_scopes
        }
        ops_scope_codes = {
            scope
            for requirement in OPS_ONLY_AUTHORIZATION_REQUIREMENTS
            for scope in requirement.required_scopes
        }

        assert business_scope_codes.isdisjoint(OPS_ONLY_SCOPE_CODES)
        assert OPS_ONLY_SCOPE_CODES.issubset(ops_scope_codes)

    def test_manifest_boundary_policy_should_match_authorization_requirements(
        self,
    ) -> None:
        """
        验证后台边界策略与集中授权事实源保持一致。
        """

        registry = WebModuleManifestRegistry()

        registry.validate_admin_boundary_authorization()

        assert len(registry.list_admin_authorization_requirements()) == (
            len(BUSINESS_ADMIN_AUTHORIZATION_REQUIREMENTS)
            + len(OPS_ONLY_AUTHORIZATION_REQUIREMENTS)
        )

    def test_catalog_when_manifest_contains_single_provider_should_build_bundle(self) -> None:
        """
        验证只修改 manifest 即可发现 provider。
        """

        envelopes = WebBundleCatalog(
            manifest_entries=[self._build_manifest_entry(ApplicationModuleName.HEALTH_PROBE.value)]
        ).list_provider_envelopes()

        assert [envelope.header.module_name for envelope in envelopes] == [
            ApplicationModuleName.HEALTH_PROBE.value
        ]

    def test_catalog_should_list_manifest_module_names(self) -> None:
        """
        验证目录应列出 manifest 中声明的模块名。
        """

        catalog = WebBundleCatalog(
            manifest_entries=[self._build_manifest_entry(ApplicationModuleName.HEALTH_PROBE.value)]
        )

        assert catalog.list_module_names() == [ApplicationModuleName.HEALTH_PROBE.value]

    def test_catalog_when_enabled_modules_contains_unknown_should_fail(self) -> None:
        """
        验证启用模块包含未知值应失败。
        """

        catalog = WebBundleCatalog(
            manifest_entries=[self._build_manifest_entry(ApplicationModuleName.HEALTH_PROBE.value)]
        )

        with pytest.raises(ValueError) as fault:
            catalog.validate_enabled_modules(
                [ApplicationModuleName.HEALTH_PROBE.value, UNKNOWN_MODULE_NAME]
            )

        error_message = str(fault.value)
        assert ENABLED_MODULES_CONFIG_PATH in error_message
        assert UNKNOWN_MODULE_NAME in error_message
        assert ApplicationModuleName.HEALTH_PROBE.value in error_message

    def test_catalog_when_manifest_contains_duplicate_module_should_fail(self) -> None:
        """
        验证重复模块名应失败。
        """

        entry = self._build_manifest_entry(ApplicationModuleName.HEALTH_PROBE.value)

        with pytest.raises(ValueError, match="不允许重复模块名"):
            WebBundleCatalog(manifest_entries=[entry, entry])

    def test_catalog_when_provider_missing_should_fail(self) -> None:
        """
        验证 provider 缺失应失败。
        """

        entry = self._build_manifest_entry(
            ApplicationModuleName.HEALTH_PROBE.value,
            provider_import_path=MISSING_PROVIDER_IMPORT_PATH,
        )

        with pytest.raises(ValueError, match="provider 导入失败"):
            WebBundleCatalog(manifest_entries=[entry]).list_provider_envelopes()

    def test_catalog_when_module_disabled_should_not_include_provider(self) -> None:
        """
        验证禁用模块不应挂载路由。
        """

        entry = self._build_manifest_entry(
            ApplicationModuleName.HEALTH_PROBE.value,
            enabled=False,
        )

        assert WebBundleCatalog(manifest_entries=[entry]).build() == []

    def test_catalog_when_disabled_module_configured_enabled_should_fail(self) -> None:
        """
        验证配置启用已禁用 manifest 模块时应失败。
        """

        module_name = ApplicationModuleName.HEALTH_PROBE.value
        entry = self._build_manifest_entry(module_name, enabled=False)
        catalog = WebBundleCatalog(manifest_entries=[entry])

        with pytest.raises(ValueError) as fault:
            catalog.validate_enabled_modules([module_name])

        assert ENABLED_MODULES_CONFIG_PATH in str(fault.value)
        assert module_name in str(fault.value)

    def test_catalog_when_provider_module_mismatch_should_fail(self) -> None:
        """
        验证 provider 与 manifest 模块名不一致应失败。
        """

        entry = self._build_manifest_entry(UNKNOWN_MODULE_NAME)

        with pytest.raises(ValueError, match="module_name 不一致"):
            WebBundleCatalog(manifest_entries=[entry]).list_provider_envelopes()

    def test_catalog_when_provider_route_tags_mismatch_should_fail(self) -> None:
        """
        验证 provider 路由标签与 manifest 不一致时应失败。
        """

        entry = self._build_manifest_entry(
            ApplicationModuleName.HEALTH_PROBE.value,
            route_tags=[UNEXPECTED_ROUTE_TAG],
        )

        with pytest.raises(ValueError) as fault:
            WebBundleCatalog(manifest_entries=[entry]).list_provider_envelopes()

        assert str(fault.value) == PROVIDER_ROUTE_TAGS_MISMATCH_MESSAGE

    def _build_manifest_entry(
        self,
        module_name: str,
        *,
        provider_import_path: str = HEALTH_PROVIDER_IMPORT_PATH,
        enabled: bool = True,
        route_tags: list[str] | None = None,
    ) -> WebModuleManifestEnvelope:
        """
        构建测试用 Web 模块清单条目。
        """

        return WebModuleManifestEnvelope(
            header=WebModuleHeader(
                kind=ROUTER_PROVIDER_KIND,
                module_name=module_name,
                enabled=enabled,
            ),
            detail=RouterProviderDetail(
                provider_import_path=provider_import_path,
                route_tags=route_tags or ["health"],
            ),
        )
