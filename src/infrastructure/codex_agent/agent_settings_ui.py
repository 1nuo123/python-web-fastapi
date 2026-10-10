"""Windows Agent 设置窗口。"""

from __future__ import annotations

import tkinter
import asyncio
import os
import webbrowser
from concurrent.futures import Future, ThreadPoolExecutor
from collections.abc import Callable
from pathlib import Path
from typing import Final, cast

from src.core.codex_contract.workspace_contract import (
    ProjectExecutionOverrides,
    CodexWorkspaceExecutionPreferences,
)
from src.infrastructure.codex_agent.agent_configuration import (
    AgentBootstrapSettings,
    CodexHostAgentSettings,
    CodexHostAgentSettingsLoader,
)
from src.infrastructure.codex_agent.agent_deployment_profile import AgentDeploymentProfile
from src.infrastructure.codex_agent.agent_setup import WindowsEnrollmentUi
from src.infrastructure.codex_agent.agent_doctor import AgentDoctor
from src.infrastructure.codex_agent.agent_secret_store import WindowsAgentSecretStore
from src.infrastructure.codex_agent.windows_dpapi_device_key_store import WindowsDpapiDeviceKeyStore
from src.infrastructure.worktree.git_worktree_adapter import GitWorktreeAdapter
from src.core.worktree_contract.worktree_contract import (
    GitWorktreeRemoveRequest,
    GitWorktreeSnapshot,
)
from src.infrastructure.codex_agent.agent_runtime_status_store import AgentRuntimeStatusStore
from src.infrastructure.codex_agent.agent_workspace_configuration import (
    WindowsAgentWorkspaceConfiguration,
)
from src.infrastructure.codex_agent.agent_workspace_registry import (
    WindowsAgentConfigPermissionVerifier,
    AgentWorkspaceRegistry,
)
from src.infrastructure.codex_agent.windows_agent_task import (
    WindowsAgentTaskController,
    WindowsAgentTaskError,
)
from src.infrastructure.codex_agent.windows_dpapi_device_key_store import (
    WindowsCurrentUserAclEnforcer,
)

SETTINGS_ACTION_LABELS: Final = (
    "打开网站",
    "管理项目",
    "启动 Agent",
    "重启 Agent",
    "停止 Agent",
    "关闭设置",
)


class WindowsAgentSettingsWindow:
    """提供网站、项目与 Agent 生命周期入口。"""

    def __init__(
        self,
        *,
        config_path: Path,
        bootstrap: AgentBootstrapSettings,
        deployment_profile: AgentDeploymentProfile = AgentDeploymentProfile.PRODUCTION,
    ) -> None:
        self._config_path = config_path
        self._bootstrap = bootstrap
        self._settings_loader = CodexHostAgentSettingsLoader(WindowsAgentConfigPermissionVerifier())
        self._task_controller = WindowsAgentTaskController(
            config_path=config_path,
            deployment_profile=deployment_profile,
        )
        self._workspace_configuration = WindowsAgentWorkspaceConfiguration(
            config_path=config_path,
            settings_loader=self._settings_loader,
            acl_enforcer=WindowsCurrentUserAclEnforcer(),
            task_controller=self._task_controller,
        )
        self._root: tkinter.Tk | None = None
        self._status_variable: tkinter.StringVar | None = None
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="agent-settings")
        self._action_future: Future[object] | None = None
        self._status_future: Future[str] | None = None

    def show(self) -> None:
        """运行 Windows 设置窗口。"""

        from tkinter import ttk

        root = tkinter.Tk()
        self._root = root
        root.title("Codex Remote Agent 设置")
        root.resizable(True, True)
        frame = ttk.Frame(root, padding=16)
        frame.grid(row=0, column=0, sticky="nsew")
        status_variable = tkinter.StringVar(value="正在读取本机状态…")
        self._status_variable = status_variable
        ttk.Label(frame, textvariable=status_variable).grid(
            row=0,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(0, 12),
        )
        actions = (
            (SETTINGS_ACTION_LABELS[0], self._open_website),
            (SETTINGS_ACTION_LABELS[1], self._manage_workspaces),
            (SETTINGS_ACTION_LABELS[2], self._start_agent),
            (SETTINGS_ACTION_LABELS[3], self._restart_agent),
            (SETTINGS_ACTION_LABELS[4], self._pause_agent),
            (SETTINGS_ACTION_LABELS[5], root.destroy),
            ("诊断", self._run_doctor),
            ("隔离工作树", self._manage_worktrees),
        )
        for index, (label, callback) in enumerate(actions):
            ttk.Button(frame, text=label, command=callback, width=20).grid(
                row=index // 2 + 1,
                column=index % 2,
                padx=4,
                pady=4,
                sticky="ew",
            )
        root.after(0, self._poll_status)
        root.mainloop()
        self._executor.shutdown(wait=False, cancel_futures=True)
        self._root = None
        self._status_variable = None

    def _open_website(self) -> None:
        from tkinter import messagebox

        try:
            opened = webbrowser.open(
                self._bootstrap.require_connection().website_url.rstrip("/") + "/codex/tasks"
            )
            if not opened:
                raise OSError("无法打开默认浏览器。")
        except (OSError, ValueError) as exc:
            messagebox.showerror("Codex Remote Agent", str(exc))

    def _manage_workspaces(self) -> None:
        from tkinter import messagebox, ttk

        root = self._root
        if root is None:
            return
        try:
            settings = self._workspace_configuration.load()
        except (OSError, PermissionError, ValueError) as exc:
            messagebox.showerror("Codex Remote Agent", str(exc))
            return

        dialog = tkinter.Toplevel(root)
        dialog.title("管理项目")
        dialog.resizable(False, False)
        dialog.transient(root)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=16)
        frame.grid(row=0, column=0, sticky="nsew")
        workspaces = list(settings.workspaces)
        listbox = tkinter.Listbox(frame, width=64, height=10, exportselection=False)
        listbox.grid(row=0, column=0, columnspan=4, sticky="nsew", pady=(0, 12))

        def refresh_list() -> None:
            listbox.delete(0, tkinter.END)
            for index, workspace in enumerate(workspaces):
                permission = "可写" if workspace.allow_write else "只读"
                listbox.insert(
                    tkinter.END,
                    f"{workspace.display_name} {'（默认）' if index == 0 else ''}  [{permission}]  {workspace.root}",
                )
            if workspaces:
                listbox.selection_set(0)

        def add_workspace() -> None:
            nonlocal workspaces
            try:
                selected_root = WindowsEnrollmentUi().select_workspace()
                workspaces = self._workspace_configuration.add(
                    workspaces,
                    selected_root,
                )
                refresh_list()
                listbox.selection_clear(0, tkinter.END)
                listbox.selection_set(len(workspaces) - 1)
            except PermissionError:
                return
            except (OSError, ValueError) as exc:
                messagebox.showerror("Codex Remote Agent", str(exc), parent=dialog)

        def remove_workspace() -> None:
            nonlocal workspaces
            if len(workspaces) <= 1:
                messagebox.showinfo("Codex Remote Agent", "至少需要保留一个项目。", parent=dialog)
                return
            selection = listbox.curselection()
            if not selection:
                messagebox.showinfo(
                    "Codex Remote Agent",
                    "请先选择要删除的项目。",
                    parent=dialog,
                )
                return
            workspace = workspaces[selection[0]]
            confirmed = messagebox.askyesno(
                "Codex Remote Agent",
                f"确定删除项目“{workspace.display_name}”吗？",
                parent=dialog,
            )
            if not confirmed:
                return
            try:
                workspaces = self._workspace_configuration.remove(
                    workspaces,
                    workspace.key,
                )
                refresh_list()
            except ValueError as exc:
                messagebox.showerror("Codex Remote Agent", str(exc), parent=dialog)

        def edit_workspace() -> None:
            selection = listbox.curselection()
            if not selection:
                return
            index = selection[0]
            workspace = workspaces[index]
            editor = tkinter.Toplevel(dialog)
            editor.title("项目设置")
            editor.transient(dialog)
            editor.grab_set()
            name = tkinter.StringVar(value=workspace.display_name)
            model = tkinter.StringVar(value=workspace.execution_overrides.model or "")
            effort = tkinter.StringVar(value=workspace.execution_overrides.reasoning_effort or "")
            mode = tkinter.StringVar(
                value={
                    "inherit": "继承本机配置",
                    "restricted": "受限访问",
                    "full_access": "完全访问",
                }[workspace.execution_overrides.permission_mode]
            )
            for row, (label, value) in enumerate(
                (("名称", name), ("模型（留空继承）", model), ("推理档位（留空继承）", effort))
            ):
                ttk.Label(editor, text=label).grid(row=row, column=0, padx=8, pady=6)
                ttk.Entry(editor, textvariable=value, width=35).grid(
                    row=row, column=1, padx=8, pady=6
                )
            ttk.Label(editor, text="访问模式").grid(row=3, column=0, padx=8)
            ttk.Combobox(
                editor,
                textvariable=mode,
                state="readonly",
                values=("继承本机配置", "受限访问", "完全访问"),
            ).grid(row=3, column=1, padx=8)
            ttk.Label(editor, text="应用前校验本机能力；执行设置保存后在下一轮生效。").grid(
                row=4, column=0, columnspan=2, padx=8, pady=8
            )

            effective_label = tkinter.StringVar(
                value=f"本机项目版本：{workspace.execution_revision}；正在核对有效设置…"
            )
            ttk.Label(editor, textvariable=effective_label, wraplength=420).grid(
                row=6, column=0, columnspan=2, padx=8, pady=8
            )

            def show_effective(result: object) -> None:
                if editor.winfo_exists():
                    effective = cast(list[CodexWorkspaceExecutionPreferences], result)[0]
                    effective_label.set(
                        f"本机项目版本：{effective.local_revision}；{effective.model} / {effective.reasoning_effort}；{effective.sandbox_mode.value} / {effective.approval_policy.value}"
                    )

            self._run_task_action(
                action=lambda: self._workspace_configuration.read_execution_settings([workspace]),
                success_message="",
                on_success=show_effective,
            )

            def save_draft() -> None:
                try:
                    overrides = ProjectExecutionOverrides(
                        model=model.get().strip() or None,
                        reasoning_effort=effort.get().strip() or None,
                        permission_mode={
                            "继承本机配置": "inherit",
                            "受限访问": "restricted",
                            "完全访问": "full_access",
                        }[mode.get()],
                    )
                    updated = workspace.model_validate(
                        {
                            **workspace.model_dump(),
                            "display_name": name.get().strip(),
                            "execution_overrides": overrides,
                        }
                    )
                    workspaces[index] = updated
                    refresh_list()
                    editor.destroy()
                    dialog.grab_set()
                except ValueError as exc:
                    messagebox.showerror("项目设置", str(exc), parent=editor)

            ttk.Button(editor, text="确定草稿", command=save_draft).grid(row=5, column=1, pady=8)

        def apply_workspaces() -> None:
            if self._action_future is not None:
                messagebox.showinfo("项目设置", "正在核对本机设置，请稍候再应用。", parent=dialog)
                return
            if workspaces == list(settings.workspaces):
                dialog.destroy()
                return
            confirmed = messagebox.askyesno(
                "Codex Remote Agent",
                "应用项目草稿？执行设置在下一轮生效；目录、名称或集合改变时会重启 Agent。",
                parent=dialog,
            )
            if not confirmed:
                return
            submitted = list(workspaces)
            dialog.destroy()
            self._run_task_action(
                action=lambda: self._workspace_configuration.apply(
                    submitted, expected=list(settings.workspaces)
                ),
                success_message="项目配置已应用；执行设置将在下一轮使用。",
            )

        ttk.Button(frame, text="增加", command=add_workspace, width=14).grid(
            row=1, column=0, padx=4, pady=4
        )
        ttk.Button(frame, text="删除", command=remove_workspace, width=14).grid(
            row=1, column=1, padx=4, pady=4
        )
        ttk.Button(frame, text="确定", command=apply_workspaces, width=14).grid(
            row=1, column=2, padx=4, pady=4
        )
        ttk.Button(frame, text="取消", command=dialog.destroy, width=14).grid(
            row=1, column=3, padx=4, pady=4
        )
        ttk.Button(frame, text="编辑设置", command=edit_workspace).grid(
            row=2, column=0, padx=4, pady=4
        )
        refresh_list()
        dialog.wait_window()

    def _run_doctor(self) -> None:
        def diagnose() -> None:
            settings = self._load_settings()
            report = asyncio.run(
                AgentDoctor(
                    settings=settings,
                    secret_store=WindowsAgentSecretStore(),
                    device_key_store=WindowsDpapiDeviceKeyStore(
                        root=settings.agent.state_database.parent / "keys"
                    ),
                ).run()
            )
            from datetime import UTC, datetime
            from src.core.codex_contract.agent_runtime_health_contract import AgentRuntimeStatus

            status = AgentRuntimeStatus.from_doctor_report(report, checked_at=datetime.now(UTC))
            AgentRuntimeStatusStore(settings.agent.state_database).update(
                status.model_dump(exclude_none=True)
            )
            if report.exit_code:
                raise OSError(
                    "；".join(
                        check.detail or check.reason_code
                        for check in report.checks
                        if check.state != "pass"
                    )
                )

        self._run_task_action(action=diagnose, success_message="诊断完成，已有环境检查通过。")

    def _manage_worktrees(self) -> None:
        def load_worktrees() -> object:
            settings = self._load_settings()
            registry = AgentWorkspaceRegistry(
                [workspace.to_definition() for workspace in settings.workspaces]
            )
            adapter = GitWorktreeAdapter(registry)
            items = [
                item
                for workspace in settings.workspaces
                if (workspace.root / ".git").exists()
                for item in adapter.list(workspace.key).items
            ]
            return adapter, items

        self._run_task_action(
            action=load_worktrees, success_message="", on_success=self._show_worktrees
        )

    def _show_worktrees(self, result: object) -> None:
        from tkinter import messagebox, ttk

        adapter, items = cast(tuple[GitWorktreeAdapter, list[GitWorktreeSnapshot]], result)
        dialog = tkinter.Toplevel(self._root)
        dialog.title("隔离工作树")
        box = tkinter.Listbox(dialog, width=90, height=12)
        box.pack(padx=12, pady=12)
        for item in items:
            box.insert(
                tkinter.END,
                f"{item.state.value} · {'有修改，保留' if item.dirty else '干净'} · {item.path}",
            )
        ttk.Label(
            dialog,
            text="归档后保留到期；有修改的目录不会自动删除。请在本机复制结果或使用 Git 提交、合并。",
        ).pack(padx=12)

        def open_directory() -> None:
            if box.curselection():
                os.startfile(str(items[box.curselection()[0]].path))

        def cleanup() -> None:
            if not box.curselection():
                return
            item = items[box.curselection()[0]]
            if not messagebox.askyesno(
                "清理工作树",
                "仅清理已归档且没有修改的目录。清理后旧会话不能继续执行，是否继续？",
                parent=dialog,
            ):
                return

            def remove_worktree() -> None:
                result = adapter.remove(
                    GitWorktreeRemoveRequest(
                        workspace_key=item.workspace_key,
                        worktree_id=item.worktree_id,
                        require_archived=True,
                    )
                )
                if not result.success:
                    raise OSError(result.message or "工作树未清理。")

            dialog.destroy()
            self._run_task_action(
                action=remove_worktree,
                success_message="已清理选中工作树；会话审计和原项目保持不变。",
            )

        ttk.Button(dialog, text="打开目录", command=open_directory).pack(
            side="left", padx=12, pady=12
        )
        ttk.Button(dialog, text="清理选中工作树", command=cleanup).pack(
            side="right", padx=12, pady=12
        )

    def _start_agent(self) -> None:
        self._run_task_action(
            action=self._task_controller.start,
            success_message="Agent 已启动。",
        )

    def _restart_agent(self) -> None:
        self._run_task_action(
            action=self._task_controller.restart,
            success_message="Agent 已重新启动。",
        )

    def _pause_agent(self) -> None:
        self._run_task_action(
            action=self._task_controller.pause,
            success_message="Agent 已暂停。",
        )

    def _run_task_action(
        self,
        *,
        action: Callable[[], object],
        success_message: str,
        on_success: Callable[[object], None] | None = None,
    ) -> None:
        from tkinter import messagebox

        if self._root is None or self._action_future is not None:
            return
        self._action_future = self._executor.submit(action)
        if self._status_variable is not None:
            self._status_variable.set("正在执行，请稍候…")

        def finish() -> None:
            future = self._action_future
            if self._root is None or future is None:
                return
            if not future.done():
                self._root.after(100, finish)
                return
            self._action_future = None
            try:
                result = future.result()
                if on_success is not None:
                    on_success(result)
                elif success_message:
                    messagebox.showinfo("Codex Remote Agent", success_message)
            except (OSError, RuntimeError, ValueError, WindowsAgentTaskError) as exc:
                messagebox.showerror("Codex Remote Agent", str(exc))
            self._refresh_status()

        self._root.after(100, finish)

    def _load_settings(self) -> CodexHostAgentSettings:
        return self._workspace_configuration.load()

    def _read_status_label(self) -> str:
        if not self._config_path.exists():
            if self._bootstrap.deployment_state == "unconfigured":
                return "状态：安装包尚未配置正式服务器"
            return "状态：等待连接电脑"
        try:
            settings = self._load_settings()
            task_status = self._task_controller.read_status()
        except (OSError, PermissionError, ValueError):
            return "状态：本地配置或计划任务需要修复"
        if not task_status.is_running:
            return "状态：Agent 已停止"
        observed = AgentRuntimeStatusStore(settings.agent.state_database).read()
        if observed is None:
            return "状态：进程运行中，连接尚未确认"
        labels = {
            "starting": "检查本机 Codex",
            "connecting": "连接中",
            "online": "已上线",
            "offline": "连接已断开",
            "blocked": "连接受阻",
            "stopped": "已停止",
        }
        label = labels.get(observed.connection_state, "连接尚未确认")
        reason = observed.connection_reason or "、".join(observed.doctor_issue_codes)
        return f"状态：{settings.agent.display_name} · {label}" + (
            f"\n诊断：{reason}" if reason else ""
        )

    def _refresh_status(self) -> None:
        if self._status_future is None:
            self._status_future = self._executor.submit(self._read_status_label)

    def _poll_status(self) -> None:
        if self._root is None:
            return
        if self._status_future is not None and self._status_future.done():
            if self._status_variable is not None and self._action_future is None:
                self._status_variable.set(self._status_future.result())
            self._status_future = None
        self._refresh_status()
        self._root.after(1000, self._poll_status)
