from .base import BaseHandler, DecisionRequest
from ..knowledge_loader import relic_brief
from ..session import Session


class ShoppingHandler(BaseHandler):
    endpoint = "/decide/shopping"
    prompt_name = "shopping"
    required_by_action = {
        "buy_list": ["purchases"],
        "inspect": ["target"],
    }

    def mock_decide(self, session: Session, req: DecisionRequest) -> dict:
        ctx = req.context
        hope = ctx.get("hope", 0)
        items = ctx.get("shop_items", [])
        purchases: list[int] = []
        for i, it in enumerate(items):
            if not isinstance(it, dict):
                continue
            price = it.get("price", 0)
            if isinstance(price, int) and price <= hope:
                purchases.append(i)
                hope -= price
        return {
            "action": "buy_list",
            "purchases": purchases,
            "reasoning": "[MOCK] 贪心从前往后买能买的",
            "confidence": 0.4,
        }

    def build_user_text(self, session: Session, req: DecisionRequest) -> str:
        ctx = req.context
        items = ctx.get("shop_items") or []
        item_relics = [
            str(item.get("name"))
            for item in items
            if isinstance(item, dict) and item.get("type") == "relic" and item.get("name")
        ]
        current_relics = ctx.get("current_relics") or session.relics
        relics_text = relic_brief(current_relics + item_relics) or "（PRTS 没找到这些藏品资料）"
        return (
            f"楼层 {ctx.get('floor')} 希望 {ctx.get('hope')}\n"
            f"商品: {ctx.get('shop_items')}\n"
            f"队伍: {ctx.get('current_roster_summary')}\n"
            f"藏品: {current_relics}\n"
            f"PRTS 相关藏品效果（**必读**）:\n{relics_text}\n"
            "决策步骤：\n"
            "1) 通读上面 PRTS 资料；\n"
            "2) 对每个考虑买的藏品，在 reasoning 里**显式引用** PRTS 对应条目里的效果描述，解释为何要买；\n"
            "3) 返回要买的商品下标列表（按购买顺序，可空）。"
        )

    def update_session(self, session: Session, req: DecisionRequest, decision: dict) -> None:
        if decision.get("action") != "buy_list":
            return
        items = req.context.get("shop_items") or []
        remaining_hope = session.hope
        for idx in decision.get("purchases") or []:
            if not isinstance(idx, int) or idx < 0 or idx >= len(items) or not isinstance(items[idx], dict):
                continue
            item = items[idx]
            price = item.get("price", 0)
            if isinstance(price, int):
                remaining_hope -= price
            if item.get("type") == "relic" and item.get("name"):
                session.add_relic(str(item["name"]))
            elif item.get("type") == "promote" and item.get("operator"):
                session.add_or_update_operator({"name": item["operator"], "elite": 2})
        session.hope = max(0, remaining_hope)

    def repair_decision(self, session: Session, req: DecisionRequest, decision: dict) -> dict:
        if decision.get("action") != "buy_list":
            return decision
        items = req.context.get("shop_items") or []
        valid: list[int] = []
        remaining_hope = session.hope
        for idx in decision.get("purchases", []):
            if not isinstance(idx, int) or idx < 0 or idx >= len(items) or not isinstance(items[idx], dict):
                continue
            price = items[idx].get("price", 0)
            if isinstance(price, int) and price <= remaining_hope:
                valid.append(idx)
                remaining_hope -= price
        decision["purchases"] = valid
        if valid:
            reasoning = str(decision.get("reasoning") or "")
            if len(reasoning) < 30:
                return self._fallback_decision(
                    session, req,
                    "购物 reasoning 太短，必须基于 PRTS 藏品资料解释为何买（>=30 字符）",
                )
        return decision

    def tool_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["buy_list", "inspect"]},
                "purchases": {"type": "array", "items": {"type": "integer"}},
                "target": {"type": "object"},
                "reasoning": {"type": "string"},
                "confidence": {"type": "number"},
            },
            "required": ["action", "reasoning", "confidence"],
        }
