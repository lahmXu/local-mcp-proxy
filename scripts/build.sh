#!/usr/bin/env bash
# 在已激活的 Conda 环境（如 mcp）中打包单文件可执行程序。
# 用法: sh build.sh [版本号]
# 示例: sh build.sh 0.0.1
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# 解析版本号参数，默认 latest
VERSION="${1:-latest}"

# 获取系统架构
OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH="$(uname -m)"
case "$ARCH" in
    x86_64)  ARCH="amd64" ;;
    aarch64) ARCH="arm64" ;;
esac

# 构建目录名
DIST_NAME="dist-v${VERSION}-${OS}-${ARCH}"

CONDA_ENV="${CONDA_ENV:-mcp}"

# 清空构建产物
echo "清理旧构建..."
rm -rf dist build
if [ -d "$DIST_NAME" ]; then
    echo "删除旧的发布目录: $DIST_NAME"
    rm -rf "$DIST_NAME"
fi

echo "使用 Conda 环境: $CONDA_ENV"
conda run -n "$CONDA_ENV" --no-capture-output pip install -q pyinstaller
conda run -n "$CONDA_ENV" --no-capture-output pip install -q -r requirements.txt
conda run -n "$CONDA_ENV" --no-capture-output pyinstaller --clean -y mcp_proxy.spec

# 复制发布脚本到 dist
echo "复制 release 到 dist/..."
cp release/start.sh release/stop.sh dist/
chmod +x dist/start.sh dist/stop.sh

# 复制初始登录配置到 dist/configs（不覆盖已有配置）
echo "复制初始配置到 dist/configs..."
mkdir -p dist/configs
if [ ! -f dist/configs/proxy_configs.json ]; then
    cp configs/proxy_configs.json dist/configs/proxy_configs.json
fi

# 重命名 dist 目录
echo "重命名 dist -> ${DIST_NAME}"
mv dist "$DIST_NAME"

# 创建 zip 文件并放到目录内
echo "创建 ${DIST_NAME}.zip"
cd "$PROJECT_DIR"
zip -r "${DIST_NAME}/${DIST_NAME}.zip" "$DIST_NAME" -x "${DIST_NAME}/${DIST_NAME}.zip"

echo ""
echo "完成: ${DIST_NAME}/"
echo "  可执行文件: ${DIST_NAME}/local-mcp-proxy"
echo "  启动脚本:   ${DIST_NAME}/start.sh"
echo "  停止脚本:   ${DIST_NAME}/stop.sh"
echo "  配置目录:   ${DIST_NAME}/configs/"
echo "  发布包:     ${DIST_NAME}/${DIST_NAME}.zip"
echo ""
echo "运行示例: ./${DIST_NAME}/start.sh"