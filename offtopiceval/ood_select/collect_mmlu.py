from datasets import load_dataset, get_dataset_config_names, concatenate_datasets
from pathlib import Path
import json
import json
from collections import Counter
import argparse
from utils import random_seed
import os

def collect_mmlu_en(repo_id, output_dir):
    os.makedirs(output_dir, exist_ok=True)


    sub_data = load_dataset(repo_id)
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
        # 提取四个选项，按 a-d 顺序加入 choices 数组
        choices = [item.get(f"option_{ch}", "") for ch in ["a", "b", "c", "d"]]
        item["choices"] = choices

        # 如果你不再需要 option_a/b/c/d 字段，也可以删除它们
        for ch in ["a", "b", "c", "d"]:
            item.pop(f"option_{ch}", None)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)



# def collect_en_mmlu():
#     big_data = json.load(
#         open(
#             "/home/ubuntu/leijingdi/Workspace/code/safetyBench/select_ood/multiligual/mmlu_en.json",
#             "r",
#             encoding="utf-8",
#         )
#     )

#     small_data = json.load(
#         open(
#             "/home/ubuntu/leijingdi/Workspace/code/safetyBench/select_ood/result_simple.json"
#         )
#     )

#     ls = []
#     not_found = []

#     for data in small_data:
#         found = False
#         for item in big_data:
#             if data["question"] == item["question"]:
#                 data["sample_id"] = item["sample_id"]
#                 ls.append(data)
#                 found = True
#                 break
#         # if not found:
#         #     not_found.append(data)

#     with open(
#         "/home/ubuntu/leijingdi/Workspace/code/safetyBench/select_ood/result_simple_with_id.json",
#         "w",
#         encoding="utf-8",
#     ) as f:
#         json.dump(ls, f, indent=4, ensure_ascii=False)
#     print(len(ls))
#     # with open("/home/ubuntu/leijingdi/Workspace/code/safetyBench/select_ood/not_found.json", "w", encoding="utf-8")as f:
#     #     json.dump(not_found, f, indent=4, ensure_ascii=False)


def count_domain(data_path):
    with open(data_path, 'r') as f:
        data = json.load(f)

    unique_domains = set()

    for item in data:
        if "subject" in item:
            unique_domains.add(item["subject"])
    print(f"different domains count: {len(unique_domains)}")


# def collect_multi_mmlu():
#     en_data = json.load(
#         open(
#             "/home/ubuntu/leijingdi/Workspace/code/safetyBench/select_ood/result_simple_en.json",
#             "r",
#             encoding="utf-8",
#         )
#     )

#     zh_data = json.load(
#         open(
#             "/home/ubuntu/leijingdi/Workspace/code/safetyBench/select_ood/multiligual/mmlu_zh.json",
#             "r",
#             encoding="utf-8",
#         )
#     )
#     hi_data = json.load(
#         open(
#             "/home/ubuntu/leijingdi/Workspace/code/safetyBench/select_ood/multiligual/mmlu_hi.json",
#             "r",
#             encoding="utf-8",
#         )
#     )

#     zh_data_ls = []
#     hi_data_ls = []
#     for item in en_data:
#         idx = item["sample_id"]
#         for d in zh_data:
#             if d["sample_id"] == idx:
#                 zh_data_ls.append(d)
#                 break
#         for d in hi_data:
#             if d["sample_id"] == idx:
#                 hi_data_ls.append(d)
#                 break

#     with open(
#         "/home/ubuntu/leijingdi/Workspace/code/safetyBench/select_ood/result_simple_zh.json",
#         "w",
#         encoding="utf-8",
#     ) as f:
#         json.dump(zh_data_ls, f, indent=4, ensure_ascii=False)

#     with open(
#         "/home/ubuntu/leijingdi/Workspace/code/safetyBench/select_ood/result_simple_hi.json",
#         "w",
#         encoding="utf-8",
#     ) as f:
#         json.dump(hi_data_ls, f, indent=4, ensure_ascii=False)





if __name__=="__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--en_repo_id", type=str,required=True)
    ap.add_argument("--global_repo_id", type=str,required=True)
    ap.add_argument("--out_dir", type=str, required=True)
    ap.add_argument("--global_subsets", type=list, default=['zh','hi'])
    ap.add_argument("--seed", type=int, default=24)
    
    args = ap.parse_args()

    random_seed.set_seed(args.seed)
    
    collect_mmlu_en(args.en_repo_id, args.out_dir)

    collect_mmlu_zh_hi(args.global_repo_id, args.global_subsets, args.out_dir)