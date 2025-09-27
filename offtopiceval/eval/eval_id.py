import argparse
import json
import logging
import os
import random
import regex as re
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue
from threading import Event, Thread
import string
import numpy as np
import torch
from openai import OpenAI
from tqdm import tqdm
from utils.writer import DeamonWriter
from utils.random_seed import set_seed
from instruct import P_INSTRUCT, Q_INSTRUCT, BASE_INSTRUCT
from utils.extract_system_prompt import extract_part_system_prompt
from utils.is_refusal import is_refusal


# Precompiled regex (logic unchanged)
_REFUSAL_BRACES_RE = re.compile(r"\{\s*([^{}]+?)\s*\}")
_THINK_CLOSE_RE = re.compile(r"</think\s*>", flags=re.IGNORECASE)
_FIRST_JSON_LIKE_RE = re.compile(r"[\{\[]")




def create_client(api_key, base_url):
    return OpenAI(api_key=api_key, base_url=base_url)


def _pre_clean_output(text):
    if not text:
        return ""
    matches = list(_THINK_CLOSE_RE.finditer(text))
    if matches:
        text = text[matches[-1].end() :]
    m = _FIRST_JSON_LIKE_RE.search(text)
    if m:
        text = text[m.start() :]
    return text.strip()


def llm_call(messages, model, client):
    if "Qwen3" in model:
        extra_body = {"top_k":20, "chat_template_kwargs": {"enable_thinking": False}}
    else:
        extra_body = {"top_k":20}
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=8192,
        temperature=0.6,
        top_p=0.95,
        extra_body=extra_body
    )
    return _pre_clean_output(response.choices[0].message.content)


def worker(data, **kwargs):
    choices_with_labels = [f"{label}. {choice}" for label, choice in zip(string.ascii_uppercase, data['choices'])]
    question = data['question'] + '\n' + '\n'.join(choices_with_labels)

    # question = data["question"]
    domain = kwargs["domain"]
    domain_name = kwargs["domain_name"]
    client = kwargs["client"]
    model = kwargs["model"]

    base_instruction = BASE_INSTRUCT

    system_prompt = domain
    user_prompt = f"{question} \n\n {base_instruction}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    res = llm_call(messages, model, client)
    eval_result = is_refusal(res)


    item =  {
        "in_domain": domain_name,
        "question": question,
        "response": res,
        "eval_result": eval_result,
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
    }

    if eval_result == "NA":
        model_name = model.split("/")[-1]
        base_dir = f"/offtopiceval/ID/results_{kwargs['lang']}/{model_name}/NA"
        os.makedirs(base_dir, exist_ok=True)

        file_path = os.path.join(base_dir, f"{domain_name}_NA.jsonl")
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")



    return item

def list_domains(folder_path):
    md_files = sorted(f for f in os.listdir(folder_path) if f.endswith(".md"))
    results = []
    for fname in md_files:
        with open(os.path.join(folder_path, fname), "r", encoding="utf-8") as f:
            results.append((fname.replace(".md",""), f.read().strip()))
    return results


def cal_metric(total_success):
    filtered = [x for x in total_success if x in [True, False]]
    return (sum(filtered) / len(filtered)) if filtered else 0.0



def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", type=str, required=True)
    ap.add_argument("--output_dir", type=str, required=True)
    ap.add_argument("--domain_dir", type=str, required=True)
    ap.add_argument("--prompt_level", type=int, default=4)
    ap.add_argument(
        "--model", type=str, default="RedHatAI/Llama-3.3-70B-Instruct-FP8-dynamic"
    )
    ap.add_argument("--api_key", type=str, default="EMPTY")
    ap.add_argument("--lang", type=str, default="en")
    ap.add_argument("--base_url", type=str, default="http://localhost:8000/v1")
    ap.add_argument("--seed", type=int, default=24)
    ap.add_argument("--max_workers", type=int, default=128)
    args = ap.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    client = create_client(api_key=args.api_key, base_url=args.base_url)
    set_seed(args.seed)

    # Load questions
    with open(args.questions, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    for (domain_name, domain_content) in list_domains(args.domain_dir):
        domain_content = extract_part_system_prompt(domain_content, level=args.prompt_level)
        os.makedirs(f"{args.output_dir}/{args.model.split('/')[-1]}", exist_ok=True)

        output_path = os.path.join(args.output_dir, args.model.split("/")[-1], f"{domain_name}.jsonl")
        print(f"Output Path: {output_path}")
        mode = "a" if os.path.exists(output_path) else "w"
        writer = DeamonWriter(output_path, mode=mode)

        kwargs = {
            "client": client,
            "model": args.model,
            "domain_name": domain_name,
            "domain": domain_content,
        }

        result_ls = []
        with ThreadPoolExecutor(max_workers=args.max_workers) as executor:

            all_data = [d for d in dataset if d.get("in_domain_name") == domain_name]
            futures = [executor.submit(worker, data, **kwargs) for data in all_data]
            for future in tqdm(
                as_completed(futures),
                total=len(futures),
                leave=False,
                desc=domain_name,
            ):
                try:
                    r = future.result()
                    if r:
                        result_ls.append(r)
                        writer.put(r)

                except Exception as e:
                    logging.warning(
                        f"[{domain_name}] Worker failed with exception: {e}"
                    )

        # Compute metrics at the end
        writer.graceful_terminate()

        refusal_rate = cal_metric([item["eval_result"] for item in result_ls])
        print(
            f"[{domain_name}] Saved: {output_path} | Refusal Rate: {refusal_rate:.4f}"
        )

        with open(
            os.path.join(args.output_dir, args.model.split("/")[-1], "summary.txt"), "a", encoding="utf-8"
        ) as f:
            f.write(
                f"{domain_name}\t{refusal_rate:.4f}\n"
            )

if __name__ == "__main__":
    logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s")
    main()
