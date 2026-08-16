"""Windows Agent 设置窗口。"""

from __future__ import annotations

import tkinter
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Final

from src.infrastructure.codex_agent.agent_configuration import (
    AgentBootstrapSettings,
    CodexHostAgentSettings,
    CodexHostAgentSettingsLoader,
)
from src.infrastructure.codex_agent.agent_setup import WindowsEnrollmentUi
from src.infrastructure.codex_agent.agent_workspace_configuration import (
    WindowsAgentWorkspaceConfiguration,
)
from src.infrastructure.codex_agent.agent_workspace_registry import (
    WindowsAgentConfigPermissionVerifier,
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
    "暂停 Agent",
    "退出",
)


class WindowsAgentSettingsWindow:
    """提供网站、项目与 Agent 生命周期入口。"""

    def __init__(
        self,
        *,
        config_path: Path,
        bootstrap: AgentBootstrapSettings,
    ) -> None:
        self._config_path = config_path
        self._bootstrap = bootstrap
        self._settings_loader = CodexHostAgentSettingsLoader(WindowsAgentConfigPermissionVerifier())
        self._task_controller = WindowsAgentTaskController(config_path=config_path)
        self._workspace_configuration = WindowsAgentWorkspaceConfiguration(
            config_path=config_path,
            settings_loader=self._settings_loader,
            acl_enforcer=WindowsCurrentUserAclEnforcer(),
            task_controller=self._task_controller,
        )
        self._root: tkinter.Tk | None = None
        self._status_variable: tkinter.StringVar | None = None

    def show(self) -> None:
        """运行 Windows 设置窗口。"""

        from tkinter import ttk

        root = tkinter.Tk()
        self._root = root
        root.title("Codex Remote Agent 设置")
        root.resizable(False, False)
        root.attributes("-topmost", True)
        frame = ttk.Frame(root, padding=16)
        frame.grid(row=0, column=0, sticky="nsew")
        status_variable = tkinter.StringVar(value=self._read_status_label())
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
        )
        for index, (label, callback) in enumerate(actions):
            ttk.Button(frame, text=label, command=callback, width=20).grid(
                row=index // 2 + 1,
                column=index % 2,
                padx=4,
                pady=4,
                sticky="ew",
            )
        root.mainloop()
        self._root = None
        self._status_variable = None

    def _open_website(self) -> None:
        from tkinter import messagebox

        try:
            opened = webbrowser.open(self._bootstrap.require_connection().website_url)
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
        dialog.attributes("-topmost", True)
        frame = ttk.Frame(dialog, padding=16)
        frame.grid(row=0, column=0, sticky="nsew")
        workspaces = list(settings.workspaces)
        listbox = tkinter.Listbox(frame, width=64, height=10, exportselection=False)
        listbox.grid(row=0, column=0, columnspan=4, sticky="nsew", pady=(0, 12))

        def refresh_list() -> None:
            listbox.delete(0, tkinter.END)
            for workspace in workspaces:
                permission = "可写" if workspace.allow_write else "只读"
                listbox.insert(
                    tkinter.END,
                    f"{workspace.display_name}  [{permission}]  {workspace.root}",
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

        def apply_workspaces() -> None:
            confirmed = messagebox.askyesno(
                "Codex Remote Agent",
                "保存项目配置并立即重启 Agent？",
                parent=dialog,
            )
            if not confirmed:
                return
            try:
                self._workspace_configuration.apply(workspaces)
                self._refresh_status()
                dialog.destroy()
                messagebox.showinfo(
                    "Codex Remote Agent",
                    "项目配置已保存，Agent 已重新启动。",
                    parent=root,
                )
            except (OSError, PermissionError, ValueError) as exc:
                messagebox.showerror("Codex Remote Agent", str(exc), parent=dialog)

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
        refresh_list()
        dialog.wait_window()

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
    ) -> None:
        from tkinter import messagebox

        try:
            action()
            self._refresh_status()
            messagebox.showinfo("Codex Remote Agent", success_message)
        except (OSError, WindowsAgentTaskError) as exc:
            self._refresh_status()
            messagebox.showerror("Codex Remote Agent", str(exc))

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
        task_label = "Agent 运行中" if task_status.is_running else "Agent 已暂停"
        return f"状态：已连接 {settings.agent.display_name} · {task_label}"

    def _refresh_status(self) -> None:
        if self._status_variable is not None:
            self._status_variable.set(self._read_status_label())
