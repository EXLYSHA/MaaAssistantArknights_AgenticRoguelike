"""单局会话状态。所有决策端点共享同一份 session 上下文。"""
from __future__ import annotations

import copy
import time
import uuid
from dataclasses import dataclass, field
from threading import Lock
from typing import Any


@dataclass
class DecisionLog:
    endpoint: str
    request_summary: str
    response: dict
    timestamp: float


@dataclass
class Session:
    session_id: str
    theme: str
    mode: int
    difficulty: int
    goal_hint: str
    created_at: float

    squad: str = ""
    roster: list[dict] = field(default_factory=list)
    relics: list[str] = field(default_factory=list)
    floor: int = 1
    hope: int = 6
    hp: int = 8

    planned_path: list[str] = field(default_factory=list)
    decision_log: list[DecisionLog] = field(default_factory=list)

    inspect_rounds: dict[str, int] = field(default_factory=dict)
    inspected_operators: dict[str, list[str]] = field(default_factory=dict)

    def log(self, endpoint: str, summary: str, response: dict) -> None:
        self.decision_log.append(
            DecisionLog(endpoint, summary, response, time.time())
        )

    def update_from_context(self, context: dict[str, Any]) -> None:
        """Merge authoritative state fields supplied by MaaCore into the session."""
        for key in ("floor", "hope", "hp"):
            value = context.get(key)
            if isinstance(value, int):
                setattr(self, key, value)

        roster = context.get("current_roster")
        if isinstance(roster, list):
            self.roster = [copy.deepcopy(op) for op in roster if isinstance(op, dict)]
        elif isinstance(context.get("full_roster"), list):
            self.roster = [copy.deepcopy(op) for op in context["full_roster"] if isinstance(op, dict)]

        relics = context.get("current_relics")
        if isinstance(relics, list):
            self.relics = [str(name) for name in relics if name]

    def add_or_update_operator(self, oper: dict[str, Any]) -> None:
        name = oper.get("name")
        if not name:
            return
        new_oper = copy.deepcopy(oper)
        for idx, existing in enumerate(self.roster):
            if existing.get("name") == name:
                merged = copy.deepcopy(existing)
                merged.update(new_oper)
                self.roster[idx] = merged
                return
        self.roster.append(new_oper)

    def add_relic(self, name: str) -> None:
        if name and name not in self.relics:
            self.relics.append(name)

    def recent_log_text(self, n: int = 5) -> str:
        items = self.decision_log[-n:]
        return "\n".join(
            f"[{d.endpoint}] {d.request_summary} -> {d.response.get('action')} "
            f"({d.response.get('reasoning', '')})"
            for d in items
        )


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = Lock()

    def create(self, theme: str, mode: int, difficulty: int, goal_hint: str) -> Session:
        sid = f"sess-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        s = Session(
            session_id=sid,
            theme=theme,
            mode=mode,
            difficulty=difficulty,
            goal_hint=goal_hint,
            created_at=time.time(),
        )
        with self._lock:
            self._sessions[sid] = s
        return s

    def get(self, sid: str) -> Session | None:
        with self._lock:
            return self._sessions.get(sid)

    def end(self, sid: str) -> bool:
        with self._lock:
            return self._sessions.pop(sid, None) is not None

    def all(self) -> list[Session]:
        with self._lock:
            return list(self._sessions.values())


store = SessionStore()
