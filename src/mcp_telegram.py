#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MCP Telegram Push Notification Service
- Agent 可通过此工具向用户的 Telegram 发送消息
- 用户的 chat_id 存储在 data/user_files/<username>/tg_chat_id.txt
- 使用 .env 中的 TELEGRAM_BOT_TOKEN 发送
"""

import os
import httpx
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

mcp = FastMCP("TelegramPush")

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
load_dotenv(dotenv_path=os.path.join(root_dir, "config", ".env"))

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
USER_DATA_DIR = os.path.join(root_dir, "data", "user_files")


def _chat_id_path(username: str) -> str:
    return os.path.join(USER_DATA_DIR, username, "tg_chat_id.txt")


def _read_chat_id(username: str) -> str | None:
    path = _chat_id_path(username)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            val = f.read().strip()
            return val if val else None
    return None


@mcp.tool()
async def set_telegram_chat_id(username: str, chat_id: str) -> str:
    """
    Save the user's Telegram chat_id for push notifications.
    The user can get their chat_id by sending /start to the bot or using @userinfobot.
    :param username: User identifier (auto-injected by system, do NOT provide)
    :param chat_id: The Telegram chat ID (numeric string, e.g. "123456789")
    """
    if not chat_id or not chat_id.strip():
        return "❌ chat_id 不能为空。"
    chat_id = chat_id.strip()

    user_dir = os.path.join(USER_DATA_DIR, username)
    os.makedirs(user_dir, exist_ok=True)

    with open(_chat_id_path(username), "w", encoding="utf-8") as f:
        f.write(chat_id)

    return f"✅ Telegram chat_id 已保存：{chat_id}，后续可通过 Telegram 接收通知。"


@mcp.tool()
async def send_telegram_message(
    username: str, text: str, source_session: str = "", parse_mode: str = "Markdown"
) -> str:
    """
    Send a text message to the user via Telegram Bot.
    Use this to proactively notify the user about task results, reminders, or important updates.
    The message will automatically include a tag showing which session it originates from.
    :param username: User identifier (auto-injected by system, do NOT provide)
    :param text: Message content to send. Supports Markdown formatting.
    :param source_session: (auto-injected) The session that triggers this notification. Do NOT set manually.
    :param parse_mode: Text formatting mode: "Markdown", "HTML", or "" for plain text. Default: "Markdown"
    """
    if not TELEGRAM_BOT_TOKEN:
        return "❌ 未配置 TELEGRAM_BOT_TOKEN，无法发送 Telegram 消息。请在 .env 中设置。"

    chat_id = _read_chat_id(username)
    if not chat_id:
        return (
            "❌ 尚未配置 Telegram chat_id，无法发送消息。\n"
            "请让用户提供 Telegram chat_id（可通过 @userinfobot 获取）。"
        )

    # 自动在消息前标注来源 session
    if source_session and source_session != "tg":
        tag = f"[来自会话: {source_session}]\n"
        text = tag + text

    payload = {
        "chat_id": chat_id,
        "text": text,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{TELEGRAM_API}/sendMessage",
                json=payload,
                timeout=15.0,
            )
            data = resp.json()
            if data.get("ok"):
                return f"✅ Telegram 消息已发送！"
            else:
                desc = data.get("description", "未知错误")
                # Markdown 解析失败时自动降级为纯文本重试
                if "parse" in desc.lower() and parse_mode:
                    payload["parse_mode"] = ""
                    retry_resp = await client.post(
                        f"{TELEGRAM_API}/sendMessage",
                        json=payload,
                        timeout=15.0,
                    )
                    retry_data = retry_resp.json()
                    if retry_data.get("ok"):
                        return f"✅ Telegram 消息已发送（降级为纯文本格式）。"
                return f"❌ Telegram 发送失败: {desc}"
        except httpx.ConnectError:
            return "❌ 无法连接 Telegram API，请检查网络。"
        except Exception as e:
            return f"⚠️ Telegram 发送异常: {str(e)}"


@mcp.tool()
async def get_telegram_status(username: str) -> str:
    """
    Check if Telegram push notification is configured for the user.
    :param username: User identifier (auto-injected by system, do NOT provide)
    """
    chat_id = _read_chat_id(username)
    lines = ["📱 Telegram 推送配置状态："]

    if chat_id:
        lines.append(f"  ✅ Chat ID: {chat_id}")
    else:
        lines.append("  ❌ Chat ID: 未配置")

    if TELEGRAM_BOT_TOKEN:
        masked = TELEGRAM_BOT_TOKEN[:8] + "****" if len(TELEGRAM_BOT_TOKEN) > 8 else "****"
        lines.append(f"  ✅ Bot Token: {masked}")
    else:
        lines.append("  ❌ Bot Token: 未配置（.env 中缺少 TELEGRAM_BOT_TOKEN）")

    if chat_id and TELEGRAM_BOT_TOKEN:
        lines.append("  ✅ 可正常发送 Telegram 通知")
    else:
        lines.append("  ⚠️ 配置不完整，无法发送通知")

    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
