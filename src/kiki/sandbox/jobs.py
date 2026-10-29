"""Windows Job Object: memory cap, kill-on-close, and peak accounting.

The worker is started suspended, placed in the job, then resumed, so it never
runs outside the job. Closing the job (or Kiki exiting) kills the worker.
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
from ctypes import wintypes

CREATE_SUSPENDED = 0x4
LIMIT_JOB_MEMORY = 0x200
LIMIT_DIE_ON_UNHANDLED_EXCEPTION = 0x400
LIMIT_KILL_ON_JOB_CLOSE = 0x2000
EXTENDED_LIMIT_INFORMATION = 9


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _BasicLimit(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _ExtendedLimit(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimit),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def supported() -> bool:
    return sys.platform == "win32"


class Job:
    def __init__(self, memory_bytes: int) -> None:
        if not supported():
            raise OSError("Job Objects require Windows")
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._ntdll = ctypes.WinDLL("ntdll")
        k = self._kernel32
        k.CreateJobObjectW.restype = wintypes.HANDLE
        k.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k.QueryInformationJobObject.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
        k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        self._ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]

        self.handle = k.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        info = _ExtendedLimit()
        info.BasicLimitInformation.LimitFlags = (
            LIMIT_JOB_MEMORY | LIMIT_KILL_ON_JOB_CLOSE | LIMIT_DIE_ON_UNHANDLED_EXCEPTION)
        info.JobMemoryLimit = memory_bytes
        if not k.SetInformationJobObject(
                self.handle, EXTENDED_LIMIT_INFORMATION, ctypes.byref(info), ctypes.sizeof(info)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def start(self, argv: list[str]) -> subprocess.Popen[bytes]:
        process = subprocess.Popen(
            argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
            creationflags=CREATE_SUSPENDED, shell=False)
        handle = wintypes.HANDLE(int(process._handle))  # type: ignore[attr-defined]
        if not self._kernel32.AssignProcessToJobObject(self.handle, handle):
            error = ctypes.WinError(ctypes.get_last_error())
            process.kill()
            process.wait()
            raise error
        self._ntdll.NtResumeProcess(handle)
        return process

    def peak_mb(self) -> float:
        info = _ExtendedLimit()
        self._kernel32.QueryInformationJobObject(
            self.handle, EXTENDED_LIMIT_INFORMATION, ctypes.byref(info), ctypes.sizeof(info), None)
        return round(info.PeakJobMemoryUsed / 2**20, 1)

    def close(self) -> None:
        if self.handle:
            self._kernel32.CloseHandle(self.handle)
            self.handle = None
