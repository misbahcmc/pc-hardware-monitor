# Windows ViewHP Implementation Plan & Universal AI Prompt

This document provides a comprehensive technical implementation plan and a ready-to-use prompt designed to recreate `app.py` on a **Windows PC** supporting **any CPU** (Intel / AMD), **any GPU** (NVIDIA, AMD, Intel Arc / Iris, or fallback), and **multi-monitor display tracking** using native Windows APIs.

---

## 1. Technical Architecture for Windows

### A. Core Metrics & Hardware Sampling
| Metric | Windows Mechanism | Fallback / Details |
| :--- | :--- | :--- |
| **CPU Usage** | `psutil.cpu_percent(interval=None)` | Native Windows Performance Counters |
| **CPU Clock & Temp** | `psutil.cpu_freq()`, WMI (`MSAcpi_ThermalZoneTemperature` or `root/LibreHardwareMonitor` / `root/OpenHardwareMonitor`) | If BIOS blocks WMI thermal queries, report `psutil.cpu_freq()` (`X.X GHz`) |
| **RAM Usage** | `psutil.virtual_memory()` | Reports used, total, and percentage |
| **GPU (Universal)** | **Multi-tier GPU Resolver**: <br>1. **NVIDIA**: `pynvml` (`nvmlDeviceGetUtilizationRates`, `nvmlDeviceGetTemperature`)<br>2. **Windows Universal PDH Counter**: `\GPU Engine(*)\Utilization Percentage`<br>3. **WMI**: `Win32_VideoController` for GPU name and VRAM | Covers NVIDIA GeForce/RTX, AMD Radeon, Intel Arc / Iris Xe, and integrated GPUs |
| **Top Processes** | `psutil.process_iter(['name', 'cpu_percent'])` | Filter system idle process, take top 5 by CPU % |

### B. Windows Display & Active Window Detection
Instead of X11/Wayland/KWin, Windows provides fast Win32 APIs via `ctypes.windll.user32`:
1. **Monitors & Refresh Rates**:
   - `EnumDisplayMonitors` iterates all active displays.
   - `GetMonitorInfoW` retrieves monitor bounding coordinates `(left, top, right, bottom)`.
   - `EnumDisplaySettingsW(device_name, ENUM_CURRENT_SETTINGS)` retrieves current refresh rate (`dmDisplayFrequency`, e.g. `60`, `144`, `165`, `240 Hz`).
2. **Top / Active Window per Monitor**:
   - `GetForegroundWindow()` retrieves the active focused window.
   - `GetWindowTextW()` and `GetWindowThreadProcessId()` retrieve window title and executable process name.
   - `MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)` maps the window to its respective display.
   - For monitors not currently holding the focused window, `EnumWindows()` finds the topmost visible, non-minimized window intersecting each monitor rect.

### C. Server & Dashboard UI
- Native Python `http.server` & `socketserver` listening on `0.0.0.0:42069`.
- Embedded HTML/CSS/JS optimized for **1280x720** resolution.
- Digital Clock (large time + date, no circular ring).
- CPU, Memory, GPU cards with top circular gauges, large `34px` numbers, and subtext below.
- Displays & Top App panel with per-monitor names, refresh rates, active apps, and frame rates.
- Floating offline banner and `--` values if `app.py` is stopped or closed.

---

## 2. Copy-Pasteable Prompt for Windows PC

> [!TIP]
> Copy the prompt block below and paste it directly into your AI assistant on your Windows PC (e.g. Antigravity, Cursor, Claude, ChatGPT, etc.) to generate the Windows version of `app.py`.

```markdown
You are creating a standalone Python PC hardware monitor web dashboard called `ViewHP` (`app.py`) for Windows 10/11.

### Objective
Create a single-file Python script `app.py` that runs a lightweight HTTP server on port 42069 and serves an embedded HTML/CSS/JS dashboard optimized for a 1280x720 secondary display (e.g., an Android phone running scrcpy or Fully Kiosk Browser).

### Requirements

#### 1. Hardware & System Monitoring (Windows Native)
- **CPU**:
  - Track real-time CPU percentage using `psutil.cpu_percent()`.
  - Track CPU frequency in GHz using `psutil.cpu_freq()`.
  - Attempt to read CPU temperature via WMI (`MSAcpi_ThermalZoneTemperature` or OpenHardwareMonitor / LibreHardwareMonitor if present). If temperature is not accessible through WMI without admin, gracefully fallback to CPU frequency and load without crashing.
- **Memory**:
  - Track total RAM, used RAM in GB, and percentage using `psutil.virtual_memory()`.
- **Universal GPU Detection (NVIDIA, AMD, Intel Arc, iGPU)**:
  - Implement a universal `GpuMonitor` class in a background thread that samples GPU usage every 1s:
    1. Check for NVIDIA GPU first using `pynvml` (if available, query device utilization % and temperature).
    2. If not NVIDIA or pynvml not installed, query Windows Performance Counters (PDH) or WMI for `\GPU Engine(*)\Utilization Percentage` which works across Intel Arc, AMD Radeon, and NVIDIA.
    3. Retrieve the GPU model name from WMI `Win32_VideoController`.
    4. Provide graceful fallback returning usage, temperature (or N/A), and detected GPU model name.
- **Top Processes**:
  - Return the top 5 processes by CPU percentage using `psutil.process_iter(['name', 'cpu_percent'])`. Exclude "System Idle Process".
- **Displays & Topmost Active App per Monitor (Win32)**:
  - Use `ctypes.windll.user32` to enumerate displays and detect topmost applications:
    1. Enumerate monitors using `EnumDisplayMonitors` and get bounding rectangles.
    2. Get monitor refresh rates (Hz) using `EnumDisplaySettingsW` (`dmDisplayFrequency`).
    3. Detect the currently focused window using `GetForegroundWindow()`, get its window title and executable process name, and find which monitor it resides on via `MonitorFromWindow`.
    4. Enumerate visible non-minimized windows using `EnumWindows` to identify the topmost window for any other monitors.
    5. Return an array of monitors: `[{"name": "Display 1", "model": "...", "hz": 165, "fps": 165, "app": "Firefox", "appName": "firefox.exe"}, ...]`.

#### 2. HTTP Server & Endpoints
- Run on `http://0.0.0.0:42069`.
- Endpoints:
  - `GET /`: Serves the complete self-contained HTML page.
  - `GET /api/stats`: Returns JSON containing `{ "cpu", "cpu_temp", "cpu_freq", "ram", "ram_used", "ram_total", "gpu": {"usage", "temp", "name"}, "processes": [...], "monitors": [...] }`.

#### 3. Dashboard Frontend UI Specifications (1280x720 Optimized)
- Deep black cyber aesthetic (`#000000` background, `#0d0d0d` cards with `#222222` subtle borders).
- Must include `<meta name="color-scheme" content="dark only">` and `:root { color-scheme: dark only; }` to prevent mobile browsers from inverting dark colors.
- **Top Row (4 Cards, 48% height)**:
  1. **Clock Card**:
     - No circular ring.
     - Large bold numeric time: `48px` monospace `HH:MM:SS` (seconds in `#3d84ff`).
     - Uppercase date underneath: `14px` bold `DAY, DD MON`.
  2. **CPU Card**:
     - Top: 105px circular SVG gauge (`viewBox="0 0 100 100"`, `cx="50" cy="50" r="40"`, stroke `rgba(255,255,255,0.12)`, progress stroke `#00e676`).
     - Bottom: Large `34px` bold percentage (`X%`) and `12px` subtext (`{temp}°C · {freq}GHz`).
  3. **Memory Card**:
     - Top: 105px circular SVG gauge (progress stroke `#3d84ff`).
     - Bottom: Large `34px` bold percentage (`X%`) and `12px` subtext (`{used} / {total} GB`).
  4. **GPU Card**:
     - Top: 105px circular SVG gauge (progress stroke `#ab47bc`).
     - Bottom: Large `34px` bold percentage (`X%`) and `12px` subtext (`{gpu_name} · {temp}°C`).
- **Bottom Row (2 Panels, 52% height)**:
  1. **Top Processes Panel**:
     - Displays top 5 processes with name and green CPU %.
  2. **Displays & Top App FPS Panel**:
     - Cards for each monitor displaying Monitor Name & Model, refresh rate pill (e.g. `165 Hz`), Topmost application name (`Top: AppName`), and frame rate counter in green `FPS`.
- **Offline / Inactive Indicator**:
  - In JavaScript, if `fetch('/api/stats')` fails twice in a row (using `AbortController` with 2s timeout):
    - Display a floating pill banner at the top center: `● MONITORING NOT ACTIVE · APP.PY IS OFFLINE`.
    - Set dial gauges to inactive dim gray (`#2a2a2a`).
    - Set metric values to `--` with `Monitoring Inactive` subtext.
    - Set Process and Display panels to offline status cards.
    - Keep the local clock running so the device functions as a desk clock.
    - Automatically reconnect and restore live metrics as soon as `app.py` is reachable again.

#### 4. Dependencies
- Use only standard library + `psutil` + `pywin32` (or pure `ctypes` for user32 calls) + optional `pynvml` for NVIDIA. Keep external dependencies minimal so it can run via `pip install psutil`.
```

---

## 3. Quick Windows Setup Instructions

To run the Windows version on your PC:

1. Open PowerShell or Command Prompt.
2. Install the necessary lightweight libraries:
   ```powershell
   pip install psutil
   # Optional: For dedicated NVIDIA GPU sensor tracking:
   pip install pynvml
   # Optional: For WMI queries:
   pip install WMI
   ```
3. Run the script:
   ```powershell
   python app.py
   ```
4. Access `http://<your-windows-pc-ip>:42069` on your Android device (Redmi Note 5A).
