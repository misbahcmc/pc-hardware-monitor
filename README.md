# 🖥️ PC Hardware Monitor HUD (ViewHP) for Android & iOS (iPhone/iPad)

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011%20%7C%20Linux-0078D6.svg)](https://github.com/misbahcmc/pc-hardware-monitor)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![PWA](https://img.shields.io/badge/PWA-Ready-orange.svg)](https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps)

Aplikasi pemantauan hardware PC secara real-time yang dirancang khusus untuk layar smartphone atau tablet (Android & iPhone/iPad) melalui jaringan lokal (Wi-Fi atau USB Tethering). Mendukung penuh sistem operasi **Linux** (CachyOS, Arch Linux, Ubuntu, Debian, Fedora, KDE, GNOME, Hyprland, Sway, X11) dan **Windows 10 / 11**.

Menggunakan arsitektur **Python Server + Progressive Web App (PWA)**, aplikasi ini dapat langsung dipasang ke layar utama Android maupun iOS dan berjalan dalam mode **layar penuh (fullscreen)** tanpa perlu compile APK atau instalasi aplikasi pihak ketiga.

---

## 🚀 Fitur Utama

- **CPU Monitoring & Suhu Real-Time**: Model CPU otomatis terdeteksi (misal: *12th Gen Intel Core i3-12100F*), beban CPU (%), Clock Speed (GHz dynamic turbo boost hingga ~4.10 GHz), suhu CPU fisik real-time (°C) dari sensor hardware (`coretemp`, `k10temp`, MSI Afterburner, Core Temp, hwmon) dengan indikator warna dinamis, dan jumlah core/threads.
- **In-Game FPS & Gaming HUD (Native DXGI)**: Melacak frame rate (FPS) dan frame time (ms) secara real-time pada layar aktif tanpa perlu MSI Afterburner via **DirectX Desktop Duplication API (Windows)**, serta dukungan native **KWin Wayland Compositor & MangoHud (Linux)**, plus RTSS fallback.
- **Deteksi Cerdas Game vs Aplikasi**: Secara otomatis membedakan game 3D (`🎮 IN-GAME FPS`), aplikasi kerja/media aktif (`⚡ APP FPS`), dan aktivitas layar desktop (`⚡ SCREEN FPS / REFRESH`).
- **RAM Monitoring**: Persentase pemakaian, RAM terpakai (GB), dan total RAM (GB).
- **GPU Monitoring**: Beban GPU (%), Suhu (°C), serta pemakaian VRAM secara real-time via NVIDIA NVML (native zero-dependency ctypes di Linux/Windows), AMD DRM sysfs, atau `nvidia-smi`.
- **Top 5 Proses Ternormalisasi**: Memantau program yang paling memakan penggunaan CPU secara akurat (standar Task Manager 0% - 100%).
- **Multi-Monitor Display Tracking**: Mendeteksi resolusi dan refresh rate layar (misal: 1080p @ 180Hz) serta program dan FPS aktif di setiap monitor independen.
- **Pengaturan Refresh Rate (180Hz)**: Ubah refresh rate monitor langsung dari web dashboard atau via terminal (`start_monitor.bat` / `start_monitor.sh`).
- **Jaringan & Penyimpanan**: Kecepatan Download/Upload real-time dan bar kapasitas drive/partisi fisik tanpa duplikasi.
- **Tampilan PWA (Progressive Web App)**: Cukup *Add to Home Screen* dari browser Chrome atau Safari, langsung menjadi aplikasi fullscreen tanpa URL bar.
- **Fitur "⚡ Keep On" (Screen Wake Lock)**: Layar HP tetap menyala terus saat ditaruh di meja kerja/gaming.
- **Jam Digital & Auto-Reconnect**: Jam digital tetap berdetik mandiri di HP dan otomatis menyambung kembali jika PC mati/restart.

---

## 🌐 Dukungan Penuh Windows & Linux (Cross-Platform)

Program ini dibangun dengan arsitektur **Cross-Platform Dual-Engine** yang secara otomatis mengenali dan menyesuaikan diri dengan sistem operasi host:

| Fitur Telemetri | 🪟 Windows 10 & 11 | 🐧 Linux (CachyOS, Arch, Ubuntu, Debian, Fedora) |
| :--- | :--- | :--- |
| **FPS Telemetry Layar Aktif** | Direct **DXGI Desktop Duplication API** (Native tanpa Afterburner) & RTSS Shared Memory | **KWin Wayland Damage Tracker** & **MangoHud** CSV Telemetry |
| **Suhu CPU (°C)** | Multi-Source Sensor Hardware (MSI Afterburner `src_id=0x80`, Core Temp, WMI) | Linux Sysfs Kernel Hwmon (`coretemp`, `k10temp`, `zenpower`) |
| **Clock Speed & Turbo Boost** | Windows Kernel PDH Performance Counter (`\Processor Information`) | Linux Sysfs Scaling Frequency (`scaling_cur_freq`) |
| **GPU Telemetry (Load, Temp, VRAM)** | Native NVIDIA NVML ctypes & Windows PDH / WMI | NVIDIA NVML ctypes, AMD DRM Sysfs, & Intel DRM Sysfs |
| **Kontrol Refresh Rate (180Hz)** | Win32 API (`ChangeDisplaySettingsExW`) | `kscreen-doctor` (KDE), `wlr-randr` (Sway), `hyprctl` (Hyprland), `xrandr` (X11) |
| **Deteksi Jendela & Aplikasi Aktif** | Win32 `GetForegroundWindow` & `MonitorFromWindow` | KWin D-Bus Runner, Hyprland IPC, Swaymsg IPC |
| **Skrip Peluncur (One-Click)** | `start_monitor.bat` | `start_monitor.sh` |

---

## 📥 Panduan Penggunaan (Quick Start)

### 1. Prasyarat
- Komputer menjalankan **Linux** atau **Windows 10 / 11**.
- Sudah terpasang **Python 3.10 atau lebih baru**.
  - **Linux (Arch/CachyOS)**: `sudo pacman -S python python-psutil`
  - **Linux (Ubuntu/Debian)**: `sudo apt install python3 python3-psutil`
  - **Linux (Fedora)**: `sudo dnf install python3 python3-psutil`
  - **Windows**: [Unduh di python.org](https://www.python.org/downloads/) *(pastikan centang "Add python.exe to PATH")*.

### 2. Menjalankan di Linux
1. Masuk ke direktori repositori:
   ```bash
   cd "PC HW Monitor v2.5"
   ```
2. Jalankan skrip monitor:
   ```bash
   chmod +x start_monitor.sh
   ./start_monitor.sh
   ```

### 3. Menjalankan di Windows
1. Klik dua kali file **`start_monitor.bat`**.
2. Skrip akan secara otomatis memeriksa modul dan langsung menjalankan server.

### 4. Output Terminal
Terminal akan menampilkan tautan IP lokal, contoh:
```text
=================================================================
   [+] VIEWHP - PC HARDWARE MONITOR SERVER [LINUX]
=================================================================
 [OK] Server aktif di port 42069
 [URL] Buka URL ini di HP / Tablet (Pastikan 1 Wi-Fi):
       ==>  http://192.168.1.xxx:42069
=================================================================
```

---

## 📱 Membuka di Smartphone / Tablet

### Di Android (Google Chrome)
1. Pastikan HP Android terhubung ke **Wi-Fi yang sama** dengan PC (atau via USB Tethering).
2. Buka browser **Google Chrome** di HP Anda, masukkan URL yang tertera di terminal PC (contoh: `http://192.168.1.xxx:42069`).
3. **Ubah menjadi aplikasi fullscreen (PWA)**:
   - Ketuk menu titik tiga (⋮) di Chrome Android.
   - Pilih **"Tambahkan ke Layar Utama"** (*Add to Home screen*) atau **"Instal Aplikasi"**.
   - Buka ikon aplikasi yang muncul di layar utama HP Anda.
   - Ketuk tombol **`⚡ Keep On`** di pojok kanan atas agar layar HP tidak mati otomatis.

### Di iPhone atau iPad (iOS Safari)
1. Pastikan iPhone / iPad terhubung ke **Wi-Fi yang sama** dengan PC.
2. Buka browser **Safari** di iPhone/iPad, masukkan URL yang tertera di terminal PC (contoh: `http://192.168.1.xxx:42069`).
3. **Ubah menjadi aplikasi fullscreen (PWA)**:
   - Ketuk tombol **Share** di bagian bawah Safari (ikon kotak dengan panah ke atas ⬆️).
   - Gulir ke bawah, pilih **"Add to Home Screen"** (*Tambahkan ke Layar Utama*).
   - Ketuk **Add** di pojok kanan atas.
   - Buka ikon **PC Monitor** yang muncul di Home Screen iPhone/iPad Anda.
   - Ketuk tombol **`⚡ Keep On`** di pojok kanan atas agar layar tidak mati otomatis.

---

## 🛠️ Perintah CLI (Command Line Options)

```bash
# Menjalankan server secara manual
python3 app.py

# Mengubah refresh rate monitor ke 180Hz (Linux & Windows)
python3 app.py --set-hz 180

# Mengubah refresh rate ke 180Hz lalu langsung menjalankan server
python3 app.py --set-hz 180 --run
```

---

## 🔧 Penanganan Kendala (Troubleshooting)

- **Halaman tidak dapat dibuka di HP?**
  1. Pastikan PC dan HP berada di jaringan Wi-Fi lokal yang sama.
  2. **Jika menggunakan Firewall di Linux:**
     - UFW (Ubuntu/Debian):
       ```bash
       sudo ufw allow 42069/tcp
       ```
     - Firewalld (Fedora/RHEL):
       ```bash
       sudo firewall-cmd --add-port=42069/tcp --permanent
       sudo firewall-cmd --reload
       ```
  3. **Jika menggunakan Windows:**
     Jalankan perintah ini di PowerShell (Run as Administrator):
     ```powershell
     New-NetFirewallRule -DisplayName "PC Monitor 42069" -Direction Inbound -LocalPort 42069 -Protocol TCP -Action Allow
     ```
- **Ingin mematikan server**:
  - Tekan tombol `Ctrl + C` di jendela terminal PC.

---

## 📄 Lisensi

Proyek ini menggunakan lisensi [MIT License](LICENSE) - bebas digunakan, dimodifikasi, dan didistribusikan.
