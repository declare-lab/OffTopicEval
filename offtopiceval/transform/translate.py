import os
import json
import argparse
import logging
from tqdm import tqdm
from prompt import TRANSLATE_PROMPT
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI

def create_client(api_key, base_url):
    return OpenAI(api_key=api_key, base_url=base_url)


def llm_call(messages, model, client):

    extra_body = {"top_k":20}
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=4096,
        temperature=0.6,
        top_p=0.95,
        extra_body=extra_body
    )
    return response.choices[0].message.content


def worker(data, src_lang, tgt_lang, model, client):
    messages = [
        {
            "role": "system",
            "content": TRANSLATE_PROMPT.format(
                src_lang=src_lang, tgt_lang=tgt_lang
            ).strip(),
        },
        {"role": "user", "content": data['question']},
    ]
    response = llm_call(messages, model, client)

    data["question"] = response
    
    return data


def main():
    ap = argparse.ArgumentParser()

    ap.add_argument("--model", type=str, default="sarvamai/sarvam-translate")
    ap.add_argument("--api_key", type=str, default="EMPTY")
    ap.add_argument("--base_url", type=str, default="http://localhost:8000/v1")
    ap.add_argument("--seed", type=int, default=24)
    ap.add_argument("--max_workers", type=int, default=1024)
    ap.add_argument("--src_lang", type=str, default="English")
    ap.add_argument("--tgt_lang", type=str, default="Hindi")
    ap.add_argument("--base_dir", type=str, default="/home/ubuntu/leijingdi/OffTopicEval/data/out_of_domain/data_hi")

    args = ap.parse_args()
    client = create_client(api_key=args.api_key, base_url=args.base_url)

    
    base_dir = args.base_dir
    tgt_lang = args.tgt_lang


    output_dir = f"{base_dir}_translate"
    os.makedirs(output_dir, exist_ok=True)
    
    for filename in os.listdir(base_dir):
        data_path = os.path.join(base_dir, filename)
        output_path = os.path.join(output_dir, filename)
        
        with open(data_path, "r", encoding="utf-8") as f:
            all_data = json.load(f)
        
        all_results = []
        with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
            futures = [
                executor.submit(
                    worker, data, args.src_lang, tgt_lang, args.model, client
                )
                for data in all_data
            ]
            for future in tqdm(
                as_completed(futures),
                total=len(futures),
                desc=f"{args.src_lang} -> {tgt_lang}",
            ):
                try:
                    r = future.result()
                    if r:
                        all_results.append(r)
                except Exception as e:
                    logging.warning(f"Worker failed with exception: {e}")

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(all_results, f, indent=4, ensure_ascii=False)


if __name__ == "__main__":
    logging.basicConfig(
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    main()
