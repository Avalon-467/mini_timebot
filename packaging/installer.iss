; MiniTimeBot Inno Setup 安装脚本
; 使用方法：用 Inno Setup 打开此文件，点击编译

[Setup]
AppName=MiniTimeBot
AppVersion=1.0.0
AppPublisher=MiniTimeBot
DefaultDirName={autopf}\MiniTimeBot
DefaultGroupName=MiniTimeBot
OutputDir=..\dist
OutputBaseFilename=MiniTimeBot_Setup_1.0.0
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; 如有图标取消下行注释
; SetupIconFile=icon.ico

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
; checked 是默认状态，不需要写 flag。如果不想要默认勾选，才加 unchecked
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "添加快捷方式到："; Flags: 
Name: "startmenu"; Description: "创建开始菜单快捷方式"; GroupDescription: "添加快捷方式到："; Flags: 
Name: "taskbar"; Description: "固定到任务栏"; GroupDescription: "添加快捷方式到："; Flags: unchecked

[Files]
; 主程序 exe（放在根目录）
Source: "..\MiniTimeBot.exe"; DestDir: "{app}"; Flags: ignoreversion

; run 脚本
Source: "..\run.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\run.sh"; DestDir: "{app}"; Flags: ignoreversion

; scripts 目录（所有 bat/sh 脚本 + launcher.py + tunnel.py）
Source: "..\scripts\setup_env.bat"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "..\scripts\setup_env.sh"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "..\scripts\start.bat"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "..\scripts\start.sh"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "..\scripts\adduser.bat"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "..\scripts\adduser.sh"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "..\scripts\setup_apikey.bat"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "..\scripts\setup_apikey.sh"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "..\scripts\tunnel.py"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "..\scripts\tunnel.bat"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "..\scripts\tunnel.sh"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "..\scripts\launcher.py"; DestDir: "{app}\scripts"; Flags: ignoreversion

; 源码
Source: "..\src\*"; DestDir: "{app}\src"; Flags: ignoreversion recursesubdirs

; 工具
Source: "..\tools\*"; DestDir: "{app}\tools"; Flags: ignoreversion recursesubdirs

; OASIS 论坛模块
Source: "..\oasis\*"; DestDir: "{app}\oasis"; Flags: ignoreversion recursesubdirs

; 配置模板
Source: "..\config\requirements.txt"; DestDir: "{app}\config"; Flags: ignoreversion
Source: "..\config\.env.example"; DestDir: "{app}\config"; Flags: ignoreversion
Source: "..\config\users.json.example"; DestDir: "{app}\config"; Flags: ignoreversion

; 数据目录（创建空目录结构）
Source: "..\data\timeset\*"; DestDir: "{app}\data\timeset"; Flags: ignoreversion recursesubdirs skipifsourcedoesntexist
Source: "..\data\user_files\*"; DestDir: "{app}\data\user_files"; Flags: ignoreversion recursesubdirs skipifsourcedoesntexist

; 核心数据：prompts（系统 prompt + 专家定义，必需）
Source: "..\data\prompts\*"; DestDir: "{app}\data\prompts"; Flags: ignoreversion recursesubdirs

; 调度示例模板
Source: "..\data\schedules\*"; DestDir: "{app}\data\schedules"; Flags: ignoreversion recursesubdirs skipifsourcedoesntexist

; 其他数据目录（运行时按需创建）
Source: "..\data\bark\*"; DestDir: "{app}\data\bark"; Flags: ignoreversion recursesubdirs skipifsourcedoesntexist
Source: "..\data\oasis_user_experts\*"; DestDir: "{app}\data\oasis_user_experts"; Flags: ignoreversion recursesubdirs skipifsourcedoesntexist

[Dirs]
Name: "{app}\data\timeset"
Name: "{app}\data\user_files"
Name: "{app}\data\prompts"
Name: "{app}\data\schedules"
Name: "{app}\data\bark"
Name: "{app}\data\oasis_user_experts"
Name: "{app}\config"

[Icons]
; 桌面快捷方式（用户勾选时才创建）
Name: "{autodesktop}\MiniTimeBot"; Filename: "{app}\MiniTimeBot.exe"; WorkingDir: "{app}"; Tasks: desktopicon
; 开始菜单快捷方式（用户勾选时才创建）
Name: "{group}\MiniTimeBot"; Filename: "{app}\MiniTimeBot.exe"; WorkingDir: "{app}"; Tasks: startmenu
Name: "{group}\卸载 MiniTimeBot"; Filename: "{uninstallexe}"; Tasks: startmenu

[Run]
; 固定到任务栏（用户勾选时执行）
Filename: "powershell.exe"; \
    Parameters: "-Command ""$s=(New-Object -COM WScript.Shell).CreateShortcut('{app}\MiniTimeBot.lnk');$s.TargetPath='{app}\MiniTimeBot.exe';$s.WorkingDirectory='{app}';$s.Save(); (New-Object -COM Shell.Application).Namespace('{app}').ParseName('MiniTimeBot.lnk').InvokeVerb('taskbarpin')"""; \
    Tasks: taskbar; Flags: runhidden nowait

; 安装完成后选项
Filename: "notepad.exe"; Parameters: "{app}\config\.env.example"; \
    Description: "打开 .env.example 查看配置说明"; Flags: nowait postinstall skipifsilent unchecked
Filename: "{app}\MiniTimeBot.exe"; \
    Description: "立即运行 MiniTimeBot"; Flags: nowait postinstall skipifsilent

[Messages]
FinishedLabel=MiniTimeBot 已安装完成！%n%n首次使用请：%n1. 将 config\.env.example 复制为 config\.env 并填入 API Key%n2. 双击桌面快捷方式 MiniTimeBot 启动
