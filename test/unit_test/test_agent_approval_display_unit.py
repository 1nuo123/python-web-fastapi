"""Agent 审批展示摘要的结构化映射测试。"""

from __future__ import annotations

from src.infrastructure.codex_agent.agent_control_channel import AgentControlChannel


class TestAgentApprovalDisplayUnit:
    """验证官方审批字段只经过确定性、脱敏后的映射。"""

    def test_command_action_when_type_unknown_should_display_command(self) -> None:
        channel = object.__new__(AgentControlChannel)

        display = channel._build_approval_display(  # noqa: SLF001
            mapping={
                "cwd": r"E:\python_web_fastapi\typescript-web-nuxt",
                "commandActions": [
                    {
                        "type": "unknown",
                        "command": "git status --short",
                    }
                ],
            },
            approval_kind="command",
            risk_level="normal",
            reason="Inspect repository state",
        )

        assert display.command_summary == "git status --short"
        assert display.command_actions[0].action_type == "unknown"
        assert display.command_actions[0].command == "git status --short"

    def test_read_only_actions_should_keep_workspace_relative_paths(self) -> None:
        channel = object.__new__(AgentControlChannel)

        display = channel._build_approval_display(  # noqa: SLF001
            mapping={
                "cwd": r"E:\python_web_fastapi\typescript-web-nuxt",
                "commandActions": [
                    {
                        "type": "read",
                        "command": "Get-Content app.vue",
                        "path": (r"E:\python_web_fastapi\typescript-web-nuxt\app.vue"),
                    },
                    {
                        "type": "listFiles",
                        "command": "rg --files app",
                        "path": r"E:\python_web_fastapi\typescript-web-nuxt\app",
                    },
                    {
                        "type": "search",
                        "command": "rg approval app",
                        "path": r"E:\python_web_fastapi\typescript-web-nuxt\app",
                        "query": "approval",
                    },
                ],
            },
            approval_kind="command",
            risk_level="normal",
            reason="Read workspace files",
        )

        assert display.read_only is True
        assert [action.path for action in display.command_actions] == [
            "app.vue",
            "app",
            "app",
        ]
        assert display.working_directory == "."

    def test_legacy_file_changes_should_include_counts_and_sensitive_paths(self) -> None:
        channel = object.__new__(AgentControlChannel)

        display = channel._build_approval_display(  # noqa: SLF001
            mapping={
                "cwd": r"E:\python_web_fastapi\typescript-web-nuxt",
                "fileChanges": {
                    r"E:\python_web_fastapi\typescript-web-nuxt\.env": {
                        "type": "modified",
                        "addedLines": 2,
                        "deletedLines": 1,
                    },
                    r"E:\python_web_fastapi\typescript-web-nuxt\docs\new.md": {
                        "kind": "added",
                        "added_lines": 20,
                        "deleted_lines": 0,
                    },
                },
            },
            approval_kind="file_change",
            risk_level="normal",
            reason="Write documentation",
        )

        assert [change.model_dump() for change in display.file_changes] == [
            {
                "path": ".env",
                "change_kind": "modified",
                "added_lines": 2,
                "deleted_lines": 1,
                "sensitive": True,
            },
            {
                "path": r"docs\new.md",
                "change_kind": "added",
                "added_lines": 20,
                "deleted_lines": 0,
                "sensitive": False,
            },
        ]
