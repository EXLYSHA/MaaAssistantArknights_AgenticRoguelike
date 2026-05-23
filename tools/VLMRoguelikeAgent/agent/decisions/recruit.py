from .base import BaseHandler, DecisionRequest
from ..knowledge_loader import operators_brief
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
        if not cands:
            return {
                "action": "skip",
                "pick_index": -1,
                "reasoning": "[MOCK] 无候选",
                "confidence": 1.0,
            }
        # mock 默认选第一位
        return {
            "action": "pick",
            "pick_index": 0,
            "reasoning": "[MOCK] 选第一个候选",
            "confidence": 0.5,
        }

    def build_user_text(self, session: Session, req: DecisionRequest) -> str:
        ctx = req.context
        cands = ctx.get("candidates") or []
        # 仅展示候选基本身份信息（名字 / 精英 / 等级 / 翻页位置），
        # 不暴露 MAA 内部 priority、不暴露 sarkaz groups——这些会带偏 VLM。
        compact = []
        for c in cands:
            if not isinstance(c, dict):
                continue
            compact.append({
                "index": c.get("index"),
                "name": c.get("name"),
                "elite": c.get("elite"),
                "level": c.get("level"),
                "page_index": c.get("page_index"),
            })
        roster_summary = [
            {
                "name": op.get("name"),
                "elite": op.get("elite"),
                "level": op.get("level"),
            }
            for op in (ctx.get("current_roster") or [])
            if isinstance(op, dict)
        ]
        inspected_profiles = ctx.get("_inspected_profiles") or ""
        inspected_block = (
            f"\n已 inspect 干员的 PRTS 资料:\n{inspected_profiles}\n" if inspected_profiles else ""
        )
        return (
            f"是否开局招募: {ctx.get('is_start_recruit')} "
            f"（楼层/希望等数值请从截图自行读取，0 通常代表未更新而非真实值）\n"
            f"当前队伍: {roster_summary}\n"
            f"候选干员: {compact}\n"
            f"{inspected_block}"
            "你必须根据**自己**对干员强度、配置需求和当前队伍构成的判断来决策，"
            "不要依赖任何外部打分。\n"
            "如果对某些候选干员的能力不熟悉，请先发出 inspect："
            "  target = {\"kind\": \"operator_profile\", \"ref\": \"<干员名>\"}\n"
            "（每次决策最多 2 轮 inspect。inspect 命中后会在下一轮以 PRTS 资料形式追加上下文，"
            "你再据此决定 pick / skip / refresh。）\n"
            "若已经掌握足够信息，直接给出 pick + pick_index，或 skip / refresh。"
        )

    def handle(self, session: Session, req: DecisionRequest) -> dict:
        # 把 inspect 命中过的干员资料缓存进 context，供本轮 prompt 使用
        key = self.decision_key(req)
        inspected = session.inspected_operators.get(key) or []
        if inspected:
            req.context = dict(req.context)
            brief = operators_brief(inspected, limit=len(inspected), per_operator_chars=900)
            req.context["_inspected_profiles"] = brief
        return super().handle(session, req)

    def build_user_text_with_inspect(self, session: Session, req: DecisionRequest) -> str:
        # 备用：当前实现把 inspect 资料放在 context["_inspected_profiles"]，
        # build_user_text 中追加。
        return self.build_user_text(session, req)

    def update_session(self, session: Session, req: DecisionRequest, decision: dict) -> None:
        if decision.get("action") != "pick":
            return
        candidates = req.context.get("candidates") or []
        idx = decision.get("pick_index")
        if isinstance(idx, int) and 0 <= idx < len(candidates) and isinstance(candidates[idx], dict):
            session.add_or_update_operator(candidates[idx])

    def repair_decision(self, session: Session, req: DecisionRequest, decision: dict) -> dict:
        action = decision.get("action")
        if action == "inspect":
            target = decision.get("target") or {}
            if target.get("kind") == "operator_profile":
                ref = target.get("ref")
                if isinstance(ref, str) and ref:
                    key = self.decision_key(req)
                    bucket = session.inspected_operators.setdefault(key, [])
                    if ref not in bucket:
                        bucket.append(ref)
            return decision
        if action != "pick":
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
                "target": {
                    "type": "object",
                    "description": "inspect 时使用，kind=operator_profile, ref=干员名",
                    "properties": {
                        "kind": {"type": "string"},
                        "ref": {"type": "string"},
                    },
                },
                "reasoning": {"type": "string"},
                "confidence": {"type": "number"},
            },
            "required": ["action", "reasoning", "confidence"],
        }
