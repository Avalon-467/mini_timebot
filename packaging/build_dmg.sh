#!/bin/bash
# ==============================================
#  MiniTimeBot macOS DMG 打包脚本
#  用法: bash packaging/build_dmg.sh
# ==============================================

set -e

# ---- 配置 ----
APP_NAME="MiniTimeBot"
VERSION="1.0.0"
DMG_NAME="${APP_NAME}_${VERSION}.dmg"

# 项目根目录
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
BUILD_DIR="${ROOT}/build/dmg"
STAGE_DIR="${BUILD_DIR}/${APP_NAME}"
OUTPUT_DIR="${ROOT}/dist"

echo "============================================"
echo "  ${APP_NAME} macOS DMG 打包工具 v${VERSION}"
echo "============================================"
echo ""

# ---- 1. 检查运行平台 ----
if [[ "$(uname)" != "Darwin" ]]; then
    echo "⚠️  当前系统非 macOS ($(uname))，将生成 tar.gz 替代 DMG"
    echo "   DMG 格式仅支持在 macOS 上构建"
    USE_TAR=true
else
    USE_TAR=false
    # 检查 hdiutil（macOS 自带）
    if ! command -v hdiutil &>/dev/null; then
        echo "❌ 未找到 hdiutil，请确认 macOS 环境"
        exit 1
    fi
fi

# ---- 2. 清理旧构建 ----
echo "🧹 清理旧构建..."
rm -rf "${BUILD_DIR}"
mkdir -p "${STAGE_DIR}"
mkdir -p "${OUTPUT_DIR}"

# ---- 3. 复制项目文件到暂存目录 ----
echo "📦 准备打包文件..."

# 核心脚本
cp "${ROOT}/run.sh" "${STAGE_DIR}/"
chmod +x "${STAGE_DIR}/run.sh"

# scripts 目录（仅 .sh 文件）
mkdir -p "${STAGE_DIR}/scripts"
for f in setup_env.sh start.sh adduser.sh setup_apikey.sh; do
    if [ -f "${ROOT}/scripts/${f}" ]; then
        cp "${ROOT}/scripts/${f}" "${STAGE_DIR}/scripts/"
        chmod +x "${STAGE_DIR}/scripts/${f}"
    fi
done

# 源码
cp -r "${ROOT}/src" "${STAGE_DIR}/src"

# 工具
if [ -d "${ROOT}/tools" ]; then
    cp -r "${ROOT}/tools" "${STAGE_DIR}/tools"
fi

# 配置模板
mkdir -p "${STAGE_DIR}/config"
cp "${ROOT}/config/requirements.txt" "${STAGE_DIR}/config/"
if [ -f "${ROOT}/config/.env.example" ]; then
    cp "${ROOT}/config/.env.example" "${STAGE_DIR}/config/"
fi
if [ -f "${ROOT}/config/users.json.example" ]; then
    cp "${ROOT}/config/users.json.example" "${STAGE_DIR}/config/"
fi

# 数据目录结构（空目录）
mkdir -p "${STAGE_DIR}/data/timeset"
mkdir -p "${STAGE_DIR}/data/user_files"

# 许可证
if [ -f "${ROOT}/LICENSE" ]; then
    cp "${ROOT}/LICENSE" "${STAGE_DIR}/"
fi

# ---- 4. 生成 macOS 快速启动说明 ----
cat > "${STAGE_DIR}/使用说明.txt" << 'GUIDE'
==========================================
  MiniTimeBot macOS 使用说明
==========================================

【首次使用】
  1. 打开「终端」应用
  2. 将本文件夹拖入终端窗口（自动 cd 到目录）
  3. 运行: bash run.sh
  4. 按提示配置 API Key 和用户

【日常启动】
  在终端中运行: bash run.sh

【快捷方式（可选）】
  在终端中执行以下命令，创建命令别名：
  echo 'alias timebot="cd /path/to/MiniTimeBot && bash run.sh"' >> ~/.zshrc
  source ~/.zshrc
  之后直接输入 timebot 即可启动

【访问地址】
  启动后浏览器打开: http://127.0.0.1:9000

【停止服务】
  在终端中按 Ctrl+C

==========================================
GUIDE

# ---- 5. 生成安装包 ----
if [ "$USE_TAR" = true ]; then
    # 非 macOS 环境：生成 tar.gz
    ARCHIVE_NAME="${APP_NAME}_${VERSION}_macos.tar.gz"
    echo "📦 生成 ${ARCHIVE_NAME}..."
    cd "${BUILD_DIR}"
    tar -czf "${OUTPUT_DIR}/${ARCHIVE_NAME}" "${APP_NAME}"
    cd "${ROOT}"

    FINAL_PATH="${OUTPUT_DIR}/${ARCHIVE_NAME}"
    echo ""
    echo "============================================"
    echo "  ✅ 打包完成！"
    echo "  📦 文件: ${FINAL_PATH}"
    echo "  📏 大小: $(du -sh "${FINAL_PATH}" | cut -f1)"
    echo ""
    echo "  ⚠️  这是 tar.gz 格式（非 macOS 环境构建）"
    echo "  在 macOS 上运行此脚本可生成 .dmg 格式"
    echo "============================================"
else
    # macOS 环境：生成 DMG
    DMG_PATH="${OUTPUT_DIR}/${DMG_NAME}"

    # 删除旧 DMG
    rm -f "${DMG_PATH}"

    echo "💿 创建 DMG: ${DMG_NAME}..."

    # 计算所需空间（文件大小 + 10MB 余量）
    SIZE_KB=$(du -sk "${STAGE_DIR}" | cut -f1)
    SIZE_MB=$(( (SIZE_KB / 1024) + 10 ))

    # 创建临时 DMG
    TEMP_DMG="${BUILD_DIR}/temp.dmg"
    hdiutil create \
        -srcfolder "${STAGE_DIR}" \
        -volname "${APP_NAME}" \
        -fs HFS+ \
        -fsargs "-c c=64,a=16,e=16" \
        -format UDRW \
        -size "${SIZE_MB}m" \
        "${TEMP_DMG}"

    # 挂载临时 DMG
    MOUNT_DIR=$(hdiutil attach -readwrite -noverify -noautoopen "${TEMP_DMG}" | \
        grep "/Volumes/" | sed 's/.*\/Volumes/\/Volumes/')

    # 设置 DMG 窗口样式（AppleScript）
    echo "🎨 设置 DMG 窗口样式..."
    osascript << EOF
tell application "Finder"
    tell disk "${APP_NAME}"
        open
        set current view of container window to icon view
        set toolbar visible of container window to false
        set statusbar visible of container window to false
        set the bounds of container window to {200, 120, 760, 500}
        set viewOptions to the icon view options of container window
        set arrangement of viewOptions to not arranged
        set icon size of viewOptions to 80
        close
    end tell
end tell
EOF

    # 卸载
    hdiutil detach "${MOUNT_DIR}" -quiet

    # 压缩为最终 DMG
    hdiutil convert "${TEMP_DMG}" \
        -format UDZO \
        -imagekey zlib-level=9 \
        -o "${DMG_PATH}"

    # 清理临时文件
    rm -f "${TEMP_DMG}"

    echo ""
    echo "============================================"
    echo "  ✅ DMG 打包完成！"
    echo "  💿 文件: ${DMG_PATH}"
    echo "  📏 大小: $(du -sh "${DMG_PATH}" | cut -f1)"
    echo ""
    echo "  用户使用方式："
    echo "  1. 双击 .dmg 挂载"
    echo "  2. 将 ${APP_NAME} 文件夹拖到任意位置"
    echo "  3. 打开终端，cd 到文件夹，运行 bash run.sh"
    echo "============================================"
fi

# ---- 6. 清理暂存目录 ----
echo ""
echo "🧹 清理暂存文件..."
rm -rf "${BUILD_DIR}"
echo "✅ 完成"
