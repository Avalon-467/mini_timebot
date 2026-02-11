@echo off
chcp 65001 >nul 2>&1

:: 添加用户脚本 (Windows)

cd /d "%~dp0"

:: 激活虚拟环境（如果存在）
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
)

python tools\gen_password.py
pause
