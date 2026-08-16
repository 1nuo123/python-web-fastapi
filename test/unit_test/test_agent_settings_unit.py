"""Windows Agent 设置、项目配置与计划任务控制单元测试。"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
import rtoml

from src.core.codex_contract.connection_session_contract import (
    CodexConnectionProtocolVersion,
)
from src.infrastructure.codex_agent.agent_configuration import (
    AgentProcessSettings,
    AgentProtocolSettings,
    AgentWorkspaceSettings,
    CodexHostAgentSettings,
    CodexHostAgentSettingsLoader,
)
from src.infrastructure.codex_agent.agent_settings_ui import SETTINGS_ACTION_LABELS
from src.infrastructure.codex_agent.agent_workspace_configuration import (
    AgentWorkspaceConfigurationError,
    WindowsAgentWorkspaceConfiguration,
)
from src.infrastructure.codex_agent.windows_agent_task import (
    WindowsAgentTaskController,
    WindowsAgentTaskError,
    WindowsAgentTaskStatus,
)

SCHEMA_DIGEST = "a" * 64


class AllowConfigPermissions:
    def verify(self, path: Path) -> None:
        _ = path


class RecordingAclEnforcer:
    def __init__(self) -> None:
        self.paths: list[Path] = []

    def enforce(self, path: Path) -> None:
        self.paths.append(path)


class RecordingTaskController:
    def __init__(self, *, fail_first_restart: bool = False) -> None:
        self.fail_first_restart = fail_first_restart
        self.restart_calls = 0

    def restart(self) -> WindowsAgentTaskStatus:
        self.restart_calls += 1
        if self.fail_first_restart and self.restart_calls == 1:
            raise WindowsAgentTaskError("new configuration failed")
        return WindowsAgentTaskStatus(state="Running", last_task_result=0)


class InMemoryTaskBackend:
    def __init__(self, *, state: str, transition_on_start: bool = True) -> None:
        self.state = state
        self.transition_on_start = transition_on_start
        self.start_calls = 0
        self.stop_calls = 0

    def read_status(self, task_name: str) -> WindowsAgentTaskStatus:
        _ = task_name
        return WindowsAgentTaskStatus(state=self.state, last_task_result=0)

    def start(self, task_name: str) -> None:
        _ = task_name
        self.start_calls += 1
        if self.transition_on_start:
            self.state = "Running"

    def stop(self, task_name: str) -> None:
        _ = task_name
        self.stop_calls += 1
        self.state = "Ready"


class RecordingRunProcessBackend:
    def __init__(self) -> None:
        self.stop_all_calls = 0

    def stop_all(self) -> None:
        self.stop_all_calls += 1


def _settings(tmp_path: Path) -> CodexHostAgentSettings:
    first_root = tmp_path / "first"
    first_root.mkdir(exist_ok=True)
    return CodexHostAgentSettings(
        agent=AgentProcessSettings(
            host_id=uuid4(),
            key_id=uuid4(),
            display_name="Test Agent",
            control_plane_url="wss://localhost/internal/codex-agents/connect",
            control_plane_api_url="https://localhost",
            codex_binary="codex",
            state_database=tmp_path / "state.sqlite",
        ),
        protocol=AgentProtocolSettings(
            agent_schema_version=CodexConnectionProtocolVersion.V2,
            expected_codex_version="0.145.0",
            app_server_schema_digest=SCHEMA_DIGEST,
        ),
        workspaces=[
            AgentWorkspaceSettings(
                key="workspace-1",
                display_name="First",
                root=first_root,
                allow_write=True,
            )
        ],
    )


def _configuration(
    tmp_path: Path,
    *,
    task_controller: RecordingTaskController,
) -> tuple[WindowsAgentWorkspaceConfiguration, Path, RecordingAclEnforcer]:
    config_path = tmp_path / "agent.toml"
    config_path.write_text(
        rtoml.dumps(_settings(tmp_path).model_dump(mode="json", exclude_none=True)),
        encoding="utf-8",
    )
    acl_enforcer = RecordingAclEnforcer()
    configuration = WindowsAgentWorkspaceConfiguration(
        config_path=config_path,
        settings_loader=CodexHostAgentSettingsLoader(AllowConfigPermissions()),
        acl_enforcer=acl_enforcer,  # type: ignore[arg-type]
        task_controller=task_controller,  # type: ignore[arg-type]
    )
    return configuration, config_path, acl_enforcer


def test_settings_window_should_expose_only_requested_actions() -> None:
    assert SETTINGS_ACTION_LABELS == (
        "打开网站",
        "管理项目",
        "启动 Agent",
        "重启 Agent",
        "暂停 Agent",
        "退出",
    )


def test_task_controller_restart_should_stop_then_start() -> None:
    backend = InMemoryTaskBackend(state="Running")
    run_process_backend = RecordingRunProcessBackend()
    controller = WindowsAgentTaskController(
        task_name="CodexRemoteAgent-test",
        backend=backend,
        run_process_backend=run_process_backend,
        timeout_seconds=0.1,
        poll_interval_seconds=0.001,
    )

    status = controller.restart()

    assert status.is_running is True
    assert backend.stop_calls == 1
    assert backend.start_calls == 1
    assert run_process_backend.stop_all_calls == 1


def test_task_controller_pause_should_cleanup_orphans_when_task_is_ready() -> None:
    backend = InMemoryTaskBackend(state="Ready")
    run_process_backend = RecordingRunProcessBackend()
    controller = WindowsAgentTaskController(
        task_name="CodexRemoteAgent-test",
        backend=backend,
        run_process_backend=run_process_backend,
        timeout_seconds=0.1,
        poll_interval_seconds=0.001,
    )

    status = controller.pause()

    assert status.state == "Ready"
    assert backend.stop_calls == 0
    assert run_process_backend.stop_all_calls == 1


def test_task_controller_start_when_backend_never_runs_should_timeout() -> None:
    backend = InMemoryTaskBackend(state="Ready", transition_on_start=False)
    controller = WindowsAgentTaskController(
        task_name="CodexRemoteAgent-test",
        backend=backend,
        timeout_seconds=0.01,
        poll_interval_seconds=0.001,
    )

    with pytest.raises(WindowsAgentTaskError, match="启动超时"):
        controller.start()


def test_workspace_configuration_should_allocate_first_free_key(tmp_path: Path) -> None:
    controller = RecordingTaskController()
    configuration, _, _ = _configuration(tmp_path, task_controller=controller)
    second_root = tmp_path / "second"
    second_root.mkdir()
    settings = configuration.load()
    workspaces = [
        *settings.workspaces,
        AgentWorkspaceSettings(
            key="workspace-3",
            display_name="Second",
            root=second_root,
            allow_write=True,
        ),
    ]
    fourth_root = tmp_path / "fourth"
    fourth_root.mkdir()

    updated = configuration.add(workspaces, fourth_root)

    assert updated[-1].key == "workspace-2"


def test_workspace_configuration_should_reject_removing_last_workspace(
    tmp_path: Path,
) -> None:
    configuration, _, _ = _configuration(
        tmp_path,
        task_controller=RecordingTaskController(),
    )
    settings = configuration.load()

    with pytest.raises(ValueError, match="至少需要保留一个项目"):
        configuration.remove(settings.workspaces, settings.workspaces[0].key)


def test_workspace_configuration_apply_should_replace_atomically_and_restart(
    tmp_path: Path,
) -> None:
    controller = RecordingTaskController()
    configuration, config_path, acl_enforcer = _configuration(
        tmp_path,
        task_controller=controller,
    )
    second_root = tmp_path / "second"
    second_root.mkdir()
    workspaces = configuration.add(configuration.load().workspaces, second_root)

    configuration.apply(workspaces)

    persisted = configuration.load()
    assert [workspace.root for workspace in persisted.workspaces] == [
        tmp_path / "first",
        second_root,
    ]
    assert controller.restart_calls == 1
    assert acl_enforcer.paths[-1] == config_path
    assert not list(tmp_path.glob(".agent.toml.*.tmp"))


def test_workspace_configuration_when_restart_fails_should_restore_and_restart_old(
    tmp_path: Path,
) -> None:
    controller = RecordingTaskController(fail_first_restart=True)
    configuration, config_path, _ = _configuration(
        tmp_path,
        task_controller=controller,
    )
    original_content = config_path.read_bytes()
    second_root = tmp_path / "second"
    second_root.mkdir()
    workspaces = configuration.add(configuration.load().workspaces, second_root)

    with pytest.raises(AgentWorkspaceConfigurationError, match="已恢复旧配置"):
        configuration.apply(workspaces)

    assert config_path.read_bytes() == original_content
    assert controller.restart_calls == 2
