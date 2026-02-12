@echo off
chcp 65001 >nul 2>&1

:: DeepSeek API Key 配置脚本

cd /d "%~dp0\.."

set "ENV_FILE=config\.env"
set "EXAMPLE_FILE=config\.env.example"

:: 已有 .env 且 Key 已配置，询问是否重置
if not exist "%ENV_FILE%" goto ask_key

:: 读取当前 Key
for /f "tokens=1,* delims==" %%a in ('findstr /i "DEEPSEEK_API_KEY" "%ENV_FILE%"') do set "CURRENT_KEY=%%b"
if "%CURRENT_KEY%"=="" goto ask_key
if "%CURRENT_KEY%"=="your_api_key_here" goto ask_key

:: Key 已存在，显示部分内容并询问
set "KEY_PREFIX=%CURRENT_KEY:~0,8%"
echo [OK] API Key 已配置（%KEY_PREFIX%...）

:: 解决方法：先 echo 提示语，再进行 set /p
echo.
echo 是否重新配置？(y/N)
set /p RESET="> "

if /i not "%RESET%"=="y" (
    echo     保持现有配置
    timeout /t 2 >nul
    exit /b 0
)


:ask_key
echo ================================================
echo   需要配置 DeepSeek API Key 才能使用
echo   获取地址: https://platform.deepseek.com/api_keys
echo ================================================
echo.

set /p API_KEY=请输入你的 DeepSeek API Key: 

if "%API_KEY%"=="" (
    echo [SKIP] 未输入 API Key，跳过配置
    echo        请稍后手动编辑 config\.env
    exit /b 1
)

:: 如果已有 .env，用 PowerShell 原地替换 Key，保留其余配置
if exist "%ENV_FILE%" (
    :: 检查是否已有 DEEPSEEK_API_KEY 行
    findstr /i "^DEEPSEEK_API_KEY=" "%ENV_FILE%" >nul 2>&1
    if %errorlevel%==0 (
        powershell -Command "(Get-Content '%ENV_FILE%') -replace '^DEEPSEEK_API_KEY=.*', 'DEEPSEEK_API_KEY=%API_KEY%' | Set-Content '%ENV_FILE%'"
    ) else (
        echo DEEPSEEK_API_KEY=%API_KEY%>> "%ENV_FILE%"
    )
    :: 确保 API_BASE 存在
    findstr /i "^DEEPSEEK_API_BASE=" "%ENV_FILE%" >nul 2>&1
    if %errorlevel% neq 0 (
        echo DEEPSEEK_API_BASE=https://api.deepseek.com>> "%ENV_FILE%"
    )
) else (
    :: 首次创建：从模板复制再写入
    if exist "%EXAMPLE_FILE%" (
        copy /y "%EXAMPLE_FILE%" "%ENV_FILE%" >nul
        powershell -Command "(Get-Content '%ENV_FILE%') -replace '^DEEPSEEK_API_KEY=.*', 'DEEPSEEK_API_KEY=%API_KEY%' | Set-Content '%ENV_FILE%'"
    ) else (
        (
            echo DEEPSEEK_API_KEY=%API_KEY%
            echo DEEPSEEK_API_BASE=https://api.deepseek.com
        ) > "%ENV_FILE%"
    )
)

echo [OK] API Key 已保存到 config\.env
exit /b 0
