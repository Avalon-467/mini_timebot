@echo off
chcp 65001 >nul 2>&1
setlocal

:: Mini TimeBot 自动环境配置脚本 (Windows)

cd /d "%~dp0"

echo ==========================================
echo   Mini TimeBot 环境自动配置
echo ==========================================
echo.

:: --- 1. 检查并安装 uv ---
where uv >nul 2>&1
if not errorlevel 1 (
    echo [OK] uv 已安装
    uv --version
    goto :uv_ok
)

echo [INSTALL] 未检测到 uv，正在安装...
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

:: 刷新 PATH
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"

where uv >nul 2>&1
if errorlevel 1 (
    echo [ERROR] uv 安装失败，请手动安装: https://docs.astral.sh/uv/
    echo         安装后请重新打开终端再运行此脚本
    pause
    exit /b 1
)
echo [OK] uv 安装成功

:uv_ok

:: --- 2. 检查并创建虚拟环境 ---
if exist ".venv" (
    echo [OK] 虚拟环境已存在: .venv\
) else (
    echo [SETUP] 创建虚拟环境 (.venv, Python 3.11+)...
    uv venv .venv --python 3.11
    echo [OK] 虚拟环境创建完成
)

:: --- 3. 激活虚拟环境 ---
call .venv\Scripts\activate.bat
echo [OK] 虚拟环境已激活
python --version

:: --- 4. 安装/更新依赖 ---
echo [INSTALL] 安装依赖 (requirements.txt)...
uv pip install -r requirements.txt
echo [OK] 依赖安装完成

:: --- 5. 检查配置文件 ---
echo.
echo --- 配置检查 ---

if exist "config\.env" (
    echo [OK] config\.env 已存在
) else (
    echo [WARN] config\.env 不存在，请创建并填入: DEEPSEEK_API_KEY=your_key
)

if exist "config\users.json" (
    echo [OK] config\users.json 已存在
) else (
    echo [WARN] config\users.json 不存在，请运行 adduser.bat 创建用户
)

echo.
echo ==========================================
echo   环境配置完成！
echo   启动服务: start.bat
echo ==========================================
pause
