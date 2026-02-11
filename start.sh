#!/bin/bash
# Mini TimeBot 一键启动脚本

cd "$(dirname "$0")"

# 检查 .env 配置
if [ ! -f config/.env ]; then
    echo "❌ 未找到 config/.env 文件，请先创建并填入 DEEPSEEK_API_KEY"
    exit 1
fi

# 激活虚拟环境（如果存在）
if [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
fi

# 清理函数：退出时杀掉所有子进程
cleanup() {
    echo ""
    echo "🛑 正在关闭所有服务..."
    kill $PID_TIME $PID_AGENT $PID_FRONT 2>/dev/null
    wait $PID_TIME $PID_AGENT $PID_FRONT 2>/dev/null
    echo "✅ 所有服务已关闭"
    exit 0
}
trap cleanup SIGINT SIGTERM

echo "🚀 启动 Mini TimeBot..."
echo ""

# 1. 启动定时调度中心 (port 8001)
echo "⏰ [1/3] 启动定时调度中心 (port 8001)..."
python src/time.py &
PID_TIME=$!
sleep 2

# 2. 启动 AI Agent (port 8000)
echo "🤖 [2/3] 启动 AI Agent (port 8000)..."
python src/mainagent.py &
PID_AGENT=$!
sleep 3

# 3. 启动前端 (port 9000)
echo "🌐 [3/3] 启动前端 Web UI (port 9000)..."
python src/front.py &
PID_FRONT=$!
sleep 1

echo ""
echo "============================================"
echo "  ✅ Mini TimeBot 已全部启动！"
echo "  🌐 访问: http://127.0.0.1:9000"
echo "  按 Ctrl+C 停止所有服务"
echo "============================================"
echo ""

# 等待任意子进程退出
wait -n $PID_TIME $PID_AGENT $PID_FRONT 2>/dev/null
echo "⚠️ 有服务异常退出，正在关闭其余服务..."
cleanup
