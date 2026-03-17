#!/bin/bash

# Nanobanana 项目停止脚本

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$PROJECT_ROOT/config.json"

if [ -f "$CONFIG_FILE" ]; then
    SERVER_PORT=$(grep -o '"port"[[:space:]]*:[[:space:]]*[0-9]*' "$CONFIG_FILE" | head -1 | grep -o '[0-9]*')
    CLIENT_PORT=$(grep -o '"port"[[:space:]]*:[[:space:]]*[0-9]*' "$CONFIG_FILE" | tail -1 | grep -o '[0-9]*')
else
    SERVER_PORT=5000
    CLIENT_PORT=4545
fi

echo -e "${CYAN}================================${NC}"
echo -e "${CYAN}   Nanobanana 项目停止器${NC}"
echo -e "${CYAN}================================${NC}\n"

kill_tree() {
    local pid=$1
    # 先杀所有子进程
    local children=$(pgrep -P "$pid" 2>/dev/null)
    for child in $children; do
        kill_tree "$child"
    done
    kill -9 "$pid" 2>/dev/null
}

kill_by_pid_file() {
    local pid_file=$1
    local label=$2
    if [ -f "$pid_file" ]; then
        local pid=$(cat "$pid_file")
        if ps -p "$pid" > /dev/null 2>&1; then
            echo -e "${YELLOW}正在停止${label} (PID: $pid)...${NC}"
            kill_tree "$pid"
            echo -e "${GREEN}✓ ${label}已停止${NC}"
        else
            echo -e "${YELLOW}${label}未运行 (PID: $pid 不存在)${NC}"
        fi
        rm -f "$pid_file"
    fi
}

kill_by_port() {
    local port=$1
    local label=$2
    local pids=$(lsof -ti:"$port" 2>/dev/null)
    if [ -n "$pids" ]; then
        echo -e "${YELLOW}发现占用 $port 端口的进程，正在停止...${NC}"
        echo "$pids" | xargs kill -9 2>/dev/null
        echo -e "${GREEN}✓ ${label}已停止${NC}"
    fi
}

# 停止后端
kill_by_pid_file "$PROJECT_ROOT/.server.pid" "后端服务"
kill_by_port "$SERVER_PORT" "后端服务"

# 停止前端
kill_by_pid_file "$PROJECT_ROOT/.client.pid" "前端服务"
kill_by_port "$CLIENT_PORT" "前端服务"

# 清理残留进程
echo -e "\n${YELLOW}检查残留进程...${NC}"
for pattern in "python.*app.py" "flask" "vite.*--port.*$CLIENT_PORT" "node.*vite" "npm.*run.*dev"; do
    pids=$(pgrep -f "$pattern" 2>/dev/null)
    if [ -n "$pids" ]; then
        echo -e "${YELLOW}清理匹配 [$pattern] 的进程...${NC}"
        echo "$pids" | xargs kill -9 2>/dev/null
    fi
done

# 最终确认端口已释放
sleep 0.5
CLEAN=true
for port in $SERVER_PORT $CLIENT_PORT; do
    if lsof -ti:"$port" >/dev/null 2>&1; then
        echo -e "${RED}⚠ 端口 $port 仍被占用，强制清理...${NC}"
        lsof -ti:"$port" | xargs kill -9 2>/dev/null
        CLEAN=false
    fi
done

# 清理 PID 文件
rm -f "$PROJECT_ROOT/.server.pid" "$PROJECT_ROOT/.client.pid"

echo -e "\n${GREEN}================================${NC}"
echo -e "${GREEN}   停止完成！端口已释放${NC}"
echo -e "${GREEN}================================${NC}\n"

if [ -f "$PROJECT_ROOT/server.log" ] || [ -f "$PROJECT_ROOT/client.log" ]; then
    echo -e "${CYAN}是否清理日志文件？ [y/N]${NC}"
    read -r -n 1 response
    echo
    if [[ "$response" =~ ^[Yy]$ ]]; then
        rm -f "$PROJECT_ROOT/server.log" "$PROJECT_ROOT/client.log"
        echo -e "${GREEN}✓ 日志文件已清理${NC}\n"
    fi
fi
