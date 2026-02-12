@echo off
chcp 65001 >nul 2>&1

:: Cloudflare Tunnel 公网部署（独立使用）
:: 用法: scripts\tunnel.bat

cd /d "%~dp0\.."

:: 激活虚拟环境
if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
)

python scripts\tunnel.py
