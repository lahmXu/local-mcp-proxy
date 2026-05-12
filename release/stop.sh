#!/bin/bash
# local-mcp-proxy 停止脚本（发布版）

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

PIDS=$(pgrep -f "local-mcp-proxy" 2>/dev/null || true)

if [ -z "$PIDS" ]; then
    echo -e "${RED}服务未运行${NC}"
    exit 0
fi

echo "找到运行中的 local-mcp-proxy 进程: $PIDS"

for pid in $PIDS; do
    echo "停止进程 (PID: $pid)..."
    kill "$pid" 2>/dev/null
done

sleep 1

# 检查残留
REMAINING=$(pgrep -f "local-mcp-proxy" 2>/dev/null || true)
if [ -n "$REMAINING" ]; then
    echo "强制终止残留进程..."
    for pid in $REMAINING; do
        kill -9 "$pid" 2>/dev/null
    done
fi

echo -e "${GREEN}服务已停止${NC}"
