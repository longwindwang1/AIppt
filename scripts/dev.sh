#!/usr/bin/env bash
# 本地启动脚本（Linux/macOS）
cd "$(dirname "$0")/.."
export PYTHONPATH="$(pwd)"
exec uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
