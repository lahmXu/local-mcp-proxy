#!/bin/bash

# FastMCP MySQL 依赖安装脚本

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CONDA_ENV="mcp"

echo "在 conda 环境 '$CONDA_ENV' 中安装依赖..."

# 尝试使用 conda run 安装
conda run -n "$CONDA_ENV" pip install -r "$PROJECT_DIR/requirements.txt"

if [ $? -eq 0 ]; then
    echo "依赖安装成功!"
    echo ""
    echo "接下来请:"
    echo "1. 创建 .env 文件并填写 MySQL 连接信息"
    echo "3. 启动服务: ./scripts/start.sh"
else
    echo "安装失败，请手动在 mcp 环境中安装:"
    echo "  conda activate mcp"
    echo "  pip install -r requirements.txt"
fi
