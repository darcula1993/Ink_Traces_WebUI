#!/bin/bash

# Nanobanana 项目启动脚本
# 该脚本用于一键启动前端和后端服务

set -e  # 遇到错误立即退出

# 颜色定义
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# 项目根目录
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLIENT_DIR="$PROJECT_ROOT/client"
SERVER_DIR="$PROJECT_ROOT/server"
CONFIG_FILE="$PROJECT_ROOT/config.json"

echo -e "${CYAN}================================${NC}"
echo -e "${CYAN}   Nanobanana 项目启动器${NC}"
echo -e "${CYAN}================================${NC}\n"

# 检查 Node.js
if ! command -v node &> /dev/null; then
    echo -e "${RED}错误: 未安装 Node.js${NC}"
    echo "请访问 https://nodejs.org/ 安装 Node.js"
    exit 1
fi

# 检查 Python
if ! command -v python3 &> /dev/null && ! command -v python &> /dev/null; then
    echo -e "${RED}错误: 未安装 Python${NC}"
    echo "请访问 https://www.python.org/ 安装 Python 3"
    exit 1
fi

# 确定 Python 命令
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
else
    PYTHON_CMD="python"
fi

# 读取配置文件端口
if [ -f "$CONFIG_FILE" ]; then
    SERVER_PORT=$($PYTHON_CMD -c 'import json,sys; print(json.load(open(sys.argv[1])).get("server", {}).get("port", 5000))' "$CONFIG_FILE")
    CLIENT_PORT=$($PYTHON_CMD -c 'import json,sys; print(json.load(open(sys.argv[1])).get("client", {}).get("port", 4545))' "$CONFIG_FILE")
    CLIENT_HOST=$($PYTHON_CMD -c 'import json,sys; print(json.load(open(sys.argv[1])).get("client", {}).get("host", "0.0.0.0"))' "$CONFIG_FILE")
    SERVER_HOST=$($PYTHON_CMD -c 'import json,sys; print(json.load(open(sys.argv[1])).get("server", {}).get("host", "0.0.0.0"))' "$CONFIG_FILE")
    REQUEST_TIMEOUT=$($PYTHON_CMD -c 'import json,sys; print(json.load(open(sys.argv[1])).get("server", {}).get("request_timeout_seconds", 120))' "$CONFIG_FILE")
    GUNICORN_MAX_REQUESTS=$($PYTHON_CMD -c 'import json,sys; print(json.load(open(sys.argv[1])).get("server", {}).get("gunicorn_max_requests", 1500))' "$CONFIG_FILE")
    GUNICORN_MAX_REQUESTS_JITTER=$($PYTHON_CMD -c 'import json,sys; print(json.load(open(sys.argv[1])).get("server", {}).get("gunicorn_max_requests_jitter", 150))' "$CONFIG_FILE")
else
    echo -e "${YELLOW}Warning: config.json not found, using default ports${NC}"
    SERVER_PORT=5000
    CLIENT_PORT=4545
    CLIENT_HOST=0.0.0.0
    SERVER_HOST=0.0.0.0
    REQUEST_TIMEOUT=120
    GUNICORN_MAX_REQUESTS=1500
    GUNICORN_MAX_REQUESTS_JITTER=150
fi

# production: Gunicorn 同时提供构建后的 SPA；dev: 保留 Vite 热更新。
FRONTEND_MODE="${NANOBANANA_FRONTEND_MODE:-production}"
if [ "$FRONTEND_MODE" != "production" ] && [ "$FRONTEND_MODE" != "dev" ]; then
    echo -e "${RED}错误: NANOBANANA_FRONTEND_MODE 只能是 production 或 dev${NC}"
    exit 1
fi

# 检查依赖是否安装
echo -e "${YELLOW}[1/5] 检查依赖...${NC}"

# 检查前端依赖
if [ ! -d "$CLIENT_DIR/node_modules" ]; then
    echo -e "${YELLOW}前端依赖未安装，正在安装...${NC}"
    cd "$CLIENT_DIR"
    npm install
    echo -e "${GREEN}✓ 前端依赖安装完成${NC}"
else
    echo -e "${GREEN}✓ 前端依赖已安装${NC}"
fi

# 检查后端依赖
if ! $PYTHON_CMD -c "import flask, requests, PIL, gunicorn" &> /dev/null; then
    echo -e "${YELLOW}后端依赖未安装，正在安装...${NC}"
    cd "$SERVER_DIR"
    if [ -f "requirements.txt" ]; then
        $PYTHON_CMD -m pip install -r requirements.txt
    else
        $PYTHON_CMD -m pip install flask flask-cors gunicorn requests pillow
    fi
    echo -e "${GREEN}✓ 后端依赖安装完成${NC}"
else
    echo -e "${GREEN}✓ 后端依赖已安装${NC}"
fi

if [ "$FRONTEND_MODE" = "production" ]; then
    echo -e "${YELLOW}构建生产前端...${NC}"
    cd "$CLIENT_DIR"
    npm run build
    echo -e "${GREEN}✓ 生产前端构建完成${NC}"
fi

# 清理旧进程
echo -e "\n${YELLOW}[2/5] 清理旧进程...${NC}"

# 查找并终止占用后端端口的进程
if lsof -Pi :$SERVER_PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo -e "${YELLOW}发现占用 $SERVER_PORT 端口的进程，正在终止...${NC}"
    lsof -ti:$SERVER_PORT | xargs kill -9 2>/dev/null || true
    sleep 1
    echo -e "${GREEN}✓ 已终止占用 $SERVER_PORT 端口的进程${NC}"
else
    echo -e "${GREEN}✓ $SERVER_PORT 端口空闲${NC}"
fi

# 查找并终止占用前端端口的进程
if lsof -Pi :$CLIENT_PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo -e "${YELLOW}发现占用 $CLIENT_PORT 端口的进程，正在终止...${NC}"
    lsof -ti:$CLIENT_PORT | xargs kill -9 2>/dev/null || true
    sleep 1
    echo -e "${GREEN}✓ 已终止占用 $CLIENT_PORT 端口的进程${NC}"
else
    echo -e "${GREEN}✓ $CLIENT_PORT 端口空闲${NC}"
fi

# 清理旧 worker
if [ -f "$PROJECT_ROOT/.worker.pid" ]; then
    OLD_WORKER_PID=$(cat "$PROJECT_ROOT/.worker.pid")
    if ps -p "$OLD_WORKER_PID" > /dev/null 2>&1; then
        kill "$OLD_WORKER_PID" 2>/dev/null || true
        sleep 1
    fi
    rm -f "$PROJECT_ROOT/.worker.pid"
fi

# 启动任务 worker
echo -e "\n${YELLOW}[3/5] 启动任务 worker...${NC}"
cd "$SERVER_DIR"
setsid $PYTHON_CMD worker.py > "$PROJECT_ROOT/worker.log" 2>&1 < /dev/null &
WORKER_PID=$!
echo -e "${GREEN}✓ 任务 worker 已启动 (PID: $WORKER_PID)${NC}"

# 启动后端服务
echo -e "\n${YELLOW}[4/5] 启动后端服务...${NC}"
GUNICORN_TIMEOUT=$((REQUEST_TIMEOUT + 30))
GUNICORN_BINDS=(--bind "$SERVER_HOST:$SERVER_PORT")
if [ "$FRONTEND_MODE" = "production" ]; then
    GUNICORN_BINDS+=(--bind "$CLIENT_HOST:$CLIENT_PORT")
fi
setsid $PYTHON_CMD -m gunicorn "${GUNICORN_BINDS[@]}" --workers 1 --threads 8 --timeout "$GUNICORN_TIMEOUT" --max-requests "$GUNICORN_MAX_REQUESTS" --max-requests-jitter "$GUNICORN_MAX_REQUESTS_JITTER" --access-logfile /dev/null --error-logfile - app:app > "$PROJECT_ROOT/server.log" 2>&1 < /dev/null &
SERVER_PID=$!
echo -e "${GREEN}✓ 后端服务已启动 (PID: $SERVER_PID)${NC}"
echo -e "${CYAN}  后端地址: http://0.0.0.0:$SERVER_PORT${NC}"
echo -e "${CYAN}  日志文件: $PROJECT_ROOT/server.log${NC}"

# 等待后端启动
echo -e "${YELLOW}等待后端服务启动...${NC}"
for i in {1..10}; do
    if curl -s http://localhost:$SERVER_PORT/api/health > /dev/null 2>&1; then
        echo -e "${GREEN}✓ 后端服务已就绪${NC}"
        break
    fi
    if [ $i -eq 10 ]; then
        echo -e "${RED}警告: 后端服务启动超时，但将继续启动前端${NC}"
    fi
    sleep 1
done

# 启动前端服务
echo -e "\n${YELLOW}[5/5] 启动前端服务...${NC}"
CLIENT_PID=""
if [ "$FRONTEND_MODE" = "dev" ]; then
    cd "$CLIENT_DIR"
    setsid npm run dev > "$PROJECT_ROOT/client.log" 2>&1 < /dev/null &
    CLIENT_PID=$!
    echo -e "${GREEN}✓ Vite 开发服务已启动 (PID: $CLIENT_PID)${NC}"
else
    rm -f "$PROJECT_ROOT/.client.pid" "$PROJECT_ROOT/client.log"
    echo -e "${GREEN}✓ 生产前端由 Gunicorn 静态提供${NC}"
fi
echo -e "${CYAN}  前端地址: http://0.0.0.0:$CLIENT_PORT${NC}"

# 保存 PID 到文件
echo "$SERVER_PID" > "$PROJECT_ROOT/.server.pid"
if [ -n "$CLIENT_PID" ]; then
    echo "$CLIENT_PID" > "$PROJECT_ROOT/.client.pid"
fi
echo "$WORKER_PID" > "$PROJECT_ROOT/.worker.pid"

# 等待前端启动
echo -e "${YELLOW}等待前端服务启动...${NC}"
for i in {1..10}; do
    if curl -s "http://localhost:$CLIENT_PORT/" > /dev/null 2>&1; then
        echo -e "${GREEN}✓ 前端服务已就绪${NC}"
        break
    fi
    if [ $i -eq 10 ]; then
        echo -e "${RED}警告: 前端服务启动超时${NC}"
    fi
    sleep 1
done

# 显示启动信息
echo -e "\n${GREEN}================================${NC}"
echo -e "${GREEN}   启动完成！${NC}"
echo -e "${GREEN}================================${NC}\n"

echo -e "${CYAN}服务信息:${NC}"
echo -e "  后端 API: ${GREEN}http://localhost:$SERVER_PORT${NC}"
echo -e "  前端界面: ${GREEN}http://localhost:$CLIENT_PORT${NC}"
echo -e "\n${CYAN}进程信息:${NC}"
echo -e "  后端 PID: ${GREEN}$SERVER_PID${NC}"
echo -e "  Worker PID: ${GREEN}$WORKER_PID${NC}"
if [ -n "$CLIENT_PID" ]; then
    echo -e "  前端 PID: ${GREEN}$CLIENT_PID${NC}"
else
    echo -e "  前端进程: ${GREEN}复用 Gunicorn $SERVER_PID${NC}"
fi
echo -e "\n${CYAN}日志文件:${NC}"
echo -e "  后端日志: ${YELLOW}$PROJECT_ROOT/server.log${NC}"
echo -e "  Worker 日志: ${YELLOW}$PROJECT_ROOT/worker.log${NC}"
if [ -n "$CLIENT_PID" ]; then
    echo -e "  前端日志: ${YELLOW}$PROJECT_ROOT/client.log${NC}"
fi
echo -e "\n${CYAN}停止服务:${NC}"
echo -e "  运行: ${YELLOW}./stop.sh${NC}"
echo -e "  或手动: ${YELLOW}kill $SERVER_PID $WORKER_PID${CLIENT_PID:+ $CLIENT_PID}${NC}"
echo -e "\n${CYAN}查看日志:${NC}"
echo -e "  后端: ${YELLOW}tail -f server.log${NC}"
echo -e "  Worker: ${YELLOW}tail -f worker.log${NC}"
echo -e "  前端: ${YELLOW}tail -f client.log${NC}"

echo -e "\n${GREEN}提示: 在浏览器中访问 http://localhost:$CLIENT_PORT 使用应用${NC}\n"
