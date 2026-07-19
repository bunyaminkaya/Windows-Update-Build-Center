@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

title Windows Update & Build Center - GitHub Guncelle

set "REPO_URL=https://github.com/bunyaminkaya/Windows-Update-Build-Center.git"

for /f "tokens=2 delims== " %%V in ('findstr /b "APP_VERSION" app\version.py') do set "APPVER=%%~V"
set "APPVER=%APPVER:"=%"
if not defined APPVER set "APPVER=Guncelleme"

echo ============================================================
echo Windows Update ^& Build Center - GitHub Guncelleme
echo Surum: %APPVER%
echo ============================================================
echo.

where git >nul 2>&1
if errorlevel 1 (
    echo HATA: Git bilgisayarinizda bulunamadi.
    echo Once Git for Windows kurun ve bu dosyayi yeniden calistirin.
    echo https://git-scm.com/download/win
    pause
    exit /b 1
)

if not exist ".git" (
    echo [1/5] Git deposu ilk kez hazirlaniyor...
    git init || goto :error
    git branch -M main || goto :error
    git remote add origin "%REPO_URL%" || goto :error
) else (
    echo [1/5] Mevcut Git deposu bulundu.
    git branch -M main >nul 2>&1
    git remote get-url origin >nul 2>&1
    if errorlevel 1 (
        git remote add origin "%REPO_URL%" || goto :error
    ) else (
        git remote set-url origin "%REPO_URL%" || goto :error
    )
)

echo [2/5] Dosyalar hazirlaniyor...
git add -A || goto :error

git diff --cached --quiet
if not errorlevel 1 (
    echo.
    echo GitHub'a gonderilecek yeni bir degisiklik bulunamadi.
    pause
    exit /b 0
)

set "COMMIT_MSG=%APPVER%"
set /p "CUSTOM_MSG=Commit aciklamasi [%APPVER%]: "
if defined CUSTOM_MSG set "COMMIT_MSG=%CUSTOM_MSG%"

echo [3/5] Commit olusturuluyor: %COMMIT_MSG%
git commit -m "%COMMIT_MSG%" || goto :error

echo [4/5] GitHub'a baglaniliyor...
rem Ilk bos GitHub deposunda pull gerekmez. Depoda uzaktan commit varsa once birlestirmeyi dener.
git ls-remote --exit-code --heads origin main >nul 2>&1
if not errorlevel 1 (
    git pull --rebase origin main || goto :error
)

echo [5/5] Degisiklikler GitHub'a gonderiliyor...
git push -u origin main || goto :error

echo.
echo ============================================================
echo BASARILI: %APPVER% GitHub'a gonderildi.
echo https://github.com/bunyaminkaya/Windows-Update-Build-Center
echo ============================================================
pause
exit /b 0

:error
echo.
echo ============================================================
echo HATA: GitHub guncelleme islemi tamamlanamadi.
echo Yukaridaki Git hata mesajini kontrol edin.
echo ============================================================
pause
exit /b 1
