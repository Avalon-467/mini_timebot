#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mini TimeBot 跨平台启动器
- 支持 Linux/macOS/Windows
- 精确管理子进程 PID
- 安全关闭：Ctrl+C、关窗口、kill 都能正常清理
"""

import subprocess
import sys
import os
import signal
import atexit
import time
import webbrowser
from dotenv import load_dotenv

# 切换到项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJECT_ROOT)

# 检查 .env 配置
if not os.path.exists("config/.env"):
    print("❌ 未找到 config/.env 文件，请先创建并填入 DEEPSEEK_API_KEY")
    sys.exit(1)

# 加载 .env 配置
load_dotenv(dotenv_path=os.path.join(PROJECT_ROOT, "config", ".env"))

# 读取端口配置
PORT_SCHEDULER = os.getenv("PORT_SCHEDULER", "51201")
PORT_AGENT = os.getenv("PORT_AGENT", "51200")
PORT_FRONTEND = os.getenv("PORT_FRONTEND", "51209")

# 使用当前 Python 解释器（虚拟环境已由 run.sh/run.bat 激活）
venv_python = sys.executable

# 子进程列表
procs = []
cleanup_done = False


def cleanup():
    """清理所有子进程"""
    global cleanup_done
    if cleanup_done:
        return
    cleanup_done = True

    print("\n🛑 正在关闭所有服务...")

    # 先发 SIGTERM（优雅关闭）
    for p in procs:
        if p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass

    # 等待进程退出（最多 5 秒）
    for _ in range(50):
        if all(p.poll() is not None for p in procs):
            break
        time.sleep(0.1)

    # 超时未退出的进程强制杀掉
    for p in procs:
        if p.poll() is None:
            try:
                print(f"⚠️  进程 {p.pid} 未响应，强制终止...")
                p.kill()
            except Exception:
                pass

    # 等待所有进程结束
    for p in procs:
        try:
            p.wait(timeout=2)
        except Exception:
            pass

    print("✅ 所有服务已关闭")


# 注册退出清理
atexit.register(cleanup)


# 信号处理
def signal_handler(signum, frame):
    sys.exit(0)  # 触发 atexit


signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
signal.signal(signal.SIGTERM, signal_handler)  # kill

# Windows 特殊处理：捕获关闭窗口事件
if sys.platform == "win32":
    try:
        import win32api
        win32api.SetConsoleCtrlHandler(lambda x: cleanup() or True, True)
    except ImportError:
        try:
            signal.signal(signal.SIGBREAK, signal_handler)
        except Exception:
            pass

print("🚀 启动 Mini TimeBot...")
print()

# 服务配置：(提示信息, 脚本路径, 启动后等待秒数)
services = [
    (f"⏰ [1/3] 启动定时调度中心 (port {PORT_SCHEDULER})...", "src/time.py", 2),
    (f"🤖 [2/3] 启动 AI Agent (port {PORT_AGENT})...", "src/mainagent.py", 3),
    (f"🌐 [3/3] 启动前端 Web UI (port {PORT_FRONTEND})...", "src/front.py", 1),
]

for msg, script, wait_time in services:
    print(msg)
    proc = subprocess.Popen(
        [venv_python, script],
        cwd=PROJECT_ROOT,
        stdout=None,  # 继承父进程的 stdout
        stderr=None,  # 继承父进程的 stderr
    )
    procs.append(proc)
    time.sleep(wait_time)

print()
print("============================================")
print("  ✅ Mini TimeBot 已全部启动！")
print(f"  🌐 访问: http://127.0.0.1:{PORT_FRONTEND}")
print("  按 Ctrl+C 停止所有服务")
print("============================================")
print()

# 自动打开浏览器
url = f"http://127.0.0.1:{PORT_FRONTEND}"
try:
    webbrowser.open(url)
    print(f"🌐 已自动打开浏览器: {url}")
except Exception:
    print(f"⚠️  无法自动打开浏览器，请手动访问: {url}")

# 等待任意子进程退出
try:
    while True:
        for p in procs:
            if p.poll() is not None:
                print(f"⚠️ 服务 (PID {p.pid}) 异常退出，正在关闭其余服务...")
                sys.exit(1)
        time.sleep(0.5)
except KeyboardInterrupt:
    pass

sys.exit(0)
