#!/usr/bin/env bash
# 在已激活的 Conda 环境（如 mcp）中打包单文件可执行程序。
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

CONDA_ENV="${CONDA_ENV:-mcp}"

# 清空构建产物
echo "清理旧构建..."
rm -rf dist build

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

echo ""
echo "完成: dist/"
echo "  可执行文件: dist/local-mcp-proxy"
echo "  启动脚本:   dist/start.sh"
echo "  停止脚本:   dist/stop.sh"
echo "  配置目录:   dist/configs/"
echo ""
echo "运行示例: ./dist/start.sh"
