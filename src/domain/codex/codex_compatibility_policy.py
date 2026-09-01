"""Codex capability-first 兼容决策。"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from src.core.codex_contract.app_server_capability_contract import (
    AppServerCapabilityProbeOutcome,
    AppServerCapabilityProbeResult,
)
from src.core.codex_contract.app_server_schema_manifest_contract import (
    SHA256_HEX_PATTERN,
    AppServerCapabilityCode,
    AppServerMethodEffect,
    AppServerMethodName,
    AppServerSchemaManifestEnvelope,
    AppServerSchemaReviewStatus,
)
from src.core.codex_contract.connection_session_contract import CodexConnectionProtocolVersion

SEMVER_PATTERN: Final = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?P<prerelease>-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)
READ_ONLY_METHODS: Final = frozenset(
    {
        AppServerMethodName.INITIALIZE,
        AppServerMethodName.MODEL_LIST,
        AppServerMethodName.THREAD_LIST,
        AppServerMethodName.THREAD_READ,
    }
)
CORE_PROBE_METHODS: Final = frozenset(
    {
        *READ_ONLY_METHODS,
        AppServerMethodName.THREAD_START,
        AppServerMethodName.THREAD_DELETE,
        AppServerMethodName.TURN_START,
        AppServerMethodName.TURN_INTERRUPT,
        AppServerMethodName.COMMAND_APPROVAL,
    }
)


class CodexCompatibilityDecision(StrEnum):
    """控制面可以采取的兼容动作。"""

    COMPATIBLE = "compatible"
    READ_ONLY = "read_only"
    UPGRADE_REQUIRED = "upgrade_required"
    BLOCKED = "blocked"


class CodexCompatibilityReason(StrEnum):
    """稳定机器可读兼容原因。"""

    SUPPORTED = "supported"
    VERSION_NOT_SUPPORTED = "version_not_supported"
    MANIFEST_NOT_APPROVED = "manifest_not_approved"
    AGENT_PROTOCOL_NOT_SUPPORTED = "agent_protocol_not_supported"
    UNKNOWN_SCHEMA_READ_ONLY = "unknown_schema_read_only"
    UNKNOWN_SCHEMA_MUTATION_BLOCKED = "unknown_schema_mutation_blocked"
    METHOD_NOT_SUPPORTED = "method_not_supported"
    CAPABILITY_MISSING = "capability_missing"
    VERSION_TOO_OLD = "version_too_old"
    VERSION_BLOCKED = "version_blocked"
    PROBE_REQUIRED = "probe_required"
    PROBE_FAILED = "probe_failed"
    CORE_METHOD_MISSING = "core_method_missing"


class CodexCompatibilityTuple(BaseModel):
    """一次方法级兼容判定的精确输入。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    codex_version: str = Field(min_length=1, max_length=64)
    agent_protocol_version: str = Field(min_length=1, max_length=64)
    app_server_schema_digest: str | None = Field(default=None, pattern=SHA256_HEX_PATTERN)
    capabilities: frozenset[AppServerCapabilityCode]
    method: AppServerMethodName
    probe_result: AppServerCapabilityProbeResult | None = None


class CodexConnectionCompatibilityTuple(BaseModel):
    """Agent hello 阶段的兼容输入。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    codex_version: str = Field(min_length=1, max_length=64)
    agent_protocol_version: str = Field(min_length=1, max_length=64)
    app_server_schema_digest: str | None = Field(default=None, pattern=SHA256_HEX_PATTERN)
    capabilities: frozenset[AppServerCapabilityCode]
    probe_result: AppServerCapabilityProbeResult | None = None


class CodexCompatibilityResult(BaseModel):
    """兼容决策与稳定原因码。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: CodexCompatibilityDecision
    reason: CodexCompatibilityReason
    method_effect: AppServerMethodEffect | None = None
    required_capability: AppServerCapabilityCode | None = None


class CodexCompatibilityPolicy:
    """已知 manifest 走快速路径，未知版本由真实 probe fail-closed。"""

    def __init__(
        self,
        manifests: tuple[AppServerSchemaManifestEnvelope, ...],
        *,
        minimum_version: str | None = None,
        unknown_version_policy: str = "probe",
        unknown_schema_policy: str = "probe",
        blocked_versions: tuple[str, ...] = (),
        allow_prerelease: bool = False,
    ) -> None:
        self._manifests = {manifest.header.codex_version: manifest for manifest in manifests}
        self._minimum_version = minimum_version
        self._unknown_version_policy = unknown_version_policy
        self._unknown_schema_policy = unknown_schema_policy
        self._blocked_versions = frozenset(blocked_versions)
        self._allow_prerelease = allow_prerelease

    def evaluate(self, compatibility: CodexCompatibilityTuple) -> CodexCompatibilityResult:
        """计算一个目标方法是否允许执行。"""

        guard = self._evaluate_version_guard(compatibility.codex_version)
        if guard is not None:
            return guard
        manifest = self._manifests.get(compatibility.codex_version)
        if manifest is None:
            return self._evaluate_unknown_method(compatibility)
        base = self._evaluate_known_manifest(
            manifest=manifest,
            protocol_version=compatibility.agent_protocol_version,
        )
        if base is not None:
            return base
        method_policy = next(
            (
                item
                for item in manifest.detail.method_catalog
                if item.method == compatibility.method
            ),
            None,
        )
        if method_policy is None:
            return self._blocked(CodexCompatibilityReason.METHOD_NOT_SUPPORTED)
        if compatibility.app_server_schema_digest != manifest.detail.json_schema_bundle_sha256:
            return self._evaluate_unknown_schema_method(compatibility, method_policy.effect)
        required = method_policy.required_capability
        if required is not None and required not in compatibility.capabilities:
            return CodexCompatibilityResult(
                decision=CodexCompatibilityDecision.BLOCKED,
                reason=CodexCompatibilityReason.CAPABILITY_MISSING,
                method_effect=method_policy.effect,
                required_capability=required,
            )
        return CodexCompatibilityResult(
            decision=CodexCompatibilityDecision.COMPATIBLE,
            reason=CodexCompatibilityReason.SUPPORTED,
            method_effect=method_policy.effect,
            required_capability=required,
        )

    def evaluate_connection(
        self,
        compatibility: CodexConnectionCompatibilityTuple,
    ) -> CodexCompatibilityResult:
        """校验 hello 的版本、协议、digest、capability 与 probe 一致性。"""

        guard = self._evaluate_version_guard(compatibility.codex_version)
        if guard is not None:
            return guard
        manifest = self._manifests.get(compatibility.codex_version)
        if manifest is None:
            if self._unknown_version_policy == "blocked":
                return self._blocked(CodexCompatibilityReason.VERSION_NOT_SUPPORTED)
            return self._evaluate_probe_connection(compatibility)
        base = self._evaluate_known_manifest(
            manifest=manifest,
            protocol_version=compatibility.agent_protocol_version,
        )
        if base is not None:
            return base
        if compatibility.app_server_schema_digest != manifest.detail.json_schema_bundle_sha256:
            if self._unknown_schema_policy == "blocked":
                return self._blocked(CodexCompatibilityReason.UNKNOWN_SCHEMA_MUTATION_BLOCKED)
            if self._unknown_schema_policy == "read_only":
                return self._read_only(CodexCompatibilityReason.UNKNOWN_SCHEMA_READ_ONLY)
            return self._evaluate_probe_connection(compatibility)
        supported = {item.code for item in manifest.detail.capabilities}
        if not compatibility.capabilities.issubset(supported):
            return self._blocked(CodexCompatibilityReason.CAPABILITY_MISSING)
        return CodexCompatibilityResult(
            decision=CodexCompatibilityDecision.COMPATIBLE,
            reason=CodexCompatibilityReason.SUPPORTED,
        )

    def _evaluate_probe_connection(
        self,
        compatibility: CodexConnectionCompatibilityTuple,
    ) -> CodexCompatibilityResult:
        if compatibility.agent_protocol_version != CodexConnectionProtocolVersion.V2.value:
            return self._blocked(CodexCompatibilityReason.AGENT_PROTOCOL_NOT_SUPPORTED)
        probe = compatibility.probe_result
        if probe is None:
            return self._blocked(CodexCompatibilityReason.PROBE_REQUIRED)
        probe_capabilities = {item.code for item in probe.capabilities}
        if not compatibility.capabilities.issubset(probe_capabilities):
            return self._blocked(CodexCompatibilityReason.CAPABILITY_MISSING)
        methods = frozenset(probe.methods)
        if probe.outcome is AppServerCapabilityProbeOutcome.COMPATIBLE:
            if not CORE_PROBE_METHODS.issubset(methods):
                return self._blocked(CodexCompatibilityReason.CORE_METHOD_MISSING)
            return CodexCompatibilityResult(
                decision=CodexCompatibilityDecision.COMPATIBLE,
                reason=CodexCompatibilityReason.SUPPORTED,
            )
        if probe.outcome is AppServerCapabilityProbeOutcome.READ_ONLY:
            if not READ_ONLY_METHODS.issubset(methods):
                return self._blocked(CodexCompatibilityReason.CORE_METHOD_MISSING)
            return self._read_only(CodexCompatibilityReason.UNKNOWN_SCHEMA_READ_ONLY)
        return self._blocked(CodexCompatibilityReason.PROBE_FAILED)

    def _evaluate_unknown_method(
        self,
        compatibility: CodexCompatibilityTuple,
    ) -> CodexCompatibilityResult:
        if self._unknown_version_policy == "blocked":
            return self._blocked(CodexCompatibilityReason.VERSION_NOT_SUPPORTED)
        probe = compatibility.probe_result
        if probe is None:
            return self._blocked(CodexCompatibilityReason.PROBE_REQUIRED)
        if compatibility.method not in probe.methods:
            return self._blocked(CodexCompatibilityReason.CORE_METHOD_MISSING)
        if probe.outcome is AppServerCapabilityProbeOutcome.COMPATIBLE:
            return CodexCompatibilityResult(
                decision=CodexCompatibilityDecision.COMPATIBLE,
                reason=CodexCompatibilityReason.SUPPORTED,
            )
        if compatibility.method in READ_ONLY_METHODS and probe.read_only_confirmed:
            return self._read_only(CodexCompatibilityReason.UNKNOWN_SCHEMA_READ_ONLY)
        return self._blocked(CodexCompatibilityReason.UNKNOWN_SCHEMA_MUTATION_BLOCKED)

    def _evaluate_unknown_schema_method(
        self,
        compatibility: CodexCompatibilityTuple,
        effect: AppServerMethodEffect,
    ) -> CodexCompatibilityResult:
        if self._unknown_schema_policy == "probe" and compatibility.probe_result is not None:
            return self._evaluate_unknown_method(compatibility)
        if effect is AppServerMethodEffect.READ and self._unknown_schema_policy != "blocked":
            return CodexCompatibilityResult(
                decision=CodexCompatibilityDecision.READ_ONLY,
                reason=CodexCompatibilityReason.UNKNOWN_SCHEMA_READ_ONLY,
                method_effect=effect,
            )
        return CodexCompatibilityResult(
            decision=CodexCompatibilityDecision.BLOCKED,
            reason=CodexCompatibilityReason.UNKNOWN_SCHEMA_MUTATION_BLOCKED,
            method_effect=effect,
        )

    def _evaluate_known_manifest(
        self,
        *,
        manifest: AppServerSchemaManifestEnvelope,
        protocol_version: str,
    ) -> CodexCompatibilityResult | None:
        if manifest.header.review_status is AppServerSchemaReviewStatus.BLOCKED:
            return self._blocked(CodexCompatibilityReason.VERSION_BLOCKED)
        if protocol_version not in manifest.detail.supported_agent_protocol_versions:
            return self._blocked(CodexCompatibilityReason.AGENT_PROTOCOL_NOT_SUPPORTED)
        if manifest.header.review_status is not AppServerSchemaReviewStatus.APPROVED:
            return self._read_only(CodexCompatibilityReason.MANIFEST_NOT_APPROVED)
        return None

    def _evaluate_version_guard(self, version: str) -> CodexCompatibilityResult | None:
        parsed = _parse_semver(version)
        if version in self._blocked_versions:
            return self._blocked(CodexCompatibilityReason.VERSION_BLOCKED)
        if parsed is None:
            return self._blocked(CodexCompatibilityReason.VERSION_NOT_SUPPORTED)
        if not self._allow_prerelease and parsed[3] == 0:
            return CodexCompatibilityResult(
                decision=CodexCompatibilityDecision.UPGRADE_REQUIRED,
                reason=CodexCompatibilityReason.VERSION_NOT_SUPPORTED,
            )
        if self._minimum_version is not None:
            minimum = _parse_semver(self._minimum_version)
            if minimum is None:
                raise ValueError("minimum_version不是有效语义版本。")
            if parsed < minimum:
                return CodexCompatibilityResult(
                    decision=CodexCompatibilityDecision.UPGRADE_REQUIRED,
                    reason=CodexCompatibilityReason.VERSION_TOO_OLD,
                )
        return None

    @staticmethod
    def _blocked(reason: CodexCompatibilityReason) -> CodexCompatibilityResult:
        return CodexCompatibilityResult(
            decision=CodexCompatibilityDecision.BLOCKED,
            reason=reason,
        )

    @staticmethod
    def _read_only(reason: CodexCompatibilityReason) -> CodexCompatibilityResult:
        return CodexCompatibilityResult(
            decision=CodexCompatibilityDecision.READ_ONLY,
            reason=reason,
        )


def _parse_semver(value: str) -> tuple[int, int, int, int] | None:
    """返回可比较 semver；release 高于同号 prerelease。"""

    match = SEMVER_PATTERN.fullmatch(value)
    if match is None:
        return None
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
        0 if match.group("prerelease") else 1,
    )
