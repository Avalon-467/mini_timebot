import os
import sys
from dotenv import load_dotenv

# Windows 控制台 UTF-8 编码
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# 加载 .env 文件
load_dotenv()

QQ_CONF = {
    "appid": os.getenv("QQ_APP_ID"),
    "secret": os.getenv("QQ_BOT_SECRET"),
}

AI_CONF = {
    "api_key": os.getenv("AI_API_KEY")+":QQ",
    "url": os.getenv("AI_API_URL"),
    "model": os.getenv("AI_MODEL_QQ")
}

# 外部手动开启的 SSH 隧道地址
PROXY_URL = "socks5://127.0.0.1:1080"
# ============================================
import av
import os
import io
import wave
import base64
import httpx
import pilk
import aiohttp
import asyncio
from functools import wraps
from aiohttp_socks import ProxyConnector
from pydub import AudioSegment
# --- 1. 深度拦截：强制 botpy 内部请求走外部隧道 (解决白名单401) ---
_original_init = aiohttp.ClientSession.__init__
@wraps(_original_init)
def _patched_init(self, *args, **kwargs):
    kwargs["connector"] = ProxyConnector.from_url(PROXY_URL)
    _original_init(self, *args, **kwargs)
aiohttp.ClientSession.__init__ = _patched_init

import botpy
from botpy.message import C2CMessage, GroupMessage

class MyClient(botpy.Client):
    async def process_media_to_b64(self, url: str, is_silk: bool = False):
        """
        核心附件处理：直连下载 + 双缓冲区转码
        """
        try:
            # 1. 下载阶段：必须直连腾讯服务器，避免代理 403
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.get(url)
                if res.status_code != 200:
                    print(f"❌ 附件下载失败: {res.status_code}")
                    return None
                raw_data = res.content

            # 如果是图片，直接转 Base64
            if not is_silk:
                return base64.b64encode(raw_data).decode('utf-8')

            # 2. 语音转码阶段：针对要求双 File-like 对象的 pysilk 版本
            # 定位真实 Silk 头部
            silk_index = raw_data.find(b"#!SILK")
            if silk_index == -1:
                print("❌ 未找到 SILK 头部，跳过处理")
                return None
            silk_data = raw_data[silk_index:]

            # 创建输入和输出缓冲区
            input_file = io.BytesIO(silk_data)
            output_pcm = io.BytesIO()

            # 核心调用：decode(输入文件对象, 输出文件对象, 采样率)
            # 采样率 24000 是 QQ 语音的标准
            pilk.decode(input_file, output_pcm, 24000)
            
            # 从输出流获取原始 PCM 数据
            pcm_data = output_pcm.getvalue()
            if not pcm_data:
                print("❌ 解码出的 PCM 数据为空")
                return None

            # 3. 封装阶段：将 PCM 包装为 WAV 给 AI 识别
            with io.BytesIO() as wav_buffer:
                with wave.open(wav_buffer, 'wb') as wav_file:
                    wav_file.setnchannels(1)   # 单声道
                    wav_file.setsampwidth(2)   # 16-bit
                    wav_file.setframerate(24000)
                    wav_file.writeframes(pcm_data)
                wav_bytes = wav_buffer.getvalue()

            # 返回纯净 Base64，移除换行符
            return base64.b64encode(wav_bytes).decode('utf-8').replace("\n", "").replace("\r", "")

        except Exception as e:
            print(f"❌ 媒体处理异常: {e}")
            return None
    async def call_llm(self, content_list):
        """发送多模态数据至 AI (OpenAI 兼容格式)"""
        # 再次确保 content_list 中不含有空的 data 字段
        filtered_content = [
            item for item in content_list 
            if not (isinstance(item.get("input_audio"), dict) and not item["input_audio"].get("data"))
        ]

        async with httpx.AsyncClient(proxy=None, timeout=60.0) as client:
            try:
                response = await client.post(
                    AI_CONF["url"],
                    headers={"Authorization": f"Bearer {AI_CONF['api_key']}"},
                    json={
                        "model": AI_CONF["model"],
                        "messages": [{"role": "user", "content": filtered_content}]
                    }
                )
                res_data = response.json()
                if "choices" in res_data:
                    return res_data["choices"][0]["message"]["content"]
                return f"❌ AI 接口返回异常: {res_data.get('error', {}).get('message', '未知错误')}"
            except Exception as e:
                return f"❌ 网络请求失败: {str(e)}"

    async def handle_main_logic(self, message):
        """统一处理私聊与群聊逻辑"""
        # 1. 清洗文本（去除机器人艾特）
        raw_text = message.content.strip()
        user_text = raw_text.replace(f"<@!{QQ_CONF['appid']}>", "").strip()
        
        # 2. 构建多模态列表
        content_list = [{"type": "text", "text": user_text or "请分析内容"}]
        
        # 3. 处理附件 (图片/语音)
        if hasattr(message, 'attachments') and message.attachments:
                # 针对你 log 中 attachments 是列表对象的情况
                for attach in message.attachments:
                    # 1. 判定类型：Log 显示语音是 'voice'，文件后缀可能是 .amr
                    is_silk = attach.content_type == "voice" or attach.filename.endswith(".silk") or attach.filename.endswith(".amr")
                    
                    # 2. 统一转码（只调用一次）
                    b64 = await self.process_media_to_b64(attach.url, is_silk=is_silk)
                    
                    if not b64:
                        continue

                    if is_silk:
                        # --- 这里必须对齐你的后端逻辑 ---
                        content_list.append({
                            "type": "input_audio", 
                            "input_audio": {
                                "data": b64,      # 对齐后端 audio.get("base64")
                                "format": "wav"     # 配合 pysilk 建议用 wav，后端更稳
                            }
                        })
                    else:
                        # 图片逻辑
                        content_list.append({
                            "type": "image_url", 
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
                        })
            
        # 兜底：如果 content_list 为空（纯语音且没文字），加一个 text part 
        # 因为 Gemini 接口通常要求 content 列表里至少有一个 text 类型的元素
        if not any(item['type'] == 'text' for item in content_list):
            content_list.insert(0, {"type": "text", "text": "请分析这段内容"})

        # 4. 回复用户
        reply = await self.call_llm(content_list)
        await message.reply(content=reply)

    # --- 触发器配置 ---
    async def on_c2c_message_create(self, message: C2CMessage):
        print(f"📩 收到私聊: {message.author.user_openid}")
        await self.handle_main_logic(message)

    async def on_group_at_message_create(self, message: GroupMessage):
        print(f"👥 收到群聊 @ 消息")
        await self.handle_main_logic(message)

if __name__ == "__main__":
    # 使用位运算开启 C2C (1<<30) 和 频道 (1<<25) 权限
    intents = botpy.Intents.none()
    intents.value = (1 << 25) | (1 << 30) 
    
    client = MyClient(intents=intents)
    print(f"🚀 机器人已启动！请确保外部 SSH 隧道 (1080) 正在运行...")
    client.run(appid=QQ_CONF["appid"], secret=QQ_CONF["secret"])