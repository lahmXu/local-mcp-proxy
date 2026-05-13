#!/bin/bash
# local-mcp-proxy 启动脚本（发布版）

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BINARY="$SCRIPT_DIR/local-mcp-proxy"
LOG_DIR="$SCRIPT_DIR/logs"
LOG_FILE="$LOG_DIR/server.log"

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

# 检查二进制文件
if [ ! -f "$BINARY" ]; then
    echo -e "${RED}找不到可执行文件: $BINARY${NC}"
    exit 1
fi

# 检查是否已在运行
if pgrep -f "local-mcp-proxy" > /dev/null 2>&1; then
    echo -e "${GREEN}检测到已有服务在运行，先执行停止...${NC}"
    bash "$SCRIPT_DIR/stop.sh"
fi

# 确保 logs 目录存在
mkdir -p "$LOG_DIR"

# 解析参数
TRANSPORT="streamable-http"
HOST="127.0.0.1"
PORT=9210
WEB_PORT=9211

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
            echo "用法: ./start.sh [--stdio] [--host HOST] [--port PORT]"
            exit 1
            ;;
    esac
done

# 启动服务
echo "启动 local-mcp-proxy..."
echo "传输方式: $TRANSPORT"

if [ "$TRANSPORT" = "stdio" ]; then
    nohup "$BINARY" --mcp-transport stdio > "$LOG_FILE" 2>&1 &
else
    echo "监听地址: $HOST:$PORT"
    nohup "$BINARY" --mcp-transport streamable-http --mcp-host "$HOST" --mcp-port "$PORT" > "$LOG_FILE" 2>&1 &
fi

PID=$!

# 等待 FastMCP 启动完成（检查日志中的启动标志）
echo "等待服务启动..."
MAX_WAIT=30
WAITED=0

while [ $WAITED -lt $MAX_WAIT ]; do
    # 检查进程是否还在运行
    if ! kill -0 "$PID" 2>/dev/null; then
        echo -e "${RED}服务启动失败，请查看日志:${NC}"
        cat "$LOG_FILE"
        exit 1
    fi

    # 检查日志中是否出现启动完成标志
    if [ -f "$LOG_FILE" ] && grep -q "启动 MCP Proxy" "$LOG_FILE" 2>/dev/null; then
        break
    fi

    sleep 1
    WAITED=$((WAITED + 1))
done

if [ $WAITED -ge $MAX_WAIT ]; then
    echo -e "${RED}服务启动超时（${MAX_WAIT}s），请查看日志:${NC}"
    cat "$LOG_FILE"
    exit 1
fi

echo -e "${GREEN}服务启动成功 (PID: $PID)${NC}"
echo ""
echo "=================================================="
if [ "$TRANSPORT" = "streamable-http" ]; then
    echo "  MCP 地址:   http://$HOST:$PORT/mcp"
else
    echo "  传输模式:   stdio"
fi
echo "  配置页面:   http://127.0.0.1:$WEB_PORT"
echo "  配置文件:   $SCRIPT_DIR/configs/"
echo "  日志文件:   $LOG_FILE"
echo "=================================================="
echo ""
