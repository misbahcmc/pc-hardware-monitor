# 🖥️ PC Hardware Monitor HUD (ViewHP) for Android & iOS (iPhone/iPad)

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-0078D6.svg)](https://www.microsoft.com/windows)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![PWA](https://img.shields.io/badge/PWA-Ready-orange.svg)](https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps)

Aplikasi pemantauan hardware PC secara real-time yang dirancang khusus untuk layar smartphone atau tablet (Android & iPhone/iPad) melalui jaringan lokal (Wi-Fi atau USB Tethering).

Menggunakan arsitektur **Python Server + Progressive Web App (PWA)**, aplikasi ini dapat langsung dipasang ke layar utama Android maupun iOS dan berjalan dalam mode **layar penuh (fullscreen)** tanpa perlu compile APK atau instalasi aplikasi pihak ketiga.

---

## 🚀 Fitur Utama

- **CPU Monitoring**: Model CPU otomatis terdeteksi (misal: *12th Gen Intel Core i3-12100F*), beban CPU (%), Clock Speed (GHz), dan jumlah core/threads.
- **RAM Monitoring**: Persentase pemakaian, RAM terpakai (GB), dan total RAM (GB).
- **GPU Monitoring**: Beban GPU (%), Suhu (°C), serta pemakaian VRAM secara real-time.
- **Top 5 Proses**: Memantau program yang paling memakan penggunaan CPU di komputer.
- **Deteksi Monitor & Program Aktif**: Mendeteksi resolusi dan refresh rate layar (misal: 1080p @ 180Hz) serta program yang sedang aktif di layar Windows.
- **Jaringan & Penyimpanan**: Kecepatan Download/Upload real-time dan bar kapasitas drive (C:, D:, dll.).
- **Tampilan PWA (Progressive Web App)**: Cukup *Add to Home Screen* dari browser Chrome, langsung menjadi aplikasi fullscreen tanpa URL bar.
- **Fitur "⚡ Keep On" (Screen Wake Lock)**: Layar HP tetap menyala terus saat ditaruh di meja kerja/gaming.
- **Jam Digital & Auto-Reconnect**: Jam digital tetap berdetik mandiri di HP dan otomatis menyambung kembali jika PC mati/restart.

---

## 📥 Panduan Penggunaan untuk Pengguna Lain (Quick Start)

Bagi siapa saja yang mengunduh repositori ini:

### 1. Prasyarat
- Komputer menjalankan **Windows 10 atau 11**.
- Sudah terpasang **Python 3.10 atau lebih baru** ([Unduh di python.org](https://www.python.org/downloads/) - *pastikan centang "Add python.exe to PATH" saat instalasi*).

### 2. Menjalankan di PC
1. **Download Repositori**:
   - Klik tombol hijau **`<> Code`** di atas, lalu pilih **Download ZIP**, kemudian ekstrak foldernya.
   - Atau via terminal:
     ```bash
     git clone https://github.com/misbahcmc/pc-hardware-monitor.git
     cd pc-hardware-monitor
     ```
2. **Jalankan Aplikasi**:
   - Cukup klik dua kali file **`start_monitor.bat`**.
   - Skrip ini akan **secara otomatis** menginstal pustaka yang diperlukan (`psutil`, `nvidia-ml-py`) dan langsung menjalankan server.
3. Terminal akan menampilkan tautan IP lokal, contoh:
   ```text
   ============================================================
      [+] VIEWHP - PC HARDWARE MONITOR SERVER FOR ANDROID
   ============================================================
    [OK] Server aktif di port 42069
    [URL] BUKA LINK INI DI BROWSER HP ANDROID (Pastikan 1 Wi-Fi):
          ==>  http://192.168.1.xxx:42069
   ============================================================
   ```

### 3. Membuka di HP Android
1. Pastikan HP Android terhubung ke **Wi-Fi yang sama** dengan PC (atau via USB Tethering).
2. Buka browser **Google Chrome** di HP Anda, masukkan URL yang tertera di terminal PC (contoh: `http://192.168.1.xxx:42069`).
3. **Ubah menjadi aplikasi fullscreen (PWA)**:
   - Ketuk menu titik tiga (⋮) di Chrome Android.
   - Pilih **"Tambahkan ke Layar Utama"** (*Add to Home screen*) atau **"Instal Aplikasi"**.
   - Buka ikon aplikasi yang muncul di layar utama HP Anda.
   - Ketuk tombol **`⚡ Keep On`** di pojok kanan atas agar layar HP tidak mati otomatis.

### 4. Membuka di iPhone atau iPad (iOS)
1. Pastikan iPhone / iPad terhubung ke **Wi-Fi yang sama** dengan PC.
2. Buka browser **Safari** di iPhone/iPad, masukkan URL yang tertera di terminal PC (contoh: `http://192.168.1.xxx:42069`).
3. **Ubah menjadi aplikasi fullscreen (PWA)**:
   - Ketuk tombol **Share** di bagian bawah Safari (ikon kotak dengan panah ke atas ⬆️).
   - Gulir ke bawah, pilih **"Add to Home Screen"** (*Tambahkan ke Layar Utama*).
   - Ketuk **Add** di pojok kanan atas.
   - Buka ikon **PC Monitor** yang muncul di Home Screen iPhone/iPad Anda untuk menikmati tampilan **layar penuh (fullscreen)** tanpa bilah alamat Safari.
   - Ketuk tombol **`⚡ Keep On`** di pojok kanan atas agar layar tidak mati otomatis.

---

## 🛠️ Instalasi Manual (Opsional)

Jika ingin menjalankan tanpa batch file:
```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Jalankan server
python app.py
```

---

## 🔧 Penanganan Kendala (Troubleshooting)

- **Halaman tidak dapat dibuka di HP Android?**
  1. Pastikan PC dan HP berada di jaringan Wi-Fi lokal yang sama.
  2. Pastikan Windows Firewall mengizinkan port `42069`. Jika terblokir, jalankan perintah ini di PowerShell (Run as Administrator):
     ```powershell
     New-NetFirewallRule -DisplayName "PC Monitor 42069" -Direction Inbound -LocalPort 42069 -Protocol TCP -Action Allow
     ```
- **Ingin mematikan server**:
  - Tekan tombol `Ctrl + C` di jendela terminal PC atau cukup tutup jendela terminalnya.

---

## 📄 Lisensi

Proyek ini menggunakan lisensi [MIT License](LICENSE) - bebas digunakan, dimodifikasi, dan didistribusikan.
