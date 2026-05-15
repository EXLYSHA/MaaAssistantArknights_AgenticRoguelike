from .base import BaseHandler, DecisionRequest
from ..knowledge_loader import operators_brief, relic_brief
from ..session import Session


class LevelRewardHandler(BaseHandler):
    endpoint = "/decide/level_reward"
    prompt_name = "level_reward"
    required_by_action = {
        "pick": ["option_index"],
        "inspect": ["target"],
    }

    def mock_decide(self, session: Session, req: DecisionRequest) -> dict:
        opts = req.context.get("options", [])
        # 优先 relic > operator_recruit > hope > skip
        order = ["relic", "operator_recruit", "hope", "skip"]
        best = 0
        for i, o in enumerate(opts):
            if not isinstance(o, dict):
                continue
            cur_rank = order.index(o.get("kind", "skip")) if o.get("kind", "skip") in order else len(order)
            best_kind = opts[best].get("kind", "skip") if isinstance(opts[best], dict) else "skip"
            best_rank = order.index(best_kind) if best_kind in order else len(order)
            if cur_rank < best_rank:
                best = i
        picked = opts[best] if opts and isinstance(opts[best], dict) else {}
        return {
            "action": "pick",
            "option_index": picked.get("index", 0),
            "reasoning": "[MOCK] relic > recruit > hope > skip",
            "confidence": 0.5,
        }

    def build_user_text(self, session: Session, req: DecisionRequest) -> str:
        ctx = req.context
        options = ctx.get("options") or []
        option_relics = [
            str(opt.get("name"))
            for opt in options
            if isinstance(opt, dict) and opt.get("kind") == "relic" and opt.get("name")
        ]
        option_operators = [
            str(opt.get("name"))
            for opt in options
            if isinstance(opt, dict) and opt.get("kind") == "operator_recruit" and opt.get("name")
        ]
        current_relics = ctx.get("current_relics") or session.relics
        return (
            f"奖励类型: {ctx.get('reward_type')} 楼层 {ctx.get('floor')}\n"
            f"选项: {ctx.get('options')}\n"
            f"队伍: {ctx.get('current_roster_summary')} 藏品: {current_relics}\n"
            f"相关藏品效果:\n{relic_brief(current_relics + option_relics) or '无'}\n"
            f"可选干员 PRTS 摘要:\n{operators_brief(option_operators, limit=4) or '无'}\n"
            "请选下标。"
        )

    def update_session(self, session: Session, req: DecisionRequest, decision: dict) -> None:
        if decision.get("action") != "pick":
            return
        options = req.context.get("options") or []
        picked_index = decision.get("option_index")
        picked = next(
            (
                opt
                for opt in options
                if isinstance(opt, dict) and opt.get("index") == picked_index
            ),
            None,
        )
        if not picked:
            return
        if picked.get("kind") == "relic" and picked.get("name"):
            session.add_relic(str(picked["name"]))
        elif picked.get("kind") == "operator_recruit" and picked.get("name"):
            session.add_or_update_operator({"name": picked["name"]})
        elif picked.get("kind") == "hope" and isinstance(picked.get("value"), int):
            session.hope += picked["value"]

    def repair_decision(self, session: Session, req: DecisionRequest, decision: dict) -> dict:
        if decision.get("action") != "pick":
            return decision
        valid_indices = {
            opt.get("index")
            for opt in req.context.get("options", [])
            if isinstance(opt, dict) and isinstance(opt.get("index"), int)
        }
        if valid_indices and decision.get("option_index") not in valid_indices:
            return self._fallback_decision(session, req, "奖励选项下标越界")
        return decision

    def tool_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["pick", "inspect"]},
                "option_index": {"type": "integer"},
                "target": {"type": "object"},
                "reasoning": {"type": "string"},
                "confidence": {"type": "number"},
            },
            "required": ["action", "reasoning", "confidence"],
        }
