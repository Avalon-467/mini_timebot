import os
import subprocess
import sys

# chatbot 目录
CHATBOT_DIR = os.path.dirname(os.path.abspath(__file__))

# 项目根目录
PROJECT_ROOT = os.path.dirname(CHATBOT_DIR)

# 配置文件路径（统一使用 config/.env）
ENV_FILE = os.path.join(PROJECT_ROOT, "config", ".env")

# 项目 uv 环境
if sys.platform == "win32":
    VENV_PYTHON = os.path.join(PROJECT_ROOT, ".venv", "Scripts", "python.exe")
else:
    VENV_PYTHON = os.path.join(PROJECT_ROOT, ".venv", "bin", "python")

def main():
    print("=== Chatbot 启动器 ===")

    # 1. 检查 .env 文件
    if not os.path.exists(ENV_FILE):
        print(f"[错误] .env 配置文件不存在: {ENV_FILE}")
        return

    # 2. 检查 venv
    if not os.path.exists(VENV_PYTHON):
        print(f"[错误] 未找到虚拟环境: {VENV_PYTHON}")
        return

    # 3. 选择启动
    print("-" * 30)
    print("你想启动哪个机器人？")
    print("1. QQ 机器人 (QQbot.py)")
    print("2. Telegram 机器人 (telegrambot.py)")
    print("3. 全部启动")
    print("4. 跳过")

    choice = input("\n请选择 (1/2/3/4): ").strip()

    # 日志目录
    log_dir = os.path.join(CHATBOT_DIR, "logs")
    os.makedirs(log_dir, exist_ok=True)

    if choice == "1":
        print("\n🚀 正在启动 QQ 机器人...")
        log_file = open(os.path.join(log_dir, "qqbot.log"), "a", encoding="utf-8")
        subprocess.Popen(
            [VENV_PYTHON, os.path.join(CHATBOT_DIR, "QQbot.py")],
            stdout=log_file, stderr=log_file,
        )
        print("日志: chatbot/logs/qqbot.log")
    elif choice == "2":
        print("\n🚀 正在启动 Telegram 机器人...")
        log_file = open(os.path.join(log_dir, "telegrambot.log"), "a", encoding="utf-8")
        subprocess.Popen(
            [VENV_PYTHON, os.path.join(CHATBOT_DIR, "telegrambot.py")],
            stdout=log_file, stderr=log_file,
        )
        print("日志: chatbot/logs/telegrambot.log")
    elif choice == "3":
        print("\n🚀 正在启动所有机器人...")
        qq_log = open(os.path.join(log_dir, "qqbot.log"), "a", encoding="utf-8")
        tg_log = open(os.path.join(log_dir, "telegrambot.log"), "a", encoding="utf-8")
        subprocess.Popen(
            [VENV_PYTHON, os.path.join(CHATBOT_DIR, "QQbot.py")],
            stdout=qq_log, stderr=qq_log,
        )
        subprocess.Popen(
            [VENV_PYTHON, os.path.join(CHATBOT_DIR, "telegrambot.py")],
            stdout=tg_log, stderr=tg_log,
        )
        print("日志: chatbot/logs/qqbot.log, chatbot/logs/telegrambot.log")
    else:
        print("\n跳过启动。")
    print("-" * 30)

if __name__ == "__main__":
    main()
