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

# 读取配置文件端口
if [ -f "$CONFIG_FILE" ]; then
    SERVER_PORT=$(grep -o '"port"[[:space:]]*:[[:space:]]*[0-9]*' "$CONFIG_FILE" | head -1 | grep -o '[0-9]*')
    CLIENT_PORT=$(grep -o '"port"[[:space:]]*:[[:space:]]*[0-9]*' "$CONFIG_FILE" | tail -1 | grep -o '[0-9]*')
else
    echo -e "${YELLOW}Warning: config.json not found, using default ports${NC}"
    SERVER_PORT=5000
    CLIENT_PORT=4545
fi

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

# 检查依赖是否安装
echo -e "${YELLOW}[1/4] 检查依赖...${NC}"

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
if ! $PYTHON_CMD -c "import flask" &> /dev/null; then
    echo -e "${YELLOW}后端依赖未安装，正在安装...${NC}"
    cd "$SERVER_DIR"
    if [ -f "requirements.txt" ]; then
        pip install -r requirements.txt
    else
        pip install flask flask-cors requests pillow
    fi
    echo -e "${GREEN}✓ 后端依赖安装完成${NC}"
else
    echo -e "${GREEN}✓ 后端依赖已安装${NC}"
fi

# 清理旧进程
echo -e "\n${YELLOW}[2/4] 清理旧进程...${NC}"

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

# 启动后端服务
echo -e "\n${YELLOW}[3/4] 启动后端服务...${NC}"
cd "$SERVER_DIR"
nohup $PYTHON_CMD app.py > "$PROJECT_ROOT/server.log" 2>&1 &
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
echo -e "\n${YELLOW}[4/4] 启动前端服务...${NC}"
cd "$CLIENT_DIR"
nohup npm run dev > "$PROJECT_ROOT/client.log" 2>&1 &
CLIENT_PID=$!
echo -e "${GREEN}✓ 前端服务已启动 (PID: $CLIENT_PID)${NC}"
echo -e "${CYAN}  前端地址: http://0.0.0.0:$CLIENT_PORT${NC}"
echo -e "${CYAN}  日志文件: $PROJECT_ROOT/client.log${NC}"

# 保存 PID 到文件
echo "$SERVER_PID" > "$PROJECT_ROOT/.server.pid"
echo "$CLIENT_PID" > "$PROJECT_ROOT/.client.pid"

# 等待前端启动
echo -e "${YELLOW}等待前端服务启动...${NC}"
sleep 5

# 显示启动信息
echo -e "\n${GREEN}================================${NC}"
echo -e "${GREEN}   启动完成！${NC}"
echo -e "${GREEN}================================${NC}\n"

echo -e "${CYAN}服务信息:${NC}"
echo -e "  后端 API: ${GREEN}http://localhost:$SERVER_PORT${NC}"
echo -e "  前端界面: ${GREEN}http://localhost:$CLIENT_PORT${NC}"
echo -e "\n${CYAN}进程信息:${NC}"
echo -e "  后端 PID: ${GREEN}$SERVER_PID${NC}"
echo -e "  前端 PID: ${GREEN}$CLIENT_PID${NC}"
echo -e "\n${CYAN}日志文件:${NC}"
echo -e "  后端日志: ${YELLOW}$PROJECT_ROOT/server.log${NC}"
echo -e "  前端日志: ${YELLOW}$PROJECT_ROOT/client.log${NC}"
echo -e "\n${CYAN}停止服务:${NC}"
echo -e "  运行: ${YELLOW}./stop.sh${NC}"
echo -e "  或手动: ${YELLOW}kill $SERVER_PID $CLIENT_PID${NC}"
echo -e "\n${CYAN}查看日志:${NC}"
echo -e "  后端: ${YELLOW}tail -f server.log${NC}"
echo -e "  前端: ${YELLOW}tail -f client.log${NC}"

echo -e "\n${GREEN}提示: 在浏览器中访问 http://localhost:$CLIENT_PORT 使用应用${NC}\n"
