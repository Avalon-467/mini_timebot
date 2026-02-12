#!/bin/bash
# Mini TimeBot 一键运行（环境配置 + API Key + 注册用户 + 启动服务）

# 锁定绝对路径：确保无论在哪启动，都能找到项目根目录
export PROJECT_ROOT="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
cd "$PROJECT_ROOT"

echo "========== 1/4 环境检查与配置 =========="
bash scripts/setup_env.sh
if [ $? -ne 0 ]; then
    echo "❌ 环境配置失败，请检查错误信息"
    exit 1
fi

echo ""
echo "========== 2/4 API Key 配置 =========="
# 建议加上判断，防止配置失败后继续运行
bash scripts/setup_apikey.sh
if [ $? -ne 0 ]; then
    echo "⚠️  API Key 配置未完成（可能已跳过或出错）"
fi

echo ""
echo "========== 3/4 用户管理 =========="
read -p "是否需要添加新用户？(y/N): " answer
if [[ "$answer" =~ ^[Yy]$ ]]; then
    bash scripts/adduser.sh
fi

echo ""
echo "========== 4/4 启动服务 =========="
# 使用 exec 可以在启动服务时接管进程，释放当前 shell
# 或者保持 bash 运行以便观察日志
bash scripts/start.sh