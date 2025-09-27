import os
import json
import argparse
import logging
from tqdm import tqdm
from prompt import TRANSLATE_PROMPT
from utils import create_client, llm_call
from concurrent.futures import ThreadPoolExecutor, as_completed


def combine(data):
    return f"{data['question'].strip()}\n{data['choices'][0].strip()}\n{data['choices'][1].strip()}\n{data['choices'][2].strip()}\n{data['choices'][3].strip()}".strip()


def worker(i, data, src_lang, tgt_lang, model, client):
    messages = [
        {
            "role": "system",
            "content": TRANSLATE_PROMPT.format(
                src_lang=src_lang, tgt_lang=tgt_lang
            ).strip(),
        },
        {"role": "user", "content": combine(data)},
    ]
    response = llm_call(messages, model, client)

    data["idx"] = i
    data["translated_question"] = response
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", type=str, required=True)
    ap.add_argument("--output_dir", type=str, required=True)
    ap.add_argument("--model", type=str, required=True)
    ap.add_argument("--api_key", type=str, default="EMPTY")
    ap.add_argument("--base_url", type=str, default="http://localhost:54321/v1")
    ap.add_argument("--seed", type=int, default=24)
    ap.add_argument("--max_workers", type=int, default=32)
    ap.add_argument("--src_lang", type=str, default="English")
    ap.add_argument("--tgt_lang", type=str, default="Hindi")
    args = ap.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    chatbot_name = os.path.basename(args.questions).split(".")[0]

    output_path = os.path.join(args.output_dir, os.path.basename(args.questions))
    print(f"Output Path: {output_path}")

    client = create_client(api_key=args.api_key, base_url=args.base_url)

    with open(args.questions, "r", encoding="utf-8") as f:
        all_data = json.load(f)

    if os.path.exists(output_path):
        print("File already exists.")
        return

    all_results = []

    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        futures = [
            executor.submit(
                worker, i, data, args.src_lang, args.tgt_lang, args.model, client
            )
            for i, data in enumerate(all_data)
        ]
        for future in tqdm(
            as_completed(futures),
            total=len(futures),
            desc=f"[{chatbot_name}]: {args.src_lang} -> {args.tgt_lang}",
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
