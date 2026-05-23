"""决策处理器基类。每个端点对应一个 handler。"""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from .. import debug_io
from .. import vlm_client
from ..knowledge_loader import sarkaz_overview
from ..session import Session


class DecisionRequest(BaseModel):
    session_id: str
    screenshots: list[str] = Field(default_factory=list, min_length=1)
    context: dict[str, Any] = Field(default_factory=dict)


class DecisionResponse(BaseModel):
    action: str
    reasoning: str = ""
    confidence: float = 0.0
    # 端点专属字段以 extra 形式附加
    model_config = {"extra": "allow"}


class BaseHandler:
    endpoint: str = "<override>"
    prompt_name: str = "<override>"
    required_by_action: dict[str, list[str]] = {}
    max_inspect_rounds: int = 2

    def mock_decide(self, session: Session, req: DecisionRequest) -> dict:
        """mock 模式下返回的固定决策。子类必须实现。"""
        raise NotImplementedError

    def build_user_text(self, session: Session, req: DecisionRequest) -> str:
        """构造发给 VLM 的用户消息文本（不含图）。子类实现。"""
        raise NotImplementedError

    def tool_schema(self) -> dict:
        """submit_decision 工具的 input schema。子类实现。"""
        raise NotImplementedError

    def update_session(self, session: Session, req: DecisionRequest, decision: dict) -> None:
        """决策成功后把确定性结果写入 session。子类按需覆盖。"""

    def repair_decision(self, session: Session, req: DecisionRequest, decision: dict) -> dict:
        """端点级范围校验/修正。子类按需覆盖。"""
        return decision

    def common_user_text(self, session: Session, req: DecisionRequest) -> str:
        recent = session.recent_log_text()
        parts = [
            "会话状态:",
            f"- 目标: {session.goal_hint}",
            f"- 难度: {session.difficulty}",
            f"- 分队: {session.squad or '未知'}",
            f"- 已招干员: {[op.get('name') for op in session.roster if op.get('name')]}",
            f"- 已有藏品: {session.relics}",
        ]
        if session.planned_path:
            parts.append(f"- 当前规划路径: {session.planned_path}")
        if recent:
            parts.append("最近决策:\n" + recent)
        return "\n".join(parts)

    def decision_key(self, req: DecisionRequest) -> str:
        """用于限制同一决策点 inspect 轮数。"""
        ctx = req.context
        stable = {
            "endpoint": self.endpoint,
            "floor": ctx.get("floor"),
            "stage_name": ctx.get("stage_name"),
            "event_name_ocr": ctx.get("event_name_ocr"),
            "operator": ctx.get("operator"),
            "reward_type": ctx.get("reward_type"),
            "options": ctx.get("options") or ctx.get("options_ocr"),
            "candidates": [c.get("name") for c in ctx.get("candidates", []) if isinstance(c, dict)],
        }
        return json.dumps(stable, ensure_ascii=False, sort_keys=True)

    def _allowed_actions(self) -> set[str]:
        try:
            enum = self.tool_schema()["properties"]["action"]["enum"]
        except KeyError:
            return set()
        return set(enum)

    def _fallback_decision(self, session: Session, req: DecisionRequest, why: str) -> dict:
        decision = self.mock_decide(session, req)
        decision["reasoning"] = f"{why}; 使用本地兜底策略"
        decision["confidence"] = min(self._clamp_confidence(decision.get("confidence")), 0.35)
        return decision

    @staticmethod
    def _clamp_confidence(value: Any) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, confidence))

    @staticmethod
    def _coerce_int(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().lstrip("-").isdigit():
            return int(value)
        return None

    def _coerce_common_fields(self, decision: dict) -> None:
        for field in ("pick_index", "skill_index", "option_index"):
            if field in decision:
                coerced = self._coerce_int(decision[field])
                if coerced is not None:
                    decision[field] = coerced

        if "purchases" in decision and isinstance(decision["purchases"], list):
            purchases = []
            for item in decision["purchases"]:
                coerced = self._coerce_int(item)
                if coerced is not None:
                    purchases.append(coerced)
            decision["purchases"] = purchases

        for field in ("selected", "planned_path_next"):
            if field in decision and isinstance(decision[field], list):
                decision[field] = [str(item) for item in decision[field] if item]

    def normalize_decision(self, session: Session, req: DecisionRequest, raw: Any) -> dict:
        if not isinstance(raw, dict):
            return self._fallback_decision(session, req, "VLM 返回非 JSON 对象")

        try:
            decision = DecisionResponse.model_validate(raw).model_dump()
        except Exception:
            return self._fallback_decision(session, req, "VLM 响应基础字段不合法")

        action = decision.get("action")
        allowed = self._allowed_actions()
        if allowed and action not in allowed:
            return self._fallback_decision(session, req, f"VLM 返回未知动作 {action}")

        decision["reasoning"] = str(decision.get("reasoning") or "无理由")
        decision["confidence"] = self._clamp_confidence(decision.get("confidence"))
        self._coerce_common_fields(decision)

        missing = [
            field
            for field in self.required_by_action.get(action, [])
            if field not in decision or decision[field] is None
        ]
        if missing:
            return self._fallback_decision(session, req, f"动作 {action} 缺少字段 {missing}")

        if action == "inspect":
            target = decision.get("target")
            if not isinstance(target, dict) or not target.get("kind"):
                return self._fallback_decision(session, req, "inspect 缺少 target")

            key = self.decision_key(req)
            count = session.inspect_rounds.get(key, 0)
            if count >= self.max_inspect_rounds:
                return self._fallback_decision(session, req, "inspect 已达到 2 轮上限")
            session.inspect_rounds[key] = count + 1
        else:
            decision = self.repair_decision(session, req, decision)
            session.inspect_rounds.pop(self.decision_key(req), None)

        return decision

    def handle(self, session: Session, req: DecisionRequest) -> dict:
        session.update_from_context(req.context)
        system = ""
        user_text = self.common_user_text(session, req) + "\n\n本次请求:\n" + self.build_user_text(session, req)
        if vlm_client.is_mock():
            raw_decision = self.mock_decide(session, req)
        else:
            from ..prompts_loader import load as load_prompt

            system = (
                load_prompt("system_base")
                + "\n\n萨卡兹主题静态知识:\n"
                + sarkaz_overview()
                + "\n\n"
                + load_prompt(self.prompt_name)
            )
            raw_decision = vlm_client.call_vlm(
                system=system,
                user_text=user_text,
                images_b64=req.screenshots,
                tool_schema=self.tool_schema(),
            )

        decision = self.normalize_decision(session, req, raw_decision)
        debug_io.trace_decision(
            endpoint=self.endpoint,
            session_id=req.session_id,
            context=req.context,
            screenshots=req.screenshots,
            user_text=user_text,
            system_text=system,
            raw_decision=raw_decision,
            decision=decision,
        )
        if decision.get("action") != "inspect":
            self.update_session(session, req, decision)
            session.log(self.endpoint, str(req.context)[:200], decision)
        return decision
