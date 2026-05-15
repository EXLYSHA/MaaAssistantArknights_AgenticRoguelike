from .base import BaseHandler, DecisionRequest
from ..session import Session


_PREF = {"shop": 4, "safehouse": 5, "encounter": 3, "battle": 2, "elite": 1, "boss": 6}


class MapNodeHandler(BaseHandler):
    endpoint = "/decide/map_node"
    prompt_name = "map_node"
    required_by_action = {
        "goto": ["node_id"],
        "inspect": ["target"],
    }

    def mock_decide(self, session: Session, req: DecisionRequest) -> dict:
        ctx = req.context
        nodes = ctx.get("all_nodes_in_floor", [])
        nodes = [n for n in nodes if isinstance(n, dict)]
        reachable = [n for n in nodes if n.get("reachable_now")]
        if not reachable:
            reachable = nodes
        if not reachable:
            return {
                "action": "goto",
                "node_id": "",
                "planned_path_next": [],
                "reasoning": "[MOCK] 无可用节点",
                "confidence": 0.0,
            }
        # HP 低优先 safehouse > shop > encounter > battle
        hp = ctx.get("hp", 99)
        if hp <= 3:
            order = ["safehouse", "shop", "encounter", "battle", "elite", "boss"]
        else:
            order = ["battle", "elite", "encounter", "shop", "safehouse", "boss"]
        reachable.sort(key=lambda n: order.index(n.get("type", "battle"))
                       if n.get("type") in order else 99)
        pick = reachable[0]

        return {
            "action": "goto",
            "node_id": pick["id"],
            "planned_path_next": [pick["id"]],
            "reasoning": f"[MOCK] HP={hp} 选 {pick.get('type')}",
            "confidence": 0.5,
        }

    def build_user_text(self, session: Session, req: DecisionRequest) -> str:
        ctx = req.context
        return (
            f"楼层 {ctx.get('floor')} 希望 {ctx.get('hope')} HP {ctx.get('hp')}\n"
            f"整层节点: {ctx.get('all_nodes_in_floor')}\n"
            f"已走过: {ctx.get('planned_path_so_far')}\n"
            f"上次规划路径: {session.planned_path}\n"
            f"队伍: {ctx.get('current_roster_summary')}\n"
            "请选下一个可达节点的 id；若可规划后续路径请填 planned_path_next。"
        )

    def update_session(self, session: Session, req: DecisionRequest, decision: dict) -> None:
        if decision.get("action") != "goto":
            return
        planned = decision.get("planned_path_next")
        if isinstance(planned, list):
            session.planned_path = [str(node_id) for node_id in planned if node_id]
        elif decision.get("node_id"):
            session.planned_path.append(str(decision["node_id"]))

    def repair_decision(self, session: Session, req: DecisionRequest, decision: dict) -> dict:
        if decision.get("action") != "goto":
            return decision
        nodes = [n for n in req.context.get("all_nodes_in_floor", []) if isinstance(n, dict)]
        reachable_ids = {n.get("id") for n in nodes if n.get("reachable_now")}
        if not reachable_ids:
            reachable_ids = {n.get("id") for n in nodes}
        if reachable_ids and decision.get("node_id") not in reachable_ids:
            return self._fallback_decision(session, req, "地图节点不可达或不存在")
        decision["planned_path_next"] = [
            node_id
            for node_id in decision.get("planned_path_next", [])
            if node_id in {n.get("id") for n in nodes}
        ]
        return decision

    def tool_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["goto", "inspect"]},
                "node_id": {"type": "string"},
                "planned_path_next": {"type": "array", "items": {"type": "string"}},
                "target": {"type": "object"},
                "reasoning": {"type": "string"},
                "confidence": {"type": "number"},
            },
            "required": ["action", "reasoning", "confidence"],
        }
