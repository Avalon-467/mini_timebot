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

:: 延迟 8 秒后自动打开浏览器（端口从 .env 读取，默认 51209）
start "" cmd /c "echo 正在启动中，请稍等 8 秒... && timeout /t 8 /nobreak >nul && start http://127.0.0.1:51209"

:: 使用 Python 启动器，确保子进程能被正确管理和清理
python scripts\launcher.py
