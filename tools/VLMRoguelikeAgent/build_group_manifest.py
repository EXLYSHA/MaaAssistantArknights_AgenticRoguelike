"""预处理脚本：扫描 resource/roguelike/Sarkaz/autopilot/*.json 提取分组需求。

输出 knowledge/sarkaz_group_manifest.json，结构:
{
    "per_stage": { "<stage>": { "<group>": <count> } },
    "global_required_groups": ["地面阻挡", "高台输出", ...],
    "stage_list": ["丛林密布", ...]
}

用法:
    python build_group_manifest.py
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AUTOPILOT_DIR = REPO_ROOT / "resource" / "roguelike" / "Sarkaz" / "autopilot"
OUT_FILE = Path(__file__).resolve().parent / "knowledge" / "sarkaz_group_manifest.json"


def collect() -> dict:
    per_stage: dict[str, dict[str, int]] = {}
    all_groups_global: Counter = Counter()

    for fp in sorted(AUTOPILOT_DIR.glob("*.json")):
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"skip {fp.name}: {e}")
            continue

        stage_name = data.get("stage_name", fp.stem)
        stage_counter: Counter = Counter()
        for slot in data.get("deploy_plan", []):
            for g in slot.get("groups", []):
                stage_counter[g] += 1
                all_groups_global[g] += 1
        per_stage[stage_name] = dict(stage_counter)

    # 一个"全局必需分组"近似：在至少 30% 的关卡里出现的分组
    threshold = max(1, int(len(per_stage) * 0.3))
    appears_in: Counter = Counter()
    for stage_counter in per_stage.values():
        for g in stage_counter:
            appears_in[g] += 1
    global_required = sorted(
        [g for g, c in appears_in.items() if c >= threshold],
        key=lambda g: -appears_in[g],
    )

    return {
        "per_stage": per_stage,
        "stage_list": sorted(per_stage),
        "global_required_groups": global_required,
        "all_groups_total_slots": dict(all_groups_global),
    }


def main() -> None:
    out = collect()
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT_FILE}")
    print(f"  stages: {len(out['stage_list'])}")
    print(f"  global_required_groups: {out['global_required_groups']}")


if __name__ == "__main__":
    main()
