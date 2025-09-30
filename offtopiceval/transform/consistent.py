import json
import os
from openai import OpenAI
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from tqdm import tqdm
import random

# ========== 配置 ==========
DATA_DIR = "data_en"
OUTPUT_FILE_ALL = "question_alignment.json"
OUTPUT_FILE_MISMATCH = "mismatch.json"
OUTPUT_FILE_STATS = "file_stats.json"
MODEL_NAME = "mistralai/Mistral-Small-3.2-24B-Instruct-2506"   
API_KEY = "YOUR_API_KEY"              
BASE_URL = "http://localhost:8000/v1" 
MAX_WORKERS = 1024                       

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

def ask_model(origin, question):
    prompt = f"""
You are a strict evaluator.
Compare the following two questions:

[Origin]
{origin}

[Transformed]
{question}

Are they essentially asking the same core question (ignoring rephrasing, role-play, and formatting)?
Answer only in JSON:
{{
  "same_question": true/false,
  "reason": "short explanation"
}}
"""
    # prompt = "hello"
    resp = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.6
    )
    raw_text = resp.choices[0].message.content.strip()
    if raw_text.startswith("```"):
            raw_text = raw_text.strip("`")  # 去掉所有反引号
            if raw_text.lower().startswith("json"):
                raw_text = raw_text[4:].strip()  # 去掉开头的 "json"

    try:
        return json.loads(raw_text)
    except Exception as e:
        return {"same_question": False, "reason": f"Parse error: {e}", "raw": raw_text}


def process_item(path, index, origin, question):
    eval_result = ask_model(origin, question)
    record = {
        "file": path,
        "index": index,
        "origin_question": origin,
        "question": question,
        "same_question": eval_result.get("same_question", False),
        "reason": eval_result.get("reason", "")
    }
    return record


results = []
mismatches = []

tasks = []
with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
    for path in os.listdir(DATA_DIR):

        if not path.endswith(".json"):
            continue

        json_path = os.path.join(DATA_DIR, path)
        with open(json_path, "r", encoding="utf-8") as f:
            dataset = json.load(f)


        for i, item in enumerate(dataset, 1):
            origin = item["origin_question"]
            question = item["question"]

            tasks.append(executor.submit(process_item, path, i, origin, question))


    for future in tqdm(as_completed(tasks), total=len(tasks), desc="Evaluating"):
        record = future.result()
        results.append(record)
        if not record["same_question"]:
            mismatches.append(record)


with open(OUTPUT_FILE_ALL, "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)


with open(OUTPUT_FILE_MISMATCH, "w", encoding="utf-8") as f:
    json.dump(mismatches, f, indent=2, ensure_ascii=False)


file_stats = defaultdict(lambda: {"total": 0, "same": 0, "ratio": 0.0})
for r in results:
    f = r["file"]
    file_stats[f]["total"] += 1
    if r["same_question"]:
        file_stats[f]["same"] += 1

for f, stats in file_stats.items():
    stats["ratio"] = stats["same"] / stats["total"] if stats["total"] > 0 else 0

with open(OUTPUT_FILE_STATS, "w", encoding="utf-8") as f:
    json.dump(file_stats, f, indent=2, ensure_ascii=False)

print(f"\n全部结果已保存到 {OUTPUT_FILE_ALL}，共 {len(results)} 条。")
print(f"不一致的结果已保存到 {OUTPUT_FILE_MISMATCH}，共 {len(mismatches)} 条。")
print(f"文件级别统计已保存到 {OUTPUT_FILE_STATS}，共 {len(file_stats)} 个文件。")
