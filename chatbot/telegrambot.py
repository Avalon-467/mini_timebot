import os
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

# --- 配置区 ---
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
AI_API_KEY = os.getenv("AI_API_KEY")+":TG"
AI_URL = os.getenv("AI_API_URL")
AI_MODEL = os.getenv("AI_MODEL_TG")

import logging
import httpx
import base64
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters


logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

async def download_as_b64(file_id: str, context: ContextTypes.DEFAULT_TYPE) -> str:
    """下载 Telegram 文件并转换为 Base64 字符串"""
    file = await context.bot.get_file(file_id)
    async with httpx.AsyncClient() as client:
        response = await client.get(file.file_path)
        return base64.b64encode(response.content).decode('utf-8')

async def handle_multimodal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    # 获取文字：Telegram 中媒体消息的文字在 caption，纯文字在 text
    user_text = update.message.caption or update.message.text or "请分析此内容"
    
    # 1. 立即显示“正在输入...”
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    # 2. 初始化 OpenAI 格式的 content 列表
    # 所有的多模态内容都必须放在这个 content 列表里
    content_list = [{"type": "text", "text": user_text}]

    try:
        # 3. 处理图片 (OpenAI 格式：image_url)
        if update.message.photo:
            file_id = update.message.photo[-1].file_id  # 获取最高清版本
            b64_image = await download_as_b64(file_id, context)
            content_list.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"}
            })

        # 4. 处理语音 (OpenAI 最新格式：input_audio)
        elif update.message.voice:
            file_id = update.message.voice.file_id
            b64_audio = await download_as_b64(file_id, context)
            content_list.append({
                "type": "input_audio",
                "input_audio": {
                    "data": b64_audio,
                    "format": "wav" # Telegram 语音通常需要模型具备解析能力，Gemini 支持多种格式
                }
            })

        # 5. 调用 AI 接口 (标准 OpenAI POST 结构)
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                AI_URL,
                headers={"Authorization": f"Bearer {AI_API_KEY}"},
                json={
                    "model": AI_MODEL, # 这里确保模型支持多模态
                    "messages": [
                        {"role": "user", "content": content_list}
                    ]
                }
            )
            
            # 检查响应状态
            if response.status_code != 200:
                raise Exception(f"AI 接口报错: {response.text}")
                
            res_json = response.json()
            ai_reply = res_json["choices"][0]["message"]["content"]

    except Exception as e:
        logging.error(f"Error: {e}")
        ai_reply = f"❌ 发生错误: {str(e)}"

    # 6. 回复用户
    await update.message.reply_text(ai_reply)

if __name__ == '__main__':
    # 初始化
    application = ApplicationBuilder().token(TG_TOKEN).build()

    # 注册触发器，捕获文字、图片、语音
    handler = MessageHandler(
        (filters.TEXT | filters.PHOTO | filters.VOICE) & (~filters.COMMAND), 
        handle_multimodal
    )
    application.add_handler(handler)

    print("--- 机器人已启动 (轮询模式) ---")
    print("支持：文字 / 图片 / 语音 (OpenAI 多模态格式)")
    application.run_polling(drop_pending_updates=True)