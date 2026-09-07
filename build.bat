@echo off
setlocal enabledelayedexpansion

REM Build the Windows app, a portable zip, and the installer.
REM The version comes from core/__init__.VERSION -- never typed twice.

for /f %%v in ('python -c "import core; print(core.VERSION)"') do set VER=%%v
if "%VER%"=="" (
    echo Could not read the version from core/__init__.py
    exit /b 1
)
echo Building Archiver %VER%
echo.

echo [1/4] Running the tests first...
python tests\run_all.py >nul 2>&1
if errorlevel 1 (
    echo Tests FAILED -- refusing to package. Run: python tests\run_all.py
    exit /b 1
)
echo       tests pass.
echo.

echo [2/4] Building with PyInstaller...
pyinstaller Archiver.spec --clean -y
if errorlevel 1 (
    echo PyInstaller failed.
    exit /b 1
)
echo.

echo [3/4] Zipping the portable build...
if not exist releases mkdir releases
powershell -NoProfile -Command "Compress-Archive -Path 'dist\Archiver\*' -DestinationPath 'releases\Archiver_v%VER%_portable.zip' -Force"
if errorlevel 1 (
    echo Zip failed.
    exit /b 1
)
echo.

echo [4/4] Compiling the installer...
set ISCC=
for %%P in (
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    "C:\Program Files\Inno Setup 6\ISCC.exe"
) do (
    if exist %%P set ISCC=%%P
)

if not defined ISCC (
    echo.
    echo   Inno Setup not found -- portable zip only.
    echo   Zip: releases\Archiver_v%VER%_portable.zip
    echo.
    echo   For the installer, get Inno Setup: https://jrsoftware.org/isdl.php
    goto :done
)

%ISCC% /DMyAppVersion=%VER% installer.iss
if errorlevel 1 (
    echo Inno Setup compilation failed.
    exit /b 1
)

:done
echo.
echo Done.
echo   Portable:  releases\Archiver_v%VER%_portable.zip
if defined ISCC echo   Installer: installer_out\Archiver_Setup_%VER%.exe
