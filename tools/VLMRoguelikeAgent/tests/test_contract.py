"""Offline contract checks for the VLM roguelike decision handlers.

This test imports handlers directly, so it does not require a running HTTP server
or a real VLM API key.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("VLM_MOCK", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.decisions.base import DecisionRequest
from agent.decisions.encounter import EncounterHandler
from agent.decisions.level_reward import LevelRewardHandler
from agent.decisions.map_node import MapNodeHandler
from agent.decisions.pre_battle_team import PreBattleTeamHandler
from agent.decisions.recruit import RecruitHandler
from agent.decisions.shopping import ShoppingHandler
from agent.decisions.skill_selection import SkillSelectionHandler
from agent.decisions.squad import SquadHandler
from agent.session import store


def _req(session_id: str, context: dict) -> DecisionRequest:
    return DecisionRequest(session_id=session_id, screenshots=[""], context=context)


def main() -> int:
    session = store.create("Sarkaz", 30001, 15, "通关")
    sid = session.session_id

    cases = [
        (
            SquadHandler(),
            {
                "available_squads": ["蓝图测绘分队", "心胜于物分队", "生活至上分队"],
            },
            "pick",
        ),
        (
            RecruitHandler(),
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
            "pick",
        ),
        (
            SkillSelectionHandler(),
            {
                "operator": "棘刺",
                "occasion": "promote",
                "skills": [{"index": 1}, {"index": 2}, {"index": 3}],
                "current_roster_summary": "队伍 3 人",
            },
            "pick",
        ),
        (
            PreBattleTeamHandler(),
            {
                "stage_name": "丛林密布",
                "formation_limit": 6,
                "full_roster": [
                    {"name": "棘刺", "elite": 2, "level": 60, "groups": ["地面阻挡"]},
                    {"name": "维什戴尔", "elite": 2, "level": 60, "groups": ["高台输出"]},
                ],
                "stage_required_groups": ["地面阻挡", "高台输出"],
            },
            "form",
        ),
        (
            EncounterHandler(),
            {
                "floor": 3,
                "hope": 7,
                "hp": 4,
                "vision": 5,
                "event_name_ocr": "随到随取",
                "options_ocr": ["开锁查看", "使用热像仪"],
                "current_relics": ["夜莺的歌声"],
            },
            "choose",
        ),
        (
            ShoppingHandler(),
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
            "buy_list",
        ),
        (
            MapNodeHandler(),
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
            "goto",
        ),
        (
            LevelRewardHandler(),
            {
                "floor": 3,
                "reward_type": "level_clear",
                "options": [
                    {"index": 0, "kind": "relic", "name": "安玛的爱"},
                    {"index": 1, "kind": "hope", "value": 3},
                    {"index": 2, "kind": "skip"},
                ],
                "current_roster_summary": "队伍 6 人",
                "current_relics": [],
            },
            "pick",
        ),
    ]

    for handler, context, expected_action in cases:
        decision = handler.handle(session, _req(sid, context))
        assert decision["action"] == expected_action, (handler.endpoint, decision)
        assert isinstance(decision["reasoning"], str)
        assert 0.0 <= decision["confidence"] <= 1.0

    assert session.squad == "蓝图测绘分队"
    assert any(op.get("name") == "维什戴尔" for op in session.roster)
    assert "安玛的爱" in session.relics
    assert session.planned_path

    squad_handler = SquadHandler()
    locked_squad_req = _req(
        sid,
        {
            "available_squads": ["指挥分队"],
            "locked_squads": ["博闻广记分队"],
        },
    )
    locked_squad_raw = {
        "action": "pick",
        "squad_name": "博闻广记分队",
        "reasoning": "想选强力分队",
        "confidence": 0.9,
    }
    repaired = squad_handler.normalize_decision(session, locked_squad_req, locked_squad_raw)
    assert repaired["squad_name"] == "指挥分队"
    assert repaired["confidence"] <= 0.35

    visual_squad_req = _req(
        sid,
        {
            "selection_mode": "visual_slots",
            "screenshot_count": 2,
            "slots_per_screenshot": 4,
            "visual_slots": [
                {"screenshot_index": 0, "slot_index": 0, "click_point": [170, 445]},
                {"screenshot_index": 1, "slot_index": 2, "click_point": [740, 445]},
            ],
            "available_squads": ["指挥分队"],
            "locked_squads": ["博闻广记分队"],
        },
    )
    visual_squad_raw = {
        "action": "pick",
        "screenshot_index": "1",
        "slot_index": "2",
        "reasoning": "截图 1 的第 3 张完整卡没有锁图标",
        "confidence": 0.9,
    }
    visual_repaired = squad_handler.normalize_decision(session, visual_squad_req, visual_squad_raw)
    assert visual_repaired["screenshot_index"] == 1
    assert visual_repaired["slot_index"] == 2
    assert "squad_name" not in visual_repaired or visual_repaired["squad_name"] is None

    inspect_handler = SkillSelectionHandler()
    inspect_req = _req(
        sid,
        {
            "operator": "棘刺",
            "occasion": "pre_battle",
            "skills": [{"index": 1}, {"index": 2}, {"index": 3}],
        },
    )
    inspect_raw = {
        "action": "inspect",
        "target": {"kind": "operator_skill", "ref": "棘刺"},
        "reasoning": "需要看技能",
        "confidence": 0.8,
    }
    assert inspect_handler.normalize_decision(session, inspect_req, inspect_raw)["action"] == "inspect"
    assert inspect_handler.normalize_decision(session, inspect_req, inspect_raw)["action"] == "inspect"
    assert inspect_handler.normalize_decision(session, inspect_req, inspect_raw)["action"] == "pick"

    store.end(sid)
    print("all offline contract checks OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
