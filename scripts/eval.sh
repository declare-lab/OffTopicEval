#!/bin/bash
set -e

cd OffTopicEval/offtopiceval/eval

MODEL_LIST=(
    "RedHatAI/Llama-3.3-70B-Instruct-FP8-dynamic"
    "google/gemma-3-27b-it"
    "mistralai/Mistral-Small-3.2-24B-Instruct-2506"
    "microsoft/phi-4"
    "Qwen/Qwen3-30B-A3B-Instruct-2507"
)
LANGS=("zh" "hi")

wait_until_ready() {
    local url=$1
    local retries=1000
    local wait_time=5

    for ((i=1; i<=retries; i++)); do
        if curl --silent --fail "$url" > /dev/null; then
            echo "[✓] Model is ready at $url"
            return 0
        fi
        echo "[$i/$retries] Waiting for model to be ready at $url..."
        sleep $wait_time
    done
    echo "[✗] Timeout: Model did not become ready after $((retries * wait_time)) seconds."
    exit 1
}

run_eval() {
    local lang=$1
    local model_name=$2

    for fname in /home/ubuntu/leijingdi/safetybench/transform/data_${lang}/*; do
        python eval_solution.py \
            --model $model_name \
            --questions $fname \
            --domain_dir "/home/ubuntu/leijingdi/safetybench/select_ood/new_prompts" \
            --output_dir "/home/ubuntu/leijingdi/offtopicbench_results/results_solution_${lang}" \
            --max_workers 1024 \
            --prompt_level 8 \
            --lang $lang \
    done
}

run_eval_id() {
    local lang=$1
    local model_name=$2


    OUTPUT_DIR="/home/ubuntu/leijingdi/offtopicbench_results/results_solution_${lang}/ID"
    python eval_id.py \
        --model $model_name \
        --questions "/home/ubuntu/leijingdi/safetybench/multilingual_data/in_domain_${lang}.json" \
        --domain_dir "/home/ubuntu/leijingdi/safetybench/select_ood/new_prompts" \
        --output_dir $OUTPUT_DIR \
        --max_workers 1024 \
        --prompt_level 8 \
        --lang $lang \
}



for MODEL_NAME in "${MODEL_LIST[@]}"; do
    bash start_server.sh "$MODEL_NAME"
    wait_until_ready "http://localhost:8000/health"
    for LANG in "${LANGS[@]}"; do

        run_eval "$LANG" "$MODEL_NAME" 
        run_eval_id "$LANG" "$MODEL_NAME" 

    done
    bash end_server.sh
    sleep 10
done
