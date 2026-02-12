#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cloudflare Tunnel 公网部署脚本
- 自动检测平台（Linux/macOS + amd64/arm64）
- 自动下载 cloudflared 到 bin/ 目录
- 启动隧道并打印公网地址
"""

import os
import sys
import re
import stat
import signal
import platform
import subprocess
import urllib.request
import tarfile
import shutil
import tempfile
import threading
from dotenv import load_dotenv

# ── 项目路径 ──────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJECT_ROOT)

BIN_DIR = os.path.join(PROJECT_ROOT, "bin")
os.makedirs(BIN_DIR, exist_ok=True)

CLOUDFLARED_PATH = os.path.join(BIN_DIR, "cloudflared")

# ── 加载配置 ──────────────────────────────────────────────
load_dotenv(dotenv_path=os.path.join(PROJECT_ROOT, "config", ".env"))
PORT_FRONTEND = os.getenv("PORT_FRONTEND", "51209")

# ── 全局进程引用 ──────────────────────────────────────────
tunnel_proc = None


def detect_platform():
    """检测当前平台，返回 (os_name, arch)"""
    os_name = platform.system().lower()   # linux / darwin
    machine = platform.machine().lower()  # x86_64 / aarch64 / arm64

    if os_name not in ("linux", "darwin"):
        print(f"❌ 不支持的操作系统: {os_name}")
        sys.exit(1)

    if machine in ("x86_64", "amd64"):
        arch = "amd64"
    elif machine in ("aarch64", "arm64"):
        arch = "arm64"
    else:
        print(f"❌ 不支持的架构: {machine}")
        sys.exit(1)

    return os_name, arch


def download_url(os_name, arch):
    """根据平台返回 cloudflared 下载 URL"""
    if os_name == "linux":
        return f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{arch}"
    elif os_name == "darwin":
        # macOS 只提供 amd64 版本（arm64 通过 Rosetta 2 兼容）
        return "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz"


def download_cloudflared():
    """下载 cloudflared 并放到 bin/ 目录"""
    os_name, arch = detect_platform()
    url = download_url(os_name, arch)

    print(f"📥 正在下载 cloudflared ({os_name}/{arch})...")
    print(f"   来源: {url}")

    try:
        if os_name == "darwin":
            # macOS: 下载 tgz 压缩包并解压
            tgz_path = os.path.join(BIN_DIR, "cloudflared.tgz")
            urllib.request.urlretrieve(url, tgz_path)
            with tarfile.open(tgz_path, "r:gz") as tar:
                tar.extractall(path=BIN_DIR)
            os.remove(tgz_path)
        else:
            # Linux: 直接下载二进制
            urllib.request.urlretrieve(url, CLOUDFLARED_PATH)

        # 添加可执行权限
        os.chmod(CLOUDFLARED_PATH, os.stat(CLOUDFLARED_PATH).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        print("✅ cloudflared 下载完成")

    except Exception as e:
        print(f"❌ 下载失败: {e}")
        sys.exit(1)


def ensure_cloudflared():
    """确保 cloudflared 可用"""
    # 优先检查 bin/ 目录
    if os.path.isfile(CLOUDFLARED_PATH) and os.access(CLOUDFLARED_PATH, os.X_OK):
        print(f"✅ 已找到 cloudflared: {CLOUDFLARED_PATH}")
        return CLOUDFLARED_PATH

    # 检查系统 PATH
    system_cf = shutil.which("cloudflared")
    if system_cf:
        print(f"✅ 已找到系统 cloudflared: {system_cf}")
        return system_cf

    # 都没有，自动下载
    print("⚠️  未找到 cloudflared，开始自动下载...")
    download_cloudflared()
    return CLOUDFLARED_PATH


def cleanup(signum=None, frame=None):
    """清理隧道进程"""
    global tunnel_proc
    if tunnel_proc and tunnel_proc.poll() is None:
        print("\n🛑 正在关闭 Cloudflare Tunnel...")
        tunnel_proc.terminate()
        try:
            tunnel_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            tunnel_proc.kill()
        print("✅ 隧道已关闭")
    if signum is not None:
        sys.exit(0)


def start_tunnel():
    """启动 Cloudflare Tunnel 并解析公网地址"""
    global tunnel_proc

    cf_bin = ensure_cloudflared()

    print(f"\n🌐 正在启动 Cloudflare Tunnel (转发 → 127.0.0.1:{PORT_FRONTEND})...")

    # 注册信号处理
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    tunnel_proc = subprocess.Popen(
        [cf_bin, "tunnel", "--url", f"http://127.0.0.1:{PORT_FRONTEND}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    # 解析输出，提取公网地址
    public_url = None
    url_pattern = re.compile(r"(https://[a-zA-Z0-9-]+\.trycloudflare\.com)")

    try:
        for line in tunnel_proc.stdout:
            line = line.strip()
            if not public_url:
                match = url_pattern.search(line)
                if match:
                    public_url = match.group(1)
                    print()
                    print("============================================")
                    print("  🎉 公网部署成功！")
                    print(f"  🌍 公网地址: {public_url}")
                    print("  按 Ctrl+C 关闭隧道")
                    print("============================================")
                    print()

        # stdout 结束意味着进程退出
        tunnel_proc.wait()
        if tunnel_proc.returncode != 0 and not public_url:
            print("❌ Cloudflare Tunnel 启动失败")
            sys.exit(1)

    except KeyboardInterrupt:
        pass
    finally:
        cleanup()


if __name__ == "__main__":
    start_tunnel()
