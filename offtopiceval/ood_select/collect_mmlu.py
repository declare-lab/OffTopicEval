from datasets import load_dataset, get_dataset_config_names, concatenate_datasets
from pathlib import Path
import json
import json
from collections import Counter
import argparse
import os

def collect_mmlu_en(repo_id, output_dir):
    os.makedirs(output_dir, exist_ok=True)


    sub_data = load_dataset(repo_id, "all")
    parts = []
    for part in sub_data:
        for item in sub_data[part]:
            item['split'] = part
            parts.append(item)

    output_path = os.path.join(output_dir, f"mmlu_en.json")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(parts, f, indent=2, ensure_ascii=False)


def collect_mmlu_zh_hi(repo_id, subsets, output_dir):
    os.makedirs(output_dir, exist_ok=True)

    for subset in subsets:
        sub_data = load_dataset(repo_id, subset)

        parts = []
        for part in sub_data:
            for item in sub_data[part]:
                item['split'] = part
                parts.append(item)
        output_path = os.path.join(output_dir, f"mmlu_{subset}.json")
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(parts, f, indent=2, ensure_ascii=False)

def global_mmlu_convert_options_to_choices(input_path, output_path):
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    for item in data:
        
        choices = [item.get(f"option_{ch}", "") for ch in ["a", "b", "c", "d"]]
        item["choices"] = choices


        for ch in ["a", "b", "c", "d"]:
            item.pop(f"option_{ch}", None)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)




if __name__=="__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--en_repo_id", type=str,required=True)
    ap.add_argument("--global_repo_id", type=str,required=True)
    ap.add_argument("--out_dir", type=str, required=True)
    ap.add_argument("--global_subsets", type=list, default=['zh','hi'])
    ap.add_argument("--seed", type=int, default=24)

    
    args = ap.parse_args()

    collect_mmlu_en(args.en_repo_id, args.out_dir)

    
    collect_mmlu_zh_hi(args.global_repo_id, args.global_subsets, args.out_dir)
    for lang in args.global_subsets:
        output_path = args.out_dir + f"mmlu_{lang}.json"
        global_mmlu_convert_options_to_choices(output_path, output_path)