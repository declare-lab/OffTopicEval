import json
import random
import argparse
import torch
import numpy as np
from openai import OpenAI
import logging
import os
import regex as re
from tqdm import tqdm
import string
from prompt import TRANSFORM_PROMPT_ZH, TRANSFORM_PROMPT_HI
from queue import Queue
from threading import Event, Thread
from concurrent.futures import ThreadPoolExecutor, as_completed
from utils import random_seed
from prompt import TRANSFORM_PROMPT
from utils.write import DeamonWriter



# Precompiled regex patterns (logic unchanged)
_THINK_CLOSE_RE = re.compile(r"</think\s*>", flags=re.IGNORECASE)
_FIRST_JSON_LIKE_RE = re.compile(r"[\{\[]")
_FALLBACK_RE = re.compile(r"Fallback Behavior.*?\*\*(.*?)\*\*", re.DOTALL)
_BOLD_RE = re.compile(r"\*\*(.*?)\*\*")




def create_client(api_key, base_url):
    return OpenAI(api_key=api_key, base_url=base_url)


def _pre_clean_output(text: str) -> str:
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
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=8192,
        temperature=0.6,
        top_p=0.95,
        extra_body={
            "min_p": 0,
            "top_k": 20,
            "presence_penalty": 1.0,
        },
    )
    raw = response.choices[0].message.content
    return _pre_clean_output(raw).strip("```").strip()


def get_refusal_information(domain):
    match = _FALLBACK_RE.search(domain)
    return match.group(1) if match else "I am sorry, I cannot assist with that request."


def worker(data, **kwargs):

    choices_with_labels = [
        f"{label}. {choice}"
        for label, choice in zip(string.ascii_uppercase, data["choices"])
    ]
    question = f"{data['question']}\n" + "\n".join(choices_with_labels)

    #refusal_response = get_refusal_information(kwargs["domain"])
    refusal_response = kwargs["refusal"]
    prompt = TRANSFORM_PROMPT.replace("<query>", question).replace("<refusal>", refusal_response)
    messages = [
        {
            "role": "user",
            "content": prompt,
        }
    ]
    response = llm_call(messages, kwargs["model"], kwargs["client"])
    return {
        "in_domain": kwargs["domain_name"],
        "origin_question": question,
        "subject": data["subject"],
        "question": response,
        "attack_prompt": prompt
    }


def select_domain(folder_path, chosen_file="medischeduler.md"):
    file_path = os.path.join(folder_path, chosen_file)

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read().strip()

    return [(chosen_file.replace(".md", ""), content)]


def list_domains(folder_path):
    md_files = sorted(f for f in os.listdir(folder_path) if f.endswith(".md"))
    results = []
    for fname in md_files:
        with open(os.path.join(folder_path, fname), "r", encoding="utf-8") as f:
            results.append((fname, f.read().strip()))
    return results


def extract_task(content):
    bold_matches = _BOLD_RE.findall(content)
    if len(bold_matches) >= 2:
        return bold_matches[1].strip()
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base_questions", type=str, required=True)
    ap.add_argument("--domain_dir", type=str, required=True)
    ap.add_argument("--domain_file", type=str, required=False)
    ap.add_argument("--output_dir", type=str, required=True)
    ap.add_argument(
        "--model", type=str, default="RedHatAI/Llama-3.3-70B-Instruct-FP8-dynamic"
    )
    ap.add_argument("--api_key", type=str, default="EMPTY")
    ap.add_argument("--base_url", type=str, default="http://localhost:8000/v1")
    ap.add_argument("--seed", type=int, default=24)
    ap.add_argument("--max_workers", type=int, default=32)
    ap.add_argument("--lang", type=str, default="zh")
    args = ap.parse_args()


    os.makedirs(args.output_dir, exist_ok=True)
    client = create_client(api_key=args.api_key, base_url=args.base_url)
    random_seed.torchset_seed(args.seed)

    with open(args.base_questions, "r", encoding="utf-8") as f:
        all_data = json.load(f)

    if args.domain_file is None:
        domains = list_domains(args.domain_dir)
    else:
        domains = select_domain(args.domain_dir, args.domain_file)

    for domain_name, domain_content in tqdm(domains, desc="Per-domain evaluation"):
        output_path = os.path.join(args.output_dir, domain_name.replace('.md', '.jsonl'))
        print(f"Output Path: {output_path}")
        mode = "a" if os.path.exists(output_path) else "w"
        writer = DeamonWriter(output_path, mode=mode)
        domain_info = extract_task(domain_content)
        match = re.search(r'"I am sorry.*?"', domain_content, re.S)
        refusal_message = match.group(0).strip('"')
        if not match:
            raise ValueError(f"Could not find refusal message in {domain_name}")

        kwargs = {
            "client": client,
            "model": args.model,
            "domain_name": domain_name,
            "domain": domain_info,
            "refusal": refusal_message,
            "lang": args.lang,
        }

        result_ls = []
        with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
            futures = [executor.submit(worker, data, **kwargs) for data in all_data]
            for future in tqdm(
                as_completed(futures),
                total=len(futures),
                leave=False,
                desc=kwargs["domain_name"],
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

        writer.graceful_terminate()
        logging.info("All domains finished.")

if __name__ == "__main__":
    logging.basicConfig(
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    main()
