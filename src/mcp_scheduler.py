from mcp.server.fastmcp import FastMCP
import httpx
import os
from dotenv import load_dotenv

# 初始化 MCP 服务
mcp = FastMCP("TimeMaster")

# 加载 .env 配置
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
load_dotenv(dotenv_path=os.path.join(root_dir, "config", ".env"))

PORT_SCHEDULER = int(os.getenv("PORT_SCHEDULER", "51201"))
SCHEDULER_URL = f"http://127.0.0.1:{PORT_SCHEDULER}/tasks"

@mcp.tool()
async def add_alarm(user_id: str, cron: str, text: str) -> str:
    """
    为用户设置一个定时任务（闹钟）。
    :param user_id: 用户唯一标识符
    :param cron: Cron 表达式 (分 时 日 月 周)，例如 "0 1 * * *" 代表凌晨1点
    :param text: 到点时需要执行的指令内容
    """
    async with httpx.AsyncClient() as client:
        try:
            payload = {"user_id": user_id, "cron": cron, "text": text}
            resp = await client.post(SCHEDULER_URL, json=payload, timeout=10.0)
            if resp.status_code == 200:
                data = resp.json()
                return f"✅ 闹钟设置成功！任务 ID: {data['task_id']}，下次运行时间: {data.get('next_run')}"
            return f"❌ 设置失败，服务器返回: {resp.text}"
        except Exception as e:
            return f"⚠️ 无法连接到定时服务器: {str(e)}"

@mcp.tool()
async def list_alarms() -> str:
    """获取当前所有已设置的定时任务列表。"""
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(SCHEDULER_URL)
            tasks = resp.json()
            if not tasks:
                return "📭 当前没有设定任何闹钟。"
            
            res = "📅 当前定时任务列表:\n"
            for t in tasks:
                res += f"- [ID: {t['task_id']}] 规则: {t['cron']}, 内容: {t['text']}\n"
            return res
        except Exception as e:
            return f"⚠️ 读取列表失败: {str(e)}"

@mcp.tool()
async def delete_alarm(task_id: str) -> str:
    """
    根据任务 ID 删除指定的定时任务。
    :param task_id: 之前创建任务时分配的 8 位 ID
    """
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.delete(f"{SCHEDULER_URL}/{task_id}")
            if resp.status_code == 200:
                return f"🗑️ 任务 {task_id} 已成功删除。"
            return f"❌ 删除失败: {resp.text}"
        except Exception as e:
            return f"⚠️ 连接失败: {str(e)}"

if __name__ == "__main__":
    mcp.run()