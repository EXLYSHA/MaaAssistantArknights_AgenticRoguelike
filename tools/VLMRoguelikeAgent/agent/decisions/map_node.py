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
        nodes = ctx.get("all_nodes_in_floor") or []
        reachable_ids = ctx.get("reachable_node_ids") or [
            n.get("id") for n in nodes if isinstance(n, dict) and n.get("reachable_now")
        ]
        # 仅给一个 id->click_point 映射（让模型把图上节点和 nXX 对应起来），
        # 不给文字化的有向图、铭牌 OCR——这些信息让模型直接从截图读，准确度更高。
        id_pos = []
        for n in nodes:
            if not isinstance(n, dict):
                continue
            id_pos.append({
                "id": n.get("id"),
                "click_point": n.get("click_point"),
                "depth": n.get("depth_from_start"),
                "reachable_now": n.get("reachable_now"),
            })

        return (
            "请直接看截图理解地图：从图标判断每个节点的关卡名/类型，从连线判断后继关系。\n"
            "**截图 UI 区域**（按位置精确读取）：\n"
            "  - 左上角：剩余生命值 HP（X/Y 形式） → 等级。\n"
            "  - 右上角：希望（金黄色双手图案 + 数字）、源石锭（绿色三角形图标 + 数字）。\n"
            "  - 左下角：收藏品入口（一般无需读数）。\n"
            "  - 右下角：思维负荷（X/Y）、**构想/思绪**（多边形图标下带数字）、干员、编队。\n"
            "**资源用途**：构想（右下）用于打开纵向通路/部分不期而遇（一般 2 构想/条），不足时绝不能选；"
            "源石锭（右上）购物；HP（左上）低时避战；思维负荷（右下）满了惩罚；希望（右上）招募。\n"
            "**严禁**选择当前资源不够进入的节点（典型例子：构想 < 节点要求时绝不点纵向通路 / 不期而遇）。\n"
            "你**必须**在响应里填好 observed_resources 五项（hp/hope/ingot/thoughts/construct），"
            "用截图实际读到的字符串。漏填或写空字符串都会被拒绝。\n"
            f"当前所在节点: {ctx.get('current_node_id', 'start')}\n"
            f"节点 id 与屏幕坐标对应（用于把 nXX 对到画面位置）:\n{id_pos}\n"
            f"当前**可走**的节点 id（必须从中选一个作为 node_id）: {reachable_ids}\n"
            f"已走过: {ctx.get('planned_path_so_far')}\n"
            f"上次规划路径: {session.planned_path}\n"
            f"队伍: {ctx.get('current_roster_summary')}\n"
            f"补充说明: {ctx.get('note', '')}\n"
            "决策步骤：\n"
            "1) 在截图上确认每个 nXX 是哪个具体节点（关卡名/图标）；\n"
            "2) **先填 observed_resources**：从截图读取 hp/hope/ingot/thoughts/construct 五个数值；\n"
            "3) 排除资源不够进入的节点：如果某节点是纵向通路/不期而遇且需要构想，且 construct 数值不够，绝对不要选；\n"
            "4) 在剩余可走节点里挑最优 node_id，沿连线规划 planned_path_next；\n"
            "5) reasoning 中必须显式提到 construct 数值，并说明该路径是否需要构想消耗。"
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
        # 强制读取并报告关键资源数值，避免模型不看数值就乱走
        observed = decision.get("observed_resources") or {}
        if not isinstance(observed, dict) or not all(
            k in observed for k in ("hp", "hope", "ingot", "thoughts", "construct")
        ):
            return self._fallback_decision(
                session, req,
                "必须在 observed_resources 里完整报告 hp/hope/ingot/thoughts/construct 五个数值，从截图读取",
            )
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
                "observed_resources": {
                    "type": "object",
                    "description": "从截图读取的关键资源数值；必须填全。",
                    "properties": {
                        "hp": {"type": "string", "description": "左上心形 X/Y，例如 '8/8'"},
                        "hope": {"type": "string", "description": "右上希望，例如 '4'"},
                        "ingot": {"type": "string", "description": "右上源石锭数量，例如 '8'"},
                        "thoughts": {"type": "string", "description": "右下思维负荷 X/Y，例如 '1/14'"},
                        "construct": {"type": "string", "description": "右下构想/思绪数字，例如 '0' 或 '2'"},
                    },
                    "required": ["hp", "hope", "ingot", "thoughts", "construct"],
                },
                "target": {"type": "object"},
                "reasoning": {"type": "string"},
                "confidence": {"type": "number"},
            },
            "required": ["action", "reasoning", "confidence"],
        }
