#!/bin/bash

# FastMCP MySQL Server 停止脚本

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

# 根据进程名查找并停止（只匹配 python3 进程，排除 conda 包装进程）
PIDS=$(ps aux | grep "[p]ython3.*main.py" | awk '{print $2}' || true)

if [ -z "$PIDS" ]; then
    echo -e "${RED}服务未运行${NC}"
    exit 0
fi

echo "找到运行中的 mcp-proxy 进程: $PIDS"

for pid in $PIDS; do
    echo "停止进程 (PID: $pid)..."
    kill "$pid" 2>/dev/null
done

# 等待进程结束
sleep 1

# 检查是否还有残留进程
REMAINING=$(ps aux | grep "[p]ython3.*main.py" | awk '{print $2}' || true)
if [ -n "$REMAINING" ]; then
    echo "强制终止残留进程..."
    for pid in $REMAINING; do
        kill -9 "$pid" 2>/dev/null
    done
fi

echo -e "${GREEN}服务已停止${NC}"
