from .base import BaseHandler, DecisionRequest
from ..knowledge_loader import global_group_brief
from ..session import Session


class SquadHandler(BaseHandler):
    endpoint = "/decide/squad"
    prompt_name = "squad"
    required_by_action = {"pick": []}

    def mock_decide(self, session: Session, req: DecisionRequest) -> dict:
        squads = req.context.get("available_squads", [])
        pick = squads[0] if squads else "蓝图测绘分队"
        decision = {
            "action": "pick",
            "squad_name": pick,
            "reasoning": f"[MOCK] 选第一个可用分队 {pick}",
            "confidence": 1.0,
        }
        if req.context.get("selection_mode") == "visual_slots":
            decision["screenshot_index"] = 0
            decision["slot_index"] = 0
            decision["reasoning"] = "[MOCK] 选择第 1 张截图第 1 个可视分队槽位"
        return decision

    def build_user_text(self, session: Session, req: DecisionRequest) -> str:
        ctx = req.context
        if ctx.get("selection_mode") == "visual_slots":
            return (
                f"目标: {session.goal_hint}\n"
                f"萨卡兹常见关键分组: {global_group_brief()}\n"
                f"选择模式: visual_slots\n"
                f"截图数量: {ctx.get('screenshot_count')}\n"
                f"每张截图完整分队卡片槽位数: {ctx.get('slots_per_screenshot', 4)}\n"
                f"可选视觉槽位: {ctx.get('visual_slots')}\n"
                f"OCR 识别到的可能可用分队（仅辅助，可能漏识别/误识别）: {ctx.get('available_squads')}\n"
                f"OCR 识别到的未解锁分队（禁止选择）: {ctx.get('locked_squads', [])}\n"
                f"用户偏好: {ctx.get('user_hint', '无')}\n"
                f"额外指令: {ctx.get('instruction', '')}\n"
                "请优先看截图本身，不要依赖 OCR 列表。选择一个没有锁图标、没有“解锁条件”的完整分队卡片，"
                "返回对应 screenshot_index 和 slot_index；如果卡片名称能看清，再附带 squad_name。"
            )
        return (
            f"目标: {session.goal_hint}\n"
            f"萨卡兹常见关键分组: {global_group_brief()}\n"
            f"可选分队（已过滤为当前可点击/未上锁）: {ctx.get('available_squads')}\n"
            f"已识别但未解锁的分队（禁止选择）: {ctx.get('locked_squads', [])}\n"
            f"用户偏好: {ctx.get('user_hint', '无')}\n"
            "请只从可选分队列表中逐字选择一个最适合本目标的分队。"
        )

    def update_session(self, session: Session, req: DecisionRequest, decision: dict) -> None:
        squad_name = decision.get("squad_name")
        if squad_name:
            session.squad = str(squad_name)

    def repair_decision(self, session: Session, req: DecisionRequest, decision: dict) -> dict:
        ctx = req.context
        squads = req.context.get("available_squads") or []
        locked = set(ctx.get("locked_squads") or [])

        if decision.get("action") == "pick" and ctx.get("selection_mode") == "visual_slots":
            screenshot_index = self._coerce_int(decision.get("screenshot_index"))
            slot_index = self._coerce_int(decision.get("slot_index"))
            screenshot_count = self._coerce_int(ctx.get("screenshot_count")) or 0
            slots_per_screenshot = self._coerce_int(ctx.get("slots_per_screenshot")) or 4
            if screenshot_index is None or slot_index is None:
                return self._fallback_decision(session, req, "visual_slots 缺少截图或槽位编号")
            if screenshot_index < 0 or screenshot_index >= screenshot_count:
                return self._fallback_decision(session, req, "visual_slots 截图编号越界")
            if slot_index < 0 or slot_index >= slots_per_screenshot:
                return self._fallback_decision(session, req, "visual_slots 槽位编号越界")
            decision["screenshot_index"] = screenshot_index
            decision["slot_index"] = slot_index
            return decision

        if decision.get("action") == "pick" and decision.get("squad_name") in locked:
            return self._fallback_decision(session, req, "分队未解锁")
        if decision.get("action") == "pick" and squads and decision.get("squad_name") not in squads:
            return self._fallback_decision(session, req, "分队不在可选列表中")
        return decision

    def tool_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["pick"]},
                "squad_name": {"type": "string", "description": "能看清时填写分队名称；visual_slots 模式可为空或省略"},
                "screenshot_index": {
                    "type": "integer",
                    "description": "visual_slots 模式下选择的截图编号，从 0 开始",
                },
                "slot_index": {
                    "type": "integer",
                    "description": "visual_slots 模式下该截图内从左到右的完整卡片槽位编号，从 0 开始",
                    "minimum": 0,
                },
                "reasoning": {"type": "string"},
                "confidence": {"type": "number"},
            },
            "required": ["action", "reasoning", "confidence"],
        }
