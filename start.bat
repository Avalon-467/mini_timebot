@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion

:: Mini TimeBot 一键启动脚本 (Windows)

cd /d "%~dp0"

:: 检查 .env 配置
if not exist "config\.env" (
    echo [ERROR] 未找到 config\.env 文件，请先创建并填入 DEEPSEEK_API_KEY
    pause
    exit /b 1
)

:: 激活虚拟环境（如果存在）
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
)

echo [START] 启动 Mini TimeBot...
echo.

:: 1. 启动定时调度中心 (port 8001)
echo [1/3] 启动定时调度中心 (port 8001)...
start /b "" python src/time.py
timeout /t 2 /nobreak >nul

:: 2. 启动 AI Agent (port 8000)
echo [2/3] 启动 AI Agent (port 8000)...
start /b "" python src/mainagent.py
timeout /t 3 /nobreak >nul

:: 3. 启动前端 (port 9000)
echo [3/3] 启动前端 Web UI (port 9000)...
start /b "" python src/front.py
timeout /t 1 /nobreak >nul

echo.
echo ============================================
echo   Mini TimeBot 已全部启动！
echo   访问: http://127.0.0.1:9000
echo   按任意键停止所有服务
echo ============================================
echo.

pause >nul

:: 关闭所有 python 子进程（按端口精确杀）
echo [STOP] 正在关闭所有服务...

for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8001.*LISTENING"') do taskkill /f /pid %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000.*LISTENING"') do taskkill /f /pid %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":9000.*LISTENING"') do taskkill /f /pid %%a >nul 2>&1

echo [DONE] 所有服务已关闭
pause
