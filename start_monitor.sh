#!/usr/bin/env bash
# ==============================================================================
# ViewHP - PC Hardware Monitor Server Launcher for Linux
# ==============================================================================

set -e
cd "$(dirname "$0")"

# Colors for terminal formatting
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${CYAN}========================================================${NC}"
echo -e "${GREEN}   [+] VIEWHP - PC HARDWARE MONITOR SERVER FOR LINUX${NC}"
echo -e "${CYAN}========================================================${NC}"

# 1. Detect Python 3
PY_CMD=""
if command -v python3 >/dev/null 2>&1; then
    PY_CMD="python3"
elif command -v python >/dev/null 2>&1; then
    PY_CMD="python"
fi

if [ -z "$PY_CMD" ]; then
    echo -e "${RED}[!] ERROR: Python 3 tidak ditemukan di sistem ini.${NC}"
    echo "    Silakan pasang Python 3.10+ terlebih dahulu:"
    echo "    - Arch/CachyOS: sudo pacman -S python"
    echo "    - Ubuntu/Debian: sudo apt install python3"
    echo "    - Fedora: sudo dnf install python3"
    exit 1
fi

# Verify Python version >= 3.10
PY_VER_OK=$("$PY_CMD" -c "import sys; print(1 if sys.version_info >= (3, 10) else 0)" 2>/dev/null || echo "0")
if [ "$PY_VER_OK" != "1" ]; then
    echo -e "${YELLOW}[!] Peringatan: Disarankan menggunakan Python 3.10 atau lebih baru.${NC}"
fi

# 2. Check psutil dependency
if ! "$PY_CMD" -c "import psutil" >/dev/null 2>&1; then
    echo -e "${YELLOW}[*] Modul psutil belum terpasang. Mencoba instalasi otomatis...${NC}"
    if command -v pip3 >/dev/null 2>&1 || command -v pip >/dev/null 2>&1; then
        PIP_CMD=$(command -v pip3 || command -v pip)
        "$PIP_CMD" install -r requirements.txt || "$PIP_CMD" install -r requirements.txt --break-system-packages || true
    fi

    # Verify if installed successfully
    if ! "$PY_CMD" -c "import psutil" >/dev/null 2>&1; then
        echo -e "${RED}[!] Gagal menginstal psutil secara otomatis.${NC}"
        echo "    Silakan jalankan perintah instalasi paket sesuai distro Anda:"
        echo "    - Arch/CachyOS: sudo pacman -S python-psutil"
        echo "    - Ubuntu/Debian: sudo apt install python3-psutil"
        echo "    - Fedora: sudo dnf install python3-psutil"
        echo "    - openSUSE: sudo zypper in python3-psutil"
        exit 1
    fi
fi

# 3. Launch server
echo -e "${GREEN}[*] Memulai server PC Hardware Monitor...${NC}\n"
exec "$PY_CMD" app.py "$@"
