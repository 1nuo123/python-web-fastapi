"""Capability-first Codex compatibility policy tests."""

from __future__ import annotations

from pathlib import Path

from src.core.codex_contract.app_server_capability_contract import (
    AppServerCapabilityProbeFailure,
    AppServerCapabilityProbeOutcome,
    AppServerCapabilityProbeResult,
)
from src.core.codex_contract.app_server_schema_manifest_contract import (
    AppServerCapabilityCode,
    AppServerCapabilityDetail,
    AppServerMethodName,
    AppServerSchemaManifestEnvelope,
)
from src.domain.codex.codex_compatibility_policy import (
    CodexCompatibilityDecision,
    CodexCompatibilityPolicy,
    CodexCompatibilityReason,
    CodexConnectionCompatibilityTuple,
)

MANIFEST_PATH = Path("protocol/codex_app_server/0.145.0/manifest.json")
BASE_DIGEST = "86501505d7a626582cd7ded6eee36ab6bbaae30fd5d5c1021c0330e3f99d8109"


def _policy(**kwargs: object) -> CodexCompatibilityPolicy:
    manifest = AppServerSchemaManifestEnvelope.model_validate_json(
        MANIFEST_PATH.read_text(encoding="utf-8")
    )
    return CodexCompatibilityPolicy((manifest,), **kwargs)


def _probe(outcome: AppServerCapabilityProbeOutcome) -> AppServerCapabilityProbeResult:
    methods = tuple(AppServerMethodName)
    capabilities = tuple(
        AppServerCapabilityDetail(code=code, version=1) for code in AppServerCapabilityCode
    )
    return AppServerCapabilityProbeResult(
        outcome=outcome,
        initialize_passed=True,
        methods=methods,
        capabilities=capabilities,
        read_only_confirmed=outcome is not AppServerCapabilityProbeOutcome.BLOCKED,
        mutation_confirmed=outcome is AppServerCapabilityProbeOutcome.COMPATIBLE,
        approval_confirmed=outcome is AppServerCapabilityProbeOutcome.COMPATIBLE,
        interrupt_confirmed=outcome is AppServerCapabilityProbeOutcome.COMPATIBLE,
        failure=(
            None
            if outcome is not AppServerCapabilityProbeOutcome.BLOCKED
            else AppServerCapabilityProbeFailure.PROTOCOL_ERROR
        ),
    )


def test_known_manifest_and_digest_remain_compatible() -> None:
    result = _policy().evaluate_connection(
        CodexConnectionCompatibilityTuple(
            codex_version="0.145.0",
            agent_protocol_version="2.0",
            app_server_schema_digest=BASE_DIGEST,
            capabilities=frozenset(AppServerCapabilityCode),
        )
    )
    assert result.decision is CodexCompatibilityDecision.COMPATIBLE


def test_unknown_version_uses_successful_probe() -> None:
    result = _policy().evaluate_connection(
        CodexConnectionCompatibilityTuple(
            codex_version="0.152.0",
            agent_protocol_version="2.0",
            app_server_schema_digest=None,
            capabilities=frozenset(AppServerCapabilityCode),
            probe_result=_probe(AppServerCapabilityProbeOutcome.COMPATIBLE),
        )
    )
    assert result.decision is CodexCompatibilityDecision.COMPATIBLE


def test_unknown_version_without_probe_is_blocked() -> None:
    result = _policy().evaluate_connection(
        CodexConnectionCompatibilityTuple(
            codex_version="0.152.0",
            agent_protocol_version="2.0",
            app_server_schema_digest=None,
            capabilities=frozenset(),
        )
    )
    assert result.decision is CodexCompatibilityDecision.BLOCKED
    assert result.reason is CodexCompatibilityReason.PROBE_REQUIRED


def test_unknown_version_read_only_probe_cannot_mutate() -> None:
    result = _policy().evaluate_connection(
        CodexConnectionCompatibilityTuple(
            codex_version="0.152.0",
            agent_protocol_version="2.0",
            app_server_schema_digest=None,
            capabilities=frozenset(
                {
                    AppServerCapabilityCode.MODEL_LIST,
                    AppServerCapabilityCode.THREAD_LIST,
                    AppServerCapabilityCode.THREAD_READ,
                }
            ),
            probe_result=_probe(AppServerCapabilityProbeOutcome.READ_ONLY),
        )
    )
    assert result.decision is CodexCompatibilityDecision.READ_ONLY


def test_blocked_version_and_minimum_version_are_explicit_guards() -> None:
    blocked = _policy(blocked_versions=("0.152.0",)).evaluate_connection(
        CodexConnectionCompatibilityTuple(
            codex_version="0.152.0",
            agent_protocol_version="2.0",
            capabilities=frozenset(),
        )
    )
    old = _policy(minimum_version="0.146.0").evaluate_connection(
        CodexConnectionCompatibilityTuple(
            codex_version="0.145.0",
            agent_protocol_version="2.0",
            app_server_schema_digest=BASE_DIGEST,
            capabilities=frozenset(AppServerCapabilityCode),
        )
    )
    assert blocked.reason is CodexCompatibilityReason.VERSION_BLOCKED
    assert old.decision is CodexCompatibilityDecision.UPGRADE_REQUIRED
