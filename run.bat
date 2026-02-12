@echo off
chcp 65001 >nul 2>&1

:: Mini TimeBot 一键运行（环境配置 + API Key + 注册用户 + 启动服务）

cd /d "%~dp0"

echo ========== 1/4 环境检查与配置 ==========
call scripts\setup_env.bat
if errorlevel 1 (
    echo [ERROR] 环境配置失败，请检查错误信息
    pause
    exit /b 1
)

:: 激活虚拟环境（如果存在），后续所有 python 调用均使用虚拟环境
if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
)

echo.
echo ========== 2/4 API Key 配置 ==========
call scripts\setup_apikey.bat

echo.
echo ========== 3/4 用户管理 ==========
set /p answer=是否需要添加新用户？(y/N): 
if /i "%answer%"=="y" (
    call scripts\adduser.bat
)

echo.
echo ========== 4/4 启动服务 ==========

:: 询问是否部署公网
set /p tunnel_answer=是否部署到公网？(y/N): 
if /i "%tunnel_answer%"=="y" (
    echo 正在后台启动 Cloudflare Tunnel...
    start /b python scripts\tunnel.py
    timeout /t 2 /nobreak >nul
)

:: 使用 Python 启动器（启动完成后自动打开浏览器）
python scripts\launcher.py
