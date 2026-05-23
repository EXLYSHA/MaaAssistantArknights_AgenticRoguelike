from .base import BaseHandler, DecisionRequest
from ..knowledge_loader import operator_brief
from ..session import Session


class SkillSelectionHandler(BaseHandler):
    endpoint = "/decide/skill_selection"
    prompt_name = "skill_selection"
    required_by_action = {
        "pick": ["skill_index"],
        "inspect": ["target"],
    }

    def mock_decide(self, session: Session, req: DecisionRequest) -> dict:
        return {
            "action": "pick",
            "skill_index": 3,
            "reasoning": "[MOCK] 默认选择技能 3",
            "confidence": 0.5,
        }

    def build_user_text(self, session: Session, req: DecisionRequest) -> str:
        ctx = req.context
        operator = str(ctx.get("operator") or "")
        prts = operator_brief(operator) or "（PRTS 上没找到该干员资料，请直接看截图判断）"
        return (
            f"干员: {operator}\n"
            f"场景: {ctx.get('occasion')}\n"
            f"技能选项: {ctx.get('skills')}\n"
            f"PRTS 干员知识（必须先读再决策）:\n{prts}\n"
            f"当前队伍: {ctx.get('current_roster_summary')}\n"
            "决策步骤：\n"
            "1) 通读上面 PRTS 资料里关于该干员各技能的描述与定位；\n"
            "2) 在 reasoning 里**显式引用** PRTS 资料中至少一项你看到的关键事实"
            "（如某技能的伤害类型、机制、推荐场景），并解释为何选这个技能；\n"
            "3) 给出 skill_index (1/2/3)。\n"
            "技能描述可能 OCR 不全，请同时结合截图。"
        )

    def repair_decision(self, session: Session, req: DecisionRequest, decision: dict) -> dict:
        if decision.get("action") != "pick":
            return decision
        available = {
            item.get("index")
            for item in req.context.get("skills", [])
            if isinstance(item, dict) and isinstance(item.get("index"), int)
        } or {1, 2, 3}
        if decision.get("skill_index") not in available:
            return self._fallback_decision(session, req, "技能编号不在可选列表中")
        reasoning = str(decision.get("reasoning") or "")
        if len(reasoning) < 30:
            return self._fallback_decision(
                session, req,
                "技能选择的 reasoning 太短，必须基于 PRTS 资料解释为何选该技能（>=30 字符）",
            )
        return decision

    def tool_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["pick", "inspect"]},
                "skill_index": {"type": "integer", "enum": [1, 2, 3]},
                "target": {"type": "object"},
                "reasoning": {"type": "string"},
                "confidence": {"type": "number"},
            },
            "required": ["action", "reasoning", "confidence"],
        }
