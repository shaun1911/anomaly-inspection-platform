"""系统指标采集（Windows 原生，不引第三方依赖）。

- CPU：GetSystemTimes 差分（首次调用返回 None，第二次起有效）
- 内存：GlobalMemoryStatusEx
- 进程内存：GetProcessMemoryInfo
- GPU：nvidia-smi（存在则采，失败返回 None）
- 模型加载：当前为 FakePredictor，不常驻真实模型，接口如实报告
"""

from __future__ import annotations

import ctypes
import shutil
import subprocess
import sys
import time
from pathlib import Path

_IS_WIN = sys.platform == "win32"
_START = time.time()
_LAST_CPU: tuple[int, int, int] | None = None


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", ctypes.c_uint32), ("dwHighDateTime", ctypes.c_uint32)]


def _ft(value: _FILETIME) -> int:
    return (value.dwHighDateTime << 32) | value.dwLowDateTime


def _system_times() -> tuple[int, int, int] | None:
    if not _IS_WIN:
        return None
    idle, kernel, user = _FILETIME(), _FILETIME(), _FILETIME()
    ok = ctypes.windll.kernel32.GetSystemTimes(
        ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
    )
    if not ok:
        return None
    return _ft(idle), _ft(kernel), _ft(user)


def cpu_percent() -> float | None:
    global _LAST_CPU
    now = _system_times()
    if now is None:
        return None
    if _LAST_CPU is None:
        # 首次调用没有基线：短暂采样一次，保证首屏就有数字
        time.sleep(0.15)
        first = now
        now = _system_times()
        if now is None:
            return None
        _LAST_CPU = first
    idle_d = now[0] - _LAST_CPU[0]
    total_d = (now[1] - _LAST_CPU[1]) + (now[2] - _LAST_CPU[2])
    _LAST_CPU = now
    if total_d <= 0:
        return None
    busy = 1.0 - idle_d / total_d
    return round(max(0.0, min(1.0, busy)) * 100, 1)


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_uint32),
        ("dwMemoryLoad", ctypes.c_uint32),
        ("ullTotalPhys", ctypes.c_uint64),
        ("ullAvailPhys", ctypes.c_uint64),
        ("ullTotalPageFile", ctypes.c_uint64),
        ("ullAvailPageFile", ctypes.c_uint64),
        ("ullTotalVirtual", ctypes.c_uint64),
        ("ullAvailVirtual", ctypes.c_uint64),
        ("ullAvailExtendedVirtual", ctypes.c_uint64),
    ]


def memory() -> dict | None:
    if not _IS_WIN:
        return None
    status = _MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    used = status.ullTotalPhys - status.ullAvailPhys
    return {
        "total": status.ullTotalPhys,
        "available": status.ullAvailPhys,
        "used": used,
        "percent": round(used / status.ullTotalPhys * 100, 1) if status.ullTotalPhys else None,
    }


class _PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_uint32),
        ("PageFaultCount", ctypes.c_uint32),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def process_rss() -> int | None:
    if not _IS_WIN:
        return None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(_PROCESS_MEMORY_COUNTERS), ctypes.c_uint32
    ]
    psapi.GetProcessMemoryInfo.restype = ctypes.c_int

    counters = _PROCESS_MEMORY_COUNTERS()
    counters.cb = ctypes.sizeof(_PROCESS_MEMORY_COUNTERS)
    handle = kernel32.GetCurrentProcess()
    if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
        return None
    return int(counters.WorkingSetSize)


def disk(path: Path) -> dict | None:
    try:
        usage = shutil.disk_usage(str(path))
    except OSError:
        return None
    return {
        "total": usage.total,
        "used": usage.used,
        "free": usage.free,
        "percent": round(usage.used / usage.total * 100, 1) if usage.total else None,
    }


def gpu() -> list[dict] | None:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,utilization.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=2,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    out = []
    for line in result.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        try:
            out.append({
                "name": parts[0],
                "mem_total": int(float(parts[1])) * 1024 * 1024,
                "mem_used": int(float(parts[2])) * 1024 * 1024,
                "util": float(parts[3]),
            })
        except ValueError:
            continue
    return out or None


def uptime() -> float:
    return round(time.time() - _START, 1)
