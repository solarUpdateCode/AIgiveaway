@echo off
setlocal
echo ============================================
echo   AIgiveaway - Local Windows Build Script
echo ============================================
python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt pyinstaller
python -m app.icon_gen
pyinstaller --clean --noconfirm build\AIgiveaway.spec

set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if exist %ISCC% (
    %ISCC% installer\AIgiveaway.iss
    echo.
    echo [DONE] Windows Installer created at: installer\output\AIgiveaway-Setup-1.0.0.exe
) else (
    echo.
    echo [DONE] Executable created at: dist\AIgiveaway\AIgiveaway.exe
    echo [NOTE] Install Inno Setup 6 to also build installer\output\AIgiveaway-Setup-1.0.0.exe
)
pause
