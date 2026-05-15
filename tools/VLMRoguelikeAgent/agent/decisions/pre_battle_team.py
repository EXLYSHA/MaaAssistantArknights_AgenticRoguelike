from .base import BaseHandler, DecisionRequest
from ..knowledge_loader import operators_brief, stage_group_brief
from ..session import Session


class PreBattleTeamHandler(BaseHandler):
    endpoint = "/decide/pre_battle_team"
    prompt_name = "pre_battle_team"
    required_by_action = {
        "form": ["selected"],
        "inspect": ["target"],
    }

    def mock_decide(self, session: Session, req: DecisionRequest) -> dict:
        ctx = req.context
        roster = ctx.get("full_roster", [])
        limit = ctx.get("formation_limit", 6)
        selected = [op["name"] for op in roster[:limit] if isinstance(op, dict) and op.get("name")]
        return {
            "action": "form",
            "selected": selected,
            "reasoning": f"[MOCK] 取前 {limit} 个干员",
            "confidence": 0.5,
        }

    def build_user_text(self, session: Session, req: DecisionRequest) -> str:
        ctx = req.context
        stage_name = str(ctx.get("stage_name") or "")
        roster_names = [
            str(op.get("name", ""))
            for op in (ctx.get("full_roster") or [])
            if isinstance(op, dict)
        ]
        return (
            f"关卡: {stage_name}\n"
            f"编队上限: {ctx.get('formation_limit')}\n"
            f"完整队伍: {ctx.get('full_roster')}\n"
            f"该关卡需要分组: {ctx.get('stage_required_groups')}\n"
            f"知识库关卡分组需求:\n{stage_group_brief(stage_name) or '无'}\n"
            f"队伍干员 PRTS 摘要:\n{operators_brief(roster_names, limit=14, per_operator_chars=520) or '无'}\n"
            "请从队伍中选不超过编队上限的干员上场，覆盖关卡所需职能。"
        )

    def repair_decision(self, session: Session, req: DecisionRequest, decision: dict) -> dict:
        if decision.get("action") != "form":
            return decision
        roster_names = {
            op.get("name")
            for op in req.context.get("full_roster", [])
            if isinstance(op, dict) and op.get("name")
        }
        limit = req.context.get("formation_limit", 6)
        limit = limit if isinstance(limit, int) and limit > 0 else 6
        selected = [
            name
            for name in decision.get("selected", [])
            if isinstance(name, str) and name in roster_names
        ][:limit]
        if not selected and roster_names:
            return self._fallback_decision(session, req, "编队结果不在队伍名单中")
        decision["selected"] = selected
        return decision

    def tool_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["form", "inspect"]},
                "selected": {"type": "array", "items": {"type": "string"}},
                "target": {"type": "object"},
                "reasoning": {"type": "string"},
                "confidence": {"type": "number"},
            },
            "required": ["action", "reasoning", "confidence"],
        }
