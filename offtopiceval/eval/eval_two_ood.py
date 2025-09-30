import argparse
import json
import logging
import os
import random
import regex as re
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Event, Thread
from queue import Queue
from datetime import datetime
import numpy as np
import torch
from openai import OpenAI
from tqdm import tqdm
from utils.random_seed import set_seed
from utils.writer import DeamonWriter
from utils.is_refusal import is_refusal
from utils.extract_system_prompt import extract_part_system_prompt
from eval.instruct import BASE_INSTRUCT


# ========= Optional async writer kept for compatibility (unused in JSON mode) =========

def create_client(api_key, base_url):
    return OpenAI(api_key=api_key, base_url=base_url)


def llm_call(messages, model, client):
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=8192,
        temperature=0.6,
        top_p=0.95,
        extra_body={"top_k": 20},
    )
    return response.choices[0].message.content


def cal_metric(bools):
    filtered = [x for x in bools if x in [True, False]]
    return (sum(filtered) / len(filtered)) if filtered else 0.0


def list_domains(folder_path):
    md_files = sorted(f for f in os.listdir(folder_path) if f.endswith(".md"))
    results = []
    for fname in md_files:
        with open(os.path.join(folder_path, fname), "r", encoding="utf-8") as f:
            results.append((fname, f.read().strip()))
    return results


def select_domain(folder_path, level=4, chosen_file="bankhelper.json"):
    file_path = os.path.join(folder_path, chosen_file)
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read().strip()
    content = extract_part_system_prompt(content, level)
    return (chosen_file.replace(".md", ""), content)

# ========= Twice-OOD helpers =========
BASE_INSTRUCTION = BASE_INSTRUCT
def _two_turn_dialog(system_prompt, q1, q2, client, model):
    """Run a 2-turn conversation and return (res1, eval1, res2, eval2)."""
    # Turn 1
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"{q1}\n\n{BASE_INSTRUCTION}"},
    ]
    res1 = llm_call(messages, model, client)
    eval1 = is_refusal(res1)

    # Turn 2 (keep history)
    messages.append({"role": "assistant", "content": res1})
    messages.append({"role": "user", "content": f"{q2}\n\n{BASE_INSTRUCTION}"})
    res2 = llm_call(messages, model, client)
    eval2 = is_refusal(res2)
    return res1, eval1, res2, eval2


def _single_turn(system_prompt, q, client, model):
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"{q}\n\n{BASE_INSTRUCTION}"},
    ]
    res = llm_call(messages, model, client)
    return res, is_refusal(res)

# ========= Twice-OOD main runner (uses 1 item from ood1, all items from ood2) =========
def run_twice_ood(ood1_item, ood2_items, domain_name, system_prompt, client, model, output_dir, max_workers=128):
    """
    Evaluates four modes:
      A: {(OOD1-attack, response), (OOD2, response)}       # Two turns
      B: {(OOD1-attack, response), (OOD2-attack, response)} # Two turns
      C: {(OOD2, response)}                                 # Single turn
      D: {(OOD2-attack, response)}                          # Single turn
    Only one sample is used from ood1_item; all samples are used from ood2_items.
    """
    model_name = model.split("/")[-1]
    out_dir = os.path.join(output_dir, model_name)
    os.makedirs(out_dir, exist_ok=True)

    # Collect all outputs in-memory; finally dump to JSON files (arrays)
    outputs_A = []
    outputs_B = []
    outputs_C = []
    outputs_D = []

    A_results_step1, A_results_step2 = [], []
    B_results_step1, B_results_step2 = [], []
    C_results, D_results = [], []

    o1 = ood1_item  # fixed
    o1_q_attack = o1["question"]

    def task_A(o2):
        q1 = o1_q_attack             # OOD1-attack
        q2 = o2["origin_question"]   # OOD2
        res1, eval1, res2, eval2 = _two_turn_dialog(system_prompt, q1, q2, client, model)
        item = {
            "mode": "comboA",
            "in_domain": domain_name,
            "subject_ood1": o1.get("subject"),
            "subject_ood2": o2.get("subject"),
            "ood1_attack_question": q1,
            "ood2_question": q2,
            "response_ood1": res1,
            "response_ood2": res2,
            "eval_ood1": eval1,
            "eval_ood2": eval2,
            "system_prompt": system_prompt,
            "sequence": ["OOD1-attack", "OOD2"],
        }
        return item, eval1, eval2

    def task_B(o2):
        q1 = o1_q_attack             # OOD1-attack
        q2 = o2["question"]          # OOD2-attack
        res1, eval1, res2, eval2 = _two_turn_dialog(system_prompt, q1, q2, client, model)
        item = {
            "mode": "comboB",
            "in_domain": domain_name,
            "subject_ood1": o1.get("subject"),
            "subject_ood2": o2.get("subject"),
            "ood1_attack_question": q1,
            "ood2_attack_question": q2,
            "response_ood1": res1,
            "response_ood2_attack": res2,
            "eval_ood1": eval1,
            "eval_ood2_attack": eval2,
            "system_prompt": system_prompt,
            "sequence": ["OOD1-attack", "OOD2-attack"],
        }
        return item, eval1, eval2

    def task_C(o2):
        q = o2["origin_question"]    # OOD2
        res, ev = _single_turn(system_prompt, q, client, model)
        item = {
            "mode": "single_OOD2",
            "in_domain": domain_name,
            "subject": o2.get("subject"),
            "query_type": "OOD2",
            "question": q,
            "response": res,
            "eval_result": ev,
            "system_prompt": system_prompt,
        }
        return item, ev

    def task_D(o2):
        q = o2["question"]           # OOD2-attack
        res, ev = _single_turn(system_prompt, q, client, model)
        item = {
            "mode": "single_OOD2_attack",
            "in_domain": domain_name,
            "subject": o2.get("subject"),
            "query_type": "OOD2-attack",
            "question": q,
            "response": res,
            "eval_result": ev,
            "system_prompt": system_prompt,
        }
        return item, ev

    # --- Execute with threads for each mode ---
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        # A
        fut_A = [ex.submit(task_A, o2) for o2 in ood2_items]
        for fut in tqdm(as_completed(fut_A), total=len(fut_A), leave=False, desc=f"{domain_name} ComboA"):
            item, e1, e2 = fut.result()
            outputs_A.append(item)
            A_results_step1.append(e1)
            A_results_step2.append(e2)

        # B
        fut_B = [ex.submit(task_B, o2) for o2 in ood2_items]
        for fut in tqdm(as_completed(fut_B), total=len(fut_B), leave=False, desc=f"{domain_name} ComboB"):
            item, e1, e2 = fut.result()
            outputs_B.append(item)
            B_results_step1.append(e1)
            B_results_step2.append(e2)

        # C
        fut_C = [ex.submit(task_C, o2) for o2 in ood2_items]
        for fut in tqdm(as_completed(fut_C), total=len(fut_C), leave=False, desc=f"{domain_name} Single OOD2"):
            item, ev = fut.result()
            outputs_C.append(item)
            C_results.append(ev)

        # D
        fut_D = [ex.submit(task_D, o2) for o2 in ood2_items]
        for fut in tqdm(as_completed(fut_D), total=len(fut_D), leave=False, desc=f"{domain_name} Single OOD2-attack"):
            item, ev = fut.result()
            outputs_D.append(item)
            D_results.append(ev)

    # --- Metrics ---
    A_rate_step1 = cal_metric(A_results_step1)  # OOD1-attack refusal rate
    A_rate_step2 = cal_metric(A_results_step2)  # OOD2 refusal rate
    B_rate_step1 = cal_metric(B_results_step1)  # OOD1-attack refusal rate
    B_rate_step2 = cal_metric(B_results_step2)  # OOD2-attack refusal rate
    C_rate = cal_metric(C_results)              # OOD2 refusal rate
    D_rate = cal_metric(D_results)              # OOD2-attack refusal rate

    # --- Save all outputs as JSON arrays ---
    def _dump_json(path, obj):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)

    _dump_json(os.path.join(out_dir, f"{domain_name}__comboA.json"), outputs_A)
    _dump_json(os.path.join(out_dir, f"{domain_name}__comboB.json"), outputs_B)
    _dump_json(os.path.join(out_dir, f"{domain_name}__single_OOD2.json"), outputs_C)
    _dump_json(os.path.join(out_dir, f"{domain_name}__single_OOD2_attack.json"), outputs_D)

    # --- Save summary (JSON) ---
    summary_path = os.path.join(out_dir, "summary_twice_ood.json")
    summary_payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "domain": domain_name,
        "model": model_name,
        "counts": {
            "comboA": len(outputs_A),
            "comboB": len(outputs_B),
            "single_OOD2": len(outputs_C),
            "single_OOD2_attack": len(outputs_D),
        },
        "refusal_rates": {
            "comboA": {
                "OOD1_attack": A_rate_step1,
                "OOD2": A_rate_step2,
            },
            "comboB": {
                "OOD1_attack": B_rate_step1,
                "OOD2_attack": B_rate_step2,
            },
            "single_OOD2": C_rate,
            "single_OOD2_attack": D_rate,
        },
    }

    # Append-friendly: if file exists, load-append this domain; else create
    if os.path.exists(summary_path):
        try:
            prev = json.load(open(summary_path, "r", encoding="utf-8"))
            if isinstance(prev, list):
                prev.append(summary_payload)
                json.dump(prev, open(summary_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            else:
                json.dump([prev, summary_payload], open(summary_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        except Exception:
            json.dump([summary_payload], open(summary_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    else:
        json.dump([summary_payload], open(summary_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    # Console logs
    print(f"[{domain_name}] ComboA  -> OOD1-attack refusal: {A_rate_step1:.4f} | OOD2 refusal: {A_rate_step2:.4f}")
    print(f"[{domain_name}] ComboB  -> OOD1-attack refusal: {B_rate_step1:.4f} | OOD2-attack refusal: {B_rate_step2:.4f}")
    print(f"[{domain_name}] Single  -> OOD2 refusal: {C_rate:.4f}")
    print(f"[{domain_name}] Single  -> OOD2-attack refusal: {D_rate:.4f}")

# ========= Original single-round flow (kept; now saves JSON arrays + summary) =========
def run_single_round(all_data, domain_name, system_prompt, client, model, output_dir, max_workers=128):
    model_name = model.split("/")[-1]
    out_dir = os.path.join(output_dir, model_name)
    os.makedirs(out_dir, exist_ok=True)

    results = []

    def _single_worker(data):
        question = data["question"]
        original_question = data["origin_question"]

        # question
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"{question} \n\n {BASE_INSTRUCTION}"},
        ]
        res = llm_call(messages, model, client)
        eval_result = is_refusal(res)

        # origin_question (direct)
        direct_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"{original_question} \n\n {BASE_INSTRUCTION}"},
        ]
        direct_res = llm_call(direct_messages, model, client)
        direct_eval_result = is_refusal(direct_res)

        return {
            "in_domain": domain_name,
            "subject": data.get("subject"),
            "question": question,
            "origin_question": original_question,
            "response": res,
            "direct_response": direct_res,
            "eval_result": eval_result,
            "direct_eval_result": direct_eval_result,
            "system_prompt": system_prompt,
        }

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = [ex.submit(_single_worker, d) for d in all_data]
        for fut in tqdm(as_completed(futs), total=len(futs), leave=False, desc=domain_name):
            results.append(fut.result())

    # Save full outputs (JSON array)
    out_json = os.path.join(out_dir, f"{domain_name}.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # Metrics
    refusal_rate = cal_metric([item["eval_result"] for item in results])
    original_refusal_rate = cal_metric([item["direct_eval_result"] for item in results])

    # Save summary (JSON)
    summary_path = os.path.join(out_dir, "summary_single.json")
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "domain": domain_name,
        "model": model_name,
        "count": len(results),
        "refusal_rates": {
            "question": refusal_rate,
            "origin_question": original_refusal_rate,
        },
    }
    if os.path.exists(summary_path):
        try:
            prev = json.load(open(summary_path, "r", encoding="utf-8"))
            if isinstance(prev, list):
                prev.append(payload)
                json.dump(prev, open(summary_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            else:
                json.dump([prev, payload], open(summary_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        except Exception:
            json.dump([payload], open(summary_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    else:
        json.dump([payload], open(summary_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print(f"[{domain_name}] Saved JSON: {out_json}")
    print(f"[{domain_name}] Refusal Rate (question): {refusal_rate:.4f}")
    print(f"[{domain_name}] Refusal Rate (origin_question): {original_refusal_rate:.4f}")

# ========= Main =========
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", type=str, required=True, help="Used to determine domain .md name")
    ap.add_argument("--output_dir", type=str, required=True)
    ap.add_argument("--domain_dir", type=str, required=True)
    ap.add_argument("--prompt_level", type=int, default=4)
    ap.add_argument("--model", type=str, default="RedHatAI/Llama-3.3-70B-Instruct-FP8-dynamic")
    ap.add_argument("--api_key", type=str, default="EMPTY")
    ap.add_argument("--base_url", type=str, default="http://localhost:8000/v1")
    ap.add_argument("--seed", type=int, default=24)
    ap.add_argument("--max_workers", type=int, default=128)

    # Twice-OOD
    ap.add_argument("--ood1_file", type=str, default="hrhelper_ood1.json", help="File where origin accepted, question refused. Use 'question' as OOD1-attack.")
    ap.add_argument("--ood2_file", type=str, default="hrhelper_ood2.json", help="All OOD data. Use 'origin_question' as OOD2, 'question' as OOD2-attack.")
    ap.add_argument("--ood1_index", type=int, default=0, help="Pick a single item from ood1_file (default 0)")

    args = ap.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    client = create_client(api_key=args.api_key, base_url=args.base_url)
    set_seed(args.seed)

    # Derive domain .md name from questions path
    domain_file = os.path.basename(args.questions).replace(".json", ".md")
    domain_name, domain_content = select_domain(args.domain_dir, args.prompt_level, domain_file)
    os.makedirs(os.path.join(args.output_dir, args.model.split("/")[-1]), exist_ok=True)

    # Twice-OOD branch
    if args.ood1_file and args.ood2_file:
        with open(args.ood1_file, "r", encoding="utf-8") as f:
            ood1_data = json.load(f)
        with open(args.ood2_file, "r", encoding="utf-8") as f:
            ood2_data = json.load(f)


        idx = max(0, min(args.ood1_index, len(ood1_data) - 1))
        ood1_item = ood1_data[idx]
        print(f"[Twice-OOD] Using ood1 index: {idx}, subject: {ood1_item.get('subject')} | ood2 total: {len(ood2_data)}")

        run_twice_ood(
            ood1_item=ood1_item,
            ood2_items=ood2_data,
            domain_name=domain_name,
            system_prompt=domain_content,
            client=client,
            model=args.model,
            output_dir=args.output_dir,
            max_workers=args.max_workers,
        )
        return

    # Single-round default
    with open(args.questions, "r", encoding="utf-8") as f:
        all_data = json.load(f)

    run_single_round(
        all_data=all_data,
        domain_name=domain_name,
        system_prompt=domain_content,
        client=client,
        model=args.model,
        output_dir=args.output_dir,
        max_workers=args.max_workers,
    )

if __name__ == "__main__":
    logging.basicConfig(filename="eval.log", level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    main()