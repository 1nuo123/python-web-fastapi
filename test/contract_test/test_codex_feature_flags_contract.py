"""Codex 体验开关前后端共享契约测试。"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from src.core.codex_contract.feature_flags_contract import CodexExperienceFeatureFlags

SHARED_FEATURE_FLAGS_FIXTURE_PATH = (
    Path(__file__).resolve().parents[1] / "fixtures" / "codex_feature_flags_contract.json"
)


class CodexExperienceFeatureFlagsFixture(BaseModel):
    """共享 JSON fixture 的封闭输入边界。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    default_flags: CodexExperienceFeatureFlags
    server_approved_flags: CodexExperienceFeatureFlags


def test_shared_feature_flags_fixture_should_match_backend_defaults_and_overrides() -> None:
    """后端 Pydantic 合同必须接受与浏览器共用的默认和授权值。"""

    fixture = CodexExperienceFeatureFlagsFixture.model_validate_json(
        SHARED_FEATURE_FLAGS_FIXTURE_PATH.read_text(encoding="utf-8")
    )

    assert fixture.default_flags == CodexExperienceFeatureFlags()
    assert fixture.server_approved_flags == CodexExperienceFeatureFlags(
        codex_scroll_controller_v2=True,
        codex_realtime_batch_v2=False,
        codex_authority_recovery_v2=True,
    )
