#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MCP Bark Push Notification Service
- Reads user Bark Key from data/user_files/<username>/bark_key.txt
- Reads public domain from config/.env (BARK_PUBLIC_URL)
- All push requests go to local Bark Server at 127.0.0.1:58010
- The public URL is only embedded in the push payload for click-redirect
"""

import os
import json
import httpx
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

# Initialize MCP service
mcp = FastMCP("BarkPush")

# Load .env config
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
load_dotenv(dotenv_path=os.path.join(root_dir, "config", ".env"))

# Placeholder value written by launcher.py when no public tunnel is configured
PLACEHOLDER = "wait to set"

# Local Bark Server endpoint (never exposed to LLM)
BARK_LOCAL_URL = "http://127.0.0.1:58010"

# User data directory
USER_DATA_DIR = os.path.join(root_dir, "data", "user_files")


def _get_bark_key_path(username: str) -> str:
    """Return the file path where a user's Bark key is stored."""
    return os.path.join(USER_DATA_DIR, username, "bark_key.txt")


def _read_bark_key(username: str) -> str | None:
    """Read the Bark key for a given user, return None if not set."""
    key_path = _get_bark_key_path(username)
    if os.path.exists(key_path):
        with open(key_path, "r", encoding="utf-8") as f:
            key = f.read().strip()
            return key if key else None
    return None


def _get_public_url() -> str | None:
    """Read the frontend public URL from .env for click-through redirect.
    This should be the frontend tunnel URL (PUBLIC_DOMAIN), not the Bark server URL.
    Returns None if not configured or still set to placeholder 'wait to set'.
    """
    # Re-read .env each time to pick up dynamic updates
    load_dotenv(dotenv_path=os.path.join(root_dir, "config", ".env"), override=True)
    value = os.getenv("PUBLIC_DOMAIN", "").strip()
    if not value or value == PLACEHOLDER:
        return None
    return value


@mcp.tool()
async def set_push_key(username: str, bark_key: str) -> str:
    """
    Save the user's Bark device key for push notifications.
    The Bark key can be found in the Bark app on user's iPhone.
    :param username: User identifier (auto-injected by system, do NOT provide)
    :param bark_key: The Bark device key from user's Bark app (a string like "xxxxxxxxxx")
    """
    if not bark_key or not bark_key.strip():
        return "❌ Bark Key 不能为空，请提供有效的 Key。"

    bark_key = bark_key.strip()

    # Ensure user directory exists
    user_dir = os.path.join(USER_DATA_DIR, username)
    os.makedirs(user_dir, exist_ok=True)

    key_path = _get_bark_key_path(username)
    with open(key_path, "w", encoding="utf-8") as f:
        f.write(bark_key)

    return f"✅ Bark Key 已成功保存！后续推送通知将发送到您的设备。"


@mcp.tool()
async def send_push_notification(username: str, title: str, body: str, group: str = "MiniTimeBot") -> str:
    """
    Send a push notification to the user's iPhone via Bark.
    :param username: User identifier (auto-injected by system, do NOT provide)
    :param title: Notification title (e.g. "⏰ 闹钟提醒")
    :param body: Notification body content
    :param group: Notification group name for organizing (default: "MiniTimeBot")
    """
    # 1. Read user's Bark key
    bark_key = _read_bark_key(username)
    if not bark_key:
        return (
            "❌ 尚未配置 Bark Key，无法发送推送。\n"
            "请先告诉我您的 Bark Key（打开 iPhone 上的 Bark App 即可看到）。"
        )

    # 2. Read the public domain for click-through URL
    public_url = _get_public_url()
    click_url = public_url if public_url else None

    # 3. Build the push payload (sent to LOCAL Bark Server only)
    payload = {
        "title": title,
        "body": body,
        "device_key": bark_key,
        "group": group,
        "icon": "https://img.icons8.com/fluency/96/robot-2.png",
        "level": "timeSensitive",
    }

    # If we have a public URL, embed it as the click-through target
    if click_url:
        payload["url"] = click_url

    # 4. Send to local Bark Server
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{BARK_LOCAL_URL}/push",
                json=payload,
                timeout=10.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 200:
                    return f"✅ 推送已发送！标题：{title}"
                else:
                    return f"❌ Bark Server 返回错误: {data.get('message', '未知错误')}"
            else:
                return f"❌ 推送失败，HTTP 状态码: {resp.status_code}"
        except httpx.ConnectError:
            return "❌ 无法连接到 Bark Server（端口 58010），请确认服务已启动。"
        except Exception as e:
            return f"⚠️ 推送异常: {str(e)}"


@mcp.tool()
async def get_push_status(username: str) -> str:
    """
    Check if push notification is configured for the user.
    :param username: User identifier (auto-injected by system, do NOT provide)
    """
    bark_key = _read_bark_key(username)
    public_url = _get_public_url()

    status_lines = ["📱 推送通知配置状态："]

    if bark_key:
        masked_key = bark_key[:4] + "****" + bark_key[-4:] if len(bark_key) > 8 else "****"
        status_lines.append(f"  ✅ Bark Key: {masked_key}")
    else:
        status_lines.append("  ❌ Bark Key: 未配置")

    if public_url:
        status_lines.append(f"  ✅ 公网地址: {public_url}")
    else:
        raw = os.getenv("PUBLIC_DOMAIN", "").strip()
        if raw == PLACEHOLDER:
            status_lines.append("  ⏳ 公网地址: 等待配置（当前为 'wait to set'，请替换为真实地址或运行 tunnel.py）")
        else:
            status_lines.append("  ⚠️ 公网地址: 未配置（推送后点击通知无法跳转到网页）")

    # Check if Bark Server is running
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(f"{BARK_LOCAL_URL}/ping", timeout=3.0)
            if resp.status_code == 200:
                status_lines.append("  ✅ Bark Server: 运行中")
            else:
                status_lines.append("  ⚠️ Bark Server: 响应异常")
        except Exception:
            status_lines.append("  ❌ Bark Server: 未运行")

    return "\n".join(status_lines)


if __name__ == "__main__":
    mcp.run()
