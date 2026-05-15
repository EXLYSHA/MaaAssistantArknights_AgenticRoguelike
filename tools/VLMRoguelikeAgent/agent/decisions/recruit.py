from .base import BaseHandler, DecisionRequest
from ..knowledge_loader import global_group_brief, operators_brief
from ..session import Session


class RecruitHandler(BaseHandler):
    endpoint = "/decide/recruit"
    prompt_name = "recruit"
    required_by_action = {
        "pick": ["pick_index"],
        "inspect": ["target"],
    }

    def mock_decide(self, session: Session, req: DecisionRequest) -> dict:
        cands = req.context.get("candidates", [])
        needs = req.context.get("remaining_group_needs", {}) or {}

        # 简单 mock 策略：优先选所属 group 在 needs 中出现的候选
        best_idx = 0
        best_score = -1
        for i, c in enumerate(cands):
            if not isinstance(c, dict):
                continue
            score = sum(needs.get(g, 0) for g in c.get("groups", []))
            if score > best_score:
                best_score = score
                best_idx = i

        if not cands:
            return {
                "action": "skip",
                "pick_index": -1,
                "reasoning": "[MOCK] 无候选",
                "confidence": 1.0,
            }
        return {
            "action": "pick",
            "pick_index": best_idx,
            "reasoning": f"[MOCK] 按 group 需求匹配选 idx={best_idx}",
            "confidence": 0.7,
        }

    def build_user_text(self, session: Session, req: DecisionRequest) -> str:
        ctx = req.context
        cands = ctx.get("candidates") or []
        candidate_names = [str(cand.get("name", "")) for cand in cands if isinstance(cand, dict)]
        roster_names = [
            str(op.get("name", ""))
            for op in (ctx.get("current_roster") or [])
            if isinstance(op, dict)
        ]
        return (
            f"楼层: {ctx.get('floor')} 希望: {ctx.get('hope')}\n"
            f"当前队伍: {ctx.get('current_roster')}\n"
            f"候选: {ctx.get('candidates')}\n"
            f"剩余分组需求: {ctx.get('remaining_group_needs')}\n"
            f"萨卡兹常见关键分组: {global_group_brief()}\n"
            f"候选干员 PRTS 摘要:\n{operators_brief(candidate_names, limit=8) or '无'}\n"
            f"现役核心 PRTS 摘要:\n{operators_brief(roster_names, limit=6, per_operator_chars=500) or '无'}\n"
            "请从候选中挑一个最有价值的，或返回 skip。"
        )

    def update_session(self, session: Session, req: DecisionRequest, decision: dict) -> None:
        if decision.get("action") != "pick":
            return
        candidates = req.context.get("candidates") or []
        idx = decision.get("pick_index")
        if isinstance(idx, int) and 0 <= idx < len(candidates) and isinstance(candidates[idx], dict):
            session.add_or_update_operator(candidates[idx])

    def repair_decision(self, session: Session, req: DecisionRequest, decision: dict) -> dict:
        if decision.get("action") != "pick":
            return decision
        candidates = req.context.get("candidates") or []
        idx = decision.get("pick_index")
        if not isinstance(idx, int) or idx < 0 or idx >= len(candidates):
            return self._fallback_decision(session, req, "招募下标越界")
        return decision

    def tool_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["pick", "skip", "refresh", "inspect"]},
                "pick_index": {"type": "integer"},
                "target": {"type": "object"},
                "reasoning": {"type": "string"},
                "confidence": {"type": "number"},
            },
            "required": ["action", "reasoning", "confidence"],
        }
