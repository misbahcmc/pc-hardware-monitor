@echo off
title PC Hardware Monitor Server (ViewHP)
color 0A
cd /d "%~dp0"

echo ========================================================
echo    Menyiapkan PC Hardware Monitor untuk Android...
echo ========================================================

:: 1. Deteksi Python di sistem
set PY_CMD=
where python >nul 2>nul && set PY_CMD=python
if not defined PY_CMD if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY_CMD=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY_CMD if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PY_CMD=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not defined PY_CMD if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" set "PY_CMD=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
if not defined PY_CMD if exist "%ProgramFiles%\Python312\python.exe" set "PY_CMD=%ProgramFiles%\Python312\python.exe"
if not defined PY_CMD if exist "%ProgramFiles%\Python311\python.exe" set "PY_CMD=%ProgramFiles%\Python311\python.exe"
if not defined PY_CMD if exist "%ProgramFiles%\Python310\python.exe" set "PY_CMD=%ProgramFiles%\Python310\python.exe"

if not defined PY_CMD (
    echo [!] Python tidak ditemukan di komputer ini.
    echo Silakan install Python 3.10+ dari: https://www.python.org/downloads/
    echo atau jalankan di PowerShell: winget install Python.Python.3.12
    echo.
    pause
    exit /b 1
)

:: 2. Periksa apakah modul psutil sudah terpasang, jika belum instal otomatis
"%PY_CMD%" -c "import psutil" >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [*] Modul pendukung belum lengkap. Menginstal otomatis...
    "%PY_CMD%" -m pip install -r requirements.txt
    if %ERRORLEVEL% NEQ 0 (
        echo [!] Gagal menginstal dependencies via pip.
        pause
        exit /b 1
    )
)

:: 3. Jalankan server pemantauan
echo [*] Memulai server...
"%PY_CMD%" app.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [!] Server berhenti karena kendala.
    pause
)
