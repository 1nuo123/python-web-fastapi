"""Codex 精确版本、schema 与 capability 兼容决策。"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from src.core.codex_contract.app_server_schema_manifest_contract import (
    SHA256_HEX_PATTERN,
    AppServerCapabilityCode,
    AppServerMethodEffect,
    AppServerMethodName,
    AppServerSchemaManifestEnvelope,
    AppServerSchemaReviewStatus,
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
    UNKNOWN_VERSION_READ_ONLY = "unknown_version_read_only"
    UNKNOWN_SCHEMA_MUTATION_BLOCKED = "unknown_schema_mutation_blocked"
    METHOD_NOT_SUPPORTED = "method_not_supported"
    CAPABILITY_MISSING = "capability_missing"


class CodexCompatibilityTuple(BaseModel):
    """一次兼容判定的精确输入。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    codex_version: str = Field(min_length=1, max_length=64)
    agent_protocol_version: str = Field(min_length=1, max_length=64)
    app_server_schema_digest: str = Field(pattern=SHA256_HEX_PATTERN)
    capabilities: frozenset[AppServerCapabilityCode]
    method: AppServerMethodName


class CodexConnectionCompatibilityTuple(BaseModel):
    """Agent hello 阶段的精确兼容输入。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    codex_version: str = Field(min_length=1, max_length=64)
    agent_protocol_version: str = Field(min_length=1, max_length=64)
    app_server_schema_digest: str = Field(pattern=SHA256_HEX_PATTERN)
    capabilities: frozenset[AppServerCapabilityCode]


class CodexCompatibilityResult(BaseModel):
    """兼容决策与稳定原因码。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: CodexCompatibilityDecision
    reason: CodexCompatibilityReason
    method_effect: AppServerMethodEffect | None = None
    required_capability: AppServerCapabilityCode | None = None


class CodexCompatibilityPolicy:
    """只依据已审核 manifest 进行 fail-closed 决策。"""

    def __init__(self, manifests: tuple[AppServerSchemaManifestEnvelope, ...]) -> None:
        self._manifests = {
            manifest.header.codex_version: manifest
            for manifest in manifests
            if manifest.header.review_status != AppServerSchemaReviewStatus.BLOCKED
        }

    def evaluate(self, compatibility: CodexCompatibilityTuple) -> CodexCompatibilityResult:
        """计算目标方法是否允许执行。"""

        manifest = self._manifests.get(compatibility.codex_version)
        if manifest is None:
            return CodexCompatibilityResult(
                decision=CodexCompatibilityDecision.UPGRADE_REQUIRED,
                reason=CodexCompatibilityReason.VERSION_NOT_SUPPORTED,
            )
        if manifest.header.review_status != AppServerSchemaReviewStatus.APPROVED:
            return CodexCompatibilityResult(
                decision=CodexCompatibilityDecision.READ_ONLY,
                reason=CodexCompatibilityReason.MANIFEST_NOT_APPROVED,
            )
        if (
            compatibility.agent_protocol_version
            not in manifest.detail.supported_agent_protocol_versions
        ):
            return CodexCompatibilityResult(
                decision=CodexCompatibilityDecision.UPGRADE_REQUIRED,
                reason=CodexCompatibilityReason.AGENT_PROTOCOL_NOT_SUPPORTED,
            )
        method_policy = next(
            (
                policy
                for policy in manifest.detail.method_catalog
                if policy.method == compatibility.method
            ),
            None,
        )
        if method_policy is None:
            return CodexCompatibilityResult(
                decision=CodexCompatibilityDecision.BLOCKED,
                reason=CodexCompatibilityReason.METHOD_NOT_SUPPORTED,
            )
        if compatibility.app_server_schema_digest != manifest.detail.json_schema_bundle_sha256:
            if method_policy.effect == AppServerMethodEffect.READ:
                return CodexCompatibilityResult(
                    decision=CodexCompatibilityDecision.READ_ONLY,
                    reason=CodexCompatibilityReason.UNKNOWN_SCHEMA_READ_ONLY,
                    method_effect=method_policy.effect,
                )
            return CodexCompatibilityResult(
                decision=CodexCompatibilityDecision.BLOCKED,
                reason=CodexCompatibilityReason.UNKNOWN_SCHEMA_MUTATION_BLOCKED,
                method_effect=method_policy.effect,
            )
        required_capability = method_policy.required_capability
        if (
            required_capability is not None
            and required_capability not in compatibility.capabilities
        ):
            return CodexCompatibilityResult(
                decision=CodexCompatibilityDecision.BLOCKED,
                reason=CodexCompatibilityReason.CAPABILITY_MISSING,
                method_effect=method_policy.effect,
                required_capability=required_capability,
            )
        return CodexCompatibilityResult(
            decision=CodexCompatibilityDecision.COMPATIBLE,
            reason=CodexCompatibilityReason.SUPPORTED,
            method_effect=method_policy.effect,
            required_capability=required_capability,
        )

    def evaluate_connection(
        self,
        compatibility: CodexConnectionCompatibilityTuple,
    ) -> CodexCompatibilityResult:
        """校验 hello 的精确版本、digest、协议和 capability 子集。"""

        manifest = self._manifests.get(compatibility.codex_version)
        if manifest is None:
            return CodexCompatibilityResult(
                # A CLI version is an observation, not a write grant.  An
                # unreviewed version may still expose safe read-only data;
                # all mutations remain fenced by the connection decision.
                decision=CodexCompatibilityDecision.READ_ONLY,
                reason=CodexCompatibilityReason.UNKNOWN_VERSION_READ_ONLY,
            )
        if manifest.header.review_status != AppServerSchemaReviewStatus.APPROVED:
            return CodexCompatibilityResult(
                decision=CodexCompatibilityDecision.READ_ONLY,
                reason=CodexCompatibilityReason.MANIFEST_NOT_APPROVED,
            )
        if (
            compatibility.agent_protocol_version
            not in manifest.detail.supported_agent_protocol_versions
        ):
            return CodexCompatibilityResult(
                decision=CodexCompatibilityDecision.UPGRADE_REQUIRED,
                reason=CodexCompatibilityReason.AGENT_PROTOCOL_NOT_SUPPORTED,
            )
        if compatibility.app_server_schema_digest != manifest.detail.json_schema_bundle_sha256:
            return CodexCompatibilityResult(
                decision=CodexCompatibilityDecision.READ_ONLY,
                reason=CodexCompatibilityReason.UNKNOWN_SCHEMA_READ_ONLY,
            )
        supported_capabilities = {capability.code for capability in manifest.detail.capabilities}
        if not compatibility.capabilities.issubset(supported_capabilities):
            return CodexCompatibilityResult(
                decision=CodexCompatibilityDecision.BLOCKED,
                reason=CodexCompatibilityReason.CAPABILITY_MISSING,
            )
        return CodexCompatibilityResult(
            decision=CodexCompatibilityDecision.COMPATIBLE,
            reason=CodexCompatibilityReason.SUPPORTED,
        )
