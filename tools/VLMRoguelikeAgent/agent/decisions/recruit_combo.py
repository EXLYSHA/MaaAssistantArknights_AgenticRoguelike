from .base import BaseHandler, DecisionRequest
from ..session import Session


class RecruitComboHandler(BaseHandler):
    """招募组合（Roles）选择 —— 肉鸽开局选职业偏好/招募池。"""

    endpoint = "/decide/recruit_combo"
    prompt_name = "recruit_combo"
    required_by_action = {"pick": []}

    def mock_decide(self, session: Session, req: DecisionRequest) -> dict:
        return {
            "action": "pick",
            "screenshot_index": 0,
            "slot_index": 1,
            "combo_name": "",
            "reasoning": "[MOCK] 默认选第 1 张截图第 2 个招募组合",
            "confidence": 0.5,
        }

    def build_user_text(self, session: Session, req: DecisionRequest) -> str:
        ctx = req.context
        return (
            f"目标: {session.goal_hint}\n"
            f"已选分队: {ctx.get('squad') or session.squad or '未知'}\n"
            f"截图数量: {ctx.get('screenshot_count')}\n"
            f"每张截图最多卡片数: {ctx.get('slots_per_screenshot', 4)}\n"
            f"可视槽位: {ctx.get('visual_slots')}\n"
            f"OCR 辅助文字（可能不完整/误识别，仅作参考）: {ctx.get('ocr_candidates')}\n"
            f"额外指令: {ctx.get('instruction', '')}\n"
            "请通过观察截图判断每个招募组合卡片的图标/描述，挑选一个最贴合本次目标和阵容方向的，"
            "返回 screenshot_index + slot_index（必填），combo_name 可选。"
        )

    def repair_decision(self, session: Session, req: DecisionRequest, decision: dict) -> dict:
        if decision.get("action") != "pick":
            return decision
        ctx = req.context
        screenshot_count = self._coerce_int(ctx.get("screenshot_count")) or 1
        slots_per_screenshot = self._coerce_int(ctx.get("slots_per_screenshot")) or 4
        # 单图场景下允许省略 screenshot_index
        if "screenshot_index" not in decision or decision.get("screenshot_index") is None:
            decision["screenshot_index"] = 0
        screenshot_index = self._coerce_int(decision.get("screenshot_index"))
        slot_index = self._coerce_int(decision.get("slot_index"))
        if slot_index is None:
            return self._fallback_decision(session, req, "recruit_combo 缺少 slot_index")
        if screenshot_index is None or screenshot_index < 0 or screenshot_index >= screenshot_count:
            return self._fallback_decision(session, req, "recruit_combo 截图编号越界")
        if slot_index < 0 or slot_index >= slots_per_screenshot:
            return self._fallback_decision(session, req, "recruit_combo 槽位编号越界")
        decision["screenshot_index"] = screenshot_index
        decision["slot_index"] = slot_index
        return decision

    def tool_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["pick"]},
                "screenshot_index": {"type": "integer", "minimum": 0},
                "slot_index": {"type": "integer", "minimum": 0},
                "combo_name": {"type": "string"},
                "reasoning": {"type": "string"},
                "confidence": {"type": "number"},
            },
            "required": ["action", "reasoning", "confidence"],
        }
