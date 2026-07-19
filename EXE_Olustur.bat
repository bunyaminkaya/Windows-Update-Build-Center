@echo off
cd /d "%~dp0"
title Windows Update ^& Build Center - EXE Olusturma
cls
echo ============================================================
echo Windows Update ^& Build Center - EXE Olusturma
echo ============================================================
echo.

where py.exe >nul 2>nul
if not errorlevel 1 (
    py -3 "%~dp0build_exe.py"
) else (
    where python.exe >nul 2>nul
    if errorlevel 1 (
        echo HATA: Python bulunamadi. Python 3.11 veya daha yeni bir surum kurun.
        pause
        exit /b 1
    )
    python "%~dp0build_exe.py"
)

set "BUILD_RESULT=%ERRORLEVEL%"
echo.
if "%BUILD_RESULT%"=="0" (
    echo EXE olusturma tamamlandi.
) else (
    echo EXE olusturulamadi. EXE_Build.log dosyasini kontrol edin.
)
echo.
pause
exit /b %BUILD_RESULT%
