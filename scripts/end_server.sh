#!/usr/bin/env bash

# --- Configuration ---
# Main process pattern
PROCESS_PATTERN="vllm.entrypoints.openai.api_server"
# Subprocess pattern (matching VLLM worker processes)
SUBPROCESS_PATTERN="VLLM::Worker_TP"

echo "🛑 Attempting to stop VLLM service..."

# Function: check GPU usage in nvidia-smi for VLLM processes
check_gpu_usage() {
    nvidia-smi --query-compute-apps=pid,process_name --format=csv,noheader,nounits 2>/dev/null | grep -i vllm || echo "No VLLM-related GPU processes"
}

# Initial check
initial_pids_main=$(pgrep -f "${PROCESS_PATTERN}")
initial_pids_sub=$(pgrep -f "${SUBPROCESS_PATTERN}")
initial_gpu=$(check_gpu_usage)
echo "   - Initial main process PID: ${initial_pids_main:-None}"
echo "   - Initial subprocess PID: ${initial_pids_sub:-None}"
echo "   - Initial GPU usage: ${initial_gpu}"

# Terminate main process
if [ -n "$initial_pids_main" ]; then
    echo "   - Found VLLM main process, sending SIGTERM..."
    pkill -f "${PROCESS_PATTERN}"
    sleep 5  # wait for graceful shutdown
    if pgrep -f "${PROCESS_PATTERN}" > /dev/null; then
        echo "   - Main process did not terminate, sending SIGKILL..."
        pkill -9 -f "${PROCESS_PATTERN}"
        sleep 1
    fi
else
    echo "   - No VLLM main process running."
fi

# Terminate subprocess (VLLM::Worker_TP)
if [ -n "$initial_pids_sub" ]; then
    echo "   - Found VLLM subprocess (Worker_TP), sending SIGTERM..."
    pkill -f "${SUBPROCESS_PATTERN}"
    sleep 5  # wait for graceful shutdown
    if pgrep -f "${SUBPROCESS_PATTERN}" > /dev/null; then
        echo "   - Subprocess did not terminate, sending SIGKILL..."
        pkill -9 -f "${SUBPROCESS_PATTERN}"
        sleep 1
    fi
else
    echo "   - No VLLM subprocess running."
fi

# Clean up any remaining VLLM processes (using broader pattern)
all_vllm_pids=$(pgrep -f "vllm" | xargs -r echo)
if [ -n "$all_vllm_pids" ]; then
    echo "   - Found remaining VLLM processes (PID: $all_vllm_pids), sending SIGKILL..."
    pkill -9 -f "vllm"
    sleep 1
fi

# Final verification
final_pids_main=$(pgrep -f "${PROCESS_PATTERN}")
final_pids_sub=$(pgrep -f "${SUBPROCESS_PATTERN}")
final_gpu=$(check_gpu_usage)
echo "   - Final main process PID: ${final_pids_main:-None}"
echo "   - Final subprocess PID: ${final_pids_sub:-None}"
echo "   - Final GPU usage: ${final_gpu}"

if [ -z "$final_pids_main" ] && [ -z "$final_pids_sub" ] && [[ "$final_gpu" == "No VLLM-related GPU processes" ]]; then
    echo "✅ VLLM service and all subprocesses have been successfully terminated, GPU memory released."
else
    echo "⚠️  VLLM service termination incomplete. Some processes or GPU usage may remain. Suggested actions:"
    echo "   - Run 'nvidia-smi' to check for leftover processes."
    echo "   - Try 'sudo nvidia-smi --gpu-reset' to reset the GPU (requires root)."
    echo "   - Restart NVIDIA driver: 'sudo systemctl restart nvidia-persistenced' (if enabled)."
    echo "   - Last resort: reboot the system."
fi
