"""将 Remote 专属子进程及其后代绑定到 Agent 的 Windows 生命周期。"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Protocol, cast


class WindowsHandle(Protocol):
    def __int__(self) -> int: ...
    def Close(self) -> None: ...


class WindowsProcessJob:
    """Agent 异常退出或显式关闭时，由内核终止所属进程树。"""

    def __init__(self, process_id: int, *, resume: bool = False) -> None:
        self._handle: WindowsHandle | None = None
        if os.name != "nt":
            return
        import win32api
        import win32con
        import win32job

        job = cast(Callable[[None, str], WindowsHandle], win32job.CreateJobObject)(None, "")
        try:
            limits = win32job.QueryInformationJobObject(
                int(job), win32job.JobObjectExtendedLimitInformation
            )
            limits["BasicLimitInformation"]["LimitFlags"] = (
                win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            )
            win32job.SetInformationJobObject(
                int(job), win32job.JobObjectExtendedLimitInformation, limits
            )
            access = win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE
            if resume:
                access |= 0x0800  # PROCESS_SUSPEND_RESUME
            process = cast(WindowsHandle, win32api.OpenProcess(access, False, process_id))
            try:
                win32job.AssignProcessToJobObject(int(job), int(process))
                if resume:
                    import ctypes

                    resume_process = ctypes.WinDLL("ntdll").NtResumeProcess
                    resume_process.argtypes = [ctypes.c_void_p]
                    resume_process.restype = ctypes.c_long
                    status = resume_process(int(process))
                    if status < 0:
                        raise OSError(f"Remote 进程恢复失败 (NTSTATUS {status:#x})。")
            finally:
                process.Close()
        except BaseException:
            job.Close()
            raise
        self._handle = job

    def close(self) -> None:
        """只终止此监督器创建的进程，不扫描或终止独立 CLI。"""
        handle, self._handle = self._handle, None
        if handle is not None:
            handle.Close()

    def terminate(self) -> None:
        """保留句柄直到成员清空，不能把关闭句柄当作退出证明。"""
        if self._handle is not None:
            import win32job

            win32job.TerminateJobObject(int(self._handle), 1)

    @property
    def active_processes(self) -> int:
        if self._handle is None:
            return 0
        import win32job

        return int(
            win32job.QueryInformationJobObject(
                int(self._handle), win32job.JobObjectBasicAccountingInformation
            )["ActiveProcesses"]
        )
