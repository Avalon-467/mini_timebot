@echo off
chcp 65001 >nul 2>&1

:: Mini TimeBot 一键运行（环境配置 + 注册用户 + 启动服务）

cd /d "%~dp0"

echo ========== 1/3 环境检查与配置 ==========
call scripts\setup_env.bat
if errorlevel 1 (
    echo [ERROR] 环境配置失败，请检查错误信息
    pause
    exit /b 1
)

echo.
echo ========== 2/3 用户管理 ==========
set /p answer=是否需要添加新用户？(y/N): 
if /i "%answer%"=="y" (
    call scripts\adduser.bat
)

echo.
echo ========== 3/3 启动服务 ==========

:: 延迟 8 秒后自动打开浏览器
start "" cmd /c "timeout /t 8 /nobreak >nul && start http://127.0.0.1:9000"

call scripts\start.bat
