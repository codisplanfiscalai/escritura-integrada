"""Processo Windows suspenso associado a um Job Object antes de executar.

O supervisor do smoke usa apenas este job anônimo. Fechar seu handle encerra
todos os descendentes, inclusive QtWebEngineProcess, sem atingir outros apps.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path
import subprocess
import sys


class _StartupInfo(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
        ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _ProcessInfo(ctypes.Structure):
    _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong), ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD), ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
    )]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _BasicLimits), ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


class _Accounting(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_longlong), ("TotalKernelTime", ctypes.c_longlong),
        ("ThisPeriodTotalUserTime", ctypes.c_longlong),
        ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
        ("TotalPageFaultCount", wintypes.DWORD), ("TotalProcesses", wintypes.DWORD),
        ("ActiveProcesses", wintypes.DWORD), ("TotalTerminatedProcesses", wintypes.DWORD),
    ]


class WindowsJobProcess:
    def __init__(self):
        if sys.platform != "win32":
            raise OSError("O supervisor de processos exige Windows.")
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.job = None
        self.process = None
        self.pid = None
        self._declare_api()
        self.job = self.api.CreateJobObjectW(None, None)
        if not self.job:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = _ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.api.SetInformationJobObject(self.job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def _declare_api(self):
        api = self.api
        api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        api.CreateJobObjectW.restype = wintypes.HANDLE
        api.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        api.SetInformationJobObject.restype = wintypes.BOOL
        api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        api.AssignProcessToJobObject.restype = wintypes.BOOL
        api.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
        api.QueryInformationJobObject.restype = wintypes.BOOL
        api.CreateProcessW.argtypes = [
            wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
            wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
            ctypes.POINTER(_StartupInfo), ctypes.POINTER(_ProcessInfo),
        ]
        api.CreateProcessW.restype = wintypes.BOOL
        api.ResumeThread.argtypes = [wintypes.HANDLE]
        api.ResumeThread.restype = wintypes.DWORD
        api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        api.WaitForSingleObject.restype = wintypes.DWORD
        api.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        api.GetExitCodeProcess.restype = wintypes.BOOL
        api.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        api.TerminateProcess.restype = wintypes.BOOL
        api.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        api.TerminateJobObject.restype = wintypes.BOOL
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        api.CloseHandle.restype = wintypes.BOOL

    def start(self, executable: Path, *, environment: dict[str, str], cwd: Path):
        if self.process:
            raise RuntimeError("O job já possui um processo principal.")
        info, startup = _ProcessInfo(), _StartupInfo()
        startup.cb = ctypes.sizeof(startup)
        command = ctypes.create_unicode_buffer(subprocess.list2cmdline([str(executable)]))
        block = ctypes.create_unicode_buffer("\0".join(f"{k}={v}" for k, v in sorted(environment.items(), key=lambda item: item[0].upper())) + "\0\0")
        # CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT: nenhum filho pode nascer antes do job.
        if not self.api.CreateProcessW(str(executable), command, None, None, False, 0x4 | 0x400,
                                       ctypes.cast(block, ctypes.c_void_p), str(cwd),
                                       ctypes.byref(startup), ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        self.process, self.pid = info.hProcess, int(info.dwProcessId)
        try:
            if not self.api.AssignProcessToJobObject(self.job, self.process):
                raise ctypes.WinError(ctypes.get_last_error())
            if self.api.ResumeThread(info.hThread) == 0xFFFFFFFF:
                raise ctypes.WinError(ctypes.get_last_error())
        except Exception:
            # O processo ainda pode estar suspenso e fora do job se a associação falhou.
            self.api.TerminateProcess(self.process, 1)
            self.api.WaitForSingleObject(self.process, 5000)
            raise
        finally:
            self.api.CloseHandle(info.hThread)

    def poll(self) -> int | None:
        if not self.process:
            return None
        state = self.api.WaitForSingleObject(self.process, 0)
        if state == 258:  # WAIT_TIMEOUT
            return None
        if state != 0:
            raise ctypes.WinError(ctypes.get_last_error())
        code = wintypes.DWORD()
        if not self.api.GetExitCodeProcess(self.process, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(code.value)

    def accounting(self) -> dict:
        values = _Accounting()
        if not self.api.QueryInformationJobObject(self.job, 1, ctypes.byref(values), ctypes.sizeof(values), None):
            raise ctypes.WinError(ctypes.get_last_error())
        return {"active_processes": int(values.ActiveProcesses),
                "total_processes": int(values.TotalProcesses),
                "terminated_processes": int(values.TotalTerminatedProcesses)}

    def terminate(self):
        if self.job and not self.api.TerminateJobObject(self.job, 1):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.process:
            self.api.CloseHandle(self.process)
            self.process = None
        if self.job:
            # Kill-on-close também protege uma interrupção do supervisor.
            self.api.CloseHandle(self.job)
            self.job = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
