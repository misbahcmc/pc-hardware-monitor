# Changelog - PC Hardware Monitor (ViewHP)

Semua catatan perubahan dan pembaruan penting pada proyek PC Hardware Monitor didokumentasikan di berkas ini.

---

## [V2.61] - 16 November 2026

### 🎮 Peningkatan Utama & Sinkronisasi Presisi FPS (Major Improvements)
- **Pelacakan Hardware Present Game Super Akurat (`NvPresentTracker`)**:
  - **Aktivasi Streaming Present() Sesi FrameView**: Memperbaiki pemanggilan antarmuka vtbl SDK (`fn_start` dan `fn_stop`) sehingga driver GPU secara aktif mengalirkan setiap frame swapchain DirectX 9/10/11/12 & Vulkan melalui named pipe inter-process.
  - **Sinkronisasi Penuh 1:1 dengan In-Game Counter**: Mengeliminasi lonjakan angka FPS palsu akibat *batching* pembacaan buffer pipe. Kalkulasi FPS kini didasarkan langsung pada hardware timestamp `MsBetweenPresents` dari driver kernel NVIDIA (`1000 / avg_ms`), tersinkronisasi presisi dengan overlay game (Steam, RTSS, atau FPS meter bawaan game).
  - **Perbaikan Bug Pipe Worker**: Memperbaiki dependensi impor `from collections import deque` di `app.py` yang sebelumnya memicu `NameError` dan menghentikan pembacaan frame.
  - **Terverifikasi Live**: Berhasil diuji dan divalidasi langsung pada game 3D intensif (*Devil May Cry 5*: 137 FPS @ 7.3 ms frametime).

- **Fokus Pelacakan Eksklusif Aplikasi / Game Teratas (Foreground Only)**:
  - Menghilangkan gangguan deteksi FPS dari aplikasi di latar belakang (*background processes* seperti browser terminimalkan, Discord, atau launcher).
  - Sistem kini secara cerdas mengikat kalkulasi FPS hanya ke jendela proses yang sedang aktif di latar depan pengguna (`GetForegroundWindow()`).
  - **Bebas Batasan Refresh Rate Layar**: Mengatasi keluhan FPS mentok di 180 Hz pada monitor 180 Hz. Game dengan unlocked frame rate kini dapat menampilkan angka render aktual di atas 180 FPS.

- **Adaptif 3-Mode UI & Indikator Visual Dinamis**:
  - `🎮 IN-GAME FPS` (Cincin Hijau Neon): Aktif saat game 3D terdeteksi; menampilkan FPS aktual, nama executable game (misal `DevilMayCry5.exe`), dan *frametime* latensi render (ms).
  - `⚡ APP FPS` (Cincin Sian / Cyan): Aktif saat pengguna berinteraksi di aplikasi produktivitas (Brave, Chrome, media player, dsb.) yang sedang aktif merender frame grafis.
  - `🖥️ DESKTOP IDLE` (Cincin Biru Klasik): Saat berada di desktop atau jendela statis tanpa render frame aktif, ring otomatis beralih ke warna biru dengan nominal refresh rate monitor asli (misal `180 Hz`) tanpa menampilkan badge game palsu.

- **Dukungan Penuh Multi-Vendor GPU (AMD Radeon & Intel Arc)**:
  - **Native Windows DXGI Engine (`_init_dxgi`)**: Mengimplementasikan enumerasi adapter DirectX Graphics Infrastructure (`dxgi.dll` via ctypes) bawaan Windows tanpa ketergantungan library pihak ketiga. Secara otomatis membaca nama resmi GPU (*AMD Radeon RX 7800 XT, Intel Arc A770, dsb.*) dan total kapasitas dedicated VRAM.
  - **MSI Afterburner Shared Memory (`MAHMSharedMemory`)**: Menambahkan jalur telemetri pembacaan Suhu (°C), GPU Usage (%), dan pemakaian VRAM secara real-time untuk kartu grafis AMD Radeon dan Intel Arc di Windows.
  - **Linux Driver Mesa ANV / RADV**: Mendukung telemetri otomatis sysfs kernel DRM Linux dan compositor KWin Wayland.

- **Eliminasi Total Lag Penutupan Server (Instant Zero-Lag Close < 10 ms)**:
  - **Pencegahan DirectX Loader Lock Deadlock**: Menonaktifkan modul duplikasi layar DirectX (`IDXGIOutputDuplication`) yang memegang context D3D11 dan `SetThreadDesktop`. Hal ini 100% melenyapkan freeze driver grafis saat proses keluar.
  - **Native Win32 Console Control Handler (`SetConsoleCtrlHandler`)**: Mendaftarkan listener event `CTRL_CLOSE_EVENT` dan `CTRL_C_EVENT` langsung ke kernel Windows yang langsung memanggil `kernel32.TerminateProcess(kernel32.GetCurrentProcess(), 0)` sehingga jendela langsung tertutup seketika tanpa delay OS.
  - **Penutupan Named Pipe FrameView Eksplisit**: Menambahkan `kernel32.CloseHandle(self.pipe)` saat shutdown sehingga I/O named pipe tidak menahan proses.
  - **Koneksi HTTP Daemon Threads (`daemon_threads = True`)**: Menjadikan seluruh worker thread HTTP koneksi HP/tablet berstatus daemon agar tidak menahan proses keluar saat aplikasi ditutup.
  - **Pencegahan Prompt Gantung Batch File (`start_monitor.bat`)**: Menjalankan Python dengan pengalihan input `<nul` dan perintah penutup `exit /b 0`, mencegah `cmd.exe` menggantung pada prompt `Terminate batch job (Y/N)?`.
  - **Migrasi ke `schtasks.exe`**: Menggantikan pemanggilan berat `powershell.exe` di latar belakang dengan binary native Windows `schtasks.exe` (eksekusi instan ~5 ms tanpa overhead runtime .NET).

- **Pembersihan Terminal Linux di Distro Non-KDE (Ubuntu / GNOME / XFCE)**:
  - Mengatasi munculnya pesan peringatan `Call failed: The name org.kde.KWin was not provided by any .service files` saat menjalankan `./start_monitor.sh` di Ubuntu (GNOME).
  - Menambahkan deteksi desktop environment cerdas `is_kwin_available()`: jika sistem tidak menjalankan KDE Plasma / KWin, panggilan D-Bus KWin dan thread `KWinTracker` otomatis dilewati.
  - Mengisolasi seluruh pemanggilan subprocess CLI dengan `stderr=subprocess.DEVNULL` sehingga output terminal tetap bersih, rapi, dan bebas dari error internal desktop compositor.
  - Menambahkan fallback pendeteksian display output aktif via `xrandr` untuk pengguna GNOME / Ubuntu.

- **Pembersihan Folder & Optimasi Repack Distribusi Proyek**:
  - Menghapus 15 file sampah capture test `FvSDK*.csv` yang sempat terbuat saat pengujian awal.
  - Menghapus file draft lama `windows_implementation_plan.md` dan cache bytecode `__pycache__`.
  - Mengurangi ukuran arsip rilis zip dari ~175 KB menjadi ~74 KB (penurunan ukuran > 57%).

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
