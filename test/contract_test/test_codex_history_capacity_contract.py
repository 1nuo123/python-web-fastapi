"""4 MiB 历史降级产品契约测试。"""

from src.core.codex_contract.agent_protocol_contract import CodexAgentStateSnapshot
from src.core.codex_contract.thread_contract import CodexThreadAuthoritySnapshot


def test_agent_snapshot_contract_should_expose_omitted_workspace_metadata() -> None:
    fields = CodexAgentStateSnapshot.model_fields
    assert "omitted_thread_workspace_keys" in fields
    assert fields["omitted_thread_workspace_keys"].default_factory is not None


def test_thread_snapshot_contract_should_expose_stable_history_status() -> None:
    field = CodexThreadAuthoritySnapshot.model_fields["history_status"]
    assert field.default == "complete"
