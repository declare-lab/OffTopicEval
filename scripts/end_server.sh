#!/usr/bin/env bash

# --- 配置 ---
# 用于 pgrep/pkill 查找进程的唯一标识符
# 这必须与 start_server.sh 中的 PROCESS_PATTERN 完全匹配
PROCESS_PATTERN="vllm.entrypoints.openai.api_server"

echo "🛑 正在尝试停止 VLLM 服务..."

# 检查进程是否存在
if pgrep -f "${PROCESS_PATTERN}" > /dev/null; then
    echo "   - 找到了正在运行的 VLLM 进程，正在终止..."
    # 使用 pkill 终止所有匹配的进程
    pkill -f "${PROCESS_PATTERN}"
    
    # 等待一小会儿让进程退出
    sleep 2

    # 再次检查以确保进程已被终止
    if pgrep -f "${PROCESS_PATTERN}" > /dev/null; then
        echo "   - 进程未能正常终止，正在强制终止 (kill -9)..."
        pkill -9 -f "${PROCESS_PATTERN}"
        sleep 1
    fi
    
    echo "✅ VLLM 服务已成功终止。"
else
    echo "ℹ️ VLLM 服务未在运行。"
fi