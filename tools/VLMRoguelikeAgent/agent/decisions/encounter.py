from .base import BaseHandler, DecisionRequest
from ..knowledge_loader import relic_brief
from ..session import Session


class EncounterHandler(BaseHandler):
    endpoint = "/decide/encounter"
    prompt_name = "encounter"
    required_by_action = {
        "choose": ["option_index"],
        "inspect": ["target"],
    }

    def mock_decide(self, session: Session, req: DecisionRequest) -> dict:
        opts = req.context.get("options_ocr", [])
        idx = 0 if opts else 0
        return {
            "action": "choose",
            "option_index": idx,
            "reasoning": "[MOCK] 默认第一项",
            "confidence": 0.5,
        }

    def build_user_text(self, session: Session, req: DecisionRequest) -> str:
        ctx = req.context
        current_relics = ctx.get("current_relics") or session.relics
        return (
            f"事件: {ctx.get('event_name_ocr')}\n"
            f"楼层 {ctx.get('floor')} 希望 {ctx.get('hope')} HP {ctx.get('hp')} 视野 {ctx.get('vision')}\n"
            f"选项: {ctx.get('options_ocr')}\n"
            f"当前藏品: {current_relics}\n"
            f"当前藏品效果:\n{relic_brief(current_relics) or '无'}\n"
            "请选编号（0 起算）。"
        )

    def repair_decision(self, session: Session, req: DecisionRequest, decision: dict) -> dict:
        if decision.get("action") != "choose":
            return decision
        options = req.context.get("options_ocr") or []
        idx = decision.get("option_index")
        if options and (not isinstance(idx, int) or idx < 0 or idx >= len(options)):
            return self._fallback_decision(session, req, "事件选项下标越界")
        return decision

    def tool_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["choose", "inspect"]},
                "option_index": {"type": "integer"},
                "target": {"type": "object"},
                "reasoning": {"type": "string"},
                "confidence": {"type": "number"},
            },
            "required": ["action", "reasoning", "confidence"],
        }
