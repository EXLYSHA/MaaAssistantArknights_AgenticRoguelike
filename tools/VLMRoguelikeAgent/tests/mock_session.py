"""端到端 mock 测试：起一个会话，跑一遍所有决策端点，验证 schema 正确。

启动 server 后执行:
    python tests/mock_session.py
"""
from __future__ import annotations

import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8765"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with OPENER.open(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def main() -> int:
    health = json.loads(OPENER.open(BASE + "/health", timeout=30).read())
    print("health:", health)
    assert health["ok"]

    s = post("/session/start", {"theme": "Sarkaz", "mode": 30001, "difficulty": 15})
    sid = s["session_id"]
    print("session:", sid)

    cases = [
        ("/decide/squad", {
            "available_squads": ["蓝图测绘分队", "心胜于物分队", "生活至上分队"],
        }),
        ("/decide/recruit", {
            "floor": 1, "hope": 5, "is_start_recruit": True,
            "current_roster": [],
            "candidates": [
                {"name": "棘刺", "elite": 2, "level": 60, "groups": ["地面阻挡", "棘刺"]},
                {"name": "维什戴尔", "elite": 2, "level": 60, "groups": ["益达"]},
            ],
            "remaining_group_needs": {"地面阻挡": 1, "高台输出": 2},
        }),
        ("/decide/skill_selection", {
            "operator": "棘刺", "occasion": "promote",
            "skills": [{"index": 1}, {"index": 2}, {"index": 3}],
            "current_roster_summary": "队伍 3 人",
        }),
        ("/decide/pre_battle_team", {
            "stage_name": "丛林密布", "formation_limit": 6,
            "full_roster": [
                {"name": "棘刺", "elite": 2, "level": 60, "groups": ["地面阻挡"]},
                {"name": "维什戴尔", "elite": 2, "level": 60, "groups": ["益达"]},
            ],
            "stage_required_groups": ["地面阻挡", "高台输出"],
        }),
        ("/decide/encounter", {
            "floor": 3, "hope": 7, "hp": 4, "vision": 5,
            "event_name_ocr": "随到随取",
            "options_ocr": ["开锁查看", "使用热像仪"],
            "current_relics": [],
        }),
        ("/decide/shopping", {
            "floor": 2, "hope": 12,
            "shop_items": [
                {"name": "源石锭", "price": 3, "type": "currency"},
                {"name": "夜莺的歌声", "price": 8, "type": "relic"},
            ],
            "current_roster_summary": "队伍 4 人",
            "current_relics": [],
        }),
        ("/decide/map_node", {
            "floor": 4, "hope": 3, "hp": 3,
            "all_nodes_in_floor": [
                {"id": "n_a", "type": "battle", "reachable_now": True, "click_point": [340, 280]},
                {"id": "n_b", "type": "encounter", "reachable_now": True, "click_point": [620, 290]},
                {"id": "n_c", "type": "shop", "reachable_now": False, "click_point": [880, 270]},
            ],
            "planned_path_so_far": [],
            "current_roster_summary": "队伍 5 人",
        }),
        ("/decide/level_reward", {
            "floor": 3, "reward_type": "level_clear",
            "options": [
                {"index": 0, "kind": "relic", "name": "夜莺的歌声"},
                {"index": 1, "kind": "hope", "value": 3},
                {"index": 2, "kind": "skip"},
            ],
            "current_roster_summary": "队伍 6 人", "current_relics": [],
        }),
    ]

    failures = []
    for path, ctx in cases:
        r = post(path, {"session_id": sid, "screenshots": [""], "context": ctx})
        print(f"\n{path}\n  resp: {r}")
        if "action" not in r or "reasoning" not in r:
            failures.append((path, r))

    end = post("/session/end", {"session_id": sid, "outcome": "abandon", "floor_reached": 3})
    print("\nsession end:", end)

    if failures:
        print("\nFAILURES:")
        for p, r in failures:
            print(f"  {p}: {r}")
        return 1
    print("\n✅ all 8 decision endpoints OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
