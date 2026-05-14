#!/bin/bash
# 运行 Crew Demo

cd "$(dirname "$0")"

# 如果没有 venv，创建并安装依赖
if [ ! -d "../venv" ]; then
    python -m venv ../venv
    ../venv/bin/pip install flask --quiet
fi

../venv/bin/python src/app.py