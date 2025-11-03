import json
import re
import io
import ast
import hashlib
import tokenize
from pathlib import Path
from collections import defaultdict, Counter

# ========= 配置 =========
DATE = "verified_Claude-4-Sonnet_round_c_0"
# DATE = "Claude-3-5-Sonnet_round_c_2"
# DATE = "Qwen3-Coder_round_0_1"
# DATE = "Qwen3-Coder-Instruct_round_0_1_2"

regression_path = Path(f"/root/hy/logs/regression_{DATE}.jsonl")
reproduction_path = Path(f"/root/hy/logs/reproduction_{DATE}.jsonl")
output_path = Path(f"/root/hy/predictions_{DATE}.json")
stats_output_path = Path(f"/root/hy/predictions_stats_{DATE}.json")
step5_output_path = Path(f"/root/hy/predictions_step5_{DATE}.json")          
step5_min_output_path = Path(f"/root/hy/predictions_step5_min_{DATE}.json")  

combined = {}
regression_data = {}
reproduction_data = {}

# ========= 读入 regression =========
with regression_path.open("r", encoding="utf-8") as f:
    for line in f:
        data = json.loads(line)
        key = (data["instance_id"], data["patch_type"], data["patch_timestamp"])
        combined[key] = {
            "instance_id": data["instance_id"],
            "patch_type": data["patch_type"],
            "patch_timestamp": data["patch_timestamp"],
            "regression_count": data.get("passed_count", 0),
            "reproduction_count": 0,
            "patch": data["patch"],
            "source": "regression",
        }
        regression_data[key] = data.get("passed_count", 0)

# ========= 读入 reproduction =========
with reproduction_path.open("r", encoding="utf-8") as f:
    for line in f:
        data = json.loads(line)
        key = (data["instance_id"], data["patch_type"], data["patch_timestamp"])
        if key in combined:
            combined[key]["reproduction_count"] = data.get("passed_count", 0)
        else:
            combined[key] = {
                "instance_id": data["instance_id"],
                "patch_type": data["patch_type"],
                "patch_timestamp": data["patch_timestamp"],
                "regression_count": 0,
                "reproduction_count": data.get("passed_count", 0),
                "patch": data["patch"],
                "source": "reproduction",
            }
        reproduction_data[key] = data.get("passed_count", 0)

def _indent(s: str, n: int = 4) -> str:
    pad = " " * n
    return "\n".join(pad + ln if ln.strip() else ln for ln in s.splitlines())

def _strip_comments_and_whitespace(code: str) -> str:
    try:
        out = []
        tokens = tokenize.generate_tokens(io.StringIO(code).readline)
        for tok_type, tok_str, _, _, _ in tokens:
            if tok_type == tokenize.COMMENT:
                continue
            if tok_type not in (tokenize.NL, tokenize.NEWLINE):
                out.append(tok_str)
            else:
                out.append("\n")
        code = "".join(out)
    except Exception:
        code = "\n".join(re.split(r"(?<!['\"])#(?!['\"])", ln)[0] for ln in code.splitlines())
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in code.splitlines()]
    lines = [ln for ln in lines if ln]
    return "\n".join(lines)

def _try_ast_canonicalize(code: str) -> str:
    candidates = [code, f"def __frag__():\n{_indent(code)}\n", f"if True:\n{_indent(code)}\n"]
    for cand in candidates:
        try:
            tree = ast.parse(cand)
            canon = ast.unparse(tree)
            return _strip_comments_and_whitespace(canon)
        except Exception:
            continue
    return _strip_comments_and_whitespace(code)

def _extract_plus_minus_from_unified_diff(patch_text: str):
    plus_lines, minus_lines = [], []
    for ln in patch_text.splitlines():
        if ln.startswith('+++') or ln.startswith('---') or ln.startswith('@@'):
            continue
        if ln.startswith('+'):
            plus_lines.append(ln[1:])
        elif ln.startswith('-'):
            minus_lines.append(ln[1:])
        else:
            continue
    return "\n".join(plus_lines).strip(), "\n".join(minus_lines).strip()

_norm_cache: dict[str, tuple[str, int]] = {}  # patch_text -> (norm_key, norm_size)

def _normalized_parts(patch_text: str):
    plus, minus = _extract_plus_minus_from_unified_diff(patch_text)
    plus_norm = _try_ast_canonicalize(plus) if plus else ""
    minus_norm = _try_ast_canonicalize(minus) if minus else ""
    return plus_norm, minus_norm

def build_normalized_vote_key_unified(patch_text: str) -> str:
    if patch_text in _norm_cache:
        return _norm_cache[patch_text][0]
    plus_norm, minus_norm = _normalized_parts(patch_text)
    key_text = f"[UD]\nPLUS:\n{plus_norm}\nMINUS:\n{minus_norm}\n"
    norm_key = hashlib.sha256(key_text.encode("utf-8")).hexdigest()
    size = _compute_normalized_patch_size_from_parts(plus_norm, minus_norm)
    _norm_cache[patch_text] = (norm_key, size)
    return norm_key

def _compute_normalized_patch_size_from_parts(plus_norm: str, minus_norm: str) -> int:
    def _nonempty_lines(s: str) -> int:
        return sum(1 for ln in s.splitlines() if ln.strip())
    return _nonempty_lines(plus_norm) + _nonempty_lines(minus_norm)

def compute_normalized_patch_size_unified(patch_text: str) -> int:
    if patch_text in _norm_cache:
        return _norm_cache[patch_text][1]
    _ = build_normalized_vote_key_unified(patch_text)
    return _norm_cache[patch_text][1]

grouped_by_instance = defaultdict(list)
for _, v in combined.items():
    grouped_by_instance[v["instance_id"]].append(v)

raw_counter_per_instance: dict[str, Counter] = {}
norm_counter_per_instance: dict[str, Counter] = {}

for _, v in combined.items():
    inst = v["instance_id"]
    patch_text = v["patch"]

    raw_counter_per_instance.setdefault(inst, Counter())
    raw_counter_per_instance[inst][patch_text] += 1

    norm_key = build_normalized_vote_key_unified(patch_text)
    norm_counter_per_instance.setdefault(inst, Counter())
    norm_counter_per_instance[inst][norm_key] += 1

def candidates_after_step3(items):
    if not items:
        return []
    max_reg = max(i['regression_count'] for i in items)
    c1 = [i for i in items if i['regression_count'] == max_reg]
    max_rep = max(i['reproduction_count'] for i in c1)
    c2 = [i for i in c1 if i['reproduction_count'] == max_rep]
    has_raw = any(i['patch_type'] == 'raw_patch' for i in c2)
    c3 = [i for i in c2 if i['patch_type'] == 'raw_patch'] if has_raw else c2
    return c3

def candidates_after_step4(items, inst_id: str):
    c3 = candidates_after_step3(items)
    if not c3:
        return []
    votes = []
    for it in c3:
        key = build_normalized_vote_key_unified(it["patch"])
        votes.append((it, norm_counter_per_instance[inst_id][key]))
    max_vote = max(v for _, v in votes)
    c4 = [it for it, v in votes if v == max_vote]
    return c4

def candidates_after_step5(items, inst_id: str):
    c4 = candidates_after_step4(items, inst_id)
    if not c4:
        return []
    sizes = [(it, compute_normalized_patch_size_unified(it["patch"])) for it in c4]
    max_size = max(sz for _, sz in sizes)
    c5 = [it for it, sz in sizes if sz == max_size]
    return c5

best_patch_per_instance = {}
for _, val in combined.items():
    inst = val["instance_id"]
    cur = best_patch_per_instance.get(inst)
    if cur is None:
        best_patch_per_instance[inst] = val
        continue

    if val["regression_count"] > cur["regression_count"]:
        best_patch_per_instance[inst] = val
        continue
    elif val["regression_count"] < cur["regression_count"]:
        continue

    if val["reproduction_count"] > cur["reproduction_count"]:
        best_patch_per_instance[inst] = val
        continue
    elif val["reproduction_count"] < cur["reproduction_count"]:
        continue

    if val["patch_type"] == "raw_patch" and cur["patch_type"] != "raw_patch":
        best_patch_per_instance[inst] = val
        continue
    elif val["patch_type"] != "raw_patch" and cur["patch_type"] == "raw_patch":
        continue

    val_key = build_normalized_vote_key_unified(val["patch"])
    cur_key = build_normalized_vote_key_unified(cur["patch"])
    val_votes = norm_counter_per_instance[inst][val_key]
    cur_votes = norm_counter_per_instance[inst][cur_key]
    if val_votes > cur_votes:
        best_patch_per_instance[inst] = val
        continue
    elif val_votes < cur_votes:
        continue

    val_size = compute_normalized_patch_size_unified(val["patch"])
    cur_size = compute_normalized_patch_size_unified(cur["patch"])
    if val_size > cur_size:
        best_patch_per_instance[inst] = val
        continue

final_output = {
    inst: {"model_patch": data["patch"], "model_name_or_path": "hy"}
    for inst, data in best_patch_per_instance.items()
}
with output_path.open("w", encoding="utf-8") as f:
    json.dump(final_output, f, indent=2, ensure_ascii=False)

stats_output = {}
for inst, items in grouped_by_instance.items():
    chosen = best_patch_per_instance[inst]
    ties3 = candidates_after_step3(items)
    ties4 = candidates_after_step4(items, inst)
    ties5 = candidates_after_step5(items, inst)

    chosen_norm_key = build_normalized_vote_key_unified(chosen["patch"])
    norm_vote_count = norm_counter_per_instance[inst][chosen_norm_key]
    raw_vote_count = raw_counter_per_instance[inst][chosen["patch"]]
    chosen_norm_size = compute_normalized_patch_size_unified(chosen["patch"])

    stats_output[inst] = {
        "regression_count": chosen["regression_count"],
        "reproduction_count": chosen["reproduction_count"],
        "vote_count_raw": raw_vote_count,
        "vote_count_normalized": norm_vote_count,
        "normalized_patch_size": chosen_norm_size,
        "ties_after_step3": len(ties3),
        "ties_after_step4": len(ties4),
        "ties_after_step5": len(ties5),
        "total_candidates": len(items),
        "unique_patch_variants": len(set(x["patch"] for x in items)),
        "normalized_unique_variants": len(set(build_normalized_vote_key_unified(x["patch"]) for x in items)),
    }
with stats_output_path.open("w", encoding="utf-8") as f:
    json.dump(stats_output, f, indent=2, ensure_ascii=False)

step5_output = {}
for inst, items in grouped_by_instance.items():
    final_cands = candidates_after_step5(items, inst)
    cand_list = []
    for it in final_cands:
        k = build_normalized_vote_key_unified(it["patch"])
        cand_list.append({
            "instance_id": inst,
            "patch_type": it["patch_type"],
            "patch_timestamp": it["patch_timestamp"],
            "source": it["source"],
            "regression_count": it["regression_count"],
            "reproduction_count": it["reproduction_count"],
            "vote_count_normalized": norm_counter_per_instance[inst][k],
            "normalized_patch_size": compute_normalized_patch_size_unified(it["patch"]),
            "normalized_key": k,
            "patch": it["patch"],
        })
    cand_list.sort(key=lambda d: (d["vote_count_normalized"], d["normalized_patch_size"], d["patch_timestamp"]), reverse=True)
    step5_output[inst] = {
        "num_candidates_after_step5": len(cand_list),
        "candidates": cand_list
    }
with step5_output_path.open("w", encoding="utf-8") as f:
    json.dump(step5_output, f, indent=2, ensure_ascii=False)

step5_min_output = {}
for inst, data in step5_output.items():
    seen = set()
    patches = []
    for c in data["candidates"]:
        k = c["normalized_key"]
        if k in seen:
            continue
        seen.add(k)
        patches.append({"normalized_key": k, "patch": c["patch"]})
    step5_min_output[inst] = {
        "count": len(patches),
        "patches": patches
    }
with step5_min_output_path.open("w", encoding="utf-8") as f:
    json.dump(step5_min_output, f, indent=2, ensure_ascii=False)

print(f"保存完毕，共计 {len(final_output)} 个 instance_id")
print(f"预测文件: {output_path}")
print(f"统计文件: {stats_output_path}")
print(f"Step5 候选明细: {step5_output_path}")
print(f"Step5 简短结果: {step5_min_output_path}")

print("\n=== Step5 candidates per instance (short) ===")
for inst, rec in step5_min_output.items():
    print(f"Instance: {inst} | step5_candidates={rec['count']}")


count_dist = Counter(rec["count"] for rec in step5_min_output.values())

print("\n=== Step5 candidate-count distribution (instances) ===")
for k in sorted(count_dist):
    print(f"count = {k}: {count_dist[k]}")

count_dist_path = Path(f"/root/hy/predictions_step5_count_dist_{DATE}.json")
with count_dist_path.open("w", encoding="utf-8") as f:
    json.dump(dict(sorted(count_dist.items())), f, indent=2, ensure_ascii=False)
print(f"Step5 数量分布文件: {count_dist_path}")