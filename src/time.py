# 


import uuid
from typing import List, Optional
from datetime import datetime
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import uvicorn

# --- 数据模型 ---
class CronTask(BaseModel):
    user_id: str
    cron: str  # 格式: "分 时 日 月 周"
    text: str

class TaskResponse(BaseModel):
    task_id: str
    user_id: str
    cron: str
    text: str
    next_run: Optional[str]

# --- 全局调度器 ---
scheduler = AsyncIOScheduler()
AGENT_URL = "http://127.0.0.1:8000/system_trigger"

async def trigger_agent(user_id: str, text: str):
    """到达定时时间，向 Agent 发送 HTTP 请求"""
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(AGENT_URL, json={"user_id": user_id, "text": text}, timeout=10.0)
            print(f"[{datetime.now()}] 任务触发：用户={user_id}, 状态码={resp.status_code}")
        except Exception as e:
            print(f"[{datetime.now()}] 任务触发失败: {e}")

# --- 生命周期 ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("定时调度中心启动...")
    scheduler.start()
    yield
    print("定时调度中心关闭...")
    scheduler.shutdown()

app = FastAPI(title="Xavier Scheduler", lifespan=lifespan)

@app.post("/tasks", response_model=TaskResponse)
async def add_task(task: CronTask):
    task_id = str(uuid.uuid4())[:8]
    try:
        # 拆分 Cron 表达式
        c = task.cron.split()
        scheduler.add_job(
            trigger_agent,
            'cron',
            minute=c[0], hour=c[1], day=c[2], month=c[3], day_of_week=c[4],
            args=[task.user_id, task.text],
            id=task_id
        )
        return {**task.model_dump(), "task_id": task_id, "next_run": "已激活"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cron 格式错误: {e}")

@app.get("/tasks")
async def list_tasks():
    return [
        {
            "task_id": j.id, 
            "user_id": j.args[0], 
            "text": j.args[1], 
            "cron": str(j.trigger),
            "next_run": str(j.next_run_time)
        } for j in scheduler.get_jobs()
    ]

@app.delete("/tasks/{task_id}")
async def delete_task(task_id: str):
    if scheduler.get_job(task_id):
        scheduler.remove_job(task_id)
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="未找到任务")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8001)