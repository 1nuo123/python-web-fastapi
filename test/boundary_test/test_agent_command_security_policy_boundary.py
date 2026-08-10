"""Agent App Server 安全策略配置边界测试。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.infrastructure.codex_agent.agent_configuration import AgentAppServerSecuritySettings


@pytest.mark.parametrize(
    ("field_name", "unsafe_value"),
    [
        ("approval_policy", "never"),
        ("approvals_reviewer", "auto_review"),
        ("sandbox_mode", "danger-full-access"),
    ],
)
def test_security_settings_when_value_outside_single_safe_boundary_should_reject(
    field_name: str,
    unsafe_value: str,
) -> None:
    with pytest.raises(ValidationError):
        AgentAppServerSecuritySettings.model_validate({field_name: unsafe_value})
