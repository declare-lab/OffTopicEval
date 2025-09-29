#!/usr/bin/env bash
set -e

# 尝试停止任何已在运行的服务
# 确保 end_server.sh 能正确地 kill 掉 python 进程
bash end_server.sh
export CUDA_VISIBLE_DEVICES=4,5,6,7
# --- 配置 ---
# 用于 pgrep 查找进程的唯一标识符
PROCESS_PATTERN="vllm.entrypoints.openai.api_server"
LOG_DIR="logs"
LOG_FILE="${LOG_DIR}/vllm_server_$(date +'%Y%m%d_%H%M%S').log"

# 从命令行参数获取模型名称
MODEL_NAME=${1:-"meta-llama/Llama-3.3-70B-Instruct"}

# --- 脚本开始 ---
mkdir -p "${LOG_DIR}"

# 检查进程是否已在运行
if pgrep -f "${PROCESS_PATTERN}" > /dev/null; then
    echo "⚠️ VLLM 服务似乎已在运行，请先停止再启动。"
    pgrep -af "${PROCESS_PATTERN}"
    exit 1
fi


echo "🚀 正在启动 VLLM 服务..."
# 1️⃣ 在后台直接启动 VLLM 服务
# 将标准输出和标准错误都重定向到日志文件
nohup python -m vllm.entrypoints.openai.api_server \
  --model "${MODEL_NAME}" \
  --max-model-len 16384 \
  --max-num-seqs 1024 \
  --gpu-memory-utilization 0.8 \
  --max-num-batched-tokens 8192 \
  --enable-chunked-prefill \
  --enable-prefix-caching \
  --disable-log-requests \
  --tensor-parallel-size 4 \
  --port 8000 > "${LOG_FILE}" 2>&1 &

# 获取后台进程的 PID
SERVER_PID=$!

# 短暂等待，让进程有机会启动或失败
echo "⏳ 等待服务初始化... (PID: ${SERVER_PID})"
sleep 8

# 2️⃣ 检查进程是否仍在运行
if ps -p ${SERVER_PID} > /dev/null; then
    echo "✅ VLLM 服务已成功启动，PID=${SERVER_PID}"
    echo "📜 日志文件位于: ${LOG_FILE}"
    echo "   使用 'tail -f ${LOG_FILE}' 查看实时日志。"
else
    echo "❌ VLLM 服务启动失败。请检查日志文件获取错误信息: ${LOG_FILE}"
    # 打印日志文件的最后几行以帮助调试
    echo "--- 日志尾部 ---"
    tail -n 20 "${LOG_FILE}"
    echo "----------------"
    exit 1
fi