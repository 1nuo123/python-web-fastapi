"""首装与设置窗口共用的连接参数表单。"""

from __future__ import annotations

import tkinter
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from src.infrastructure.codex_agent.agent_network_policy import (
    AgentNetworkPolicy,
    AgentNetworkSettings,
)


def edit_connection_settings(binary: str, network: AgentNetworkSettings, *, parent=None):
    dialog = tkinter.Toplevel(parent) if parent else tkinter.Tk()
    dialog.title("连接设置")
    result = None
    executable = tkinter.StringVar(master=dialog, value=binary)
    mode = tkinter.StringVar(master=dialog, value=network.network_mode)
    proxy = tkinter.StringVar(master=dialog, value=network.proxy_url or "")
    certificate = tkinter.StringVar(master=dialog, value=str(network.ca_certificate_path or ""))
    for row, (label, variable) in enumerate(
        (("Codex 程序", executable), ("代理地址", proxy), ("附加 CA 证书", certificate))
    ):
        ttk.Label(dialog, text=label).grid(row=row, column=0, padx=8, pady=6)
        ttk.Entry(dialog, textvariable=variable, width=52).grid(row=row, column=1, padx=8)

    def choose(variable):
        path = filedialog.askopenfilename(parent=dialog)
        if path:
            variable.set(path)

    ttk.Button(dialog, text="选择程序", command=lambda: choose(executable)).grid(row=0, column=2)
    ttk.Button(dialog, text="选择证书", command=lambda: choose(certificate)).grid(row=2, column=2)
    ttk.Label(dialog, text="网络模式").grid(row=3, column=0)
    ttk.Combobox(
        dialog, textvariable=mode, values=("system", "direct", "explicit"), state="readonly"
    ).grid(row=3, column=1, sticky="w")
    ttk.Label(
        dialog,
        text="系统模式使用系统 HTTP/HTTPS 代理；PAC 环境请填写代理地址。已有连接在下次启动时使用新设置。",
        wraplength=440,
    ).grid(row=4, column=0, columnspan=3, padx=8, pady=8)

    def save():
        nonlocal result
        try:
            updated = replace(
                network,
                network_mode=mode.get(),
                proxy_url=proxy.get().strip() if mode.get() == "explicit" else None,
                ca_certificate_path=Path(certificate.get().strip())
                if certificate.get().strip()
                else None,
            )
            AgentNetworkPolicy(updated)
            if not executable.get().strip():
                raise ValueError("请选择 Codex 程序。")
            result = executable.get().strip(), updated
            dialog.destroy()
        except (OSError, ValueError) as exc:
            messagebox.showerror("连接设置", str(exc), parent=dialog)

    ttk.Button(dialog, text="保存并继续", command=save).grid(row=5, column=1, pady=8)
    dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
    if parent:
        dialog.transient(parent)
        dialog.grab_set()
        parent.wait_window(dialog)
    else:
        dialog.mainloop()
    return result
