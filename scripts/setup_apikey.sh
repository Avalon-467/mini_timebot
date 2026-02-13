#!/bin/bash
# DeepSeek API Key 配置脚本

cd "$(dirname "$0")/.."

ENV_FILE="config/.env"
EXAMPLE_FILE="config/.env.example"

# 已有 .env 且 Key 已配置，询问是否重置
if [ -f "$ENV_FILE" ]; then
    KEY=$(grep '^DEEPSEEK_API_KEY=' "$ENV_FILE" | cut -d'=' -f2-)
    if [ -n "$KEY" ] && [ "$KEY" != "your_api_key_here" ]; then
        echo "✅ API Key 已配置（${KEY:0:8}...${KEY: -4}）"
        read -p "是否重新配置？(y/N): " reset
        if [[ ! "$reset" =~ ^[Yy]$ ]]; then
            echo "   保持现有配置"
            return 0 2>/dev/null || exit 0
        fi
    fi
fi

echo "================================================"
echo "  需要配置 DeepSeek API Key 才能使用"
echo "  获取地址: https://platform.deepseek.com/api_keys"
echo "================================================"
echo ""

read -p "请输入你的 DeepSeek API Key: " api_key

if [ -z "$api_key" ]; then
    echo "❌ 未输入 API Key，跳过配置"
    echo "   请稍后手动编辑 config/.env"
    return 1 2>/dev/null || exit 1
fi

# 如果已有 .env，只替换/追加 Key 相关行，保留其余配置（端口等）
if [ -f "$ENV_FILE" ]; then
    # 更新 DEEPSEEK_API_KEY
    if grep -q '^DEEPSEEK_API_KEY=' "$ENV_FILE"; then
        sed -i'' -e "s|^DEEPSEEK_API_KEY=.*|DEEPSEEK_API_KEY=$api_key|" "$ENV_FILE"
    else
        echo "DEEPSEEK_API_KEY=$api_key" >> "$ENV_FILE"
    fi
    # 确保 API_BASE 存在
    if ! grep -q '^DEEPSEEK_API_BASE=' "$ENV_FILE"; then
        echo "DEEPSEEK_API_BASE=https://api.deepseek.com" >> "$ENV_FILE"
    fi
else
    # 首次创建：从模板复制再写入
    if [ -f "$EXAMPLE_FILE" ]; then
        cp "$EXAMPLE_FILE" "$ENV_FILE"
        sed -i'' -e "s|^DEEPSEEK_API_KEY=.*|DEEPSEEK_API_KEY=$api_key|" "$ENV_FILE"
    else
        cat > "$ENV_FILE" << EOF
DEEPSEEK_API_KEY=$api_key
DEEPSEEK_API_BASE=https://api.deepseek.com
EOF
    fi
fi

echo "✅ API Key 已保存到 config/.env"
