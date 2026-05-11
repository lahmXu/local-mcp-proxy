#!/bin/bash

# FastMCP MySQL Server 启动脚本

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/server.log"

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

# 检查是否已在运行，如果是则先停止
if ps aux | grep -q "[p]ython3.*main.py"; then
    echo -e "${GREEN}检测到已有服务在运行，先执行停止...${NC}"
    bash "$SCRIPT_DIR/stop.sh"
fi

# 确保 logs 目录存在
mkdir -p "$LOG_DIR"

# 解析参数
TRANSPORT="streamable-http"
HOST="127.0.0.1"
PORT=9210

while [[ $# -gt 0 ]]; do
    case $1 in
        --stdio)
            TRANSPORT="stdio"
            shift
            ;;
        --host)
            HOST="$2"
            shift 2
            ;;
        --port)
            PORT="$2"
            shift 2
            ;;
        *)
            echo "未知参数: $1"
            echo "用法: ./scripts/start.sh [--stdio] [--host HOST] [--port PORT]"
            exit 1
            ;;
    esac
done

# 启动服务
echo "启动 FastMCP MySQL Server..."
echo "传输方式: $TRANSPORT"

# 激活 conda 环境并运行 Python
eval "$(conda shell.bash hook)"
conda activate mcp

if [ "$TRANSPORT" = "stdio" ]; then
    nohup python3 "$PROJECT_DIR/main.py" --mcp-transport stdio > "$LOG_FILE" 2>&1 &
else
    echo "监听地址: $HOST:$PORT"
    nohup python3 "$PROJECT_DIR/main.py" --mcp-transport streamable-http --mcp-host "$HOST" --mcp-port "$PORT" > "$LOG_FILE" 2>&1 &
fi

PID=$!

# 等待一下检查是否启动成功
sleep 1
if kill -0 "$PID" 2>/dev/null; then
    echo -e "${GREEN}服务启动成功 (PID: $PID)${NC}"
    echo ""
    echo "=================================================="
    if [ "$TRANSPORT" = "streamable-http" ]; then
        echo "  MCP 地址:   http://$HOST:$PORT/mcp"
    else
        echo "  传输模式:   stdio"
    fi
    echo "  配置页面:   http://127.0.0.1:9211"
    echo "  配置文件:   $PROJECT_DIR/configs/mcp_configs.json"
    echo "  日志文件:   $LOG_FILE"
    echo "=================================================="
    echo ""
else
    echo -e "${RED}服务启动失败，请查看日志:${NC}"
    cat "$LOG_FILE"
    exit 1
fi
