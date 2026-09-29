"""
配置重载协调器基础设施模块。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import cast

from pydantic import BaseModel, ConfigDict, Field

from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.infrastructure.logging.app_logger_factory import AppLoggerFactory
from src.infrastructure.settings.app_settings_loader import (
    AppSettingsLoader,
)
from src.infrastructure.settings.application_settings import (
    AppEnvironment,
    ApplicationSettings,
)
from src.infrastructure.settings.raw_application_settings import SettingsOverrideMapping
from src.infrastructure.settings.settings_apply_contract import SettingsApplyResultPayload
from src.infrastructure.settings.settings_identity import (
    SettingsSerializableValue,
    identify_settings,
    normalize_settings,
)
from src.infrastructure.settings.settings_mapping_merger import (
    SettingsMappingInput,
    SettingsMappingMerger,
)
from src.infrastructure.settings.settings_snapshot_store import (
    SettingsSnapshot,
    SettingsSnapshotStore,
    SettingsStateHolder,
)

RELOAD_SCHEMA_VERSION = "1.0"
RELOAD_CANDIDATE_KIND = "reload_candidate"
RELOAD_RESULT_KIND = "reload_result"
CANDIDATE_VERSION_LENGTH = 12
SettingsFlatValue = SettingsSerializableValue


class ReloadCandidatePayload(BaseModel):
    """
    重载候选 Pydantic 模型。
    """

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(default=RELOAD_CANDIDATE_KIND)
    schema_version: str = Field(default=RELOAD_SCHEMA_VERSION)
    candidate_version: str
    digest: str


class ReloadResultPayload(BaseModel):
    """
    重载结果 Pydantic 模型。
    """

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(default=RELOAD_RESULT_KIND)
    schema_version: str = Field(default=RELOAD_SCHEMA_VERSION)
    success: bool
    rolled_back: bool
    reason: str | None
    candidate_version: str | None = None
    restored_resources: list[str] = Field(default_factory=list)
    active_snapshot_id: str | None = None


class SettingsReloadCoordinator:
    """
    配置重载协调器，负责串联候选构建、应用与快照推进。
    """

    def __init__(
        self,
        *,
        settings_loader: AppSettingsLoader,
        settings_holder: SettingsStateHolder,
        snapshot_store: SettingsSnapshotStore,
        logger_factory: AppLoggerFactory,
        logger: logging.Logger,
        on_settings_applied: Callable[[ApplicationSettings], SettingsApplyResultPayload],
        baseline_overrides: SettingsOverrideMapping | None = None,
    ) -> None:
        """
        初始化配置重载协调器。
        """

        self._settings_loader = settings_loader
        self._settings_holder = settings_holder
        self._snapshot_store = snapshot_store
        self._logger_factory = logger_factory
        self._logger = logger
        self._on_settings_applied = on_settings_applied
        self._baseline_overrides = baseline_overrides
        self._settings_mapping_merger = SettingsMappingMerger()

    def build_candidate(self, environment: AppEnvironment) -> ReloadCandidatePayload:
        """
        构建候选。
        """

        candidate_settings = self._load_candidate_settings(
            environment=environment,
            overrides=None,
        )
        identity = identify_settings(candidate_settings)
        return ReloadCandidatePayload(
            candidate_version=identity.candidate_version,
            digest=identity.full_digest,
        )

    def reload(self, environment: AppEnvironment) -> ReloadResultPayload:
        """
        处理重载。
        """

        candidate_settings = self._load_candidate_settings(
            environment=environment,
            overrides=None,
        )
        return self._apply_candidate(candidate_settings)

    def reload_from_mapping(
        self,
        *,
        environment: AppEnvironment,
        overrides: SettingsOverrideMapping,
    ) -> ReloadResultPayload:
        """
        基于覆盖映射执行重载。
        """

        candidate_settings = self._load_candidate_settings(
            environment=environment,
            overrides=overrides,
        )
        return self._apply_candidate(candidate_settings)

    def _load_candidate_settings(
        self,
        *,
        environment: AppEnvironment,
        overrides: SettingsOverrideMapping | None,
    ) -> ApplicationSettings:
        """
        加载候选配置，并保留启动阶段的显式覆盖。
        """

        merged_overrides = self._merge_baseline_overrides(overrides)
        if merged_overrides is None:
            return self._settings_loader.load_for_environment(environment)
        return self._settings_loader.load_from_mapping(
            environment=environment,
            overrides=merged_overrides,
        )

    def _merge_baseline_overrides(
        self,
        overrides: SettingsOverrideMapping | None,
    ) -> SettingsOverrideMapping | None:
        if self._baseline_overrides is None:
            return overrides
        if overrides is None:
            return cast(
                SettingsOverrideMapping,
                self._settings_mapping_merger.merge(
                    cast(SettingsMappingInput, self._baseline_overrides),
                    {},
                ),
            )
        return cast(
            SettingsOverrideMapping,
            self._settings_mapping_merger.merge(
                cast(SettingsMappingInput, self._baseline_overrides),
                cast(SettingsMappingInput, overrides),
            ),
        )

    def initialize_snapshot(self) -> None:
        """
        初始化成功快照。
        """

        current_settings = self._settings_holder.current_settings
        identity = identify_settings(current_settings)
        self._snapshot_store.save(
            SettingsSnapshot(
                version_id=identity.candidate_version,
                digest=identity.full_digest,
                settings=current_settings.model_copy(deep=True),
            )
        )

    def _apply_candidate(
        self,
        candidate_settings: ApplicationSettings,
    ) -> ReloadResultPayload:
        """
        应用候选。
        """

        current_settings = self._settings_holder.current_settings
        identity = identify_settings(candidate_settings)
        candidate_digest = identity.full_digest
        candidate_version = identity.candidate_version
        # 热更新先做“绝对禁止”校验，再做“允许但需重启”校验，避免配置进入半生效状态。
        unsafe_changes = self._collect_unsafe_changes(
            current_settings=current_settings,
            candidate_settings=candidate_settings,
        )
        if unsafe_changes:
            reason = f"以下配置不允许热更新：{','.join(unsafe_changes)}。"
            self._logger.warning("拒绝热更新：%s", reason)
            return ReloadResultPayload(
                success=False,
                rolled_back=False,
                reason=reason,
                candidate_version=candidate_version,
            )
        restricted_changes = self._collect_restricted_changes(
            current_settings=current_settings,
            candidate_settings=candidate_settings,
        )
        if restricted_changes:
            reason = f"以下配置必须重启后生效：{','.join(restricted_changes)}。"
            self._logger.warning("拒绝热更新：%s", reason)
            return ReloadResultPayload(
                success=False,
                rolled_back=False,
                reason=reason,
                candidate_version=candidate_version,
            )

        apply_result = self._on_settings_applied(candidate_settings)
        if apply_result.success:
            # 只有资源挂载点确认应用成功后，才推进快照版本，保证回滚基线可靠。
            self._snapshot_store.save(
                SettingsSnapshot(
                    version_id=candidate_version,
                    digest=candidate_digest,
                    settings=candidate_settings.model_copy(deep=True),
                )
            )
            self._logger.info("配置热更新成功，版本：%s", candidate_version)
            return ReloadResultPayload(
                success=True,
                rolled_back=False,
                reason=None,
                candidate_version=candidate_version,
                restored_resources=[],
                active_snapshot_id=apply_result.active_snapshot_id,
            )

        latest_snapshot = self._snapshot_store.load_latest()
        if latest_snapshot is not None:
            # 失败时用最近一次成功快照恢复内存态，避免部分组件继续持有候选配置。
            self._settings_holder.current_settings = latest_snapshot.settings.model_copy(deep=True)
        failure_reason = apply_result.failure_reason or CoreErrorCode.RELOAD_FAILED
        self._logger.error("配置热更新失败并已回滚：%s", failure_reason)
        return ReloadResultPayload(
            success=False,
            rolled_back=apply_result.rolled_back,
            reason=f"{CoreErrorCode.RELOAD_FAILED}:{failure_reason}",
            candidate_version=candidate_version,
            restored_resources=apply_result.restored_resources,
            active_snapshot_id=(
                latest_snapshot.version_id if latest_snapshot is not None else None
            ),
        )

    def _collect_restricted_changes(
        self,
        *,
        current_settings: ApplicationSettings,
        candidate_settings: ApplicationSettings,
    ) -> list[str]:
        """
        收集受限变更。
        """

        current_flatten = self._flatten_model("", self._serialize_settings(current_settings))
        candidate_flatten = self._flatten_model(
            "",
            self._serialize_settings(candidate_settings),
        )
        # 先把嵌套配置展平成路径字典，再与策略白名单做集合比对。
        changed_paths = [
            path
            for path, current_value in current_flatten.items()
            if candidate_flatten.get(path) != current_value
        ]
        restart_required = set(current_settings.app.reload.restart_required)
        return [path for path in changed_paths if path in restart_required]

    def _collect_unsafe_changes(
        self,
        *,
        current_settings: ApplicationSettings,
        candidate_settings: ApplicationSettings,
    ) -> list[str]:
        """
        收集不安全变更。
        """

        current_flatten = self._flatten_model("", self._serialize_settings(current_settings))
        candidate_flatten = self._flatten_model(
            "",
            self._serialize_settings(candidate_settings),
        )
        changed_paths = [
            path
            for path, current_value in current_flatten.items()
            if candidate_flatten.get(path) != current_value
        ]
        allowed_paths = set(current_settings.app.reload.hot_reload_allowed)
        restart_required = set(current_settings.app.reload.restart_required)
        return [
            path
            for path in changed_paths
            if path not in allowed_paths and path not in restart_required
        ]

    def _flatten_model(
        self,
        parent_path: str,
        value: SettingsSerializableValue,
    ) -> dict[str, SettingsFlatValue]:
        """
        展平模型。
        """

        if not isinstance(value, dict):
            return {parent_path.strip("."): value}
        flattened: dict[str, SettingsFlatValue] = {}
        for child_key, child_value in value.items():
            child_path = f"{parent_path}.{child_key}" if parent_path else child_key
            flattened.update(self._flatten_model(child_path, child_value))
        return flattened

    def _serialize_settings(
        self,
        settings: ApplicationSettings,
    ) -> dict[str, SettingsSerializableValue]:
        """Compatibility helper for change detection; identity owns normalization."""

        return normalize_settings(settings)
