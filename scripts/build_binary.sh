#!/usr/bin/env bash
# 在已激活的 Conda 环境（如 mcp）中打包单文件可执行程序。
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

CONDA_ENV="${CONDA_ENV:-mcp}"

echo "使用 Conda 环境: $CONDA_ENV"
conda run -n "$CONDA_ENV" --no-capture-output pip install -q pyinstaller
conda run -n "$CONDA_ENV" --no-capture-output pip install -q -r requirements.txt
conda run -n "$CONDA_ENV" --no-capture-output pyinstaller --clean -y mcp_proxy.spec

echo "完成: dist/mcp-proxy"
echo "运行示例: ./dist/mcp-proxy --web-host 127.0.0.1 --web-port 8765"
