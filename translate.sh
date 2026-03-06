#!/bin/bash

# Doctrans CLI 翻译脚本

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

# 检查虚拟环境
if [ ! -d "$VENV_DIR" ]; then
    echo "首次运行，正在初始化..."
    python3 -m venv "$VENV_DIR"
    source "$VENV_DIR/bin/activate"
    pip install -q -r "$SCRIPT_DIR/requirements.txt"
else
    source "$VENV_DIR/bin/activate"
fi

cd "$SCRIPT_DIR"
python -m src.main "$@"
