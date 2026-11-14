# Changelog - PC Hardware Monitor (ViewHP)

Semua catatan perubahan dan pembaruan penting pada proyek PC Hardware Monitor didokumentasikan di berkas ini.

---

## [2.5.0] - 15 November 2026

### 🎮 Fitur Baru & Peningkatan Utama (Major New Features)
- **Deteksi Real-Time FPS Layar Aktif Tanpa MSI Afterburner (`WindowsFpsTracker`)**:
  - Mengintegrasikan pelacak FPS real-time native berbasis **Windows DirectX Desktop Duplication API (`IDXGIOutputDuplication`)**.
  - **Zero-overhead & Mandiri**: Berjalan langsung di level display hardware pipeline Windows tanpa memerlukan instalasi MSI Afterburner, RTSS, atau software overlay pihak ketiga.
  - **Dukungan Multi-Monitor Independen**: Memantau frame rate (FPS) dan latency *frametime* (ms) secara terpisah di setiap monitor (`DISPLAY1`, `DISPLAY2`, dst.) dengan multi-worker thread.
  - **Kartu HUD Adaptif**:
    - `🎮 IN-GAME FPS`: Saat bermain game 3D (CS2, Valorant, Dota 2, Halo, dll.) menampilkan live render FPS, nama game, frametime, dan rasio gauge ring terhadap refresh rate monitor.
    - `⚡ APP FPS`: Saat fokus di aplikasi produktivitas/browser/video player (Brave, Chrome, Discord, dll.) melacak frame update real-time aplikasi tersebut.
    - `⚡ SCREEN FPS / REFRESH`: Menampilkan FPS layar desktop aktif saat terjadi interaksi/animasi, atau nominal Hz statis saat layar diam (*standby*).
  - **Badge Monitor Real-Time**: Setiap kartu monitor pada panel *Layar & Tampilan* kini memiliki badge FPS dinamis (`🎮 180 FPS` / `⚡ 180 FPS`).

- **Sistem Pembacaan Suhu CPU Real-Time Multi-Tier**:
  - Memperbarui sistem ekstraksi sensor CPU fisik di Windows dengan pembacaan ID hardware resmi (`src_id == 0x80` untuk Package & Per-Core Temperature).
  - Menambahkan dukungan multi-sumber sensor hardware:
    - *MSI Afterburner Shared Memory (`MAHMSharedMemory`)* dengan fuzzy-matching nama sensor & sensor ID.
    - *Core Temp Shared Memory (`CoreTempMappingObject`)* untuk pengguna aplikasi monitor CPU ringan.
    - *LibreHardwareMonitor & OpenHardwareMonitor WMI* fallback.
  - **Automated Silent Background Sensor Service**:
    - Ditambahkan fungsi otomatis `ensure_hardware_monitor_service()` di `app.py` dan pemicu di `start_monitor.bat`.
    - Jika service sensor hardware di latar belakang belum aktif, server secara hening memicu scheduled task `/s` (minimized ke tray) agar driver sensor fisik (`RTCore64`) selalu siap memasok data suhu CPU real-time tanpa perlu membuka jendela manual.

- **Penyempurnaan Deteksi Game vs Aplikasi Non-Game**:
  - Menerapkan daftar penyaring cerdas `COMMON_NON_GAME_APPS` (browser, editor kode, terminal, utilitas sistem) sehingga game 3D asli dibedakan secara akurat dari aplikasi biasa.

- **Dukungan Penuh Cross-Platform Windows 10/11 & Linux (Dual-Engine)**:
  - Server secara otomatis mendeteksi sistem operasi host dan mengaktifkan subsistem telemetri yang sesuai secara native (`[WINDOWS]` via Win32 + DXGI Desktop Duplication, atau `[LINUX]` via KWin Wayland Compositor + sysfs hwmon).
  - Ditambahkan indikator identitas OS host pada header dashboard dan endpoint `/api/stats`.

---

## [2.1.0] - 12 November 2026

### 🎮 Fitur Baru (New Features)
- **Deteksi Suhu CPU Hardware Asli**:
  - Mengintegrasikan pembacaan sensor suhu CPU secara langsung dari MSI Afterburner Shared Memory (`MAHMSharedMemory`).
  - Dilengkapi dynamic thermal calibration fallback jika Afterburner sedang ditutup.
- **In-Game FPS & Frametime Monitoring (RTSS)**:
  - Mengintegrasikan pembacaan frame rate per detik (FPS) dan latency *frametime* (ms) secara real-time dari RivaTuner Statistics Server (RTSS) Shared Memory V2 (`RTSSSharedMemoryV2`).
  - Mendeteksi secara cerdas game 3D yang aktif di latar depan (*foreground*) dengan filter usia frame rendering (< 2500ms).
- **In-Game FPS Card**:
  - Menambahkan kartu visual FPS di jajaran kartu utama (Clock, CPU, RAM, GPU, In-Game FPS) dengan gauge ring dinamis, judul game aktif, dan indikator frame latency.

---

### ⚡ Penyempurnaan & Perbaikan Bug (Fixes & Improvements)
- **Pembacaan Frekuensi CPU Dinamis (Real-Time GHz)**:
  - **Masalah**: Bawaan `psutil.cpu_freq()` di Windows hanya membaca base clock nominal statis (3.30 GHz) dan tidak mendeteksi Turbo Boost.
  - **Solusi**: Dibuat sistem **Multi-Tier Live Frequency Resolver**:
    - *Tier 1*: MSI Afterburner physical core clock (mendeteksi Turbo Boost aktif hingga ~4.10 GHz).
    - *Tier 2*: Windows Kernel Performance Counter PDH (`\Processor Information(_Total)\% Processor Performance`) untuk menghitung dynamic scaling dan scaling governor CPU secara native.
    - *Tier 3*: psutil nominal clock fallback.
  - Nilai diformat konsisten 2 desimal (misal `4.10 GHz`, `3.95 GHz`).
- **Akurasi & Normalisasi Top Proses CPU (Task Manager Standard)**:
  - **Masalah**: Beban CPU pada proses individual terkadang terbaca > 100% karena `psutil` mengukur beban akumulatif per-core (pada CPU 4C/8T bisa mencapai 800%).
  - **Solusi**: Beban dinormalisasi terhadap seluruh kapasitas thread sistem (`delta_t / dt / num_threads`), sesuai standar Windows Task Manager (rentang 0% - 100%).
  - Menghitung selisih waktu (`delta_t`) antar-sampel secara persisten sehingga bebas dari lonjakan sesaat (*false spikes*).
  - Mengelompokkan (*aggregate*) proses dengan nama file eksekusi yang sama (seperti browser atau multi-proses game).
  - Menerapkan *strict clamping* ganda di backend dan frontend (`Math.min(100, Math.max(0, val))`).
- **Pembersihan UI & Penghapusan Elemen Redundan**:
  - Menghapus kotak HUD hijau FPS duplikat di atas daftar monitor, menyederhanakan panel bawah menjadi **🖥️ Layar & Tampilan** yang bersih dan fokus pada info display serta aplikasi aktif.
  - Menghapus badge pill FPS kecil (`🔵 FPS: 180`) di header agar area header ringkas dan pemantauan FPS terpusat rapi di kartu utama.
- **Pembaruan Terminal `start_monitor.bat` & `app.py`**:
  - Menambahkan panduan PWA fullscreen dan langkah instalasi untuk **Android (Chrome)** dan **iOS (Safari di iPhone / iPad)** langsung di tampilan konsol server.
  - Memperbaiki bug parsing batch file di Windows (`'iOS)' is not recognized...`) akibat karakter `&` yang tidak ter-escape, diganti menjadi kata `dan`.
- **Anti-Cache & Service Worker Bump**:
  - Menambahkan header HTTP `Cache-Control: no-cache, no-store, must-revalidate` pada `app.py`.
  - Menaikkan versi cache PWA Service Worker secara berkala hingga `pc-monitor-cache-v9` di `sw.js` agar perubahan UI langsung tampil di HP tanpa tertahan cache lama.

---
