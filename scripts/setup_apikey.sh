#!/bin/bash
# LLM API Key 配置脚本（支持 DeepSeek / OpenAI / Gemini 等 OpenAI 兼容接口）

cd "$(dirname "$0")/.."

ENV_FILE="config/.env"
EXAMPLE_FILE="config/.env.example"

# 已有 .env 且 Key 已配置，询问是否重置
if [ -f "$ENV_FILE" ]; then
    KEY=$(grep '^LLM_API_KEY=' "$ENV_FILE" | cut -d'=' -f2-)
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
echo "  需要配置 LLM API Key 才能使用"
echo "  支持 DeepSeek / OpenAI / Gemini 等"
echo "================================================"
echo ""

read -p "请输入你的 API Key: " api_key

if [ -z "$api_key" ]; then
    echo "❌ 未输入 API Key，跳过配置"
    echo "   请稍后手动编辑 config/.env"
    return 1 2>/dev/null || exit 1
fi

read -p "请输入 API Base URL（回车默认 https://api.deepseek.com/v1）: " base_url
base_url=${base_url:-https://api.deepseek.com/v1}

read -p "请输入模型名称（回车默认 deepseek-chat）: " model_name
model_name=${model_name:-deepseek-chat}

# 如果已有 .env，只替换/追加 Key 相关行，保留其余配置（端口等）
if [ -f "$ENV_FILE" ]; then
    # 更新 LLM_API_KEY
    if grep -q '^LLM_API_KEY=' "$ENV_FILE"; then
        sed -i'' -e "s|^LLM_API_KEY=.*|LLM_API_KEY=$api_key|" "$ENV_FILE"
    else
        echo "LLM_API_KEY=$api_key" >> "$ENV_FILE"
    fi
    # 更新 LLM_BASE_URL
    if grep -q '^LLM_BASE_URL=' "$ENV_FILE"; then
        sed -i'' -e "s|^LLM_BASE_URL=.*|LLM_BASE_URL=$base_url|" "$ENV_FILE"
    else
        echo "LLM_BASE_URL=$base_url" >> "$ENV_FILE"
    fi
    # 更新 LLM_MODEL
    if grep -q '^LLM_MODEL=' "$ENV_FILE"; then
        sed -i'' -e "s|^LLM_MODEL=.*|LLM_MODEL=$model_name|" "$ENV_FILE"
    else
        echo "LLM_MODEL=$model_name" >> "$ENV_FILE"
    fi
else
    # 首次创建：从模板复制再写入
    if [ -f "$EXAMPLE_FILE" ]; then
        cp "$EXAMPLE_FILE" "$ENV_FILE"
        sed -i'' -e "s|^LLM_API_KEY=.*|LLM_API_KEY=$api_key|" "$ENV_FILE"
        sed -i'' -e "s|^LLM_BASE_URL=.*|LLM_BASE_URL=$base_url|" "$ENV_FILE"
        sed -i'' -e "s|^LLM_MODEL=.*|LLM_MODEL=$model_name|" "$ENV_FILE"
    else
        cat > "$ENV_FILE" << EOF
LLM_API_KEY=$api_key
LLM_BASE_URL=$base_url
LLM_MODEL=$model_name
EOF
    fi
fi

echo "✅ API Key 已保存到 config/.env"
