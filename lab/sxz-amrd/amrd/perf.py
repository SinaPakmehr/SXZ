"""Portable-enough process memory measurement for the Windows workspace."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes


class _PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


def peak_working_set_bytes() -> int:
    if os.name != "nt":
        return 0
    counters = _PROCESS_MEMORY_COUNTERS_EX()
    counters.cb = ctypes.sizeof(counters)
    process = ctypes.windll.kernel32.GetCurrentProcess()
    function = ctypes.windll.psapi.GetProcessMemoryInfo
    function.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_PROCESS_MEMORY_COUNTERS_EX),
        wintypes.DWORD,
    ]
    function.restype = wintypes.BOOL
    ok = function(process, ctypes.byref(counters), counters.cb)
    if not ok:
        return 0
    return int(counters.PeakWorkingSetSize)


def peak_working_set_mb() -> float:
    return peak_working_set_bytes() / (1 << 20)
