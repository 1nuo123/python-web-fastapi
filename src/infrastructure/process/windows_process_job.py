"""将 Remote 专属子进程及其后代绑定到 Agent 的 Windows 生命周期。"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pywintypes import HANDLE


class WindowsProcessJob:
    """Agent 异常退出或显式关闭时，由内核终止所属进程树。"""

    def __init__(self, process_id: int, *, resume: bool = False) -> None:
        self._handle: HANDLE | None = None
        if os.name != "nt":
            return
        import win32api
        import win32con
        import win32job

        job = win32job.CreateJobObject(None, "")
        try:
            limits = win32job.QueryInformationJobObject(
                job, win32job.JobObjectExtendedLimitInformation
            )
            limits["BasicLimitInformation"]["LimitFlags"] = (
                win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            )
            win32job.SetInformationJobObject(
                job, win32job.JobObjectExtendedLimitInformation, limits
            )
            access = win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE
            if resume:
                access |= 0x0800  # PROCESS_SUSPEND_RESUME
            process = win32api.OpenProcess(access, False, process_id)
            try:
                win32job.AssignProcessToJobObject(job, process)
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
