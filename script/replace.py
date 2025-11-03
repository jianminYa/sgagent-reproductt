from pathlib import Path

# 固定配置
FILE_A = Path("/root/hy/logs/reproduction_Claude-3-5-Sonnet_round_1.jsonl")   
FILE_B = Path("/root/hy/logs/reproduction_Claude-3-5-Sonnet_round_c_2.jsonl")  
KEYWORDS = [        "matplotlib__matplotlib-24334",
        "pylint-dev__pylint-7080",
        "sympy__sympy-18057"]  

def process_files():
    with FILE_A.open("r", encoding="utf-8") as f:
        lines_a = f.readlines()
    filtered_a = [line for line in lines_a if not any(k in line for k in KEYWORDS)]

    with FILE_B.open("r", encoding="utf-8") as f:
        lines_b = f.readlines()
    to_append = [line for line in lines_b if any(k in line for k in KEYWORDS)]

    with FILE_A.open("w", encoding="utf-8") as f:
        f.writelines(filtered_a + to_append)

    print(f"处理完成 ✅ 已更新文件: {FILE_A}")

if __name__ == "__main__":
    process_files()
