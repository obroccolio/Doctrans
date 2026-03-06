#!/bin/bash

# Doctrans 一键启动脚本

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

echo "========================================"
echo "  Doctrans - 文档翻译工具 (PPT & PDF)"
echo "========================================"

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "错误: 未找到 python3，请先安装 Python 3.9+"
    exit 1
fi

# 创建虚拟环境
if [ ! -d "$VENV_DIR" ]; then
    echo "正在创建虚拟环境..."
    python3 -m venv "$VENV_DIR"
fi

# 激活虚拟环境
source "$VENV_DIR/bin/activate"

# 安装依赖
echo "正在检查依赖..."
pip install -q -r "$SCRIPT_DIR/requirements.txt"

# 启动 Web 服务
echo ""
echo "启动 Web 服务..."
echo "访问地址: http://localhost:8020"
echo "按 Ctrl+C 停止服务"
echo ""

cd "$SCRIPT_DIR"
python -m uvicorn src.web:app --host 0.0.0.0 --port 8020
