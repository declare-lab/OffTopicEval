import re

def extract_part_system_prompt(prompt_text, level=None):
    if level == 8:
        return prompt_text
    
    selections_to_keep_per_level = {
        1: [1],
        2: [1, 2],
        3: [1, 2, 3],
        4: [1, 2, 3, 4],
        5: [1, 2, 3, 4, 5],
        6: [1, 2, 3, 4, 5, 6],
        7: [1, 2, 3, 4, 5, 6, 7],
    }


    hashes_pattern = r"(?:#|##)"  # 匹配一个或两个井号
    pattern = re.compile(rf"(?m)^[ \t]*{hashes_pattern}\s+.+$")

    matches = list(pattern.finditer(prompt_text))
    if not matches:
        return prompt_text
    
    sections = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(prompt_text)
        sections.append(prompt_text[start:end].strip())

    section_to_keep = []
    for idx in selections_to_keep_per_level[level]:
        section_to_keep.append(sections[idx - 1])
    
    return "\n\n".join(section_to_keep)
