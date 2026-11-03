#!/usr/bin/env python3
"""
ViewHP / PC Hardware Monitor Server
Runs on Windows 10/11 and serves real-time PC hardware telemetry
to Android smartphones, tablets, or secondary displays via Web/PWA.
"""

import os
import sys
import time
import json
import socket
import threading
import warnings
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import ctypes
from ctypes import wintypes

# Reconfigure stdout for utf-8 if supported
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

try:
    import psutil
except ImportError:
    print("[!] ERROR: 'psutil' is required. Run: pip install psutil")
    sys.exit(1)

# Filter any third-party deprecation warnings
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

# Try NVML (NVIDIA Management Library)
NVML_AVAILABLE = False
try:
    import pynvml
    pynvml.nvmlInit()
    NVML_AVAILABLE = True
except Exception:
    NVML_AVAILABLE = False


# Win32 Structures for Display and Window tracking
user32 = ctypes.windll.user32

class RECT(ctypes.Structure):
    _fields_ = [
        ('left', ctypes.c_long),
        ('top', ctypes.c_long),
        ('right', ctypes.c_long),
        ('bottom', ctypes.c_long)
    ]

class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ('cbSize', wintypes.DWORD),
        ('rcMonitor', RECT),
        ('rcWork', RECT),
        ('dwFlags', wintypes.DWORD),
        ('szDevice', wintypes.WCHAR * 32)
    ]

class DEVMODEW(ctypes.Structure):
    _fields_ = [
        ('dmDeviceName', wintypes.WCHAR * 32),
        ('dmSpecVersion', wintypes.WORD),
        ('dmDriverVersion', wintypes.WORD),
        ('dmSize', wintypes.WORD),
        ('dmDriverExtra', wintypes.WORD),
        ('dmFields', wintypes.DWORD),
        ('dmOrientation', ctypes.c_short),
        ('dmPaperSize', ctypes.c_short),
        ('dmPaperLength', ctypes.c_short),
        ('dmPaperWidth', ctypes.c_short),
        ('dmScale', ctypes.c_short),
        ('dmCopies', ctypes.c_short),
        ('dmDefaultSource', ctypes.c_short),
        ('dmPrintQuality', ctypes.c_short),
        ('dmColor', ctypes.c_short),
        ('dmDuplex', ctypes.c_short),
        ('dmYResolution', ctypes.c_short),
        ('dmTTOption', ctypes.c_short),
        ('dmCollate', ctypes.c_short),
        ('dmFormName', wintypes.WCHAR * 32),
        ('dmLogPixels', wintypes.WORD),
        ('dmBitsPerPel', wintypes.DWORD),
        ('dmPelsWidth', wintypes.DWORD),
        ('dmPelsHeight', wintypes.DWORD),
        ('dmDisplayFlags', wintypes.DWORD),
        ('dmDisplayFrequency', wintypes.DWORD),
    ]

MonitorEnumProc = ctypes.WINFUNCTYPE(
    ctypes.c_bool, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(RECT), wintypes.LPARAM
)


def get_cpu_model():
    """Detect CPU model name from Windows Registry."""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'HARDWARE\DESCRIPTION\System\CentralProcessor\0')
        val, _ = winreg.QueryValueEx(key, 'ProcessorNameString')
        winreg.CloseKey(key)
        cleaned = ' '.join(val.split()).replace('(R)', '').replace('(TM)', '').replace('CPU', '').strip()
        cleaned = ' '.join(cleaned.split())
        return cleaned
    except Exception:
        try:
            import platform
            return platform.processor() or "CPU"
        except Exception:
            return "CPU"


def get_local_ip():
    """Detect local LAN IP address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
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
    """Get active window title and process name."""
    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return {"title": "Desktop", "process": "explorer.exe"}

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

        return {"title": title, "process": proc_name}
    except Exception:
        return {"title": "Desktop", "process": "explorer.exe"}


def get_monitors():
    """Enumerate connected displays, resolutions, and refresh rates."""
    monitors_list = []

    def _callback(hMonitor, hdcMonitor, lprcMonitor, dwData):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        user32.GetMonitorInfoW(hMonitor, ctypes.byref(info))
        
        devmode = DEVMODEW()
        devmode.dmSize = ctypes.sizeof(DEVMODEW)
        user32.EnumDisplaySettingsW(info.szDevice, -1, ctypes.byref(devmode))
        
        name = info.szDevice.replace("\\\\.\\", "")
        monitors_list.append({
            "name": name,
            "width": devmode.dmPelsWidth,
            "height": devmode.dmPelsHeight,
            "hz": devmode.dmDisplayFrequency
        })
        return True

    user32.EnumDisplayMonitors(None, None, MonitorEnumProc(_callback), 0)
    
    active_win = get_active_window_info()
    display_info = []
    for idx, mon in enumerate(monitors_list):
        is_primary = (idx == 0)
        display_info.append({
            "name": f"Monitor {idx + 1} ({mon['width']}x{mon['height']})",
            "hz": mon["hz"],
            "app": f"{active_win['process']} ({active_win['title'][:25]}...)" if is_primary and len(active_win['title']) > 25 else (active_win['process'] if is_primary else "Background")
        })
    return display_info


class MetricsCollector:
    """Background thread that collects hardware stats every second."""

    def __init__(self):
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
        self.gpu_handle = None
        self.gpu_name = "GPU"

        if NVML_AVAILABLE:
            try:
                self.gpu_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                raw_name = pynvml.nvmlDeviceGetName(self.gpu_handle)
                self.gpu_name = raw_name.decode("utf-8") if isinstance(raw_name, bytes) else str(raw_name)
            except Exception as e:
                self.gpu_handle = None

    def sample_gpu(self):
        """Read GPU stats via NVML or fallback."""
        if NVML_AVAILABLE and self.gpu_handle:
            try:
                rates = pynvml.nvmlDeviceGetUtilizationRates(self.gpu_handle)
                temp = pynvml.nvmlDeviceGetTemperature(self.gpu_handle, 0)
                mem = pynvml.nvmlDeviceGetMemoryInfo(self.gpu_handle)
                return {
                    "name": self.gpu_name,
                    "usage": rates.gpu,
                    "temp": temp,
                    "vram_used": round(mem.used / (1024**3), 1),
                    "vram_total": round(mem.total / (1024**3), 1)
                }
            except Exception:
                pass

        return {
            "name": self.gpu_name or "GPU",
            "usage": 0,
            "temp": None,
            "vram_used": 0,
            "vram_total": 0
        }

    def sample_cpu_temp(self):
        """Sample CPU temperature if available via WMI, otherwise return None."""
        try:
            # psutil.sensors_temperatures() on Linux, but on Windows returns {}
            temps = getattr(psutil, "sensors_temperatures", lambda: {})()
            if temps:
                for name, entries in temps.items():
                    if entries:
                        return round(entries[0].current)
        except Exception:
            pass
        return None

    def sample_top_processes(self):
        """Sample top 5 processes by CPU usage."""
        procs = []
        for p in psutil.process_iter(['name', 'cpu_percent']):
            try:
                name = p.info['name']
                cpu = p.info['cpu_percent'] or 0.0
                if name and name.lower() not in ('system idle process', 'idle'):
                    procs.append({'name': name, 'cpu': cpu})
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        procs.sort(key=lambda x: x['cpu'], reverse=True)
        return procs[:5]

    def sample_disks(self):
        """Sample disk usage for partitions."""
        disks = []
        for part in psutil.disk_partitions(all=False):
            if 'cdrom' in part.opts or part.fstype == '':
                continue
            try:
                usage = psutil.disk_usage(part.mountpoint)
                disks.append({
                    "device": part.device.replace("\\", ""),
                    "total_gb": round(usage.total / (1024**3), 1),
                    "used_gb": round(usage.used / (1024**3), 1),
                    "percent": round(usage.percent)
                })
            except Exception:
                continue
        return disks

    def update_cycle(self):
        """Collect one snapshot of hardware metrics."""
        # CPU
        cpu_usage = psutil.cpu_percent(interval=None)
        freq_obj = psutil.cpu_freq()
        cpu_freq = round(freq_obj.current / 1000.0, 2) if freq_obj and freq_obj.current else None
        cpu_temp = self.sample_cpu_temp()

        # RAM
        vm = psutil.virtual_memory()
        ram_percent = vm.percent
        ram_used = round(vm.used / (1024**3), 1)
        ram_total = round(vm.total / (1024**3), 1)

        # GPU
        gpu_data = self.sample_gpu()

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

        # Displays & Top Processes
        monitors = get_monitors()
        processes = self.sample_top_processes()
        disks = self.sample_disks()

        snapshot = {
            "hostname": self.hostname,
            "ip": self.local_ip,
            "uptime": uptime_str,
            "cpu": cpu_usage,
            "cpu_model": self.cpu_model,
            "cpu_cores": self.cpu_cores,
            "cpu_threads": self.cpu_threads,
            "cpu_freq": cpu_freq,
            "cpu_temp": cpu_temp,
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
        # Initial priming call for cpu_percent
        psutil.cpu_percent(interval=None)
        while self.running:
            try:
                self.update_cycle()
            except Exception as e:
                pass
            time.sleep(1.0)

    def get_stats(self):
        with self.lock:
            return self.stats


# Global collector instance
collector = MetricsCollector()


class MonitorRequestHandler(BaseHTTPRequestHandler):
    """Handles HTTP requests for dashboard and API."""

    def log_message(self, format, *args):
        # Keep terminal output clean
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

        elif self.path in ('/', '/index.html'):
            html_path = os.path.join(base_dir, 'index.html')
            if os.path.exists(html_path):
                with open(html_path, 'rb') as f:
                    content = f.read()
            else:
                content = b"<h1>PC Monitor HUD: index.html not found</h1>"

            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-cache')
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

    url = f"http://{local_ip}:{port}"

    print("\n" + "=" * 60)
    print("   [+] VIEWHP - PC HARDWARE MONITOR SERVER FOR ANDROID")
    print("=" * 60)
    print(f" [OK] Server aktif di port {port}")
    print(f" [URL] BUKA LINK INI DI BROWSER HP ANDROID (Pastikan 1 Wi-Fi):")
    print(f"       ==>  {url}")
    print("-" * 60)
    print(" [*] PANDUAN PENGGUNAAN DI HP ANDROID:")
    print("  1. Buka browser Chrome di HP, ketik URL di atas.")
    print("  2. Ketuk menu titik tiga (...) -> Pilih 'Tambahkan ke Layar Utama'")
    print("     atau 'Instal Aplikasi' agar menjadi aplikasi fullscreen.")
    print("  3. Ketuk tombol 'Keep On' di pojok atas agar layar HP tidak mati.")
    print("=" * 60)
    print(" Tekan CTRL + C untuk mematikan server.\n")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[!] Server dimatikan.")
        collector.running = False
        httpd.server_close()


if __name__ == '__main__':
    main()
