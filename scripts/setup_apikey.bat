@echo off
chcp 65001 >nul 2>&1

:: LLM API Key 配置脚本（支持 DeepSeek / OpenAI / Gemini 等 OpenAI 兼容接口）

cd /d "%~dp0\.."

set "ENV_FILE=config\.env"
set "EXAMPLE_FILE=config\.env.example"

:: 已有 .env 且 Key 已配置，询问是否重置
if not exist "%ENV_FILE%" goto ask_key

:: 读取当前 Key
for /f "tokens=1,* delims==" %%a in ('findstr /i "LLM_API_KEY" "%ENV_FILE%"') do set "CURRENT_KEY=%%b"
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
echo   需要配置 LLM API Key 才能使用
echo   支持 DeepSeek / OpenAI / Gemini 等
echo ================================================
echo.

set /p API_KEY=请输入你的 API Key: 

if "%API_KEY%"=="" (
    echo [SKIP] 未输入 API Key，跳过配置
    echo        请稍后手动编辑 config\.env
    exit /b 1
)

set /p BASE_URL=请输入 API Base URL（回车默认 https://api.deepseek.com/v1）: 
if "%BASE_URL%"=="" set "BASE_URL=https://api.deepseek.com/v1"

set /p MODEL_NAME=请输入模型名称（回车默认 deepseek-chat）: 
if "%MODEL_NAME%"=="" set "MODEL_NAME=deepseek-chat"

set /p TTS_MODEL=请输入 TTS 模型名称（回车默认 gemini-2.5-flash-preview-tts）: 
if "%TTS_MODEL%"=="" set "TTS_MODEL=gemini-2.5-flash-preview-tts"

set /p TTS_VOICE=请输入 TTS 语音（回车默认 charon）: 
if "%TTS_VOICE%"=="" set "TTS_VOICE=charon"

:: 如果已有 .env，用 PowerShell 原地替换 Key，保留其余配置
if exist "%ENV_FILE%" (
    :: 更新 LLM_API_KEY
    findstr /i "^LLM_API_KEY=" "%ENV_FILE%" >nul 2>&1
    if %errorlevel%==0 (
        powershell -Command "$c=[System.IO.File]::ReadAllText('%ENV_FILE%',[System.Text.Encoding]::UTF8); $c=$c -replace '(?m)^LLM_API_KEY=.*','LLM_API_KEY=%API_KEY%'; [System.IO.File]::WriteAllText('%ENV_FILE%',$c,(New-Object System.Text.UTF8Encoding $false))"
    ) else (
        echo LLM_API_KEY=%API_KEY%>> "%ENV_FILE%"
    )
    :: 更新 LLM_BASE_URL
    findstr /i "^LLM_BASE_URL=" "%ENV_FILE%" >nul 2>&1
    if %errorlevel%==0 (
        powershell -Command "$c=[System.IO.File]::ReadAllText('%ENV_FILE%',[System.Text.Encoding]::UTF8); $c=$c -replace '(?m)^LLM_BASE_URL=.*','LLM_BASE_URL=%BASE_URL%'; [System.IO.File]::WriteAllText('%ENV_FILE%',$c,(New-Object System.Text.UTF8Encoding $false))"
    ) else (
        echo LLM_BASE_URL=%BASE_URL%>> "%ENV_FILE%"
    )
    :: 更新 LLM_MODEL
    findstr /i "^LLM_MODEL=" "%ENV_FILE%" >nul 2>&1
    if %errorlevel%==0 (
        powershell -Command "$c=[System.IO.File]::ReadAllText('%ENV_FILE%',[System.Text.Encoding]::UTF8); $c=$c -replace '(?m)^LLM_MODEL=.*','LLM_MODEL=%MODEL_NAME%'; [System.IO.File]::WriteAllText('%ENV_FILE%',$c,(New-Object System.Text.UTF8Encoding $false))"
    ) else (
        echo LLM_MODEL=%MODEL_NAME%>> "%ENV_FILE%"
    )
    :: 更新 TTS_MODEL
    findstr /i "^TTS_MODEL=" "%ENV_FILE%" >nul 2>&1
    if %errorlevel%==0 (
        powershell -Command "$c=[System.IO.File]::ReadAllText('%ENV_FILE%',[System.Text.Encoding]::UTF8); $c=$c -replace '(?m)^TTS_MODEL=.*','TTS_MODEL=%TTS_MODEL%'; [System.IO.File]::WriteAllText('%ENV_FILE%',$c,(New-Object System.Text.UTF8Encoding $false))"
    ) else (
        echo TTS_MODEL=%TTS_MODEL%>> "%ENV_FILE%"
    )
    :: 更新 TTS_VOICE
    findstr /i "^TTS_VOICE=" "%ENV_FILE%" >nul 2>&1
    if %errorlevel%==0 (
        powershell -Command "$c=[System.IO.File]::ReadAllText('%ENV_FILE%',[System.Text.Encoding]::UTF8); $c=$c -replace '(?m)^TTS_VOICE=.*','TTS_VOICE=%TTS_VOICE%'; [System.IO.File]::WriteAllText('%ENV_FILE%',$c,(New-Object System.Text.UTF8Encoding $false))"
    ) else (
        echo TTS_VOICE=%TTS_VOICE%>> "%ENV_FILE%"
    )
) else (
    :: 首次创建：从模板复制再写入
    if exist "%EXAMPLE_FILE%" (
        copy /y "%EXAMPLE_FILE%" "%ENV_FILE%" >nul
        powershell -Command "$c=[System.IO.File]::ReadAllText('%ENV_FILE%',[System.Text.Encoding]::UTF8); $c=$c -replace '(?m)^LLM_API_KEY=.*','LLM_API_KEY=%API_KEY%'; $c=$c -replace '(?m)^LLM_BASE_URL=.*','LLM_BASE_URL=%BASE_URL%'; $c=$c -replace '(?m)^LLM_MODEL=.*','LLM_MODEL=%MODEL_NAME%'; $c=$c -replace '(?m)^# TTS_MODEL=.*','TTS_MODEL=%TTS_MODEL%'; $c=$c -replace '(?m)^# TTS_VOICE=.*','TTS_VOICE=%TTS_VOICE%'; [System.IO.File]::WriteAllText('%ENV_FILE%',$c,(New-Object System.Text.UTF8Encoding $false))"
    ) else (
        (
            echo LLM_API_KEY=%API_KEY%
            echo LLM_BASE_URL=%BASE_URL%
            echo LLM_MODEL=%MODEL_NAME%
            echo TTS_MODEL=%TTS_MODEL%
            echo TTS_VOICE=%TTS_VOICE%
        ) > "%ENV_FILE%"
    )
)

echo [OK] API Key 已保存到 config\.env
exit /b 0
