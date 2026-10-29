"""Minimal Windows Job Object helper: memory cap, kill-on-close, peak accounting."""

import ctypes
import subprocess
from ctypes import wintypes

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
ntdll = ctypes.WinDLL("ntdll")

CREATE_SUSPENDED = 0x4
LIMIT_PROCESS_MEMORY = 0x100
LIMIT_JOB_MEMORY = 0x200
LIMIT_KILL_ON_JOB_CLOSE = 0x2000
LIMIT_DIE_ON_UNHANDLED_EXCEPTION = 0x400
EXTENDED_LIMIT_INFORMATION = 9


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class BASIC_LIMIT(ctypes.Structure):
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


class EXTENDED_LIMIT(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", BASIC_LIMIT),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


kernel32.CreateJobObjectW.restype = wintypes.HANDLE
kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
kernel32.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]


class Job:
    def __init__(self, job_memory_bytes: int) -> None:
        self.handle = kernel32.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        info = EXTENDED_LIMIT()
        info.BasicLimitInformation.LimitFlags = (
            LIMIT_JOB_MEMORY | LIMIT_KILL_ON_JOB_CLOSE | LIMIT_DIE_ON_UNHANDLED_EXCEPTION)
        info.JobMemoryLimit = job_memory_bytes
        if not kernel32.SetInformationJobObject(
                self.handle, EXTENDED_LIMIT_INFORMATION, ctypes.byref(info), ctypes.sizeof(info)):
            raise ctypes.WinError(ctypes.get_last_error())

    def start(self, argv: list[str]) -> subprocess.Popen:
        process = subprocess.Popen(
            argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
            creationflags=CREATE_SUSPENDED, shell=False)
        handle = wintypes.HANDLE(int(process._handle))
        if not kernel32.AssignProcessToJobObject(self.handle, handle):
            process.kill()
            raise ctypes.WinError(ctypes.get_last_error())
        ntdll.NtResumeProcess(handle)
        return process

    def peak_mb(self) -> float:
        info = EXTENDED_LIMIT()
        kernel32.QueryInformationJobObject(
            self.handle, EXTENDED_LIMIT_INFORMATION, ctypes.byref(info), ctypes.sizeof(info), None)
        return round(info.PeakJobMemoryUsed / 2**20, 1)

    def close(self) -> None:
        kernel32.CloseHandle(self.handle)
