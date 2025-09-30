#!/usr/bin/env bash
set -e

bash end_server.sh
export CUDA_VISIBLE_DEVICES=4,5,6,7

PROCESS_PATTERN="vllm.entrypoints.openai.api_server"
LOG_DIR="logs"
LOG_FILE="${LOG_DIR}/vllm_server_$(date +'%Y%m%d_%H%M%S').log"

MODEL_NAME=${1:-"sarvamai/sarvam-translate"}

mkdir -p "${LOG_DIR}"

# Check if the process is already running
if pgrep -f "${PROCESS_PATTERN}" > /dev/null; then
    echo "⚠️ VLLM server seems to be already running. Please stop it before starting a new one."
    pgrep -af "${PROCESS_PATTERN}"
    exit 1
fi

echo "🚀 Starting VLLM server..."

nohup python -m vllm.entrypoints.openai.api_server \
  --model "${MODEL_NAME}" \
  --max-model-len 8192 \
  --max-num-seqs 1024 \
  --gpu-memory-utilization 0.95 \
  --max-num-batched-tokens 8192 \
  --enable-chunked-prefill \
  --enable-prefix-caching \
  --disable-log-requests \
  --tensor-parallel-size 4 \
  --port 8001 > "${LOG_FILE}" 2>&1 &

SERVER_PID=$!

echo "⏳ Waiting for server initialization... (PID: ${SERVER_PID})"
sleep 8

if ps -p ${SERVER_PID} > /dev/null; then
    echo "✅ VLLM server successfully started, PID=${SERVER_PID}"
    echo "📜 Log file: ${LOG_FILE}"
    echo "   Use 'tail -f ${LOG_FILE}' to view logs in real time."
else
    echo "❌ Failed to start VLLM server. Please check the log file for errors: ${LOG_FILE}"

    echo "--- Log tail ---"
    tail -n 20 "${LOG_FILE}"
    echo "----------------"
    exit 1
fi
