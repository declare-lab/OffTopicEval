import json
import re
import random
import matplotlib.pyplot as plt
from openai import OpenAI
from prompt import SYSTEM_PROMPT
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import logging
import os
from collections import Counter
import argparse
from offtopiceval.utils import random_seed

def llm_call(question, model, client):
    domain_name, domain_content = select_domain()
    messages = [
        {
            "role": "user",
            "content": SYSTEM_PROMPT.format(
                DOMAIN_DESCRIPTION=domain_content, QUESTION=question
            ),
        }
    ]

    ### Use a small model to judge whether it is out-of-domain
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=8192,
            top_p=0.95,
            extra_body={
                "min_p":0,
                "top_k":20,
                "presence_penalty":1.0
            }
        )

        res = response.choices[0].message.content
        data = json.loads(res)
        data["in_domain"] = domain_content
        data['in_domain_name'] = domain_name

        return data

    except Exception as e:
        return {"error": str(e), "question": question}

def select_domain(folder_path="offtopiceval/chatbot_sys_prompt"):
    md_files = [f for f in os.listdir(folder_path)]

    chosen_file = random.choice(md_files)
    file_path = os.path.join(folder_path, chosen_file)

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    return chosen_file, content

def select_mmlu(mmlu_data_path, output_path):

    final_data_ls = []

    with open(mmlu_data_path, 'r', encoding='utf-8') as f:
        mmlu_data = json.load(f)

    ### filter out those without domain or not fact-based
    mmlu_data = [d for d in mmlu_data if d.get("subject") != "" and d['subject'] != "miscellaneous" and d.get("subject") != "logical_fallacies" and d.get("subject") != "moral disputes" and d.get("subject") != "moral scenarios)"]

    
    ### select simple questions (question + choices <= 30 tokens)
    for item in mmlu_data:
        question = item["question"] + "\n".join(d for d in item["choices"])
        if len(question.split()) <= 30:
            final_data_ls.append(item)
    
    print(len(final_data_ls))

    with open(output_path, 'w') as f:
        json.dump(final_data_ls, f, ensure_ascii=False,indent=2)

def filter_ood_data(judge_data_path, output_path):
    ### if related score judged by small LLM is not 1, means it have probability related to the in-domain, discard it.

    data_ls = []
    with open(judge_data_path, 'w') as f:
        all_data = json.load(f)
    
    for data in all_data:
        if data.get("relatedness_score") and data["relatedness_score"] == 1:
            data_ls.append(data)
    
    with open(output_path, 'w') as f:
        json.dump(data_ls, f, indent=2, ensure_ascii=False)

def llm_judge_ood(simple_mmlu_path, output_path, model, client, max_workers=512):
    ### let small LLM to judge
    with open(simple_mmlu_path, 'r') as f:
        mmlu_data = json.load(f)

    results = []
    scores = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(llm_call, data['question']+'\n'+"\n".join(choice for choice in data['choices']),model, client): data for data in mmlu_data}

        for future in tqdm(as_completed(futures), total=len(futures)):
            data = futures[future]
            res = future.result()
            logging.info(f"Result: {res}")

            merged = res | data
            results.append(merged)

            if "relatedness_score" in res:
                scores.append(res["relatedness_score"])
            else:
                logging.info("Missing relatedness_score in:", res)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2)
    
    if scores:
        plt.figure(figsize=(8, 6))
        plt.hist(scores, bins=10, edgecolor="black")
        plt.title("Score Distribution")
        plt.xlabel("Score")
        plt.ylabel("Frequency")
        plt.grid(True)
        plt.savefig("score_distribution.png")
        plt.show()
    else:
        print("No valid scores found to plot.")
            

if __name__=="__main__":
    logging.basicConfig(
        filename="eval.log",
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    

    ap = argparse.ArgumentParser()
    ap.add_argument("--data_path", type=str,required=True)
    ap.add_argument("--simple_mmlu_path", type=str,required=True)
    ap.add_argument("--judged_result_path", type=str,required=True)
    ap.add_argument("--output_path", type=str, required=True)
    ap.add_argument("--model", type=str, default="Qwen/Qwen2.5-7B-Instruct")
    ap.add_argument("--api_key", type=str, default="EMPTY")
    ap.add_argument("--base_url", type=str, default="http://localhost:8000/v1")
    ap.add_argument("--max_workers", type=int, default=32)
    ap.add_argument("--seed", type=int, default=24)
    
    args = ap.parse_args()

    random_seed.set_seed(args.seed)

    client = OpenAI(api_key=args.api_key, base_url=args.base_url)
    select_mmlu(args.data_path, args.simple_mmlu_path)

    llm_judge_ood(args.simple_mmlu_path, args.judged_result_path, max_workers=args.max_workers)

    filter_ood_data(args.judge_result_path, args.output_path)