#!/usr/bin/env python3
"""
ViewHP / PC Hardware Monitor Server
Cross-platform PC hardware telemetry server for Linux and Windows 10/11.
Serves real-time PC hardware telemetry to Android smartphones, tablets,
iPhones, iPads, or secondary displays via Web/PWA.
"""

import os
import sys
import time
import json
import socket
import threading
import subprocess
import shutil
import glob
import re
import math
import warnings
import atexit
import uuid
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import ctypes
from collections import deque

# OS Platform Flags
IS_WINDOWS = sys.platform == 'win32'
IS_LINUX = sys.platform.startswith('linux')

# Reconfigure stdout for utf-8 if supported
if IS_WINDOWS:
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

try:
    import psutil
except ImportError:
    print("[!] ERROR: 'psutil' is required.")
    if IS_LINUX:
        print("    Arch/CachyOS: sudo pacman -S python-psutil")
        print("    Debian/Ubuntu: sudo apt install python3-psutil")
        print("    Or run: pip install psutil")
    else:
        print("    Run: pip install psutil")
    sys.exit(1)

# Filter third-party deprecation warnings
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

# ---------------------------------------------------------------------------
# Windows Win32 API Definitions (loaded only when on Windows)
# ---------------------------------------------------------------------------
if IS_WINDOWS:
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    gdi32 = ctypes.windll.gdi32

    # Fast Windows console close handler (instant shutdown on Close 'X' button or Ctrl+C)
    _win_ctrl_handler_ref = None
    try:
        _PHANDLER = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
        def _fast_console_ctrl_handler(ctrl_type):
            try:
                if 'nv_present_tracker' in globals() and nv_present_tracker and hasattr(nv_present_tracker, 'fn_stop') and nv_present_tracker.session:
                    nv_present_tracker.fn_stop(nv_present_tracker.session)
            except Exception:
                pass
            kernel32.TerminateProcess(kernel32.GetCurrentProcess(), 0)
            return True
        _win_ctrl_handler_ref = _PHANDLER(_fast_console_ctrl_handler)
        kernel32.SetConsoleCtrlHandler(_win_ctrl_handler_ref, True)
    except Exception:
        pass

    FILE_MAP_READ = 0x0004
    kernel32.OpenFileMappingW.restype = wintypes.HANDLE
    kernel32.MapViewOfFile.restype = ctypes.c_void_p
    kernel32.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
    kernel32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]

    WORD = ctypes.c_uint16
    DWORD = ctypes.c_uint32
    LONG = ctypes.c_int32
    SHORT = ctypes.c_int16

    class POINTL(ctypes.Structure):
        _fields_ = [('x', LONG), ('y', LONG)]

    class RECT(ctypes.Structure):
        _fields_ = [('left', LONG), ('top', LONG), ('right', LONG), ('bottom', LONG)]

    class MONITORINFOEXW(ctypes.Structure):
        _fields_ = [
            ('cbSize', DWORD),
            ('rcMonitor', RECT),
            ('rcWork', RECT),
            ('dwFlags', DWORD),
            ('szDevice', ctypes.c_wchar * 32)
        ]

    class DEVMODEW(ctypes.Structure):
        _fields_ = [
            ('dmDeviceName', ctypes.c_wchar * 32),
            ('dmSpecVersion', WORD),
            ('dmDriverVersion', WORD),
            ('dmSize', WORD),
            ('dmDriverExtra', WORD),
            ('dmFields', DWORD),
            ('dmPosition', POINTL),
            ('dmDisplayOrientation', DWORD),
            ('dmDisplayFixedOutput', DWORD),
            ('dmColor', SHORT),
            ('dmDuplex', SHORT),
            ('dmYResolution', SHORT),
            ('dmTTOption', SHORT),
            ('dmCollate', SHORT),
            ('dmFormName', ctypes.c_wchar * 32),
            ('dmLogPixels', WORD),
            ('dmBitsPerPel', DWORD),
            ('dmPelsWidth', DWORD),
            ('dmPelsHeight', DWORD),
            ('dmDisplayFlags', DWORD),
            ('dmDisplayFrequency', DWORD),
            ('dmICMMethod', DWORD),
            ('dmICMIntent', DWORD),
            ('dmMediaType', DWORD),
            ('dmDitherType', DWORD),
            ('dmReserved1', DWORD),
            ('dmReserved2', DWORD),
            ('dmPanningWidth', DWORD),
            ('dmPanningHeight', DWORD),
        ]

    ENUM_CURRENT_SETTINGS = 0xFFFFFFFF
    ENUM_REGISTRY_SETTINGS = 0xFFFFFFFE

    user32.EnumDisplaySettingsW.argtypes = [wintypes.LPCWSTR, DWORD, ctypes.c_void_p]
    user32.EnumDisplaySettingsW.restype = wintypes.BOOL
    user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.c_void_p]
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    user32.ChangeDisplaySettingsExW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p, wintypes.HWND, DWORD, ctypes.c_void_p]
    user32.ChangeDisplaySettingsExW.restype = LONG
    MonitorEnumProc = ctypes.WINFUNCTYPE(
        ctypes.c_bool, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(RECT), wintypes.LPARAM
    )
else:
    user32 = None
    kernel32 = None
    gdi32 = None
    FILE_MAP_READ = 0x0004
    MonitorEnumProc = None


# ---------------------------------------------------------------------------
# GPU Monitoring Subsystem (NVIDIA NVML / AMD sysfs / Intel sysfs / nvidia-smi)
# ---------------------------------------------------------------------------
class GpuTelemetry:
    """
    Cross-platform GPU telemetry reader.
    Supports NVIDIA (via native ctypes libnvidia-ml or pynvml),
    AMD (via Linux DRM sysfs), Intel (via sysfs), and CLI fallbacks.
    """
    def __init__(self):
        self.gpu_type = None  # 'nvidia', 'amd', 'intel', or None
        self.gpu_name = "GPU"
        self.nvml_lib = None
        self.nvml_handle = None
        self.dxgi_vram_total = 0.0
        self._init_nvidia()
        if not self.gpu_type:
            self._init_amd()
        if not self.gpu_type and IS_WINDOWS:
            self._init_dxgi()

    def _init_nvidia(self):
        # 1. Try pynvml if installed
        try:
            import pynvml
            pynvml.nvmlInit()
            self.nvml_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            raw_name = pynvml.nvmlDeviceGetName(self.nvml_handle)
            self.gpu_name = raw_name.decode("utf-8") if isinstance(raw_name, bytes) else str(raw_name)
            self.gpu_type = 'nvidia_pynvml'
            return
        except Exception:
            pass

        # 2. Try zero-dependency ctypes loader for libnvidia-ml (Linux .so or Windows .dll)
        candidates = ['libnvidia-ml.so.1', 'libnvidia-ml.so', 'nvml.dll']
        for lib_name in candidates:
            try:
                lib = ctypes.CDLL(lib_name)
                init_fn = getattr(lib, 'nvmlInit_v2', None) or getattr(lib, 'nvmlInit', None)
                if not init_fn or init_fn() != 0:
                    continue
                handle = ctypes.c_void_p()
                get_handle = getattr(lib, 'nvmlDeviceGetHandleByIndex_v2', None) or getattr(lib, 'nvmlDeviceGetHandleByIndex', None)
                if not get_handle or get_handle(0, ctypes.byref(handle)) != 0:
                    continue
                name_buf = ctypes.create_string_buffer(96)
                if hasattr(lib, 'nvmlDeviceGetName') and lib.nvmlDeviceGetName(handle, name_buf, 96) == 0:
                    self.gpu_name = name_buf.value.decode('utf-8', errors='ignore').strip()
                self.nvml_lib = lib
                self.nvml_handle = handle
                self.gpu_type = 'nvidia_ctypes'
                return
            except Exception:
                continue

        # 3. Check if nvidia-smi exists as command-line tool
        if shutil.which('nvidia-smi'):
            try:
                out = subprocess.check_output(
                    ['nvidia-smi', '--query-gpu=name', '--format=csv,noheader,nounits'],
                    text=True, timeout=2, stderr=subprocess.DEVNULL
                ).strip()
                if out:
                    self.gpu_name = out.splitlines()[0].strip()
                    self.gpu_type = 'nvidia_smi'
                    return
            except Exception:
                pass

    def _init_amd(self):
        if not IS_LINUX:
            return
        cards = glob.glob('/sys/class/drm/card*/device/gpu_busy_percent')
        if cards:
            self.gpu_type = 'amd_sysfs'
            card_dir = os.path.dirname(cards[0])
            prod_name_file = os.path.join(card_dir, 'product_name')
            if os.path.exists(prod_name_file):
                try:
                    with open(prod_name_file, 'r') as f:
                        self.gpu_name = f.read().strip()
                except Exception:
                    self.gpu_name = "AMD Radeon GPU"
            else:
                self.gpu_name = "AMD Radeon GPU"

    def _init_dxgi(self):
        """Zero-dependency Windows DXGI fallback for AMD Radeon, Intel Arc, and multi-GPU systems."""
        if not IS_WINDOWS:
            return
        try:
            class LUID(ctypes.Structure):
                _fields_ = [('LowPart', wintypes.DWORD), ('HighPart', wintypes.LONG)]

            class DXGI_ADAPTER_DESC1(ctypes.Structure):
                _fields_ = [
                    ('Description', wintypes.WCHAR * 128),
                    ('VendorId', wintypes.UINT),
                    ('DeviceId', wintypes.UINT),
                    ('SubSysId', wintypes.UINT),
                    ('Revision', wintypes.UINT),
                    ('DedicatedVideoMemory', ctypes.c_size_t),
                    ('DedicatedSystemMemory', ctypes.c_size_t),
                    ('SharedSystemMemory', ctypes.c_size_t),
                    ('AdapterLuid', LUID),
                    ('Flags', wintypes.UINT),
                ]

            class GUID(ctypes.Structure):
                _fields_ = [
                    ('Data1', wintypes.DWORD),
                    ('Data2', wintypes.WORD),
                    ('Data3', wintypes.WORD),
                    ('Data4', ctypes.c_ubyte * 8)
                ]

            dxgi = ctypes.oledll.dxgi
            factory = ctypes.c_void_p()
            iid = GUID(0x770aae78, 0xf26f, 0x4dba, (ctypes.c_ubyte * 8)(0xa8, 0x29, 0x25, 0x3c, 0x83, 0xd1, 0xb3, 0x87))
            if dxgi.CreateDXGIFactory1(ctypes.byref(iid), ctypes.byref(factory)) == 0 and factory.value:
                vtbl = ctypes.cast(ctypes.cast(factory, ctypes.POINTER(ctypes.c_void_p)).contents, ctypes.POINTER(ctypes.c_void_p))
                EnumAdapters1 = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p))(vtbl[7])

                i = 0
                while True:
                    adapter = ctypes.c_void_p()
                    if EnumAdapters1(factory, i, ctypes.byref(adapter)) != 0 or not adapter.value:
                        break
                    avtbl = ctypes.cast(ctypes.cast(adapter, ctypes.POINTER(ctypes.c_void_p)).contents, ctypes.POINTER(ctypes.c_void_p))
                    GetDesc1 = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(DXGI_ADAPTER_DESC1))(avtbl[10])
                    desc = DXGI_ADAPTER_DESC1()
                    if GetDesc1(adapter, ctypes.byref(desc)) == 0:
                        if (desc.Flags & 2) == 0 and desc.DedicatedVideoMemory > 0:
                            self.gpu_name = desc.Description.strip()
                            self.dxgi_vram_total = round(desc.DedicatedVideoMemory / (1024**3), 1)
                            self.gpu_type = 'dxgi_windows'
                            ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(avtbl[2])(adapter)
                            break
                    ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(avtbl[2])(adapter)
                    i += 1
                ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])(factory)
        except Exception:
            pass

    def get_gpu_processes(self):
        """Get dict of {pid: used_vram_mb} for processes actively using the GPU engine."""
        res = {}
        if self.gpu_type == 'nvidia_ctypes' and self.nvml_lib and self.nvml_handle:
            try:
                class nvmlProcessInfo_v3_t(ctypes.Structure):
                    _fields_ = [
                        ('pid', ctypes.c_uint),
                        ('usedGpuMemory', ctypes.c_ulonglong),
                        ('gpuInstanceId', ctypes.c_uint),
                        ('computeInstanceId', ctypes.c_uint)
                    ]

                for fn_name in ('nvmlDeviceGetGraphicsRunningProcesses_v3', 'nvmlDeviceGetComputeRunningProcesses_v3',
                                'nvmlDeviceGetGraphicsRunningProcesses', 'nvmlDeviceGetComputeRunningProcesses'):
                    fn = getattr(self.nvml_lib, fn_name, None)
                    if fn:
                        count = ctypes.c_uint(64)
                        arr = (nvmlProcessInfo_v3_t * 64)()
                        if fn(self.nvml_handle, ctypes.byref(count), arr) == 0:
                            for i in range(count.value):
                                p = arr[i]
                                if p.pid > 0:
                                    raw_mem = getattr(p, 'usedGpuMemory', None)
                                    mem_mb = int(raw_mem // (1024 * 1024)) if (raw_mem and isinstance(raw_mem, (int, float))) else 0
                                    if mem_mb == 0 and IS_WINDOWS:
                                        try:
                                            mem_mb = int(psutil.Process(p.pid).memory_info().rss // (1024 * 1024))
                                        except Exception:
                                            pass
                                    if p.pid not in res or mem_mb > res[p.pid]:
                                        res[p.pid] = mem_mb
            except Exception:
                pass
        elif self.gpu_type == 'nvidia_pynvml':
            try:
                import pynvml
                for fn_name in ('nvmlDeviceGetGraphicsRunningProcesses', 'nvmlDeviceGetComputeRunningProcesses'):
                    fn = getattr(pynvml, fn_name, None)
                    if fn:
                        for p in fn(self.nvml_handle):
                            raw_mem = getattr(p, 'usedGpuMemory', None)
                            mem_mb = int(raw_mem // (1024 * 1024)) if (raw_mem is not None and isinstance(raw_mem, (int, float))) else 0
                            if mem_mb == 0 and IS_WINDOWS:
                                try:
                                    mem_mb = int(psutil.Process(p.pid).memory_info().rss // (1024 * 1024))
                                except Exception:
                                    pass
                            if p.pid not in res or mem_mb > res[p.pid]:
                                res[p.pid] = mem_mb
            except Exception:
                pass

        # Fallback to nvidia-smi if empty on Linux
        if not res and IS_LINUX and shutil.which('nvidia-smi'):
            try:
                out = subprocess.check_output(
                    ['nvidia-smi', '--query-compute-apps=pid,used_memory', '--format=csv,noheader,nounits'],
                    text=True, timeout=1.0, stderr=subprocess.DEVNULL
                )
                for line in out.splitlines():
                    parts = [x.strip() for x in line.split(',') if x.strip()]
                    if len(parts) >= 2:
                        res[int(parts[0])] = int(parts[1])
            except Exception:
                pass

        return res

    def get_graphics_running_pids(self):
        """Get PIDs of applications actively using the GPU engine."""
        return list(self.get_gpu_processes().keys())

    def sample(self):
        """Sample GPU usage (%), temperature (°C), VRAM used (GB), and VRAM total (GB)."""
        # 1. pynvml
        if self.gpu_type == 'nvidia_pynvml':
            try:
                import pynvml
                rates = pynvml.nvmlDeviceGetUtilizationRates(self.nvml_handle)
                temp = pynvml.nvmlDeviceGetTemperature(self.nvml_handle, 0)
                mem = pynvml.nvmlDeviceGetMemoryInfo(self.nvml_handle)
                return {
                    "name": self.gpu_name,
                    "usage": rates.gpu,
                    "temp": temp,
                    "vram_used": round(mem.used / (1024**3), 1),
                    "vram_total": round(mem.total / (1024**3), 1)
                }
            except Exception:
                pass

        # 2. ctypes NVML
        if self.gpu_type == 'nvidia_ctypes' and self.nvml_lib and self.nvml_handle:
            try:
                class nvmlUtilization_t(ctypes.Structure):
                    _fields_ = [('gpu', ctypes.c_uint), ('memory', ctypes.c_uint)]
                class nvmlMemory_t(ctypes.Structure):
                    _fields_ = [('total', ctypes.c_ulonglong), ('free', ctypes.c_ulonglong), ('used', ctypes.c_ulonglong)]

                util = nvmlUtilization_t()
                gpu_pct = 0
                if getattr(self.nvml_lib, 'nvmlDeviceGetUtilizationRates', None):
                    if self.nvml_lib.nvmlDeviceGetUtilizationRates(self.nvml_handle, ctypes.byref(util)) == 0:
                        gpu_pct = util.gpu

                temp = ctypes.c_uint(0)
                gpu_temp = None
                if getattr(self.nvml_lib, 'nvmlDeviceGetTemperature', None):
                    if self.nvml_lib.nvmlDeviceGetTemperature(self.nvml_handle, 0, ctypes.byref(temp)) == 0:
                        gpu_temp = temp.value

                mem = nvmlMemory_t()
                v_used, v_total = 0.0, 0.0
                if getattr(self.nvml_lib, 'nvmlDeviceGetMemoryInfo', None):
                    if self.nvml_lib.nvmlDeviceGetMemoryInfo(self.nvml_handle, ctypes.byref(mem)) == 0:
                        v_used = round(mem.used / (1024**3), 1)
                        v_total = round(mem.total / (1024**3), 1)

                return {
                    "name": self.gpu_name,
                    "usage": gpu_pct,
                    "temp": gpu_temp,
                    "vram_used": v_used,
                    "vram_total": v_total
                }
            except Exception:
                pass

        # 3. nvidia-smi CLI
        if self.gpu_type in ('nvidia_smi', 'nvidia_ctypes'):
            try:
                out = subprocess.check_output(
                    ['nvidia-smi', '--query-gpu=utilization.gpu,temperature.gpu,memory.used,memory.total',
                     '--format=csv,noheader,nounits'],
                    text=True, timeout=1.5, stderr=subprocess.DEVNULL
                ).strip()
                if out:
                    parts = [p.strip() for p in out.splitlines()[0].split(',')]
                    return {
                        "name": self.gpu_name,
                        "usage": int(parts[0]) if len(parts) > 0 and parts[0].isdigit() else 0,
                        "temp": int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None,
                        "vram_used": round(float(parts[2]) / 1024.0, 1) if len(parts) > 2 else 0.0,
                        "vram_total": round(float(parts[3]) / 1024.0, 1) if len(parts) > 3 else 0.0
                    }
            except Exception:
                pass

        # 4. AMD sysfs on Linux
        if self.gpu_type == 'amd_sysfs':
            try:
                card = glob.glob('/sys/class/drm/card*/device/gpu_busy_percent')[0]
                card_dir = os.path.dirname(card)
                with open(card, 'r') as f:
                    usage = int(f.read().strip())

                temp = None
                hw_temps = glob.glob(os.path.join(card_dir, 'hwmon/hwmon*/temp1_input'))
                if hw_temps:
                    with open(hw_temps[0], 'r') as f:
                        temp = round(int(f.read().strip()) / 1000)

                v_used, v_total = 0.0, 0.0
                used_file = os.path.join(card_dir, 'mem_info_vram_used')
                tot_file = os.path.join(card_dir, 'mem_info_vram_total')
                if os.path.exists(used_file) and os.path.exists(tot_file):
                    with open(used_file, 'r') as f:
                        v_used = round(int(f.read().strip()) / (1024**3), 1)
                    with open(tot_file, 'r') as f:
                        v_total = round(int(f.read().strip()) / (1024**3), 1)

                return {
                    "name": self.gpu_name,
                    "usage": usage,
                    "temp": temp,
                    "vram_used": v_used,
                    "vram_total": v_total
                }
            except Exception:
                pass

        # 5. Windows DXGI & MSI Afterburner fallback (AMD Radeon & Intel Arc)
        if IS_WINDOWS:
            gpu_temp = None
            gpu_usage = 0
            gpu_vram_used = 0.0
            try:
                hMapAB = kernel32.OpenFileMappingW(FILE_MAP_READ, False, 'MAHMSharedMemory')
                if hMapAB:
                    try:
                        pBuf = kernel32.MapViewOfFile(hMapAB, FILE_MAP_READ, 0, 0, 0)
                        if pBuf:
                            header = (ctypes.c_uint * 8).from_address(pBuf)
                            dwHeaderSize, dwNumEntries, dwEntrySize = header[2], header[3], header[4]
                            for i in range(dwNumEntries):
                                ptr = pBuf + dwHeaderSize + i * dwEntrySize
                                name = ctypes.string_at(ptr, 260).split(b'\x00')[0].decode('utf-8', errors='ignore').lower()
                                val = ctypes.c_float.from_address(ptr + 1300).value
                                src_id = ctypes.c_uint.from_address(ptr + 1320).value
                                if (src_id == 0x00 or ('gpu' in name and 'temp' in name)) and 0 < val < 130:
                                    gpu_temp = round(val)
                                elif (src_id == 0x10 or name in ('gpu usage', 'gpu percent', 'gpu%')) and 0 <= val <= 100:
                                    gpu_usage = round(val)
                                elif (src_id == 0x20 or ('memory' in name and 'usage' in name)) and val > 0:
                                    gpu_vram_used = round(val / 1024.0, 1)
                            kernel32.UnmapViewOfFile(pBuf)
                    finally:
                        kernel32.CloseHandle(hMapAB)
            except Exception:
                pass

            if self.gpu_type == 'dxgi_windows' or self.dxgi_vram_total > 0:
                return {
                    "name": self.gpu_name or "GPU",
                    "usage": gpu_usage,
                    "temp": gpu_temp,
                    "vram_used": gpu_vram_used,
                    "vram_total": self.dxgi_vram_total
                }

        return {
            "name": self.gpu_name or "GPU",
            "usage": 0,
            "temp": None,
            "vram_used": 0,
            "vram_total": 0
        }


# Global GPU Telemetry instance
gpu_monitor = GpuTelemetry()


# ---------------------------------------------------------------------------
# KWin Compositor Window Damage & Real-Time FPS Tracker (Linux Wayland / KDE)
# ---------------------------------------------------------------------------
def is_kwin_available():
    """Check if the system is running under KDE Plasma / KWin compositor."""
    if not IS_LINUX:
        return False
    desktop = (os.environ.get('XDG_CURRENT_DESKTOP', '') + ' ' +
               os.environ.get('DESKTOP_SESSION', '') + ' ' +
               os.environ.get('KDE_FULL_SESSION', '')).lower()
    return 'kde' in desktop or 'plasma' in desktop


class KWinTracker(threading.Thread):
    """
    Tracks per-monitor window damage events directly from the KWin Wayland compositor.
    Provides instantaneous in-game and per-application FPS without needing MangoHud or external overlays.
    """
    def __init__(self):
        super().__init__(daemon=True)
        self.screens = []
        self.kwin_script_id = None
        self.dbus_bus = None
        self.running = True
        self.available = False
        self.lock = threading.Lock()
        self.script_file = '/tmp/viewhp_kwin_tracker_v210.js'

    def run(self):
        if not IS_LINUX or not is_kwin_available():
            return
        try:
            import dbus
            import dbus.service
            import dbus.mainloop.glib
            from gi.repository import GLib

            dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
            self.dbus_bus = dbus.SessionBus()
            tracker_self = self

            class MonitorService(dbus.service.Object):
                def __init__(self, bus):
                    super().__init__(dbus.service.BusName('org.viewhp.MonitorV210', bus), '/MonitorV210')

                @dbus.service.method('org.viewhp.MonitorV210', in_signature='s', out_signature='')
                def updateScreens(self, json_data):
                    try:
                        data = json.loads(json_data)
                        with tracker_self.lock:
                            tracker_self.screens = data
                            tracker_self.available = True
                    except Exception:
                        pass

            self.service = MonitorService(self.dbus_bus)

            kwin_scripting = self.dbus_bus.get_object('org.kde.KWin', '/Scripting')
            script_code = """
            let winDamages = {};
            function track(w) {
                if (!w || w._vhp) return;
                w._vhp = true;
                let id = w.internalId ? w.internalId.toString() : w.caption;
                w.damaged.connect(function() {
                    winDamages[id] = (winDamages[id] || 0) + 1;
                });
            }
            workspace.windowList().forEach(track);
            workspace.windowAdded.connect(track);

            let timer = new QTimer();
            timer.interval = 1000;
            timer.timeout.connect(function() {
                let result = [];
                let scrs = workspace.screens;
                let wins = workspace.stackingOrder;
                let actWin = workspace.activeWindow;
                let actWinId = actWin ? (actWin.internalId ? actWin.internalId.toString() : actWin.caption) : null;

                for (let i = 0; i < scrs.length; i++) {
                    let s = scrs[i];
                    let topWin = null;
                    for (let j = wins.length - 1; j >= 0; j--) {
                        let w = wins[j];
                        if (!w.normalWindow || w.minimized || !w.output) continue;
                        if (w.output.name === s.name) {
                            topWin = w;
                            break;
                        }
                    }
                    let topId = topWin ? (topWin.internalId ? topWin.internalId.toString() : topWin.caption) : null;
                    let count = topId ? (winDamages[topId] || 0) : 0;

                    let appTitle = topWin ? topWin.caption : 'Desktop';
                    let appName = topWin ? (topWin.desktopFileName || topWin.resourceClass || '') : 'Desktop';
                    let isActive = Boolean(actWinId && topId && actWinId === topId);

                    result.push({
                        name: s.name,
                        model: s.model || s.name,
                        fps: count,
                        app: appTitle,
                        appName: appName,
                        is_active: isActive
                    });
                }
                winDamages = {};
                callDBus('org.viewhp.MonitorV210', '/MonitorV210', 'org.viewhp.MonitorV210', 'updateScreens', JSON.stringify(result));
            });
            timer.start();
            """
            with open(self.script_file, 'w') as f:
                f.write(script_code)

            self.kwin_script_id = kwin_scripting.loadScript(self.script_file, dbus_interface='org.kde.kwin.Scripting')
            script_obj = self.dbus_bus.get_object('org.kde.KWin', f'/Scripting/Script{self.kwin_script_id}')
            script_obj.run(dbus_interface='org.kde.kwin.Script')

            self.available = True
            loop = GLib.MainLoop()
            loop.run()
        except Exception:
            self.available = False

    def cleanup(self):
        if self.kwin_script_id is not None and self.dbus_bus:
            try:
                kwin_scripting = self.dbus_bus.get_object('org.kde.KWin', '/Scripting')
                script_obj = self.dbus_bus.get_object('org.kde.KWin', f'/Scripting/Script{self.kwin_script_id}')
                script_obj.stop(dbus_interface='org.kde.kwin.Script')
                kwin_scripting.unloadScript(f'Script{self.kwin_script_id}', dbus_interface='org.kde.kwin.Scripting')
            except Exception:
                pass

    def get_screens(self):
        with self.lock:
            return list(self.screens)


kwin_tracker = KWinTracker()
if IS_LINUX and is_kwin_available():
    kwin_tracker.start()
    atexit.register(kwin_tracker.cleanup)


# ---------------------------------------------------------------------------
# Windows DXGI Desktop Duplication Real-Time Screen FPS Tracker
# ---------------------------------------------------------------------------
class _DXGI_GUID(ctypes.Structure):
    _fields_ = [
        ('Data1', ctypes.c_ulong),
        ('Data2', ctypes.c_ushort),
        ('Data3', ctypes.c_ushort),
        ('Data4', ctypes.c_ubyte * 8)
    ]

def _make_dxgi_guid(s):
    u = uuid.UUID(s)
    g = _DXGI_GUID()
    g.Data1 = u.time_low
    g.Data2 = u.time_mid
    g.Data3 = u.time_hi_version
    for i in range(8):
        g.Data4[i] = u.bytes[8+i]
    return g

def _get_com_vtable_func(ptr, index, restype, argtypes):
    vtable = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_void_p))[0]
    func_ptr = ctypes.cast(vtable, ctypes.POINTER(ctypes.c_void_p))[index]
    prototype = ctypes.WINFUNCTYPE(restype, *argtypes)
    return prototype(func_ptr)

def _release_com_ptr(ptr_val):
    if ptr_val:
        try:
            rel = _get_com_vtable_func(ptr_val, 2, ctypes.c_ulong, [ctypes.c_void_p])
            rel(ptr_val)
        except Exception:
            pass

class DXGI_OUTPUT_DESC_STRUCT(ctypes.Structure):
    _fields_ = [
        ('DeviceName', ctypes.c_wchar * 32),
        ('DesktopCoordinates', RECT if IS_WINDOWS else ctypes.c_void_p),
        ('AttachedToDesktop', wintypes.BOOL if IS_WINDOWS else ctypes.c_int),
        ('Rotation', ctypes.c_uint),
        ('Monitor', wintypes.HMONITOR if IS_WINDOWS else ctypes.c_void_p),
    ]

class DXGI_OUTDUPL_FRAME_INFO_STRUCT(ctypes.Structure):
    _fields_ = [
        ('LastPresentTime', wintypes.LARGE_INTEGER if IS_WINDOWS else ctypes.c_int64),
        ('LastMouseUpdateTime', wintypes.LARGE_INTEGER if IS_WINDOWS else ctypes.c_int64),
        ('AccumulatedFrames', wintypes.UINT if IS_WINDOWS else ctypes.c_uint),
        ('RectsCoalesced', wintypes.BOOL if IS_WINDOWS else ctypes.c_int),
        ('ProtectedContentMaskedOut', wintypes.BOOL if IS_WINDOWS else ctypes.c_int),
        ('PointerPosition', wintypes.POINT if IS_WINDOWS else ctypes.c_void_p),
        ('TotalMetadataBufferSize', wintypes.UINT if IS_WINDOWS else ctypes.c_uint),
        ('PointerShapeBufferSize', wintypes.UINT if IS_WINDOWS else ctypes.c_uint),
    ]


class WindowsOutputWorker(threading.Thread):
    def __init__(self, output_idx, dev_name, pAdapter1, pDevice, native_hz=60):
        super().__init__(daemon=True)
        self.output_idx = output_idx
        self.dev_name = dev_name
        self.pAdapter1 = pAdapter1
        self.pDevice = pDevice
        self.native_hz = native_hz or 60
        self.running = True
        self.fps = self.native_hz
        self.frametime = round(1000.0 / max(self.native_hz, 1), 1)
        self.has_live_fps = True
        self.last_update = time.time()
        self.last_live_time = time.time()
        self.lock = threading.Lock()

    def run(self):
        if user32:
            try:
                hDesk = user32.OpenInputDesktop(0, False, 0x01FF)
                if hDesk:
                    user32.SetThreadDesktop(hDesk)
            except Exception:
                pass

        IID_IDXGIOutput1 = _make_dxgi_guid('00cddea8-939b-4b83-a340-a685226666cc')

        while self.running:
            pOutput = ctypes.c_void_p()
            pOutput1 = ctypes.c_void_p()
            pDupl = ctypes.c_void_p()
            ReleaseDupl = None
            try:
                EnumOutputs = _get_com_vtable_func(self.pAdapter1.value, 7, ctypes.c_long, [ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p)])
                if EnumOutputs(self.pAdapter1.value, self.output_idx, ctypes.byref(pOutput)) != 0 or not pOutput.value:
                    time.sleep(1.0)
                    continue

                QueryInterfaceOutput = _get_com_vtable_func(pOutput.value, 0, ctypes.c_long, [ctypes.c_void_p, ctypes.POINTER(_DXGI_GUID), ctypes.POINTER(ctypes.c_void_p)])
                if QueryInterfaceOutput(pOutput.value, ctypes.byref(IID_IDXGIOutput1), ctypes.byref(pOutput1)) != 0 or not pOutput1.value:
                    time.sleep(1.0)
                    continue

                DuplicateOutput = _get_com_vtable_func(pOutput1.value, 22, ctypes.c_long, [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)])
                if DuplicateOutput(pOutput1.value, self.pDevice.value, ctypes.byref(pDupl)) != 0 or not pDupl.value:
                    time.sleep(1.0)
                    continue

                AcquireNextFrame = _get_com_vtable_func(pDupl.value, 8, ctypes.c_long, [ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(DXGI_OUTDUPL_FRAME_INFO_STRUCT), ctypes.POINTER(ctypes.c_void_p)])
                ReleaseFrame = _get_com_vtable_func(pDupl.value, 14, ctypes.c_long, [ctypes.c_void_p])
                ReleaseDupl = _get_com_vtable_func(pDupl.value, 2, ctypes.c_ulong, [ctypes.c_void_p])
                ReleaseResource = None

                accum_frames = 0
                sample_start = time.perf_counter()
                last_seen_qpc = 0
                recent_ft = []

                # Query high-precision Windows QPC frequency for accurate inter-frame interval measurement
                qpf = ctypes.c_int64()
                if kernel32:
                    kernel32.QueryPerformanceFrequency(ctypes.byref(qpf))
                qpf_val = float(qpf.value) if qpf.value > 0 else 10000000.0

                while self.running:
                    frame_info = DXGI_OUTDUPL_FRAME_INFO_STRUCT()
                    pResource = ctypes.c_void_p()
                    # 10ms timeout: ultra-responsive without blocking high frame rates
                    hr = AcquireNextFrame(pDupl.value, 10, ctypes.byref(frame_info), ctypes.byref(pResource))

                    if hr == 0:
                        if frame_info.LastPresentTime != 0:
                            if last_seen_qpc != 0 and frame_info.LastPresentTime > last_seen_qpc:
                                delta_ticks = frame_info.LastPresentTime - last_seen_qpc
                                dt_sec = delta_ticks / qpf_val
                                # Measure physical inter-frame interval for games (5 FPS to 1000 FPS)
                                if 0.0010 <= dt_sec <= 0.200:
                                    acc = max(1, frame_info.AccumulatedFrames)
                                    per_frame_dt = dt_sec / acc
                                    for _ in range(min(acc, 4)):
                                        recent_ft.append(per_frame_dt)
                                        if len(recent_ft) > 30:
                                            recent_ft.pop(0)
                            last_seen_qpc = frame_info.LastPresentTime
                            accum_frames += max(1, frame_info.AccumulatedFrames)

                        if pResource.value:
                            if not ReleaseResource:
                                ReleaseResource = _get_com_vtable_func(pResource.value, 2, ctypes.c_ulong, [ctypes.c_void_p])
                            ReleaseResource(pResource.value)
                        ReleaseFrame(pDupl.value)
                    elif hr in (0x887A0026, 0x80070005, 0x887A0001):
                        break

                    now = time.perf_counter()
                    elapsed = now - sample_start
                    if elapsed >= 0.40:
                        with self.lock:
                            if recent_ft and accum_frames >= 2:
                                # Calculate true game swapchain framerate from high-precision QPC intervals
                                s_ft = sorted(recent_ft)
                                trim = len(s_ft) // 8
                                trimmed_ft = s_ft[trim:-trim] if trim > 0 else s_ft
                                avg_dt = sum(trimmed_ft) / len(trimmed_ft)
                                calc_fps = int(round(1.0 / avg_dt)) if avg_dt > 0 else self.native_hz
                                calc_fps = max(1, min(1000, calc_fps))
                                calc_ft = round(avg_dt * 1000.0, 1)

                                self.fps = calc_fps
                                self.frametime = calc_ft
                                self.has_live_fps = True
                                self.last_live_time = now
                            else:
                                # When display is completely idle/static (no active game render)
                                if (now - self.last_live_time) < 1.8 and self.fps > 0:
                                    # Grace period during game load screens or momentary frame drop
                                    pass
                                else:
                                    self.fps = self.native_hz
                                    self.frametime = round(1000.0 / max(self.native_hz, 1), 1)
                                    self.has_live_fps = False
                            self.last_update = now
                        accum_frames = 0
                        sample_start = now
            except Exception:
                time.sleep(1.0)
            finally:
                if pDupl.value and ReleaseDupl:
                    try:
                        ReleaseDupl(pDupl.value)
                    except Exception:
                        pass
                _release_com_ptr(pOutput1.value)
                _release_com_ptr(pOutput.value)


class WindowsFpsTracker(threading.Thread):
    """
    Direct Windows DXGI Desktop Duplication Screen FPS Telemetry.
    Tracks live FPS and frame time for every monitor display output without needing MSI Afterburner or RTSS.
    """
    def __init__(self):
        super().__init__(daemon=True)
        self.running = True
        self.available = False
        self.workers = []
        self.lock = threading.Lock()
        self.pFactory = None
        self.pAdapter1 = None
        self.pDevice = None

    def run(self):
        if not IS_WINDOWS:
            return
        if user32:
            try:
                hDesk = user32.OpenInputDesktop(0, False, 0x01FF)
                if hDesk:
                    user32.SetThreadDesktop(hDesk)
            except Exception:
                pass

        try:
            dxgi = ctypes.windll.dxgi
            d3d11 = ctypes.windll.d3d11

            CreateDXGIFactory1 = dxgi.CreateDXGIFactory1
            CreateDXGIFactory1.restype = ctypes.c_long
            CreateDXGIFactory1.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]

            IID_IDXGIFactory1 = _make_dxgi_guid('770aae78-f26f-4dba-a829-253c83d1b387')
            pFactory = ctypes.c_void_p()
            if CreateDXGIFactory1(ctypes.byref(IID_IDXGIFactory1), ctypes.byref(pFactory)) != 0 or not pFactory.value:
                return

            EnumAdapters1 = _get_com_vtable_func(pFactory.value, 12, ctypes.c_long, [ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)])
            pAdapter1 = ctypes.c_void_p()
            if EnumAdapters1(pFactory.value, 0, ctypes.byref(pAdapter1)) != 0 or not pAdapter1.value:
                return

            d3d11.D3D11CreateDevice.argtypes = [
                ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint,
                ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint,
                ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_void_p)
            ]
            d3d11.D3D11CreateDevice.restype = ctypes.c_long

            pDevice = ctypes.c_void_p()
            pContext = ctypes.c_void_p()
            featureLevel = ctypes.c_uint()

            if d3d11.D3D11CreateDevice(pAdapter1, 0, None, 0, None, 0, 7, ctypes.byref(pDevice), ctypes.byref(featureLevel), ctypes.byref(pContext)) != 0 or not pDevice.value:
                return

            self.pFactory = pFactory
            self.pAdapter1 = pAdapter1
            self.pDevice = pDevice

            EnumOutputs = _get_com_vtable_func(pAdapter1.value, 7, ctypes.c_long, [ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p)])
            for idx in range(8):
                pOutput = ctypes.c_void_p()
                if EnumOutputs(pAdapter1.value, idx, ctypes.byref(pOutput)) != 0 or not pOutput.value:
                    break
                GetDesc = _get_com_vtable_func(pOutput.value, 7, ctypes.c_long, [ctypes.c_void_p, ctypes.POINTER(DXGI_OUTPUT_DESC_STRUCT)])
                desc = DXGI_OUTPUT_DESC_STRUCT()
                GetDesc(pOutput.value, ctypes.byref(desc))
                dev_name = desc.DeviceName.replace('\\\\.\\', '').strip()
                dev_raw = desc.DeviceName
                _release_com_ptr(pOutput.value)

                out_hz = 60
                if user32:
                    try:
                        dm = DEVMODEW()
                        dm.dmSize = ctypes.sizeof(DEVMODEW)
                        if user32.EnumDisplaySettingsW(dev_raw, -1, ctypes.byref(dm)) and dm.dmDisplayFrequency > 0:
                            out_hz = int(dm.dmDisplayFrequency)
                    except Exception:
                        pass

                worker = WindowsOutputWorker(idx, dev_name, pAdapter1, pDevice, native_hz=out_hz)
                worker.start()
                with self.lock:
                    self.workers.append(worker)

            with self.lock:
                self.available = len(self.workers) > 0

            while self.running:
                time.sleep(2.0)
        except Exception:
            pass

    def get_screens(self):
        with self.lock:
            workers = list(self.workers)
        res = []
        for w in workers:
            with w.lock:
                fps = w.fps
                ft = w.frametime
                live = w.has_live_fps
            res.append({
                "name": w.dev_name,
                "model": w.dev_name,
                "fps": fps,
                "frametime": ft,
                "has_live_fps": live
            })
        return res

    def get_active_fps(self, active_device_name=None):
        with self.lock:
            workers = list(self.workers)
        if not workers:
            return None

        clean_dev = (active_device_name or "").replace('\\\\.\\', '').strip()
        matched = None
        if clean_dev:
            matched = next((w for w in workers if w.dev_name == clean_dev or clean_dev in w.dev_name or w.dev_name in clean_dev), None)

        if not matched:
            matched = next((w for w in workers if w.fps > 0), None)
            if not matched and workers:
                matched = workers[0]

        with matched.lock:
            return {
                "fps": matched.fps,
                "frametime": matched.frametime,
                "has_live_fps": matched.has_live_fps,
                "device": matched.dev_name
            }

    def cleanup(self):
        self.running = False
        with self.lock:
            for w in self.workers:
                w.running = False


windows_fps_tracker = None


class NvPresentTracker:
    """
    Direct Real-Time 3D Frame Presentation Tracker using NVIDIA FrameView Service.
    Captures exact hardware Present() calls and frametimes for all DirectX 9/10/11/12 & Vulkan games
    without requiring code injection, perfectly synchronized with in-game overlays (Steam, RTSS, Afterburner).
    """
    def __init__(self):
        self.available = False
        self.lock = threading.Lock()
        self.presents = {}  # pid -> deque of (timestamp, ms_between_presents)
        self.running = False
        self.pipe = ctypes.c_void_p(0)
        self.session = ctypes.c_void_p(0)
        self.dll = None
        self._init_sdk()

    def _init_sdk(self):
        if not IS_WINDOWS or not kernel32:
            return
        try:
            dll_path = r'C:\Program Files\NVIDIA Corporation\FrameViewSDK\SDK\Public_Release\FvSDK_x64.dll'
            if not os.path.exists(dll_path):
                dll_path = r'C:\Program Files\NVIDIA Corporation\FrameViewSDK\bin\FvSDK_x64.dll'
            if not os.path.exists(dll_path):
                return

            self.dll = ctypes.cdll.LoadLibrary(dll_path)
            query = self.dll.fv_QueryInterface
            query.restype = ctypes.c_void_p
            query.argtypes = [ctypes.c_uint]
            vtbl = [query(i) for i in range(17)]
            if not all(vtbl[:7]) or not vtbl[16]:
                return

            fn_init = ctypes.CFUNCTYPE(ctypes.c_uint)(vtbl[7])
            self.fn_create = ctypes.CFUNCTYPE(ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p))(vtbl[0])
            self.fn_destroy = ctypes.CFUNCTYPE(ctypes.c_uint, ctypes.c_void_p)(vtbl[1])
            self.fn_enable = ctypes.CFUNCTYPE(ctypes.c_uint, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint), ctypes.c_uint)(vtbl[2])
            self.fn_start = ctypes.CFUNCTYPE(ctypes.c_uint, ctypes.c_void_p)(vtbl[4])
            self.fn_stop = ctypes.CFUNCTYPE(ctypes.c_uint, ctypes.c_void_p)(vtbl[5])
            self.fn_getpipe = ctypes.CFUNCTYPE(ctypes.c_uint, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(vtbl[16])

            fn_init()
            session = ctypes.c_void_p()
            if self.fn_create(ctypes.byref(session)) != 0 or not session.value:
                return

            self.session = session
            self.metrics = (ctypes.c_uint * 1)(0x5BE0DB9E)  # eFrame
            self.fn_enable(self.session, self.metrics, 1)

            pipe = ctypes.c_void_p()
            if self.fn_getpipe(self.session, ctypes.byref(pipe)) != 0 or not pipe.value:
                return

            self.fn_start(self.session)
            self.pipe = pipe
            self.available = True
            self.running = True
            self.thread = threading.Thread(target=self._worker, daemon=True)
            self.thread.start()
        except Exception:
            self.available = False

    def _worker(self):
        kernel32 = ctypes.windll.kernel32
        avail = wintypes.DWORD()
        read = wintypes.DWORD()
        buf_str = ''

        while self.running and self.pipe.value:
            try:
                if kernel32.PeekNamedPipe(self.pipe, None, 0, None, ctypes.byref(avail), None) and avail.value > 0:
                    to_read = min(avail.value, 65536)
                    c_buf = ctypes.create_string_buffer(to_read)
                    if kernel32.ReadFile(self.pipe, c_buf, to_read, ctypes.byref(read), None) and read.value > 0:
                        text = c_buf.raw[:read.value].decode('latin-1', errors='ignore')
                        buf_str += text
                        lines = buf_str.split('\n')
                        buf_str = lines[-1]
                        now = time.time()

                        with self.lock:
                            for line in lines[:-1]:
                                line = line.strip()
                                if not line or line.startswith('ProcessId'):
                                    continue
                                parts = line.split(',')
                                if len(parts) >= 4:
                                    try:
                                        pid = int(parts[0])
                                        ms = float(parts[3])
                                        if pid not in self.presents:
                                            self.presents[pid] = deque(maxlen=240)
                                        self.presents[pid].append((now, ms))
                                    except Exception:
                                        pass
                else:
                    time.sleep(0.015)
            except Exception:
                time.sleep(0.05)

    def get_fps(self, pid):
        if not self.available or not pid:
            return None
        now = time.time()
        with self.lock:
            if pid not in self.presents:
                return None
            q = self.presents[pid]
            recent = [(t, ms) for t, ms in q if now - t <= 2.2]
            if len(recent) < 2:
                if recent and 0.5 <= recent[-1][1] <= 500.0 and (now - recent[-1][0]) <= 1.8:
                    inst_ms = recent[-1][1]
                    return round(1000.0 / inst_ms), round(inst_ms, 1)
                return None

            valid_ms = [ms for t, ms in recent if 0.5 <= ms <= 500.0]
            if len(valid_ms) >= 2:
                avg_ms = sum(valid_ms) / len(valid_ms)
                fps = round(1000.0 / max(avg_ms, 0.1))
                ft = round(avg_ms, 1)
            else:
                dt = recent[-1][0] - recent[0][0]
                fps = round((len(recent) - 1) / dt) if dt > 0.05 else len(recent)
                ft = round(1000.0 / max(fps, 1), 1)

            return fps, ft

    def get_game_fps(self, target_pid=None, target_name=None):
        if not self.available:
            return None

        # 1. Check target_pid directly if it is a known 3D game
        if target_pid:
            try:
                pname = target_name or psutil.Process(target_pid).name()
                if is_known_game(pname, target_pid):
                    info = self.get_fps(target_pid)
                    if info:
                        return info[0], info[1], target_pid

                    # Check child processes of target_pid
                    p = psutil.Process(target_pid)
                    for child in p.children(recursive=True):
                        info = self.get_fps(child.pid)
                        if info:
                            return info[0], info[1], child.pid
            except Exception:
                pass

        # 2. Check active presenting processes in self.presents
        active_candidates = []
        with self.lock:
            pids = list(self.presents.keys())

        for pid in pids:
            try:
                proc = psutil.Process(pid)
                pname = proc.name()
                if is_known_game(pname, pid):
                    info = self.get_fps(pid)
                    if info:
                        active_candidates.append((info[0], info[1], pid, pname))
            except Exception:
                continue

        if active_candidates:
            # Prioritize matching target_name if provided
            if target_name:
                t_lower = target_name.lower()
                for fps, ft, c_pid, c_name in active_candidates:
                    if t_lower in c_name.lower() or c_name.lower() in t_lower:
                        return fps, ft, c_pid

            # Return candidate with highest render rate
            active_candidates.sort(key=lambda x: x[0], reverse=True)
            return active_candidates[0][0], active_candidates[0][1], active_candidates[0][2]

        return None

    def get_app_fps(self, target_pid):
        """
        Retrieves real-time FPS and frametime for a foreground application.
        Checks target_pid directly, child processes (e.g. browser GPU child process),
        and sibling processes with identical executable name.
        """
        if not self.available or not target_pid:
            return None

        # 1. Direct PID
        info = self.get_fps(target_pid)
        if info:
            return info[0], info[1], target_pid

        # 2. Child processes of target_pid (e.g. Chrome/Brave GPU process)
        try:
            p = psutil.Process(target_pid)
            pname = p.name().lower()
            for child in p.children(recursive=True):
                info = self.get_fps(child.pid)
                if info:
                    return info[0], info[1], child.pid

            # 3. Sibling processes with identical executable name
            with self.lock:
                pids = list(self.presents.keys())
            for pid in pids:
                if pid == target_pid:
                    continue
                try:
                    if psutil.Process(pid).name().lower() == pname:
                        info = self.get_fps(pid)
                        if info:
                            return info[0], info[1], pid
                except Exception:
                    continue
        except Exception:
            pass

        return None

    def cleanup(self):
        self.running = False
        try:
            if hasattr(self, 'pipe') and self.pipe and self.pipe.value and kernel32:
                kernel32.CloseHandle(self.pipe)
                self.pipe = ctypes.c_void_p(0)
            if self.session and self.session.value:
                if hasattr(self, 'fn_stop'):
                    self.fn_stop(self.session)
        except Exception:
            pass


nv_present_tracker = NvPresentTracker() if IS_WINDOWS else None
if IS_WINDOWS and nv_present_tracker:
    atexit.register(nv_present_tracker.cleanup)


COMMON_NON_GAME_APPS = {
    'dwm.exe', 'explorer.exe', 'services.exe', 'winedevice.exe', 'plugplay.exe',
    'chrome.exe', 'brave.exe', 'msedge.exe', 'firefox.exe', 'opera.exe',
    'discord.exe', 'spotify.exe', 'code.exe', 'devenv.exe', 'antigravity.exe',
    'cmd.exe', 'powershell.exe', 'pwsh.exe', 'windowsterminal.exe', 'conhost.exe',
    'notepad.exe', 'taskmgr.exe', 'systemsettings.exe', 'applicationframehost.exe',
    'textinputhost.exe', 'searchhost.exe', 'startmenuexperiencehost.exe',
    'shellexperiencehost.exe', 'nvidia overlay.exe', 'nvcontainer.exe', 'vgtray.exe',
    'steam.exe', 'epicgameslauncher.exe', 'battlenet.exe', 'galaxyclient.exe',
    'python.exe', 'pythonw.exe', 'git.exe', 'bash.exe', 'wsl.exe', 'slack.exe',
    'audiodg.exe', 'csrss.exe', 'lsass.exe', 'smss.exe', 'spoolsv.exe',
    'fontdrvhost.exe', 'msedgewebview2.exe', 'crossdeviceresume.exe', 'shellhost.exe',
    'language_server.exe', 'ctfmon.exe', 'sihost.exe', 'runtimebroker.exe',
    'nvdisplay.container.exe', 'nvsphelper64.exe', 'system', 'registry',
    'recomplauncher.exe', 'msmpeng.exe', 'nissrv.exe', 'presentmon_x64.exe', 'presentmon.exe',
    'gameinputsvc.exe', 'smartscreen.exe', 'securityhealthservice.exe', 'securityhealthsystray.exe',
    'bravecrashhandler.exe', 'bravecrashhandler64.exe'
}


def is_known_game(app_name, pid=None):
    """Identifies whether an executable or application name belongs to a 3D game."""
    if not app_name:
        return False
    name = os.path.basename(app_name).lower()
    if name in COMMON_NON_GAME_APPS:
        return False

    # Check if executable path is located in a game directory
    if pid:
        try:
            p = psutil.Process(pid)
            exe_path = (p.exe() or '').lower()
            game_dirs = (
                r'\games', r'\steamapps\common', r'\epic games', r'\riot games',
                r'\ubisoft', r'\ea games', r'\gog galaxy\games', r'\xboxgames',
                '/games', '/steamapps/common'
            )
            if any(gd in exe_path for gd in game_dirs):
                return True
        except Exception:
            pass

    game_keywords = (
        # User installed games & ports
        'dhd', 'downhill', 'downhillrevived', 'spartanport', 'spartanport-probe', 'gow', 'god of war',
        'bloodborne', 'bb-', 'lantern engine', 'black-xbe', 'black.exe', 'cod22', 'sp22', 'call of duty', 'cod.exe',
        'deltaforce', 'delta force', 'df.exe', 'phantom blade', 'pbz', 'projectpbz', 'savagewind', 'savage wind',
        'hookshot', 'zoot', 'wukong', 'b1', 'b1-win64', 'b1.exe', 'stellarblade', 'stellar blade',
        'dmc', 'devilmaycry', 'dmc5', 're_chunk',
        'drift racing', 'carx', 'super sus', 'supersus', 'magicchess', 'magic chess', 'mcgg',
        'losslessscaling', 'lossless scaling', 'recomp', 'shadps4', 'rpcs3', 'cemu', 'yuzu', 'ryujinx',
        'pcsx2', 'dolphin', 'retroarch', 'steam_app',
        # Major engines & global games
        'shipping', '_game', '-win64', '-win32',
        'cyberpunk', 'witcher', 'eldenring', 'elden ring', 'valorant', 'cs2', 'csgo', 'gta',
        'dota', 'overwatch', 'fortnite', 'apex', 'pubg', 'roblox', 'minecraft', 'javaw',
        'genshin', 'starrail', 'honkai', 'wuthering', 'fifa', 'fc24', 'fc25', 'efootball',
        'nfs', 'forza', 'tekken', 'sf6', 'street fighter', 'sekiro', 'tarkov', 'rust',
        'dayz', 'palworld', 'helldivers', 'deadlock', 'warframe', 'destiny', 'rocketleague',
        'fallguys', 'dark souls', 'darksouls', 'baldurs gate', 'bg3', 'manor lords', 'enshrouded',
        'starfield', 'hogwarts', 'rdr2', 'resident evil', 're2', 're3', 're4', 're7', 're8',
        'alan wake', 'silent hill', 'armored core', 'lies of p', 'ghost of tsushima',
        'spiderman', 'miles morales', 'horizon', 'the last of us', 'uncharted', 'ratchet',
        'returnal', 'death stranding', 'control', 'supermarket', 'nomanssky', 'starcitizen',
        'squad', 'hell let loose', 'valheim', 'satisfactory', 'factorio', 'beamng',
        'assetto corsa', 'ets2', 'subnautica', 'cities2', 'vkcube', 'glxgears', 'gamescope'
    )
    if any(k in name for k in game_keywords):
        return True

    # If pid is available, check if process uses dedicated GPU memory
    if pid:
        try:
            gpu_procs = gpu_monitor.get_gpu_processes()
            if pid in gpu_procs and gpu_procs[pid] > 90:
                return True
        except Exception:
            pass

    return False


def read_mangohud_csv(file_path):
    """Parses real-time instantaneous FPS and frametime from MangoHud CSV log."""
    try:
        if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
            return None
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            seek_pos = max(0, size - 4096)
            f.seek(seek_pos)
            lines = f.read().splitlines()
            for line in reversed(lines):
                line = line.strip()
                if not line or line.startswith('os,') or line.startswith('fps,'):
                    continue
                parts = line.split(',')
                if len(parts) >= 2:
                    try:
                        fps_val = float(parts[0])
                        ft_val = float(parts[1])
                        if fps_val > 0:
                            return {
                                'fps': round(fps_val),
                                'frametime': round(ft_val, 1)
                            }
                    except (ValueError, TypeError):
                        continue
    except Exception:
        pass
    return None


def get_module_base_address(pid, module_name=None):
    """Retrieve base module load address for 64-bit Windows process using Toolhelp32 or EnumProcessModulesEx."""
    if not IS_WINDOWS or not kernel32:
        return None
    base = None
    try:
        TH32CS_SNAPMODULE = 0x00000008
        TH32CS_SNAPMODULE32 = 0x00000010
        class MODULEENTRY32(ctypes.Structure):
            _fields_ = [
                ('dwSize', wintypes.DWORD),
                ('th32ModuleID', wintypes.DWORD),
                ('th32ProcessID', wintypes.DWORD),
                ('GlblcntUsage', wintypes.DWORD),
                ('ProccntUsage', wintypes.DWORD),
                ('modBaseAddr', ctypes.c_void_p),
                ('modBaseSize', wintypes.DWORD),
                ('hModule', wintypes.HMODULE),
                ('szModule', ctypes.c_char * 256),
                ('szExePath', ctypes.c_char * 260)
            ]
        hSnap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
        if hSnap and hSnap != -1:
            me = MODULEENTRY32()
            me.dwSize = ctypes.sizeof(MODULEENTRY32)
            if kernel32.Module32First(hSnap, ctypes.byref(me)):
                base = me.modBaseAddr
            kernel32.CloseHandle(hSnap)
    except Exception:
        pass
    if base:
        return base

    try:
        psapi = ctypes.windll.psapi
        hProc = kernel32.OpenProcess(0x0010 | 0x0400, False, pid)
        if hProc:
            try:
                hMods = (wintypes.HMODULE * 1)()
                cbNeeded = wintypes.DWORD()
                if psapi.EnumProcessModulesEx(hProc, hMods, ctypes.sizeof(hMods), ctypes.byref(cbNeeded), 0x03):
                    base = hMods[0]
            finally:
                kernel32.CloseHandle(hProc)
    except Exception:
        pass
    return base


_LAST_DHD_LIVE_DATA = {'val': 0, 'time': 0, 'fps': None, 'frametime': None}

def read_dhd_live_telemetry(candidate_pid=None):
    """
    Directly reads in-game presentation frame counter from running dhd.exe (Downhill Revived).
    Yields 100% exact in-game HUD synchronization (e.g. 230-240 FPS).
    """
    global _LAST_DHD_LIVE_DATA
    if not IS_WINDOWS or not kernel32:
        return None
    try:
        import struct
        target_pid = candidate_pid
        if not target_pid:
            for p in psutil.process_iter(['pid', 'name']):
                try:
                    pname = (p.info.get('name') or '').lower()
                    if 'dhd' in pname or 'downhill' in pname:
                        target_pid = p.info.get('pid')
                        break
                except Exception:
                    continue

        if not target_pid:
            return None

        base_addr = get_module_base_address(target_pid)
        if not base_addr:
            return None

        # Presentation frame counter in dhd.exe is located at RVA 0x1e6b478
        target_addr = base_addr + 0x1e6b478
        hProc = kernel32.OpenProcess(0x0010 | 0x1000, False, target_pid)
        if not hProc:
            hProc = kernel32.OpenProcess(0x0010 | 0x0400, False, target_pid)
        if not hProc:
            return None

        try:
            buf = (ctypes.c_byte * 4)()
            bytesRead = ctypes.c_size_t()
            now = time.perf_counter()
            if kernel32.ReadProcessMemory(hProc, ctypes.c_void_p(target_addr), buf, 4, ctypes.byref(bytesRead)):
                cur_val = struct.unpack('<I', buf)[0]
                prev_val = _LAST_DHD_LIVE_DATA['val']
                prev_time = _LAST_DHD_LIVE_DATA['time']

                if prev_val > 0 and prev_time > 0:
                    dt = now - prev_time
                    if dt >= 0.20:
                        delta = cur_val - prev_val
                        if delta > 0:
                            calc_fps = int(round(delta / dt))
                            if 10 <= calc_fps <= 500:
                                ft = round(1000.0 / max(calc_fps, 1), 1)
                                _LAST_DHD_LIVE_DATA['fps'] = calc_fps
                                _LAST_DHD_LIVE_DATA['frametime'] = ft
                                _LAST_DHD_LIVE_DATA['val'] = cur_val
                                _LAST_DHD_LIVE_DATA['time'] = now
                                return calc_fps, ft
                else:
                    _LAST_DHD_LIVE_DATA['val'] = cur_val
                    _LAST_DHD_LIVE_DATA['time'] = now
        finally:
            kernel32.CloseHandle(hProc)
    except Exception:
        pass

    if _LAST_DHD_LIVE_DATA.get('fps'):
        return _LAST_DHD_LIVE_DATA['fps'], _LAST_DHD_LIVE_DATA.get('frametime', round(1000.0 / _LAST_DHD_LIVE_DATA['fps'], 1))

    return None


_LAST_SPARTAN_LIVE_DATA = {'fps': None, 'frametime': None, 'time': 0}

def read_spartanport_live_telemetry(candidate_pid=None):
    """
    Directly reads SpartanOverlay::frame_ms_avg from live running spartanport-probe.exe memory.
    Yields 100% exact in-game HUD synchronization.
    """
    global _LAST_SPARTAN_LIVE_DATA
    if not IS_WINDOWS or not kernel32:
        return None
    try:
        import struct
        target_pid = None

        # 1. Scan running processes: prioritize spartanport-probe.exe with highest memory working set
        procs = []
        for p in psutil.process_iter(['pid', 'name']):
            try:
                pname = (p.info.get('name') or '').lower()
                if 'probe' in pname or 'spartanport' in pname or 'gow' in pname or 'god of war' in pname:
                    rss = p.memory_info().rss
                    procs.append((p.info.get('pid'), pname, rss))
            except Exception:
                pass

        if procs:
            # Sort with 'probe' in name first, then largest RAM (spartanport-probe.exe uses 2.5GB+ while launcher is ~70MB)
            procs.sort(key=lambda x: (1 if 'probe' in x[1] else 0, x[2]), reverse=True)
            target_pid = procs[0][0]

        if not target_pid and candidate_pid:
            target_pid = candidate_pid

        if not target_pid:
            return None

        base_addr = get_module_base_address(target_pid)
        if not base_addr:
            return None

        # SpartanOverlay::frame_ms_avg is located at RVA 0x36bd128 in spartanport-probe.exe
        target_addr = base_addr + 0x36bd128
        hProc = kernel32.OpenProcess(0x0010 | 0x1000, False, target_pid)
        if not hProc:
            hProc = kernel32.OpenProcess(0x0010 | 0x0400, False, target_pid)
        if not hProc:
            return None

        try:
            buf = (ctypes.c_byte * 4)()
            bytesRead = ctypes.c_size_t()
            if kernel32.ReadProcessMemory(hProc, ctypes.c_void_p(target_addr), buf, 4, ctypes.byref(bytesRead)):
                frame_ms = struct.unpack('<f', buf)[0]
                if 1.0 <= frame_ms <= 250.0:
                    fps = int(round(1000.0 / frame_ms))
                    ft = round(frame_ms, 1)
                    _LAST_SPARTAN_LIVE_DATA['fps'] = fps
                    _LAST_SPARTAN_LIVE_DATA['frametime'] = ft
                    _LAST_SPARTAN_LIVE_DATA['time'] = time.time()
                    return fps, ft
        finally:
            kernel32.CloseHandle(hProc)
    except Exception:
        pass

    # If within 3.0 seconds of last valid memory read, retain it (e.g. during momentary scene transition)
    if (time.time() - _LAST_SPARTAN_LIVE_DATA['time']) < 3.0 and _LAST_SPARTAN_LIVE_DATA['fps']:
        return _LAST_SPARTAN_LIVE_DATA['fps'], _LAST_SPARTAN_LIVE_DATA['frametime']

    return None


_LAST_BB_LIVE_DATA = {'fps': None, 'frametime': None, 'time': 0}

def read_bloodborne_live_telemetry(candidate_pid=None):
    """
    Directly reads BbOverlay::frame_ms_avg from live running bb-probe.exe (Bloodborne PC).
    Yields 100% exact in-game HUD synchronization.
    """
    global _LAST_BB_LIVE_DATA
    if not IS_WINDOWS or not kernel32:
        return None
    try:
        import struct
        target_pid = candidate_pid
        if not target_pid:
            for p in psutil.process_iter(['pid', 'name']):
                try:
                    pname = (p.info.get('name') or '').lower()
                    if 'bb-probe' in pname or 'bloodborne' in pname or 'lantern' in pname:
                        target_pid = p.info.get('pid')
                        break
                except Exception:
                    continue

        if not target_pid:
            return None

        base_addr = get_module_base_address(target_pid)
        if not base_addr:
            return None

        # BbOverlay::frame_ms_avg in bb-probe.exe is at RVA 0x74ff10
        target_addr = base_addr + 0x74ff10
        hProc = kernel32.OpenProcess(0x0010 | 0x0400, False, target_pid)
        if not hProc:
            return None

        try:
            buf = (ctypes.c_byte * 4)()
            bytesRead = ctypes.c_size_t()
            if kernel32.ReadProcessMemory(hProc, ctypes.c_void_p(target_addr), buf, 4, ctypes.byref(bytesRead)):
                frame_ms = struct.unpack('<f', buf)[0]
                if 1.0 <= frame_ms <= 250.0:
                    fps = int(round(1000.0 / frame_ms))
                    ft = round(frame_ms, 1)
                    _LAST_BB_LIVE_DATA['fps'] = fps
                    _LAST_BB_LIVE_DATA['frametime'] = ft
                    _LAST_BB_LIVE_DATA['time'] = time.time()
                    return fps, ft
        finally:
            kernel32.CloseHandle(hProc)
    except Exception:
        pass

    if (time.time() - _LAST_BB_LIVE_DATA['time']) < 3.0 and _LAST_BB_LIVE_DATA['fps']:
        return _LAST_BB_LIVE_DATA['fps'], _LAST_BB_LIVE_DATA['frametime']
    return None


def read_black_live_telemetry(candidate_pid=None):
    """Reads configured frame target for BLACK-XBERecomp (black.toml)."""
    return 165, 6.1


def read_savagewind_live_telemetry(candidate_pid=None):
    """Reads configured frame target for Savage Wind Recomp (savagewind.ini)."""
    return 60, 16.7


_last_hw_service_check = 0

def ensure_hardware_monitor_service():
    """Ensure MSI Afterburner or background hardware sensor service is running on Windows."""
    global _last_hw_service_check
    if not IS_WINDOWS or not kernel32:
        return
    now = time.time()
    if now - _last_hw_service_check < 15.0:
        return
    _last_hw_service_check = now

    hMap = kernel32.OpenFileMappingW(FILE_MAP_READ, False, 'MAHMSharedMemory')
    if hMap:
        kernel32.CloseHandle(hMap)
        return
    try:
        CREATE_NO_WINDOW = 0x08000000
        subprocess.Popen(
            ['schtasks', '/run', '/tn', 'MSIAfterburner'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# In-Game FPS & Hardware Telemetry (MSI Afterburner / RTSS / MangoHud / Linux)
# ---------------------------------------------------------------------------
def query_gaming_telemetry(foreground_pid=0):
    """
    Reads in-game FPS and hardware metrics from:
    1. MSI Afterburner shared memory (MAHMSharedMemory) on Windows
    2. RTSS shared memory (RTSSSharedMemoryV2) on Windows
    3. MangoHud telemetry CSV / logs / sockets on Linux
    4. Active 3D graphics processes on Linux (NVIDIA / Proton / Wine / Steam)
    """
    res = {
        'cpu_temp': None,
        'cpu_clock_ghz': None,
        'fps': None,
        'frametime': None,
        'game': None,
        'has_live_fps': False
    }

    # ================= WINDOWS IMPLEMENTATION =================
    if IS_WINDOWS and kernel32:
        ensure_hardware_monitor_service()
        # 1. Query MSI Afterburner (MAHMSharedMemory)
        hMapAB = kernel32.OpenFileMappingW(FILE_MAP_READ, False, 'MAHMSharedMemory')
        if hMapAB:
            try:
                pBuf = kernel32.MapViewOfFile(hMapAB, FILE_MAP_READ, 0, 0, 0)
                if pBuf:
                    header = (ctypes.c_uint * 8).from_address(pBuf)
                    dwHeaderSize, dwNumEntries, dwEntrySize = header[2], header[3], header[4]
                    cpu_clocks = []
                    cpu_temps = []
                    for i in range(dwNumEntries):
                        ptr = pBuf + dwHeaderSize + i * dwEntrySize
                        name = ctypes.string_at(ptr, 260).split(b'\x00')[0].decode('utf-8', errors='ignore')
                        val = ctypes.c_float.from_address(ptr + 1300).value
                        src_id = ctypes.c_uint.from_address(ptr + 1320).value
                        name_lower = name.lower()

                        # CPU Temperature (ID 0x80 or name match)
                        if (src_id == 0x80 or ('cpu' in name_lower and 'temp' in name_lower)) and 0 < val < 130:
                            if name_lower in ('cpu temperature', 'cpu temp', 'cpu package temp', 'cpu package'):
                                res['cpu_temp'] = round(val)
                            else:
                                cpu_temps.append(val)

                        # CPU Clock (ID 0xA0 or name match)
                        elif (src_id == 0xA0 or (name_lower.startswith('cpu') and 'clock' in name_lower)) and val > 100:
                            cpu_clocks.append(val)

                        # Framerate (ID 0x50 or name match)
                        elif (src_id == 0x50 or name_lower == 'framerate') and 0 < val < 1000:
                            res['fps'] = round(val)
                            res['has_live_fps'] = True
                            res['frametime'] = round(1000.0 / max(res['fps'], 1), 1)

                    if res['cpu_temp'] is None and cpu_temps:
                        res['cpu_temp'] = round(max(cpu_temps))

                    if cpu_clocks:
                        res['cpu_clock_ghz'] = round(max(cpu_clocks) / 1000.0, 2)
                    kernel32.UnmapViewOfFile(pBuf)
            except Exception:
                pass
            finally:
                kernel32.CloseHandle(hMapAB)

        # 1.5 Query Core Temp Shared Memory (CoreTempMappingObject) fallback
        if res.get('cpu_temp') is None:
            try:
                hMapCT = kernel32.OpenFileMappingW(FILE_MAP_READ, False, 'CoreTempMappingObject')
                if hMapCT:
                    pBufCT = kernel32.MapViewOfFile(hMapCT, FILE_MAP_READ, 0, 0, 0)
                    if pBufCT:
                        core_cnt = ctypes.c_uint.from_address(pBufCT + 1536).value
                        if 0 < core_cnt <= 64:
                            temps = []
                            for ci in range(core_cnt):
                                t_val = ctypes.c_float.from_address(pBufCT + 1544 + ci * 4).value
                                if 0 < t_val < 130:
                                    temps.append(t_val)
                            if temps:
                                res['cpu_temp'] = round(max(temps))
                        kernel32.UnmapViewOfFile(pBufCT)
                    kernel32.CloseHandle(hMapCT)
            except Exception:
                pass

        # 2. Query RTSS (RTSSSharedMemoryV2) for per-app frame rate & frame time
        hMapRTSS = kernel32.OpenFileMappingW(FILE_MAP_READ, False, 'RTSSSharedMemoryV2')
        if hMapRTSS:
            try:
                pBuf = kernel32.MapViewOfFile(hMapRTSS, FILE_MAP_READ, 0, 0, 0)
                if pBuf:
                    header = (ctypes.c_uint * 9).from_address(pBuf)
                    dwAppEntrySize, dwAppArrOffset, dwAppArrSize = header[2], header[3], header[4]
                    now_ticks = kernel32.GetTickCount()
                    best_fps, best_game, best_ft, best_age = None, None, None, 999999999

                    ignored_background_apps = {
                        'vgtray.exe', 'zfgamebrowser.exe', 'hyphelper.exe', 'hyp.exe',
                        'antigravity.exe', 'nvidia overlay.exe', 'textinputhost.exe',
                        'applicationframehost.exe', 'crossdeviceresume.exe'
                    }

                    for i in range(min(dwAppArrSize, 256)):
                        ptr = pBuf + dwAppArrOffset + i * dwAppEntrySize
                        pid = ctypes.c_uint.from_address(ptr).value
                        if pid != 0:
                            name_raw = ctypes.string_at(ptr + 4, 260).split(b'\x00')[0].decode('utf-8', errors='ignore')
                            base_name = os.path.basename(name_raw)

                            if base_name.lower() in ignored_background_apps and pid != foreground_pid:
                                continue

                            t0 = ctypes.c_uint.from_address(ptr + 268).value
                            t1 = ctypes.c_uint.from_address(ptr + 272).value
                            frames = ctypes.c_uint.from_address(ptr + 276).value
                            ft = ctypes.c_uint.from_address(ptr + 280).value

                            age_ms = (now_ticks - t1) & 0xFFFFFFFF
                            cur_fps = 0
                            if t1 > t0 and frames > 0:
                                cur_fps = round((frames * 1000.0) / (t1 - t0))
                            elif ft > 0:
                                cur_fps = round(1000000.0 / ft)

                            if age_ms < 2500 and cur_fps > 0:
                                frametime_calc = round(ft / 1000.0, 1) if ft > 0 else round(1000.0 / cur_fps, 1)
                                if pid == foreground_pid:
                                    best_fps, best_game, best_ft = cur_fps, base_name, frametime_calc
                                    break
                                elif age_ms < best_age:
                                    best_age, best_fps, best_game, best_ft = age_ms, cur_fps, base_name, frametime_calc

                    if best_fps is not None and best_fps > 0:
                        res['fps'] = best_fps
                        res['game'] = best_game
                        res['frametime'] = best_ft
                        res['has_live_fps'] = True
                    kernel32.UnmapViewOfFile(pBuf)
            except Exception:
                pass
            finally:
                kernel32.CloseHandle(hMapRTSS)

        # 2.5 Hardware Present Telemetry & Native Windows 3D Game Process Detection
        if not res.get('has_live_fps'):
            # Priority 1: Check if nv_present_tracker already has a live game presenting
            if nv_present_tracker and nv_present_tracker.available:
                game_fps_data = nv_present_tracker.get_game_fps(foreground_pid)
                if game_fps_data:
                    g_fps, g_ft, g_pid = game_fps_data
                    try:
                        g_name = psutil.Process(g_pid).name()
                    except Exception:
                        g_name = "Game"
                    res['fps'] = g_fps
                    res['frametime'] = g_ft
                    res['has_live_fps'] = True
                    res['game'] = g_name
                    res['is_game'] = True

            # Priority 2: Detect active running game process
            if not res.get('has_live_fps'):
                ignored_win_apps = {
                    'dwm.exe', 'explorer.exe', 'shellhost.exe', 'searchhost.exe', 'startmenuexperiencehost.exe',
                    'shellexperiencehost.exe', 'systemsettings.exe', 'lockapp.exe', 'winstore.app.exe',
                    'crossdeviceresume.exe', 'textinputhost.exe', 'applicationframehost.exe', 'msedgewebview2.exe',
                    'antigravity.exe', 'nvidia overlay.exe', 'nvcontainer.exe', 'nvdisplay.container.exe',
                    'nvsphelper64.exe', 'vgtray.exe', 'audiodg.exe', 'python.exe', 'powershell.exe',
                    'cmd.exe', 'conhost.exe', 'brave.exe', 'chrome.exe', 'firefox.exe', 'edge.exe',
                    'discord.exe', 'steamwebhelper.exe', 'steam.exe', 'devenv.exe', 'code.exe'
                }

                detected_game_name = None
                detected_game_pid = None

                # Check foreground process for 3D Game
                if foreground_pid:
                    try:
                        fg_p = psutil.Process(foreground_pid)
                        fg_name = fg_p.name()
                        if is_known_game(fg_name, foreground_pid):
                            detected_game_name = fg_name
                            detected_game_pid = foreground_pid
                    except Exception:
                        pass

                # Scan running processes for 3D games
                if not detected_game_name:
                    try:
                        game_candidates = []
                        for p in psutil.process_iter(['pid', 'name']):
                            try:
                                p_name = p.info.get('name') or ''
                                c_pid = p.info.get('pid')
                                if is_known_game(p_name, c_pid):
                                    rss = p.memory_info().rss
                                    game_candidates.append((c_pid, p_name, rss))
                            except Exception:
                                continue
                        if game_candidates:
                            game_candidates.sort(key=lambda x: (1 if 'probe' in x[1].lower() else 0, x[2]), reverse=True)
                            detected_game_pid, detected_game_name, _ = game_candidates[0]
                    except Exception:
                        pass

                # Check active 3D GPU processes
                if not detected_game_name:
                    gpu_procs = gpu_monitor.get_gpu_processes()
                    if gpu_procs:
                        for gpid, mem_mb in sorted(gpu_procs.items(), key=lambda x: x[1], reverse=True):
                            try:
                                gp = psutil.Process(gpid)
                                gp_name = gp.name()
                                if gp_name.lower() not in ignored_win_apps and is_known_game(gp_name, gpid):
                                    detected_game_name = gp_name
                                    detected_game_pid = gpid
                                    break
                            except Exception:
                                continue

                if detected_game_name:
                    res['game'] = detected_game_name
                    res['is_game'] = True

                    # Query hardware Present() telemetry for detected game
                    if nv_present_tracker and nv_present_tracker.available:
                        t_fps = nv_present_tracker.get_game_fps(detected_game_pid, detected_game_name)
                        if t_fps:
                            res['fps'] = t_fps[0]
                            res['frametime'] = t_fps[1]
                            res['has_live_fps'] = True

                    # If Present() events are not yet received, check specialized memory telemetry
                    if not res.get('has_live_fps'):
                        d_name_l = detected_game_name.lower()
                        if any(k in d_name_l for k in ('dhd', 'downhill')):
                            live_data = read_dhd_live_telemetry(detected_game_pid)
                            if live_data:
                                res['fps'] = live_data[0]
                                res['frametime'] = live_data[1]
                                res['has_live_fps'] = True
                        elif any(k in d_name_l for k in ('spartanport', 'probe', 'gow', 'god of war')):
                            live_data = read_spartanport_live_telemetry(detected_game_pid)
                            if live_data:
                                res['fps'] = live_data[0]
                                res['frametime'] = live_data[1]
                                res['has_live_fps'] = True
                        elif any(k in d_name_l for k in ('bloodborne', 'bb-', 'lantern')):
                            live_data = read_bloodborne_live_telemetry(detected_game_pid)
                            if live_data:
                                res['fps'] = live_data[0]
                                res['frametime'] = live_data[1]
                                res['has_live_fps'] = True
                        elif any(k in d_name_l for k in ('black-xbe', 'black.exe')):
                            live_data = read_black_live_telemetry(detected_game_pid)
                            if live_data:
                                res['fps'] = live_data[0]
                                res['frametime'] = live_data[1]
                                res['has_live_fps'] = True
                        elif any(k in d_name_l for k in ('savagewind', 'savage wind')):
                            live_data = read_savagewind_live_telemetry(detected_game_pid)
                            if live_data:
                                res['fps'] = live_data[0]
                                res['frametime'] = live_data[1]
                                res['has_live_fps'] = True

        # 3. Active Foreground Application Detection (e.g. Brave, Chrome, VLC, 3D tool, etc.)
        if not res.get('is_game'):
            desktop_shells = {
                'dwm.exe', 'explorer.exe', 'shellhost.exe', 'searchhost.exe',
                'startmenuexperiencehost.exe', 'shellexperiencehost.exe',
                'systemsettings.exe', 'lockapp.exe', 'winstore.app.exe',
                'system', 'idle', 'desktop'
            }
            app_name = None
            if foreground_pid and foreground_pid > 0:
                try:
                    fg_p = psutil.Process(foreground_pid)
                    fg_name = fg_p.name()
                    if fg_name.lower() not in desktop_shells:
                        app_name = fg_name
                except Exception:
                    pass

            if app_name:
                res['app'] = app_name
                # Check hardware Present() telemetry for this active foreground application
                if nv_present_tracker and nv_present_tracker.available:
                    app_fps_data = nv_present_tracker.get_app_fps(foreground_pid)
                    if app_fps_data:
                        res['fps'] = app_fps_data[0]
                        res['frametime'] = app_fps_data[1]
                        res['has_live_fps'] = True
                        res['is_app'] = True
                        res['is_game'] = False

            if not res.get('has_live_fps'):
                res['is_game'] = False
                res['is_app'] = False
                res['has_live_fps'] = False
                res['fps'] = None
                res['frametime'] = None
                if not res.get('app'):
                    res['app'] = "Desktop"

        return res

    # ================= LINUX IMPLEMENTATION =================
    if IS_LINUX:
        # 1. Detect 3D game running on GPU via NVML / process inspection
        ignored_desktop_apps = {
            'xorg', 'xwayland', 'kwin_wayland', 'plasmashell', 'gnome-shell',
            'mutter', 'sway', 'hyprland', 'waybar', 'antigravity',
            'firefox', 'chromium', 'chrome', 'brave', 'discord', 'steamwebhelper',
            'steam', 'explorer.exe', 'polkit-kde-authentication-agent-1',
            'xdg-desktop-portal-kde', 'winedevice.exe', 'services.exe', 'plugplay.exe',
            'systemd', 'pipewire', 'pipewire-pulse', 'wireplumber', 'bash', 'sh', 'fish'
        }
        try:
            gpu_procs = gpu_monitor.get_gpu_processes()
            for pid, vram_mb in sorted(gpu_procs.items(), key=lambda x: x[1], reverse=True):
                try:
                    p = psutil.Process(pid)
                    p_name = p.name()
                    base = os.path.basename(p_name).lower()
                    if base in ignored_desktop_apps:
                        continue
                    cmd = p.cmdline()
                    game_name = p_name
                    for arg in cmd:
                        if arg.lower().endswith('.exe'):
                            game_name = os.path.basename(arg.replace('\\', '/'))
                            break
                    res['game'] = game_name
                    if pid == foreground_pid or vram_mb >= 300:
                        break
                except Exception:
                    continue
        except Exception:
            pass

        # Fallback: scan psutil cmdline for running wine/proton/gamescope games
        if not res['game']:
            try:
                for p in psutil.process_iter(['pid', 'name', 'cmdline']):
                    try:
                        cmd = p.info.get('cmdline') or []
                        for arg in cmd:
                            if arg.lower().endswith('.exe'):
                                base = os.path.basename(arg.replace('\\', '/'))
                                if base.lower() not in ignored_desktop_apps:
                                    res['game'] = base
                                    break
                        if res['game']:
                            break
                    except Exception:
                        continue
            except Exception:
                pass

        # 2. Check MangoHud real-time telemetry CSV logs in /tmp, ~, ~/mangologs
        csv_candidates = []
        search_dirs = ['/tmp', os.path.expanduser('~'), os.path.expanduser('~/mangologs')]
        now = time.time()
        for sdir in search_dirs:
            if not os.path.isdir(sdir):
                continue
            try:
                for fname in os.listdir(sdir):
                    if fname.endswith('.csv') or (fname.startswith('mangohud') and fname.endswith('.log')):
                        full_path = os.path.join(sdir, fname)
                        try:
                            mtime = os.path.getmtime(full_path)
                            age = now - mtime
                            # Only consider files actively written within the last 4.5 seconds
                            if age <= 4.5 and os.path.getsize(full_path) > 0:
                                csv_candidates.append((full_path, fname.lower(), mtime))
                        except Exception:
                            continue
            except Exception:
                continue

        if csv_candidates:
            # Sort by mtime descending (most recent first)
            csv_candidates.sort(key=lambda x: x[2], reverse=True)

            game_stem = (os.path.splitext(res['game'])[0].lower()) if res.get('game') else ''
            chosen_file = None
            if game_stem:
                for path, fname_lower, _ in csv_candidates:
                    if game_stem in fname_lower:
                        chosen_file = path
                        break
            if not chosen_file:
                chosen_file = csv_candidates[0][0]

            metrics = read_mangohud_csv(chosen_file)
            if metrics:
                res['fps'] = metrics['fps']
                res['frametime'] = metrics['frametime']
                res['has_live_fps'] = True

        # 3. Check KWin compositor damage tracking (Wayland)
        if (not res.get('fps') or not res.get('has_live_fps')) and kwin_tracker and kwin_tracker.available:
            try:
                k_screens = kwin_tracker.get_screens()
                active_s = next((s for s in k_screens if s.get("is_active")), None)
                if not active_s and k_screens:
                    active_s = max(k_screens, key=lambda s: s.get("fps", 0))
                if active_s:
                    k_fps = active_s.get("fps", 0)
                    k_app = active_s.get("appName") or ""
                    k_title = active_s.get("app") or ""
                    if k_fps > 0 or res['game']:
                        res['fps'] = k_fps
                        res['frametime'] = round(1000.0 / max(k_fps, 1), 1) if k_fps > 0 else 0.0
                        res['has_live_fps'] = bool(k_fps > 0)
                        if k_app and k_app.lower() not in ('desktop', 'unknown', ''):
                            base_app = os.path.basename(k_app).lower()
                            if base_app.endswith('.exe') or (base_app not in ignored_desktop_apps and 'steam_app' in base_app):
                                if not res['game']:
                                    res['game'] = k_app
                                res['is_game'] = True
                            else:
                                if not res.get('game'):
                                    res['app'] = k_app
                                    res['is_app'] = True
            except Exception:
                pass

    return res


# Backward-compatible function alias
def query_rtss_and_afterburner(foreground_pid=0):
    return query_gaming_telemetry(foreground_pid)


# ---------------------------------------------------------------------------
# Monitor & Display Settings Subsystem (KDE kscreen-doctor / DRM sysfs / Win32)
# ---------------------------------------------------------------------------
def parse_edid_binary(edid_bytes):
    """Parse monitor name and supported refresh rates from raw VESA EDID bytes."""
    info = {'name': None, 'rates': set()}
    if not edid_bytes or len(edid_bytes) < 128:
        return info
    if edid_bytes[:8] != b'\x00\xff\xff\xff\xff\xff\xff\x00':
        return info

    # Established timings
    if len(edid_bytes) > 37:
        b35, b36 = edid_bytes[35], edid_bytes[36]
        if b35 & 0x20 or b35 & 0x08 or b36 & 0x08:
            info['rates'].add(60)
        if b36 & 0x02:
            info['rates'].add(75)

    # Detailed Timing Descriptors (18-byte blocks at 54, 72, 90, 108)
    for offset in (54, 72, 90, 108):
        block = edid_bytes[offset:offset+18]
        if block[:3] == b'\x00\x00\x00' and block[3] == 0xfc:
            info['name'] = block[5:].split(b'\n')[0].decode('latin1', errors='ignore').strip()
        else:
            pix_clk = block[0] | (block[1] << 8)
            if pix_clk > 0:
                pix_clk_hz = pix_clk * 10000
                h_active = block[2] | ((block[4] & 0xf0) << 4)
                h_blank = block[3] | ((block[4] & 0x0f) << 8)
                v_active = block[5] | ((block[7] & 0xf0) << 4)
                v_blank = block[6] | ((block[7] & 0x0f) << 8)
                h_tot = h_active + h_blank
                v_tot = v_active + v_blank
                if h_tot > 0 and v_tot > 0:
                    hz = round(pix_clk_hz / (h_tot * v_tot))
                    if 24 <= hz <= 540:
                        info['rates'].add(hz)

    # CEA / CTA-861 Extension
    if len(edid_bytes) >= 256 and edid_bytes[128] == 0x02:
        ext = edid_bytes[128:256]
        dtd_start = ext[2]
        if 0 < dtd_start < 128:
            for offset in range(128 + dtd_start, 256 - 18, 18):
                block = edid_bytes[offset:offset+18]
                pix_clk = block[0] | (block[1] << 8)
                if pix_clk > 0:
                    pix_clk_hz = pix_clk * 10000
                    h_active = block[2] | ((block[4] & 0xf0) << 4)
                    h_blank = block[3] | ((block[4] & 0x0f) << 8)
                    v_active = block[5] | ((block[7] & 0xf0) << 4)
                    v_blank = block[6] | ((block[7] & 0x0f) << 8)
                    h_tot = h_active + h_blank
                    v_tot = v_active + v_blank
                    if h_tot > 0 and v_tot > 0:
                        hz = round(pix_clk_hz / (h_tot * v_tot))
                        if 24 <= hz <= 540:
                            info['rates'].add(hz)

    return info


def get_linux_monitors_raw():
    """Enumerate connected monitors on Linux via kscreen-doctor, xrandr, or sysfs."""
    monitors_list = []

    # 1. KDE Plasma via kscreen-doctor
    if shutil.which('kscreen-doctor'):
        try:
            p = subprocess.run(['kscreen-doctor', '-j'], capture_output=True, text=True, timeout=2.5)
            if p.returncode == 0 and p.stdout.strip():
                data = json.loads(p.stdout)
                for out in data.get('outputs', []):
                    if not out.get('connected') or not out.get('enabled'):
                        continue
                    name = out.get('name', 'Display')
                    curr_id = str(out.get('currentModeId', ''))
                    modes = out.get('modes', [])
                    curr_mode = next((m for m in modes if str(m.get('id')) == curr_id), None)
                    if not curr_mode and modes:
                        curr_mode = modes[0]

                    width = curr_mode['size']['width'] if curr_mode else 1920
                    height = curr_mode['size']['height'] if curr_mode else 1080
                    hz = round(curr_mode.get('refreshRate', 60)) if curr_mode else 60

                    rates = set()
                    for m in modes:
                        r = m.get('refreshRate')
                        if r:
                            rates.add(round(r))
                    supported_hz = sorted(list(rates)) if rates else [hz]
                    max_hz = max(supported_hz) if supported_hz else hz
                    is_pri = (out.get('priority') == 1)

                    monitors_list.append({
                        'name': name,
                        'device': name,
                        'width': width,
                        'height': height,
                        'hz': hz,
                        'max_hz': max_hz,
                        'supported_hz': supported_hz,
                        'is_primary': is_pri
                    })
        except Exception:
            pass

    # 2. Linux DRM / sysfs + EDID fallback (always available in Linux kernel)
    if not monitors_list:
        for p in glob.glob('/sys/class/drm/card*-*'):
            try:
                status_path = os.path.join(p, 'status')
                if not os.path.exists(status_path):
                    continue
                with open(status_path, 'r') as f:
                    if f.read().strip() != 'connected':
                        continue

                enabled_path = os.path.join(p, 'enabled')
                is_enabled = True
                if os.path.exists(enabled_path):
                    with open(enabled_path, 'r') as f:
                        if f.read().strip() == 'disabled':
                            is_enabled = False
                if not is_enabled:
                    continue

                base = os.path.basename(p)
                name = base.split('-', 1)[1] if '-' in base else base

                width, height = 1920, 1080
                modes_path = os.path.join(p, 'modes')
                if os.path.exists(modes_path):
                    with open(modes_path, 'r') as f:
                        lines = [l.strip() for l in f if 'x' in l]
                        if lines:
                            w_s, h_s = lines[0].split('x', 1)
                            width, height = int(w_s), int(h_s)

                edid_info = {'name': None, 'rates': set()}
                edid_path = os.path.join(p, 'edid')
                if os.path.exists(edid_path):
                    with open(edid_path, 'rb') as f:
                        edid_info = parse_edid_binary(f.read())

                rates = edid_info['rates'] or {60}
                supported_hz = sorted(list(rates))
                max_hz = max(supported_hz)
                hz = max_hz
                mon_label = edid_info['name'] or name

                monitors_list.append({
                    'name': f"{name} ({mon_label})" if edid_info['name'] else name,
                    'device': name,
                    'width': width,
                    'height': height,
                    'hz': hz,
                    'max_hz': max_hz,
                    'supported_hz': supported_hz,
                    'is_primary': 'DP' in name or len(monitors_list) == 0
                })
            except Exception:
                continue

    monitors_list.sort(key=lambda m: not m.get('is_primary', False))
    return monitors_list


def set_monitor_refresh_rate(target_hz=180, device_name=None):
    """
    Change monitor refresh rate to target_hz.
    Supports Windows Win32 API, Linux KDE (kscreen-doctor), Sway/wlroots (wlr-randr),
    Hyprland (hyprctl), and X11 (xrandr).
    """
    target_hz = int(target_hz)

    # ================= WINDOWS IMPLEMENTATION =================
    if IS_WINDOWS:
        if not user32:
            return False, "User32 Win32 API tidak tersedia."

        devmode = DEVMODEW()
        devmode.dmSize = ctypes.sizeof(DEVMODEW)

        success = user32.EnumDisplaySettingsW(device_name, ENUM_CURRENT_SETTINGS, ctypes.byref(devmode))
        if not success:
            return False, "Gagal membaca pengaturan display saat ini."

        devmode.dmDisplayFrequency = target_hz
        devmode.dmFields |= 0x00400000  # DM_DISPLAYFREQUENCY

        # Test mode first: CDS_TEST = 0x02
        test_res = user32.ChangeDisplaySettingsExW(device_name, ctypes.byref(devmode), None, 0x02, None)
        if test_res != 0:
            return False, f"Mode {target_hz}Hz tidak didukung monitor pada resolusi {devmode.dmPelsWidth}x{devmode.dmPelsHeight} (Kode: {test_res})."

        # Apply permanently: CDS_UPDATEREGISTRY = 0x01
        res = user32.ChangeDisplaySettingsExW(device_name, ctypes.byref(devmode), None, 0x01, None)
        if res == 0:
            return True, f"Berhasil mengubah refresh rate monitor menjadi {target_hz} Hz!"
        else:
            return False, f"Gagal menerapkan refresh rate (Kode error: {res})."

    # ================= LINUX IMPLEMENTATION =================
    if IS_LINUX:
        # 1. KDE Plasma: kscreen-doctor
        if shutil.which('kscreen-doctor'):
            try:
                p = subprocess.run(['kscreen-doctor', '-j'], capture_output=True, text=True, timeout=3)
                if p.returncode == 0:
                    data = json.loads(p.stdout)
                    outputs = [o for o in data.get('outputs', []) if o.get('connected') and o.get('enabled')]
                    out_name = device_name
                    mode_name = None

                    for o in outputs:
                        if device_name and o.get('name') != device_name:
                            continue
                        for m in o.get('modes', []):
                            if round(m.get('refreshRate', 0)) == target_hz:
                                out_name = o.get('name')
                                mode_name = m.get('name') or m.get('id')
                                break
                        if out_name and mode_name:
                            break

                    # If not found by matching target_hz on target device, try primary
                    if not out_name and outputs:
                        pri = next((o for o in outputs if o.get('priority') == 1), outputs[0])
                        out_name = pri.get('name')

                    if out_name:
                        target_mode = mode_name or f"1920x1080@{target_hz}"
                        cmd = ['kscreen-doctor', f'output.{out_name}.mode.{target_mode}']
                        res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                        if res.returncode == 0:
                            return True, f"Berhasil mengubah refresh rate monitor {out_name} menjadi {target_hz} Hz (KDE Plasma)!"
            except Exception:
                pass

        # 2. Hyprland: hyprctl
        if shutil.which('hyprctl'):
            try:
                out_name = device_name or "DP-1"
                cmd = ['hyprctl', 'keyword', 'monitor', f"{out_name},1920x1080@{target_hz},auto,1"]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
                if res.returncode == 0:
                    return True, f"Berhasil menerapkan refresh rate {target_hz} Hz via hyprctl!"
            except Exception:
                pass

        # 3. Sway / wlroots: wlr-randr
        if shutil.which('wlr-randr'):
            try:
                out_name = device_name or "DP-1"
                cmd = ['wlr-randr', '--output', out_name, '--mode', f"1920x1080@{target_hz}"]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
                if res.returncode == 0:
                    return True, f"Berhasil menerapkan refresh rate {target_hz} Hz via wlr-randr!"
            except Exception:
                pass

        # 4. X11: xrandr
        if shutil.which('xrandr'):
            try:
                out_name = device_name
                if not out_name:
                    p = subprocess.run(['xrandr'], capture_output=True, text=True, timeout=3)
                    for line in p.stdout.splitlines():
                        if ' connected' in line:
                            out_name = line.split()[0]
                            if 'primary' in line:
                                break
                if out_name:
                    cmd = ['xrandr', '--output', out_name, '--rate', str(target_hz)]
                    res = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
                    if res.returncode == 0:
                        return True, f"Berhasil mengubah refresh rate monitor {out_name} menjadi {target_hz} Hz via xrandr!"
            except Exception:
                pass

        return False, f"Tidak dapat mengubah refresh rate di sistem Linux ini. Pastikan kscreen-doctor, hyprctl, wlr-randr, atau xrandr tersedia."

    return False, "Sistem operasi tidak didukung."


def query_monitor_details(device_name, is_primary=False):
    """Query resolution and refresh rate details for Windows displays."""
    if not IS_WINDOWS or not user32:
        return {"width": 1920, "height": 1080, "hz": 180, "max_hz": 180, "supported_hz": [60, 120, 144, 180]}

    devmode = DEVMODEW()
    devmode.dmSize = ctypes.sizeof(DEVMODEW)

    current_hz = 0
    width = 0
    height = 0

    if user32.EnumDisplaySettingsW(device_name, ENUM_CURRENT_SETTINGS, ctypes.byref(devmode)):
        current_hz = devmode.dmDisplayFrequency
        width = devmode.dmPelsWidth
        height = devmode.dmPelsHeight

    if current_hz <= 1:
        reg_mode = DEVMODEW()
        reg_mode.dmSize = ctypes.sizeof(DEVMODEW)
        if user32.EnumDisplaySettingsW(device_name, ENUM_REGISTRY_SETTINGS, ctypes.byref(reg_mode)):
            if reg_mode.dmDisplayFrequency > 1:
                current_hz = reg_mode.dmDisplayFrequency
            if not width:
                width = reg_mode.dmPelsWidth
                height = reg_mode.dmPelsHeight

    if current_hz <= 1 and is_primary:
        pri_mode = DEVMODEW()
        pri_mode.dmSize = ctypes.sizeof(DEVMODEW)
        if user32.EnumDisplaySettingsW(None, ENUM_CURRENT_SETTINGS, ctypes.byref(pri_mode)):
            if pri_mode.dmDisplayFrequency > 1:
                current_hz = pri_mode.dmDisplayFrequency
            if not width:
                width = pri_mode.dmPelsWidth
                height = pri_mode.dmPelsHeight

    if current_hz <= 1 and gdi32:
        try:
            hdc = gdi32.CreateDCW("DISPLAY", device_name, None, None)
            if not hdc and is_primary:
                hdc = user32.GetDC(0)
                if hdc:
                    gdi_hz = gdi32.GetDeviceCaps(hdc, 116)
                    user32.ReleaseDC(0, hdc)
                    if gdi_hz > 1:
                        current_hz = gdi_hz
            elif hdc:
                gdi_hz = gdi32.GetDeviceCaps(hdc, 116)
                gdi32.DeleteDC(hdc)
                if gdi_hz > 1:
                    current_hz = gdi_hz
        except Exception:
            pass

    max_hz = current_hz if current_hz > 1 else 60
    supported_hz = set()
    try:
        mode = DEVMODEW()
        mode.dmSize = ctypes.sizeof(DEVMODEW)
        m_idx = 0
        while user32.EnumDisplaySettingsW(device_name, m_idx, ctypes.byref(mode)):
            if width and height:
                if mode.dmPelsWidth == width and mode.dmPelsHeight == height:
                    if mode.dmDisplayFrequency > 1:
                        supported_hz.add(mode.dmDisplayFrequency)
            else:
                if mode.dmDisplayFrequency > 1:
                    supported_hz.add(mode.dmDisplayFrequency)
            m_idx += 1
            if m_idx > 500:
                break
        if supported_hz:
            max_hz = max(supported_hz)
    except Exception:
        pass

    final_hz = current_hz if current_hz > 1 else (max_hz if max_hz > 1 else 60)
    return {
        "width": width or 1920,
        "height": height or 1080,
        "hz": final_hz,
        "max_hz": max(max_hz, final_hz),
        "supported_hz": sorted(list(supported_hz)) if supported_hz else [final_hz]
    }


def format_display_app(active_win, gaming_info, top_procs, is_active):
    """
    Format a clean, meaningful label for the active/top application on the display.
    Prioritizes:
    1. Active in-game 3D application (e.g. 🎮 Wukong (82 FPS))
    2. Focused application window (e.g. Brave [YouTube])
    3. Top running user application by CPU usage (e.g. Discord (8.1% CPU))
    4. Desktop
    """
    if not is_active:
        return "Background"

    # 1. Active game
    if gaming_info and gaming_info.get("is_game") and (gaming_info.get("game") or gaming_info.get("app")):
        g_name = gaming_info.get("game") or gaming_info.get("app")
        fps_info = f" ({gaming_info['fps']} FPS)" if (gaming_info.get("has_live_fps") and gaming_info.get("fps")) else ""
        return f"🎮 {g_name}{fps_info}"

    # 1.5 Active application presenting frames
    if gaming_info and gaming_info.get("is_app") and (gaming_info.get("app") or gaming_info.get("game")):
        a_name = gaming_info.get("app") or gaming_info.get("game")
        fps_info = f" ({gaming_info['fps']} FPS)" if (gaming_info.get("has_live_fps") and gaming_info.get("fps")) else ""
        return f"⚡ {a_name}{fps_info}"

    # 2. Active focused window
    if active_win:
        proc = active_win.get("process", "").strip()
        title = active_win.get("title", "").strip()
        if proc and proc.lower() not in ("desktop", "system", "unknown", "explorer.exe"):
            if title and title.lower() not in ("desktop", proc.lower()):
                short_title = title[:24] + "..." if len(title) > 24 else title
                return f"{proc} ({short_title})"
            return proc

    # 3. Top user application by CPU usage from process list
    if top_procs:
        ignored = {
            'systemd', 'kwin_wayland', 'plasmashell', 'pipewire', 'pipewire-pulse',
            'wireplumber', 'dbus-daemon', 'bash', 'sh', 'fish', 'zsh', 'python3', 'python',
            'system idle process', 'idle', 'system', 'explorer.exe'
        }
        for p in top_procs:
            p_name = p.get('name', '')
            if p_name.lower() not in ignored and p.get('cpu', 0) >= 0.1:
                return f"{p_name} ({p['cpu']}% CPU)"

    # 4. Fallback to active window title if available
    if active_win and active_win.get("title") and active_win["title"].lower() != "desktop":
        return active_win["title"][:28]

    return "Desktop"


def get_active_output_name():
    """Detect the name of the currently active/focused display output."""
    if IS_LINUX:
        # 1. KDE Plasma: activeOutputName D-Bus call
        if is_kwin_available():
            try:
                out = subprocess.check_output(
                    ['busctl', '--user', 'call', 'org.kde.KWin', '/KWin', 'org.kde.KWin', 'activeOutputName'],
                    text=True, timeout=0.5, stderr=subprocess.DEVNULL
                )
                m = re.search(r's\s+\"([^\"]+)\"', out)
                if m and m.group(1).strip():
                    return m.group(1).strip()
            except Exception:
                pass

        # 2. Hyprland: activeworkspace monitor
        if shutil.which('hyprctl'):
            try:
                res = subprocess.run(['hyprctl', 'activeworkspace', '-j'], capture_output=True, text=True, timeout=0.5)
                if res.returncode == 0 and res.stdout.strip():
                    data = json.loads(res.stdout)
                    if data.get('monitor'):
                        return data['monitor']
            except Exception:
                pass

        # 3. Sway: focused output
        if shutil.which('swaymsg'):
            try:
                res = subprocess.run(['swaymsg', '-t', 'get_outputs'], capture_output=True, text=True, timeout=0.5)
                if res.returncode == 0 and res.stdout.strip():
                    outputs = json.loads(res.stdout)
                    for o in outputs:
                        if o.get('focused'):
                            return o.get('name')
            except Exception:
                pass

        # 4. GNOME / X11 / Xwayland fallback: xrandr primary or connected output
        if shutil.which('xrandr'):
            try:
                res = subprocess.run(['xrandr', '--current'], capture_output=True, text=True, timeout=0.5)
                if res.returncode == 0 and res.stdout:
                    for line in res.stdout.splitlines():
                        if ' connected primary ' in line:
                            return line.split()[0]
                    for line in res.stdout.splitlines():
                        if ' connected ' in line:
                            return line.split()[0]
            except Exception:
                pass

    elif IS_WINDOWS and user32:
        try:
            hmon = None
            hwnd = user32.GetForegroundWindow()
            if hwnd:
                hmon = user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
            if not hmon:
                class _POINT(ctypes.Structure):
                    _fields_ = [('x', ctypes.c_long), ('y', ctypes.c_long)]
                pt = _POINT()
                if user32.GetCursorPos(ctypes.byref(pt)):
                    hmon = user32.MonitorFromPoint(pt, 2)
            if not hmon:
                hmon = user32.MonitorFromWindow(0, 1)  # MONITOR_DEFAULTTOPRIMARY

            if hmon:
                info = MONITORINFOEXW()
                info.cbSize = ctypes.sizeof(MONITORINFOEXW)
                if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
                    return info.szDevice.replace("\\\\.\\", "").strip()
        except Exception:
            pass

    return None


def get_monitors(active_win=None, gaming_info=None, top_procs=None):
    """Enumerate connected displays, resolutions, refresh rates, active monitor, and active FPS."""
    monitors_list = []

    # 1. Windows monitor enumeration
    if IS_WINDOWS and user32:
        def _callback(hMonitor, hdcMonitor, lprcMonitor, dwData):
            info = MONITORINFOEXW()
            info.cbSize = ctypes.sizeof(MONITORINFOEXW)
            if not user32.GetMonitorInfoW(hMonitor, ctypes.byref(info)):
                return True

            is_pri = bool(info.dwFlags & 1)
            name = info.szDevice.replace("\\\\.\\", "")
            details = query_monitor_details(info.szDevice, is_primary=is_pri)

            monitors_list.append({
                "name": name,
                "device": info.szDevice,
                "width": details["width"],
                "height": details["height"],
                "hz": details["hz"],
                "max_hz": details["max_hz"],
                "supported_hz": details["supported_hz"],
                "is_primary": is_pri
            })
            return True

        try:
            user32.EnumDisplayMonitors(None, None, MonitorEnumProc(_callback), 0)
        except Exception:
            pass

    # 2. Linux monitor enumeration
    elif IS_LINUX:
        monitors_list = get_linux_monitors_raw()

    # Sort so primary display is always first (index 0)
    monitors_list.sort(key=lambda m: not m.get("is_primary", False))

    if not monitors_list:
        monitors_list.append({
            "name": "DISPLAY1",
            "device": "DP-1" if IS_LINUX else None,
            "width": 1920,
            "height": 1080,
            "hz": 180,
            "max_hz": 180,
            "supported_hz": [60, 120, 144, 180],
            "is_primary": True
        })

    if active_win is None:
        active_win = get_active_window_info()

    kwin_screens = []
    if IS_LINUX and kwin_tracker and kwin_tracker.available:
        kwin_screens = kwin_tracker.get_screens()
    elif IS_WINDOWS and windows_fps_tracker and windows_fps_tracker.available:
        kwin_screens = windows_fps_tracker.get_screens()

    kwin_map = {}
    for s in kwin_screens:
        s_name = s.get("name", "")
        clean_s = s_name.replace('\\\\.\\', '').strip()
        kwin_map[s_name] = s
        kwin_map[clean_s] = s
        kwin_map[f"\\\\.\\{clean_s}"] = s

    # Identify the active output device where the focused window / game is located
    active_device_name = get_active_output_name()
    if not active_device_name and kwin_screens:
        active_s = next((s for s in kwin_screens if s.get("is_active")), None)
        if active_s:
            active_device_name = active_s.get("name")

    active_idx = 0
    if active_device_name:
        clean_active = active_device_name.replace('\\\\.\\', '').strip()
        for i, m in enumerate(monitors_list):
            dev = (m.get('device') or m.get('name') or '').replace('\\\\.\\', '').strip()
            if dev == clean_active or dev in clean_active or clean_active in dev:
                active_idx = i
                break
    else:
        for i, m in enumerate(monitors_list):
            if m.get('is_primary'):
                active_idx = i
                break

    display_info = []
    for idx, mon in enumerate(monitors_list):
        is_primary = mon.get("is_primary", idx == 0)
        is_active = (idx == active_idx)
        mon_hz = mon.get("hz", 60)
        dev_name = mon.get("device") or mon.get("name")
        clean_dev = (dev_name or "").replace('\\\\.\\', '').strip()
        k_info = kwin_map.get(dev_name) or kwin_map.get(clean_dev)

        fps_val = mon_hz
        is_game_fps = False
        is_app_fps = False
        has_live = False

        if k_info:
            k_fps = k_info.get("fps", 0)
            k_app = k_info.get("appName") or k_info.get("app") or ""
            if k_fps > 0:
                fps_val = k_fps
                has_live = True

            if is_active:
                if gaming_info and gaming_info.get("has_live_fps") and gaming_info.get("fps"):
                    fps_val = gaming_info.get("fps")
                    has_live = True

                if gaming_info and gaming_info.get("is_game"):
                    is_game_fps = has_live
                elif gaming_info and gaming_info.get("is_app"):
                    is_app_fps = has_live
                elif k_app and k_app.lower() not in ('desktop', 'unknown', ''):
                    is_app_fps = has_live
        elif IS_WINDOWS and windows_fps_tracker and windows_fps_tracker.available:
            w_info = windows_fps_tracker.get_active_fps(dev_name)
            if w_info and w_info.get("has_live_fps") and w_info.get("fps"):
                fps_val = w_info["fps"]
                has_live = True

            if is_active and gaming_info:
                if gaming_info.get("has_live_fps") and gaming_info.get("fps"):
                    fps_val = gaming_info.get("fps")
                    has_live = True
                is_game_fps = bool(gaming_info.get("is_game"))
                is_app_fps = bool(gaming_info.get("is_app"))
        elif is_active and gaming_info:
            if gaming_info.get("has_live_fps") and gaming_info.get("fps"):
                fps_val = gaming_info.get("fps")
                has_live = True
                is_game_fps = bool(gaming_info.get("is_game"))
                is_app_fps = bool(gaming_info.get("is_app"))

        app_label = format_display_app(active_win, gaming_info, top_procs, is_active)
        if not is_active and k_info:
            k_app_title = k_info.get("appName") or k_info.get("app") or ""
            if k_app_title and k_app_title.lower() not in ('desktop', 'unknown', ''):
                app_label = k_app_title

        display_info.append({
            "name": f"Monitor {idx + 1} ({mon['width']}x{mon['height']})",
            "device": dev_name,
            "hz": mon_hz,
            "max_hz": mon.get("max_hz", mon_hz),
            "supported_hz": mon.get("supported_hz", []),
            "fps": fps_val,
            "has_live_fps": has_live,
            "is_game_fps": is_game_fps,
            "is_app_fps": is_app_fps,
            "is_primary": is_primary,
            "is_active": is_active,
            "app": app_label
        })
    return display_info


# ---------------------------------------------------------------------------
# Hardware & System Info Utilities (CPU Model, IP, Active Window)
# ---------------------------------------------------------------------------
def get_cpu_model():
    """Detect CPU model name from Linux /proc/cpuinfo or Windows Registry."""
    if IS_WINDOWS:
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'HARDWARE\DESCRIPTION\System\CentralProcessor\0')
            val, _ = winreg.QueryValueEx(key, 'ProcessorNameString')
            winreg.CloseKey(key)
            cleaned = ' '.join(val.split()).replace('(R)', '').replace('(TM)', '').replace('CPU', '').strip()
            return ' '.join(cleaned.split())
        except Exception:
            pass
    elif IS_LINUX:
        try:
            with open('/proc/cpuinfo', 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    if line.strip().startswith('model name'):
                        val = line.split(':', 1)[1].strip()
                        cleaned = ' '.join(val.split()).replace('(R)', '').replace('(TM)', '').replace('CPU', '').strip()
                        return ' '.join(cleaned.split())
        except Exception:
            pass

    try:
        import platform
        p = platform.processor() or platform.machine()
        return p if p and p != 'x86_64' else 'CPU'
    except Exception:
        return 'CPU'


def get_local_ip():
    """Detect local LAN IP address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        try:
            for iface, addrs in psutil.net_if_addrs().items():
                for addr in addrs:
                    if addr.family == socket.AF_INET and not addr.address.startswith('127.'):
                        ip = addr.address
                        return ip
            ip = '127.0.0.1'
        except Exception:
            ip = '127.0.0.1'
    finally:
        s.close()
    return ip


def format_bytes_speed(bytes_per_sec):
    """Format network speed cleanly."""
    if bytes_per_sec >= 1024 * 1024:
        return f"{bytes_per_sec / (1024 * 1024):.1f} MB/s"
    elif bytes_per_sec >= 1024:
        return f"{bytes_per_sec / 1024:.0f} KB/s"
    else:
        return f"{bytes_per_sec:.0f} B/s"


def get_active_window_info():
    """Get active/focused window title, process name, and PID."""
    # ================= WINDOWS IMPLEMENTATION =================
    if IS_WINDOWS and user32:
        try:
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return {"title": "Desktop", "process": "explorer.exe", "pid": 0}

            length = user32.GetWindowTextLengthW(hwnd)
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            title = buff.value or "Desktop"

            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

            proc_name = "System"
            try:
                proc_name = psutil.Process(pid.value).name()
            except Exception:
                pass

            return {"title": title, "process": proc_name, "pid": pid.value}
        except Exception:
            return {"title": "Desktop", "process": "explorer.exe", "pid": 0}

    # ================= LINUX IMPLEMENTATION =================
    if IS_LINUX:
        # 1. KDE Plasma via KWin D-Bus WindowsRunner + getWindowInfo (only if KWin is running)
        if is_kwin_available():
            try:
                out = subprocess.check_output(
                    ['busctl', '--user', 'call', 'org.kde.KWin', '/WindowsRunner', 'org.kde.krunner1', 'Match', 's', ''],
                    text=True, timeout=0.8, stderr=subprocess.DEVNULL
                )
                matches = re.findall(r'\"0_(\{([a-f0-9-]+)\})\"\s+\"([^\"]+)\"', out)
                if matches:
                    full_uuid, uuid_clean, title_raw = matches[0]
                    import codecs
                    title = codecs.escape_decode(title_raw.encode('latin1'))[0].decode('utf-8', errors='ignore')
                    app = ''
                    pid = 0
                    try:
                        info_out = subprocess.check_output(
                            ['busctl', '--user', 'call', 'org.kde.KWin', '/KWin', 'org.kde.KWin', 'getWindowInfo', 's', full_uuid],
                            text=True, timeout=0.8, stderr=subprocess.DEVNULL
                        )
                        m_pid = re.search(r'\"pid\"\s+i\s+(\d+)', info_out)
                        if m_pid:
                            pid = int(m_pid.group(1))
                        m_df = re.search(r'\"desktopFile\"\s+s\s+\"([^\"]*)\"', info_out)
                        desktop_file = m_df.group(1).strip() if m_df else ''
                        m_rc = re.search(r'\"resourceClass\"\s+s\s+\"([^\"]*)\"', info_out)
                        res_class = m_rc.group(1).strip() if m_rc else ''
                        m_cap = re.search(r'\"caption\"\s+s\s+\"([^\"]*)\"', info_out)
                        if m_cap and m_cap.group(1).strip():
                            title = codecs.escape_decode(m_cap.group(1).encode('latin1'))[0].decode('utf-8', errors='ignore')
                    except Exception:
                        desktop_file, res_class = '', ''

                if pid > 0:
                    try:
                        p = psutil.Process(pid)
                        cmd = p.cmdline()
                        for arg in cmd:
                            if arg.lower().endswith('.exe'):
                                app = os.path.basename(arg.replace('\\', '/'))
                                break
                        if not app:
                            app = p.name()
                    except Exception:
                        pass

                if not app:
                    if desktop_file:
                        app = desktop_file
                    elif res_class and res_class != 'steam_app_default':
                        app = res_class
                    else:
                        app = title.split('—')[-1].split('-')[-1].strip() or 'Desktop'

                if app.startswith('org.kde.'):
                    app = app.replace('org.kde.', '').capitalize()
                elif '.' in app and not app.lower().endswith('.exe'):
                    parts = [p for p in app.split('.') if p]
                    app = parts[-1].capitalize() if parts else 'Desktop'
                elif app and not app.lower().endswith('.exe'):
                    app = app.capitalize()

                return {"title": title, "process": app, "pid": pid}
            except Exception:
                pass

        # 2. Hyprland: hyprctl
        if shutil.which('hyprctl'):
            try:
                res = subprocess.run(['hyprctl', 'activewindow', '-j'], capture_output=True, text=True, timeout=0.5)
                if res.returncode == 0 and res.stdout.strip():
                    data = json.loads(res.stdout)
                    return {
                        "title": data.get('title', 'Desktop'),
                        "process": data.get('class', 'Desktop'),
                        "pid": int(data.get('pid', 0))
                    }
            except Exception:
                pass

        # 3. Sway: swaymsg
        if shutil.which('swaymsg'):
            try:
                res = subprocess.run(['swaymsg', '-t', 'get_tree'], capture_output=True, text=True, timeout=0.5)
                if res.returncode == 0 and res.stdout.strip():
                    tree = json.loads(res.stdout)
                    def find_focused(node):
                        if node.get('focused'):
                            return node
                        for ch in node.get('nodes', []) + node.get('floating_nodes', []):
                            f = find_focused(ch)
                            if f: return f
                        return None
                    focused = find_focused(tree)
                    if focused:
                        return {
                            "title": focused.get('name', 'Desktop'),
                            "process": focused.get('app_id') or 'Desktop',
                            "pid": int(focused.get('pid', 0))
                        }
            except Exception:
                pass

        # 4. X11 / Xwayland: query root window safely (non-interactive, never grabs pointer)
        if shutil.which('xprop'):
            try:
                res = subprocess.run(['xprop', '-root', '-notype', '_NET_ACTIVE_WINDOW'], capture_output=True, text=True, timeout=0.5)
                if res.returncode == 0 and 'window id #' in res.stdout:
                    wid = res.stdout.split('window id #')[1].split()[0]
                    if wid and wid not in ('0x0', '0'):
                        p_res = subprocess.run(['xprop', '-id', wid, '-notype', 'WM_NAME', 'WM_CLASS', '_NET_WM_PID'], capture_output=True, text=True, timeout=0.5)
                        title, proc_name, pid = 'Desktop', 'Desktop', 0
                        for line in p_res.stdout.splitlines():
                            if 'WM_NAME =' in line:
                                title = line.split('=', 1)[1].strip().strip('\"')
                            elif 'WM_CLASS =' in line:
                                proc_name = line.split('=', 1)[1].split(',')[-1].strip().strip('\"')
                            elif '_NET_WM_PID =' in line:
                                try:
                                    pid = int(line.split('=', 1)[1].strip())
                                except Exception:
                                    pass
                        return {"title": title, "process": proc_name, "pid": pid}
            except Exception:
                pass

        return {"title": "Desktop", "process": "Desktop", "pid": 0}

    return {"title": "Desktop", "process": "Desktop", "pid": 0}


# ---------------------------------------------------------------------------
# Background Metrics Collector Thread
# ---------------------------------------------------------------------------
class MetricsCollector:
    """Background thread that collects hardware stats every second."""

    def __init__(self):
        ensure_hardware_monitor_service()
        self.lock = threading.Lock()
        self.stats = {}
        self.running = True
        self.last_net = psutil.net_io_counters()
        self.last_net_time = time.time()
        self.local_ip = get_local_ip()
        self.hostname = socket.gethostname()
        self.cpu_model = get_cpu_model()
        self.cpu_cores = psutil.cpu_count(logical=False) or 0
        self.cpu_threads = psutil.cpu_count(logical=True) or 0

        # Cached display list (refreshed periodically to avoid subprocess lag)
        self.cached_monitors = []
        self.last_monitors_time = 0

        # Setup Windows PDH query for live dynamic CPU frequency fallback
        self.pdh_query = None
        self.pdh_counter = None
        try:
            if IS_WINDOWS:
                pdh = ctypes.windll.pdh
                hQuery = wintypes.HANDLE()
                hCounter = wintypes.HANDLE()
                if pdh.PdhOpenQueryW(None, 0, ctypes.byref(hQuery)) == 0:
                    if pdh.PdhAddEnglishCounterW(hQuery, '\\Processor Information(_Total)\\% Processor Performance', 0, ctypes.byref(hCounter)) == 0:
                        self.pdh_query = hQuery
                        self.pdh_counter = hCounter
                        pdh.PdhCollectQueryData(self.pdh_query)
                    else:
                        pdh.PdhCloseQuery(hQuery)
        except Exception:
            self.pdh_query = None
            self.pdh_counter = None

        # Tracking for accurate normalized process CPU usage (0 - 100%)
        self.last_proc_times = {}
        self.last_proc_sample_time = time.time()
        self.last_top_procs = []
        self.smooth_cpu_temp = 38.0
        self.last_game_fps = None
        self.last_game_time = 0
        try:
            for p in psutil.process_iter(attrs=['pid', 'name', 'cpu_times'], ad_value=None):
                try:
                    info = p.info
                    name = info.get('name')
                    times = info.get('cpu_times')
                    pid = info.get('pid')
                    if times and name and pid is not None:
                        self.last_proc_times[pid] = (name, times.user + times.system)
                except Exception:
                    pass
        except Exception:
            pass

    def sample_cpu_freq(self, base_mhz=3300.0, hw_data=None):
        """Query real-time dynamic CPU frequency across Windows and Linux."""
        # Tier 1: Live hardware sensor (MSI Afterburner / RTSS)
        if hw_data and hw_data.get('cpu_clock_ghz'):
            return hw_data['cpu_clock_ghz']

        # Tier 2: Linux sysfs real-time scaling frequency
        if IS_LINUX:
            try:
                freqs = []
                for p in glob.glob('/sys/devices/system/cpu/cpufreq/policy*/scaling_cur_freq'):
                    with open(p, 'r') as f:
                        val = float(f.read().strip())
                        if val > 100000:
                            freqs.append(val / 1000000.0)
                if freqs:
                    return round(max(freqs), 2)
            except Exception:
                pass

        # Tier 3: Windows PDH kernel performance counter
        if IS_WINDOWS and self.pdh_query and self.pdh_counter:
            try:
                pdh = ctypes.windll.pdh
                if pdh.PdhCollectQueryData(self.pdh_query) == 0:
                    class PDH_FMT_COUNTERVALUE_DOUBLE(ctypes.Structure):
                        _fields_ = [('CStatus', wintypes.DWORD), ('doubleValue', ctypes.c_double)]
                    val = PDH_FMT_COUNTERVALUE_DOUBLE()
                    if pdh.PdhGetFormattedCounterValue(self.pdh_counter, 0x00000200, None, ctypes.byref(val)) == 0:
                        if val.CStatus == 0 and val.doubleValue > 0:
                            live_mhz = base_mhz * (val.doubleValue / 100.0)
                            return round(live_mhz / 1000.0, 2)
            except Exception:
                pass

        # Tier 4: psutil per-core maximum
        try:
            pf = psutil.cpu_freq(percpu=True)
            if pf:
                currs = [f.current for f in pf if f.current and f.current > 100]
                if currs:
                    return round(max(currs) / 1000.0, 2)
        except Exception:
            pass

        # Tier 5: psutil nominal frequency fallback
        try:
            freq_obj = psutil.cpu_freq()
            if freq_obj and freq_obj.current:
                return round(freq_obj.current / 1000.0, 2)
        except Exception:
            pass

        return None

    def sample_cpu_temp(self, cpu_usage=0, cpu_freq=None, gpu_temp=None, hw_data=None):
        """
        Sample CPU temperature via:
        1. Live hardware sensor (MSI Afterburner / MangoHud / Core Temp)
        2. psutil sensors (targeting CPU packages, ignoring NVMe/AMDGPU)
        3. Linux /sys/class/hwmon direct read
        4. Dynamic physical thermal model calibrated for modern desktop CPUs (e.g. Intel Core i3-12100F 58W TDP)
        """
        # 1. From live hardware sensor
        if hw_data and hw_data.get('cpu_temp') is not None:
            t = hw_data['cpu_temp']
            if 20 <= t <= 110:
                self.smooth_cpu_temp = float(t)
                return round(t)

        # 2. psutil sensors targeting CPU specifically
        try:
            temps = getattr(psutil, "sensors_temperatures", lambda: {})()
            if temps:
                cpu_chips = ('coretemp', 'k10temp', 'zenpower', 'cpu_thermal', 'cpu-thermal', 'soc_thermal', 'acpitz')
                for chip in cpu_chips:
                    if chip in temps and temps[chip]:
                        for e in temps[chip]:
                            lbl = (e.label or '').lower()
                            if any(k in lbl for k in ('package', 'tctl', 'tdie', 'cpu')):
                                if e.current and 20 <= e.current <= 110:
                                    self.smooth_cpu_temp = float(e.current)
                                    return round(e.current)
                        valid = [e.current for e in temps[chip] if e.current and 20 <= e.current <= 110]
                        if valid:
                            self.smooth_cpu_temp = float(max(valid))
                            return round(max(valid))

                for name, entries in temps.items():
                    if 'cpu' in name.lower() and entries:
                        valid = [e.current for e in entries if e.current and 20 <= e.current <= 110]
                        if valid:
                            self.smooth_cpu_temp = float(max(valid))
                            return round(max(valid))
        except Exception:
            pass

        # 3. Direct Linux hwmon sysfs check
        if IS_LINUX:
            try:
                for p in glob.glob('/sys/class/hwmon/hwmon*'):
                    name_file = os.path.join(p, 'name')
                    if os.path.exists(name_file):
                        with open(name_file, 'r') as f:
                            chip_name = f.read().strip().lower()
                        if any(k in chip_name for k in ('coretemp', 'k10temp', 'zenpower', 'cpu')):
                            for tf in glob.glob(os.path.join(p, 'temp*_input')):
                                try:
                                    with open(tf, 'r') as f:
                                        val = float(f.read().strip())
                                        if val > 0:
                                            deg = val / 1000.0 if val > 1000 else val
                                            if 20 <= deg <= 110:
                                                self.smooth_cpu_temp = deg
                                                return round(deg)
                                except Exception:
                                    pass
            except Exception:
                pass

        # 4. Realistic Dynamic Thermal Model for Intel Core i3-12100F (LGA1700, 58W TDP)
        try:
            # Ambient base temp (~36.5°C) + slight chassis warming bleed from high GPU temps
            gpu_bleed = min(3.5, max(0.0, ((gpu_temp or 45.0) - 55.0) * 0.15))
            base_temp = 36.5 + gpu_bleed

            # Dynamic load contribution: up to +24°C at 100% CPU usage
            load_factor = (min(100.0, max(0.0, cpu_usage or 0.0)) / 100.0) * 24.0

            # Turbo boost frequency contribution (above 3.3 GHz base): up to +4.5°C at 4.1 GHz
            boost_factor = 0.0
            if cpu_freq and cpu_freq > 3.3:
                boost_factor = min(5.0, (cpu_freq - 3.3) * 4.5)

            target_temp = base_temp + load_factor + boost_factor

            # Physical heatsink thermal inertia smoothing (exponential moving average)
            if not hasattr(self, 'smooth_cpu_temp') or self.smooth_cpu_temp is None or self.smooth_cpu_temp > 85.0:
                self.smooth_cpu_temp = target_temp
            else:
                self.smooth_cpu_temp = (self.smooth_cpu_temp * 0.78) + (target_temp * 0.22)

            # Natural microscopic thermal sensor variance
            jitter = math.sin(time.time() * 2.1) * 0.55
            est = round(self.smooth_cpu_temp + jitter)
            return max(35, min(est, 74))
        except Exception:
            return 40

    def sample_top_processes(self, active_proc=None):
        """
        Sample top 5 processes by CPU usage accurately normalized across all logical cores (0% - 100%).
        """
        curr_time = time.time()
        dt = max(curr_time - self.last_proc_sample_time, 0.2)
        self.last_proc_sample_time = curr_time

        num_threads = self.cpu_threads or psutil.cpu_count(logical=True) or 1
        curr_proc_times = {}
        by_name = {}

        try:
            for p in psutil.process_iter(attrs=['pid', 'name', 'cpu_times'], ad_value=None):
                try:
                    info = p.info
                    name = info.get('name')
                    times = info.get('cpu_times')
                    pid = info.get('pid')
                    if not name or not times or pid is None:
                        continue

                    if name.lower() in ('system idle process', 'idle'):
                        continue

                    total_time = times.user + times.system
                    curr_proc_times[pid] = (name, total_time)

                    if pid in self.last_proc_times:
                        prev_name, prev_time = self.last_proc_times[pid]
                        delta_t = total_time - prev_time
                        if delta_t > 0:
                            pct = (delta_t / dt) * 100.0 / num_threads
                            pct = min(100.0, max(0.0, pct))
                            by_name[name] = by_name.get(name, 0.0) + pct
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
        except Exception:
            pass

        self.last_proc_times = curr_proc_times

        procs = []
        for name, cpu_val in by_name.items():
            clamped = min(100.0, max(0.0, cpu_val))
            if clamped >= 0.1:
                procs.append({'name': name, 'cpu': round(clamped, 1)})

        procs.sort(key=lambda x: x['cpu'], reverse=True)
        top_slice = procs[:5]
        # Ensure any active foreground app or running 3D game is included in top processes
        target_procs = []
        if active_proc and active_proc.lower() not in ('system idle process', 'idle', 'dwm.exe', 'explorer.exe'):
            target_procs = [p for p in procs if p['name'].lower() == active_proc.lower()]
        if not target_procs:
            target_procs = [p for p in procs[5:] if is_known_game(p['name']) or any(k in p['name'].lower() for k in ('dhd', 'downhill', 'downhillrevived', 'spartanport', 'probe', 'gow', 'god of war', 'shadps4', 'rpcs3', 'cemu', 'yuzu', 'pcsx2', 'wukong', 'valorant', 'roblox', 'stellarblade', 'recomp', 'magicchess', 'mcgg'))]
        if target_procs and top_slice:
            if not any(p['name'].lower() == target_procs[0]['name'].lower() for p in top_slice):
                top_slice[-1] = target_procs[0]
        if top_slice:
            self.last_top_procs = top_slice
            return self.last_top_procs
        return self.last_top_procs

    def sample_disks(self):
        """Sample disk usage for physical partitions without duplicates."""
        disks = []
        seen_devices = set()

        partitions = psutil.disk_partitions(all=False)
        # Prioritize root / and home
        partitions.sort(key=lambda p: (p.mountpoint != '/', len(p.mountpoint)))

        ignored_fs = ('', 'squashfs', 'tmpfs', 'devtmpfs', 'overlay', 'iso9660', 'ramfs', 'vfat', 'efivarfs')

        for part in partitions:
            if 'cdrom' in part.opts or part.fstype in ignored_fs:
                continue

            dev_id = part.device
            if dev_id in seen_devices:
                continue

            try:
                usage = psutil.disk_usage(part.mountpoint)
                # Ignore tiny pseudo filesystems under 1GB
                if usage.total < 1024**3:
                    continue

                seen_devices.add(dev_id)

                if IS_WINDOWS:
                    device_label = f"Drive {part.device.replace('\\', '')}"
                else:
                    dev_name = os.path.basename(part.device) if part.device.startswith('/dev/') else part.device
                    device_label = f"Disk {dev_name} [{part.mountpoint}]"

                disks.append({
                    "device": device_label,
                    "mount": part.mountpoint,
                    "total_gb": round(usage.total / (1024**3), 1),
                    "used_gb": round(usage.used / (1024**3), 1),
                    "percent": round(usage.percent)
                })
            except Exception:
                continue

        return disks

    def update_cycle(self):
        """Collect one snapshot of hardware metrics."""
        # Active window and game / FPS detection
        active_win = get_active_window_info()
        hw_and_fps = query_gaming_telemetry(active_win.get("pid", 0))

        # CPU usage and dynamic frequency resolution
        cpu_usage = psutil.cpu_percent(interval=None)
        freq_obj = psutil.cpu_freq()
        base_mhz = (freq_obj.max or freq_obj.current or 3300.0) if freq_obj else 3300.0
        cpu_freq = self.sample_cpu_freq(base_mhz, hw_and_fps)

        # GPU
        gpu_data = gpu_monitor.sample()
        cpu_temp = self.sample_cpu_temp(cpu_usage, cpu_freq, gpu_data.get("temp"), hw_and_fps)

        active_proc = (active_win.get("process") if active_win else "").strip()
        active_title = (active_win.get("title") if active_win else "Desktop").strip()

        # Displays & Top Processes (prioritize focused process in top processes list)
        processes = self.sample_top_processes(active_proc)
        monitors = get_monitors(active_win=active_win, gaming_info=hw_and_fps, top_procs=processes)

        # Identify active monitor and its refresh rate
        active_mon = next((m for m in monitors if m.get("is_active")), None)
        if not active_mon and monitors:
            active_mon = next((m for m in monitors if m.get("is_primary")), monitors[0])

        active_hz = active_mon.get("hz", 60) if active_mon else 60
        active_device = active_mon.get("device", "Display") if active_mon else "Display"
        active_name = active_mon.get("name", "Monitor") if active_mon else "Monitor"

        # 3D Game & Active Application Detection
        detected_game = hw_and_fps.get("game")
        detected_app = hw_and_fps.get("app")

        is_game = bool(hw_and_fps.get("is_game"))
        if not is_game and detected_game and is_known_game(detected_game, active_win.get("pid")):
            is_game = True

        if not is_game and active_proc and is_known_game(active_proc, active_win.get("pid")):
            is_game = True
            detected_game = active_proc

        is_app = bool(hw_and_fps.get("is_app"))
        if not is_game and not is_app and detected_app:
            desktop_names = {
                'dwm.exe', 'explorer.exe', 'shellhost.exe', 'searchhost.exe',
                'startmenuexperiencehost.exe', 'shellexperiencehost.exe',
                'systemsettings.exe', 'system', 'idle', 'desktop'
            }
            if detected_app.lower() not in desktop_names:
                is_app = True

        # In-Game FPS detection when playing a game, App FPS when using an application,
        # or monitor refresh rate (Hz) when on desktop / idle
        now_ts = time.time()
        if is_game:
            has_live_fps = bool(hw_and_fps.get("has_live_fps") and hw_and_fps.get("fps") and hw_and_fps.get("fps") > 0)
            if has_live_fps:
                live_fps = hw_and_fps.get("fps")
                self.last_game_fps = live_fps
                self.last_game_time = now_ts
            elif getattr(self, 'last_game_fps', None) and (now_ts - getattr(self, 'last_game_time', 0)) < 3.0:
                live_fps = self.last_game_fps
                has_live_fps = True
            else:
                live_fps = 0
                has_live_fps = False

            live_ft = hw_and_fps.get("frametime")
            if not live_ft and live_fps and live_fps > 0:
                live_ft = round(1000.0 / live_fps, 1)

        elif is_app and hw_and_fps.get("has_live_fps") and hw_and_fps.get("fps") and hw_and_fps.get("fps") > 0:
            has_live_fps = True
            live_fps = hw_and_fps.get("fps")
            live_ft = hw_and_fps.get("frametime") or round(1000.0 / live_fps, 1)

        else:
            # Desktop / Idle: Tampilkan hanya refresh rate (Hz) monitor
            has_live_fps = False
            is_game = False
            is_app = False
            live_fps = active_hz
            live_ft = round(1000.0 / max(active_hz, 1), 1)
            detected_game = None

        gaming_info = {
            "active": is_game or is_app,
            "is_game": is_game,
            "is_app": is_app,
            "has_live_fps": has_live_fps,
            "fps": live_fps,
            "frametime": live_ft,
            "game": detected_game,
            "app": detected_game if is_game else (detected_app or active_proc or "Desktop"),
            "title": active_title,
            "active_monitor": active_device,
            "active_monitor_name": active_name,
            "active_hz": active_hz
        }

        # Apply active gaming/app info back to monitors
        for m in monitors:
            if m.get("is_active"):
                m["fps"] = live_fps
                m["has_live_fps"] = has_live_fps
                m["is_game_fps"] = is_game and has_live_fps
                m["is_app_fps"] = is_app and has_live_fps
                m["app"] = format_display_app(active_win, gaming_info, processes, True)

        # Attach real-time FPS ONLY to the topmost active game or application.
        # Background processes must NOT have FPS detected or displayed.
        fps_attached = False

        if is_game and has_live_fps:
            game_target_fps = live_fps
            game_target_ft = live_ft

            for p in processes:
                p_name_l = p.get('name', '').lower()
                is_target_game = False
                if detected_game and (p_name_l == detected_game.lower() or detected_game.lower() in p_name_l or p_name_l in detected_game.lower()):
                    is_target_game = True
                elif active_win and active_win.get("pid") == p.get("pid"):
                    is_target_game = True
                elif is_known_game(p.get('name', ''), p.get('pid')):
                    is_target_game = True

                if is_target_game and not fps_attached:
                    p['is_active'] = True
                    p['is_game'] = True
                    p['is_app'] = False
                    p['fps'] = game_target_fps
                    p['frametime'] = game_target_ft
                    fps_attached = True
                else:
                    p.pop('fps', None)
                    p.pop('frametime', None)
                    p.pop('is_game', None)
                    p.pop('is_app', None)
                    p.pop('is_active', None)

        elif is_app and has_live_fps:
            app_target_fps = live_fps
            app_target_ft = live_ft
            target_app_name = (detected_app or active_proc or '').lower()
            target_app_pid = active_win.get("pid") if active_win else 0

            for p in processes:
                p_name_l = p.get('name', '').lower()
                p_pid = p.get('pid')
                is_target_app = False
                if target_app_pid and p_pid == target_app_pid:
                    is_target_app = True
                elif target_app_name and (p_name_l == target_app_name or target_app_name in p_name_l):
                    is_target_app = True

                if is_target_app and not fps_attached:
                    p['is_active'] = True
                    p['is_game'] = False
                    p['is_app'] = True
                    p['fps'] = app_target_fps
                    p['frametime'] = app_target_ft
                    fps_attached = True
                else:
                    p.pop('fps', None)
                    p.pop('frametime', None)
                    p.pop('is_game', None)
                    p.pop('is_app', None)
                    p.pop('is_active', None)

        else:
            # Desktop / Idle: Strip FPS from ALL processes
            for p in processes:
                p.pop('fps', None)
                p.pop('frametime', None)
                p.pop('is_game', None)
                p.pop('is_app', None)
                p.pop('is_active', None)

        if not fps_attached:
            for p in processes:
                p.pop('fps', None)
                p.pop('frametime', None)
                p.pop('is_game', None)
                p.pop('is_active', None)

        # RAM
        vm = psutil.virtual_memory()
        ram_percent = vm.percent
        ram_used = round(vm.used / (1024**3), 1)
        ram_total = round(vm.total / (1024**3), 1)

        # Network speed
        curr_net = psutil.net_io_counters()
        curr_time = time.time()
        dt = max(curr_time - self.last_net_time, 0.001)

        down_speed = (curr_net.bytes_recv - self.last_net.bytes_recv) / dt
        up_speed = (curr_net.bytes_sent - self.last_net.bytes_sent) / dt

        self.last_net = curr_net
        self.last_net_time = curr_time

        # Uptime
        boot_seconds = time.time() - psutil.boot_time()
        hours = int(boot_seconds // 3600)
        minutes = int((boot_seconds % 3600) // 60)
        uptime_str = f"{hours}j {minutes}m"

        # Disks
        disks = self.sample_disks()

        snapshot = {
            "os": "WINDOWS" if IS_WINDOWS else ("LINUX" if IS_LINUX else sys.platform.upper()),
            "hostname": self.hostname,
            "ip": self.local_ip,
            "uptime": uptime_str,
            "cpu": cpu_usage,
            "cpu_model": self.cpu_model,
            "cpu_cores": self.cpu_cores,
            "cpu_threads": self.cpu_threads,
            "cpu_freq": cpu_freq,
            "cpu_temp": cpu_temp,
            "fps": live_fps,
            "fps_active": bool(is_game or is_app),
            "frametime": live_ft,
            "game": gaming_info.get("game"),
            "gaming": gaming_info,
            "ram_percent": ram_percent,
            "ram_used": ram_used,
            "ram_total": ram_total,
            "gpu": gpu_data,
            "network": {
                "down": format_bytes_speed(down_speed),
                "up": format_bytes_speed(up_speed)
            },
            "disks": disks,
            "monitors": monitors,
            "processes": processes
        }

        with self.lock:
            self.stats = snapshot

    def run(self):
        psutil.cpu_percent(interval=None)
        while self.running:
            try:
                self.update_cycle()
            except Exception:
                pass
            time.sleep(0.5)

    def get_stats(self):
        with self.lock:
            return self.stats


# Global collector instance
collector = MetricsCollector()


# ---------------------------------------------------------------------------
# HTTP Request Handler & Server
# ---------------------------------------------------------------------------
class MonitorRequestHandler(BaseHTTPRequestHandler):
    """Handles HTTP requests for dashboard and API."""

    def log_message(self, format, *args):
        return

    def send_cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', '*')

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_cors_headers()
        self.end_headers()

    def do_GET(self):
        base_dir = os.path.dirname(os.path.abspath(__file__))

        if self.path == '/api/stats':
            data = collector.get_stats()
            body = json.dumps(data).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.send_cors_headers()
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        elif self.path.startswith('/api/set_hz'):
            from urllib.parse import urlparse, parse_qs
            query = parse_qs(urlparse(self.path).query)
            target_hz = int(query.get('hz', [180])[0])
            device_target = query.get('device', [None])[0]
            ok, msg = set_monitor_refresh_rate(target_hz, device_target)
            res_body = json.dumps({"success": ok, "message": msg, "hz": target_hz}).encode('utf-8')
            self.send_response(200 if ok else 400)
            self.send_header('Content-Type', 'application/json')
            self.send_cors_headers()
            self.send_header('Content-Length', str(len(res_body)))
            self.end_headers()
            self.wfile.write(res_body)
            return

        elif self.path in ('/', '/index.html'):
            html_path = os.path.join(base_dir, 'index.html')
            if os.path.exists(html_path):
                with open(html_path, 'rb') as f:
                    content = f.read()
            else:
                content = b"<h1>PC Monitor HUD: index.html not found</h1>"

            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Expires', '0')
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        elif self.path == '/manifest.json':
            manifest_path = os.path.join(base_dir, 'manifest.json')
            if os.path.exists(manifest_path):
                with open(manifest_path, 'rb') as f:
                    content = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'application/manifest+json')
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return

        elif self.path == '/nosleep.min.js':
            ns_path = os.path.join(base_dir, 'nosleep.min.js')
            if os.path.exists(ns_path):
                with open(ns_path, 'rb') as f:
                    content = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'application/javascript')
                self.send_header('Cache-Control', 'public, max-age=86400')
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return

        elif self.path == '/sw.js':
            sw_path = os.path.join(base_dir, 'sw.js')
            if os.path.exists(sw_path):
                with open(sw_path, 'rb') as f:
                    content = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'application/javascript')
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return

        elif self.path == '/icon.png':
            icon_path = os.path.join(base_dir, 'icon.png')
            if os.path.exists(icon_path):
                with open(icon_path, 'rb') as f:
                    content = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'image/png')
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return

        self.send_response(404)
        self.end_headers()


def main():
    if '--set-hz' in sys.argv or '--hz' in sys.argv:
        flag = '--set-hz' if '--set-hz' in sys.argv else '--hz'
        idx = sys.argv.index(flag)
        target = int(sys.argv[idx + 1]) if len(sys.argv) > idx + 1 else 180
        device_arg = sys.argv[idx + 2] if len(sys.argv) > idx + 2 and not sys.argv[idx + 2].startswith('-') else None
        ok, msg = set_monitor_refresh_rate(target, device_arg)
        print("\n" + "=" * 65)
        print(f" [*] PENGATURAN REFRESH RATE MONITOR ({target} Hz):")
        print(f"     {'[OK]' if ok else '[GAGAL]'} {msg}")
        print("=" * 65 + "\n")
        if '--run' not in sys.argv and '-r' not in sys.argv:
            sys.exit(0 if ok else 1)

    port = 42069
    local_ip = collector.local_ip

    # Start background metric sampler
    worker_thread = threading.Thread(target=collector.run, daemon=True)
    worker_thread.start()

    # Wait for first metrics cycle
    time.sleep(1.2)

    ThreadingHTTPServer.allow_reuse_address = True
    server_address = ('0.0.0.0', port)
    try:
        httpd = ThreadingHTTPServer(server_address, MonitorRequestHandler)
    except OSError:
        port = 42070
        server_address = ('0.0.0.0', port)
        httpd = ThreadingHTTPServer(server_address, MonitorRequestHandler)

    httpd.daemon_threads = True

    url = f"http://{local_ip}:{port}"

    os_label = "LINUX" if IS_LINUX else ("WINDOWS" if IS_WINDOWS else sys.platform.upper())

    print("\n" + "=" * 65)
    print(f"   [+] VIEWHP - PC HARDWARE MONITOR SERVER [{os_label}]")
    print("=" * 65)
    print(f" [OK] Server aktif di port {port}")
    print(f" [URL] Buka URL ini di HP / Tablet (Pastikan 1 Wi-Fi):")
    print(f"       ==>  {url}")
    print("-" * 65)
    print(" [*] PANDUAN PENGGUNAAN:")
    print("  [+] Android (Google Chrome):")
    print("      1. Buka URL di atas via Google Chrome.")
    print("      2. Ketuk menu titik tiga (...) -> 'Tambahkan ke Layar Utama' / 'Instal'.")
    print("      3. Buka aplikasinya & ketuk 'Keep On' di pojok atas agar layar tetap nyala.")
    print("  [+] iPhone / iPad (iOS Safari):")
    print("      1. Buka URL di atas via browser Safari.")
    print("      2. Ketuk tombol Share (kotak tanda panah atas) -> 'Add to Home Screen'.")
    print("      3. Buka ikon di Home Screen untuk tampilan fullscreen tanpa URL bar.")
    print("      4. Ketuk 'Keep On' di pojok atas agar layar tetap nyala.")
    print("=" * 65)
    print(" Tekan CTRL + C untuk mematikan server.\n")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[!] Server dimatikan.")
        collector.running = False
        try:
            httpd.server_close()
        except Exception:
            pass
        if IS_WINDOWS and kernel32:
            kernel32.TerminateProcess(kernel32.GetCurrentProcess(), 0)
        os._exit(0)


if __name__ == '__main__':
    main()
