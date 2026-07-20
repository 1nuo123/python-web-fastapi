"""
Web 集合目录 API 接口层模块。
"""

from __future__ import annotations

import importlib
from typing import Annotated, ClassVar, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.api.web_module_manifest import (
    WebModuleManifestEnvelope,
    WebModuleManifestRegistry,
)
from src.core.http_contract.web_bundle_contract import WebBundle

WEB_BUNDLE_PROVIDER_SCHEMA_VERSION: Final = "1.0"
WEB_BUNDLE_PROVIDER_HEADER_KIND: Final = "web_bundle_provider_header"
WEB_BUNDLE_PROVIDER_DETAIL_KIND: Final = "web_bundle_provider_detail"
PROVIDER_IMPORT_PATH_SEPARATOR = "."
PROVIDER_IMPORT_PATH_INVALID_MESSAGE = "Web 模块 provider 导入路径无效。"
PROVIDER_IMPORT_FAILED_MESSAGE = "Web 模块 provider 导入失败。"
PROVIDER_TYPE_INVALID_MESSAGE = "Web 模块 provider 必须继承 WebBundleProvider。"
PROVIDER_MODULE_MISMATCH_MESSAGE = "Web 模块 manifest 与 provider module_name 不一致。"
PROVIDER_ROUTE_TAGS_MISMATCH_MESSAGE = "Web 模块 manifest 与 provider 路由标签不一致。"
DUPLICATE_MODULE_MESSAGE = "Web 模块 manifest 不允许重复模块名。"
DISABLED_PROVIDER_NOT_INCLUDED_MESSAGE = "禁用 Web 模块不应被装配。"
PROVIDER_ROUTE_TAGS_EMPTY_MESSAGE = "Web 模块 provider 路由标签不能为空。"
ENABLED_MODULES_CONFIG_PATH = "app.modules.enabled"
MODULE_NAME_LIST_SEPARATOR = ", "
UNKNOWN_ENABLED_MODULE_MESSAGE_TEMPLATE = (
    "{config_path} 包含未知 Web 模块: {unknown_modules}。可用 Web 模块: {known_modules}。"
)


class WebBundleProviderHeader(BaseModel):
    """
    Web 模块提供者公共头。
    """

    model_config = ConfigDict(extra="forbid")

    header_kind: Literal["web_bundle_provider_header"] = WEB_BUNDLE_PROVIDER_HEADER_KIND
    schema_version: Literal["1.0"] = WEB_BUNDLE_PROVIDER_SCHEMA_VERSION
    module_name: str


class WebBundleProviderDetail(BaseModel):
    """
    Web 模块提供者扩展信息。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["web_bundle_provider_detail"] = WEB_BUNDLE_PROVIDER_DETAIL_KIND
    schema_version: Literal["1.0"] = WEB_BUNDLE_PROVIDER_SCHEMA_VERSION
    provider_name: str


WebBundleProviderDetailUnion = Annotated[
    WebBundleProviderDetail,
    Field(discriminator="kind"),
]


class WebBundleProviderEnvelope(BaseModel):
    """
    Web 模块提供者信封。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    header: WebBundleProviderHeader
    detail: WebBundleProviderDetailUnion
    bundle: WebBundle


class WebBundleProvider:
    """
    Web 模块提供者协议化实现。
    """

    module_name: ClassVar[str]

    def provide(self) -> WebBundleProviderEnvelope:
        """
        提供 Web 模块信封。
        """

        raise NotImplementedError


class WebBundleCatalog:
    """
    Web 集合目录，负责汇总并装配可用模块提供者。
    """

    def __init__(
        self,
        manifest_entries: list[WebModuleManifestEnvelope] | None = None,
    ) -> None:
        """
        初始化 Web 集合目录。
        """

        if manifest_entries is None:
            self._manifest_entries = WebModuleManifestRegistry().list_entries()
            WebModuleManifestRegistry(
                manifest_entries=self._manifest_entries
            ).validate_admin_boundary_authorization()
        else:
            self._manifest_entries = list(manifest_entries)
        self._validate_manifest_entries()

    def list_provider_envelopes(self) -> list[WebBundleProviderEnvelope]:
        """
        列出全部提供者信封。
        """

        envelopes: list[WebBundleProviderEnvelope] = []
        for entry in self._manifest_entries:
            if not entry.header.enabled:
                continue
            provider_type = self._load_provider_type(entry)
            provider = provider_type()
            envelope = provider.provide()
            self._validate_provider_envelope(entry=entry, envelope=envelope)
            envelopes.append(envelope)
        return envelopes

    def build(self) -> list[WebBundle]:
        """
        构建全部 Web 模块集合。
        """

        return [envelope.bundle for envelope in self.list_provider_envelopes()]

    def list_module_names(self) -> list[str]:
        """
        列出 manifest 中声明的 Web 模块名。
        """

        return [entry.header.module_name for entry in self._manifest_entries]

    def list_enabled_module_names(self) -> list[str]:
        """
        列出 manifest 中启用的 Web 模块名。
        """

        return [
            entry.header.module_name for entry in self._manifest_entries if entry.header.enabled
        ]

    def validate_enabled_modules(self, enabled_modules: list[str]) -> None:
        """
        校验启用模块必须存在于已启用 manifest 中。
        """

        known_module_names = self.list_enabled_module_names()
        known_module_name_set = set(known_module_names)
        unknown_module_names = [
            module_name
            for module_name in enabled_modules
            if module_name not in known_module_name_set
        ]
        if len(unknown_module_names) > 0:
            raise ValueError(
                UNKNOWN_ENABLED_MODULE_MESSAGE_TEMPLATE.format(
                    config_path=ENABLED_MODULES_CONFIG_PATH,
                    unknown_modules=MODULE_NAME_LIST_SEPARATOR.join(unknown_module_names),
                    known_modules=MODULE_NAME_LIST_SEPARATOR.join(known_module_names),
                )
            )

    def _validate_manifest_entries(self) -> None:
        """
        校验 manifest 条目集合。
        """

        module_names = [entry.header.module_name for entry in self._manifest_entries]
        if len(module_names) != len(set(module_names)):
            raise ValueError(DUPLICATE_MODULE_MESSAGE)
        for entry in self._manifest_entries:
            if entry.detail.provider_import_path.strip() == "":
                raise ValueError(PROVIDER_IMPORT_PATH_INVALID_MESSAGE)
            if len(entry.detail.route_tags) == 0:
                raise ValueError(PROVIDER_ROUTE_TAGS_EMPTY_MESSAGE)

    def _load_provider_type(
        self,
        entry: WebModuleManifestEnvelope,
    ) -> type[WebBundleProvider]:
        """
        按 manifest 导入 provider 类型。
        """

        import_path = entry.detail.provider_import_path
        if PROVIDER_IMPORT_PATH_SEPARATOR not in import_path:
            raise ValueError(PROVIDER_IMPORT_PATH_INVALID_MESSAGE)
        module_path, provider_name = import_path.rsplit(
            PROVIDER_IMPORT_PATH_SEPARATOR,
            maxsplit=1,
        )
        try:
            module = importlib.import_module(module_path)
            provider_type = getattr(module, provider_name)
        except (ImportError, AttributeError) as exc:
            raise ValueError(PROVIDER_IMPORT_FAILED_MESSAGE) from exc
        if not isinstance(provider_type, type) or not issubclass(
            provider_type,
            WebBundleProvider,
        ):
            raise ValueError(PROVIDER_TYPE_INVALID_MESSAGE)
        return provider_type

    def _validate_provider_envelope(
        self,
        *,
        entry: WebModuleManifestEnvelope,
        envelope: WebBundleProviderEnvelope,
    ) -> None:
        """
        校验 provider 输出与 manifest 一致。
        """

        if not entry.header.enabled:
            raise ValueError(DISABLED_PROVIDER_NOT_INCLUDED_MESSAGE)
        if (
            envelope.header.module_name != entry.header.module_name
            or str(envelope.bundle.module_name) != entry.header.module_name
        ):
            raise ValueError(PROVIDER_MODULE_MISMATCH_MESSAGE)
        if list(envelope.bundle.router.tags) != entry.detail.route_tags:
            raise ValueError(PROVIDER_ROUTE_TAGS_MISMATCH_MESSAGE)
