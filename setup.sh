#!/bin/bash

# Ink Traces WebUI — 一键初始化脚本

set -e

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLIENT_DIR="$PROJECT_ROOT/client"
SERVER_DIR="$PROJECT_ROOT/server"

echo -e "${CYAN}================================${NC}"
echo -e "${CYAN}  Ink Traces WebUI Setup${NC}"
echo -e "${CYAN}================================${NC}\n"

# 1. 检查环境
echo -e "${YELLOW}[1/6] 检查环境...${NC}"

MISSING=0

if command -v python3 &> /dev/null; then
    PY_VER=$(python3 --version 2>&1)
    echo -e "${GREEN}  ✓ $PY_VER${NC}"
    PYTHON_CMD="python3"
    PIP_CMD="pip3"
elif command -v python &> /dev/null; then
    PY_VER=$(python --version 2>&1)
    echo -e "${GREEN}  ✓ $PY_VER${NC}"
    PYTHON_CMD="python"
    PIP_CMD="pip"
else
    echo -e "${RED}  ✗ Python 未安装${NC}"
    echo -e "    macOS: brew install python"
    echo -e "    Linux: sudo apt install python3 python3-pip"
    MISSING=1
fi

if command -v node &> /dev/null; then
    NODE_VER=$(node --version 2>&1)
    echo -e "${GREEN}  ✓ Node.js $NODE_VER${NC}"
else
    echo -e "${RED}  ✗ Node.js 未安装${NC}"
    echo -e "    macOS: brew install node"
    echo -e "    Linux: curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash - && sudo apt install nodejs"
    MISSING=1
fi

if command -v npm &> /dev/null; then
    NPM_VER=$(npm --version 2>&1)
    echo -e "${GREEN}  ✓ npm $NPM_VER${NC}"
else
    echo -e "${RED}  ✗ npm 未安装${NC}"
    MISSING=1
fi

if [ $MISSING -eq 1 ]; then
    echo -e "\n${RED}请先安装缺失的依赖后重新运行此脚本${NC}"
    exit 1
fi

# 2. 初始化 config.json
echo -e "\n${YELLOW}[2/6] 初始化配置文件...${NC}"

if [ -f "$PROJECT_ROOT/config.json" ]; then
    echo -e "${GREEN}  ✓ config.json 已存在${NC}"
    if ! $PYTHON_CMD "$SERVER_DIR/config_v2.py" check "$PROJECT_ROOT/config.json"; then
        echo -e "${RED}  ✗ config.json 不是有效的 v2 配置；旧格式请先停服务并运行 scripts/migrate-config-v2.py（默认试运行）${NC}"
        exit 1
    fi
else
    if [ ! -f "$PROJECT_ROOT/config.json.example" ]; then
        echo -e "${RED}  ✗ 缺少 config.json.example，无法初始化配置${NC}"
        exit 1
    fi
    (umask 077 && cp "$PROJECT_ROOT/config.json.example" "$PROJECT_ROOT/config.json")
    chmod 600 "$PROJECT_ROOT/config.json"
    echo -e "${GREEN}  ✓ 已从 config.json.example 创建 config.json（v2，权限 600）${NC}"
    echo -e "${YELLOW}  → 请编辑 config.json：providers.byteplus / providers.cupsy 填写账号，providers.byteplus.endpoint_ids.seedance_2_5 填写接入点ID（替换 ep-your-endpoint-id）${NC}"
fi

# 初始化 Prompt Vault 示例数据
if [ -f "$SERVER_DIR/prompts.json" ]; then
    echo -e "${GREEN}  ✓ server/prompts.json 已存在${NC}"
elif [ -f "$SERVER_DIR/prompts.json.example" ]; then
    cp "$SERVER_DIR/prompts.json.example" "$SERVER_DIR/prompts.json"
    echo -e "${GREEN}  ✓ 已从 server/prompts.json.example 创建 server/prompts.json${NC}"
fi

# 3. 安装后端依赖
echo -e "\n${YELLOW}[3/6] 安装后端依赖...${NC}"
cd "$SERVER_DIR"
$PIP_CMD install -r requirements.txt -q 2>&1 | tail -1
echo -e "${GREEN}  ✓ 后端依赖安装完成${NC}"

# 4. 安装前端依赖
echo -e "\n${YELLOW}[4/6] 安装前端依赖...${NC}"
cd "$CLIENT_DIR"
npm install --silent 2>&1 | tail -1
echo -e "${GREEN}  ✓ 前端依赖安装完成${NC}"

# 5. 设置脚本权限
echo -e "\n${YELLOW}[5/6] 设置权限...${NC}"
chmod +x "$PROJECT_ROOT/start.sh" "$PROJECT_ROOT/stop.sh" "$PROJECT_ROOT/deploy/configure-public-source.sh" "$PROJECT_ROOT/deploy/certbot/reload-nginx.sh"
echo -e "${GREEN}  ✓ 脚本权限已设置${NC}"

# 6. 根据已有配置部署 Cupsy 公网入口；空配置会安全跳过。
echo -e "\n${YELLOW}[6/6] 配置 Cupsy 公网入口...${NC}"
AUTO_CONFIGURE_PUBLIC_SOURCE=$($PYTHON_CMD "$SERVER_DIR/config_v2.py" get deployment.cupsy_source.auto_configure "$PROJECT_ROOT/config.json")
CUPSY_SOURCE_URL=$($PYTHON_CMD "$SERVER_DIR/config_v2.py" get deployment.cupsy_source.base_url "$PROJECT_ROOT/config.json")
if [ -n "$CUPSY_SOURCE_URL" ] && [ "$AUTO_CONFIGURE_PUBLIC_SOURCE" = "true" ]; then
    "$PROJECT_ROOT/deploy/configure-public-source.sh"
elif [ -z "$CUPSY_SOURCE_URL" ]; then
    echo -e "${GREEN}  ✓ deployment.cupsy_source.base_url 为空，已跳过${NC}"
else
    echo -e "${YELLOW}  ⚠ deployment.cupsy_source.auto_configure 已关闭${NC}"
fi

# 完成
echo -e "\n${GREEN}================================${NC}"
echo -e "${GREEN}  初始化完成！${NC}"
echo -e "${GREEN}================================${NC}"
echo -e "\n${CYAN}下一步:${NC}"
echo -e "  1. 编辑 ${YELLOW}config.json${NC} 填入 API Key"
echo -e "  2. 运行 ${YELLOW}./start.sh${NC} 启动服务"
echo -e "  3. 打开 ${YELLOW}http://localhost:4545${NC}"
echo -e ""
