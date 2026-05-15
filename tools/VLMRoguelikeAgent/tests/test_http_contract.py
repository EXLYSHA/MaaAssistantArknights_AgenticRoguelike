"""Server route-function contract test without opening a real TCP socket."""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("VLM_MOCK", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.decisions.base import DecisionRequest
from server import (
    SessionEndReq,
    SessionStartReq,
    decide_encounter,
    decide_map,
    decide_recruit,
    decide_reward,
    decide_shopping,
    decide_skill,
    decide_squad,
    decide_team,
    health,
    session_end,
    session_start,
)


def main() -> int:
    assert health()["ok"]

    started = session_start(SessionStartReq(theme="Sarkaz", mode=30001, difficulty=15))
    sid = started.session_id

    cases = [
            (
                decide_squad,
                {
                    "available_squads": ["蓝图测绘分队", "心胜于物分队", "生活至上分队"],
                },
            ),
            (
                decide_recruit,
                {
                    "floor": 1,
                    "hope": 5,
                    "is_start_recruit": True,
                    "current_roster": [],
                    "candidates": [
                        {"name": "棘刺", "elite": 2, "level": 60, "groups": ["地面阻挡", "棘刺"]},
                        {"name": "维什戴尔", "elite": 2, "level": 60, "groups": ["高台输出"]},
                    ],
                    "remaining_group_needs": {"地面阻挡": 1, "高台输出": 2},
                },
            ),
            (
                decide_skill,
                {
                    "operator": "棘刺",
                    "occasion": "promote",
                    "skills": [{"index": 1}, {"index": 2}, {"index": 3}],
                    "current_roster_summary": "队伍 3 人",
                },
            ),
            (
                decide_team,
                {
                    "stage_name": "丛林密布",
                    "formation_limit": 6,
                    "full_roster": [
                        {"name": "棘刺", "elite": 2, "level": 60, "groups": ["地面阻挡"]},
                        {"name": "维什戴尔", "elite": 2, "level": 60, "groups": ["高台输出"]},
                    ],
                    "stage_required_groups": ["地面阻挡", "高台输出"],
                },
            ),
            (
                decide_encounter,
                {
                    "floor": 3,
                    "hope": 7,
                    "hp": 4,
                    "vision": 5,
                    "event_name_ocr": "随到随取",
                    "options_ocr": ["开锁查看", "使用热像仪"],
                    "current_relics": [],
                },
            ),
            (
                decide_shopping,
                {
                    "floor": 2,
                    "hope": 12,
                    "shop_items": [
                        {"name": "源石锭", "price": 3, "type": "currency"},
                        {"name": "夜莺的歌声", "price": 8, "type": "relic"},
                    ],
                    "current_roster_summary": "队伍 4 人",
                    "current_relics": [],
                },
            ),
            (
                decide_map,
                {
                    "floor": 4,
                    "hope": 3,
                    "hp": 3,
                    "all_nodes_in_floor": [
                        {"id": "n_a", "type": "battle", "reachable_now": True, "click_point": [340, 280]},
                        {"id": "n_b", "type": "encounter", "reachable_now": True, "click_point": [620, 290]},
                        {"id": "n_c", "type": "shop", "reachable_now": False, "click_point": [880, 270]},
                    ],
                    "planned_path_so_far": [],
                    "current_roster_summary": "队伍 5 人",
                },
            ),
            (
                decide_reward,
                {
                    "floor": 3,
                    "reward_type": "level_clear",
                    "options": [
                        {"index": 0, "kind": "relic", "name": "夜莺的歌声"},
                        {"index": 1, "kind": "hope", "value": 3},
                        {"index": 2, "kind": "skip"},
                    ],
                    "current_roster_summary": "队伍 6 人",
                    "current_relics": [],
                },
            ),
    ]

    for route_func, context in cases:
        payload = route_func(DecisionRequest(session_id=sid, screenshots=[""], context=context))
        assert "action" in payload and "reasoning" in payload and "confidence" in payload, payload

    ended = session_end(SessionEndReq(session_id=sid, outcome="abandon", floor_reached=3))
    assert ended["ok"] is True

    print("all server route contract checks OK", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
