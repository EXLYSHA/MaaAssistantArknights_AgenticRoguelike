"""VLM Roguelike Agent HTTP server.

启动:
    python server.py --port 8765

默认 mock 模式（无 ANTHROPIC_API_KEY 时自动启用）；
设置 OPENAI_API_KEY 或 ANTHROPIC_API_KEY 且 VLM_MOCK=0 切换到真实 VLM。
"""
from __future__ import annotations

import argparse
import logging

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from typing import Optional

from agent import debug_io
from agent import vlm_client
from agent.decisions.base import DecisionRequest
from agent.decisions.encounter import EncounterHandler
from agent.decisions.level_reward import LevelRewardHandler
from agent.decisions.map_node import MapNodeHandler
from agent.decisions.pre_battle_team import PreBattleTeamHandler
from agent.decisions.recruit import RecruitHandler
from agent.decisions.shopping import ShoppingHandler
from agent.decisions.skill_selection import SkillSelectionHandler
from agent.decisions.squad import SquadHandler
from agent.session import store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("vlm-agent")

app = FastAPI(title="MAA VLM Roguelike Agent", version="0.1.0")

DEBUG_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>MAA VLM Debug</title>
  <style>
    :root {
      color-scheme: light dark;
      --bg: #101214;
      --panel: #171b1f;
      --panel-2: #20262b;
      --text: #e9eef2;
      --muted: #96a1aa;
      --line: #303941;
      --accent: #55b4d4;
      --ok: #6fce8c;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-size: 14px;
    }
    header {
      height: 52px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 18px;
      border-bottom: 1px solid var(--line);
      background: #12161a;
    }
    header h1 { font-size: 16px; margin: 0; font-weight: 650; }
    header .status { color: var(--muted); display: flex; gap: 16px; align-items: center; }
    label { display: inline-flex; align-items: center; gap: 6px; }
    main {
      display: grid;
      grid-template-columns: minmax(260px, 340px) minmax(0, 1fr);
      height: calc(100vh - 52px);
      min-height: 0;
    }
    aside {
      border-right: 1px solid var(--line);
      overflow: auto;
      background: var(--panel);
    }
    .event {
      width: 100%;
      text-align: left;
      border: 0;
      border-bottom: 1px solid var(--line);
      background: transparent;
      color: var(--text);
      padding: 12px 14px;
      cursor: pointer;
      font: inherit;
    }
    .event:hover, .event.active { background: var(--panel-2); }
    .event .top { display: flex; justify-content: space-between; gap: 12px; margin-bottom: 6px; }
    .event .meta { color: var(--muted); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .event .action { color: var(--ok); font-weight: 650; }
    section.detail {
      min-width: 0;
      overflow: auto;
      padding: 16px;
      display: grid;
      gap: 14px;
      align-content: start;
    }
    .empty {
      color: var(--muted);
      padding: 24px;
      line-height: 1.7;
    }
    .block {
      border: 1px solid var(--line);
      background: var(--panel);
      min-width: 0;
    }
    .block h2 {
      font-size: 13px;
      margin: 0;
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      color: var(--accent);
      font-weight: 650;
    }
    pre {
      margin: 0;
      padding: 12px;
      overflow: auto;
      white-space: pre-wrap;
      word-break: break-word;
      font: 12px/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
    }
    .screens {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 12px;
      padding: 12px;
    }
    .screens img {
      max-width: 100%;
      height: auto;
      display: block;
      border: 1px solid var(--line);
      background: #000;
    }
    .grid2 {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
      gap: 14px;
    }
    @media (max-width: 900px) {
      main { grid-template-columns: 1fr; grid-template-rows: 280px minmax(0, 1fr); }
      aside { border-right: 0; border-bottom: 1px solid var(--line); }
      .grid2 { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <h1>MAA VLM Debug</h1>
    <div class="status">
      <label><input id="follow" type="checkbox" checked /> 自动跟随最新</label>
      <span id="summary">连接中</span>
    </div>
  </header>
  <main>
    <aside id="events"></aside>
    <section id="detail" class="detail">
      <div class="empty">等待 VLM 决策。启动 sidecar 时请使用 <code>--trace</code>。</div>
    </section>
  </main>
  <script>
    const state = { selected: null, events: [], lastCount: 0 };
    const $ = (id) => document.getElementById(id);

    function esc(value) {
      return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;"
      }[ch]));
    }

    function jsonText(value) {
      return esc(JSON.stringify(value ?? {}, null, 2));
    }

    async function refreshEvents() {
      try {
        const resp = await fetch("/debug/events", { cache: "no-store" });
        const data = await resp.json();
        state.events = data.events || [];
        $("summary").textContent = data.trace_enabled
          ? `trace 已开启，事件 ${state.events.length}`
          : "trace 未开启，请用 --trace 启动";
        renderEvents();
        const latest = state.events[state.events.length - 1];
        if (latest && ($("follow").checked || state.selected === null || state.events.length !== state.lastCount)) {
          await loadDetail(latest.id);
        }
        state.lastCount = state.events.length;
      } catch (err) {
        $("summary").textContent = `连接失败: ${err}`;
      }
    }

    function renderEvents() {
      const items = [...state.events].reverse();
      if (!items.length) {
        $("events").innerHTML = '<div class="empty">还没有决策事件。</div>';
        return;
      }
      $("events").innerHTML = items.map((ev) => `
        <button class="event ${ev.id === state.selected ? "active" : ""}" onclick="loadDetail(${ev.id})">
          <div class="top"><strong>#${ev.id} ${esc(ev.endpoint)}</strong><span class="action">${esc(ev.action)}</span></div>
          <div class="meta">${esc(ev.created_at)} · conf=${Number(ev.confidence || 0).toFixed(2)}</div>
          <div class="meta">${esc(ev.session_id)}</div>
        </button>
      `).join("");
    }

    async function loadDetail(id) {
      const resp = await fetch(`/debug/events/${id}`, { cache: "no-store" });
      if (!resp.ok) return;
      const detail = await resp.json();
      state.selected = id;
      renderEvents();
      const shots = ((detail.request || {}).screenshots || [])
        .filter((s) => s.file)
        .map((s) => `<img src="/debug/events/${id}/screenshot/${s.index}?t=${Date.now()}" alt="screenshot ${s.index}" />`)
        .join("");
      $("detail").innerHTML = `
        <div class="block">
          <h2>截图</h2>
          <div class="screens">${shots || '<span class="empty">本次请求没有可显示截图。</span>'}</div>
        </div>
        <div class="grid2">
          <div class="block"><h2>最终决策</h2><pre>${jsonText(detail.decision)}</pre></div>
          <div class="block"><h2>模型原始输出</h2><pre>${jsonText(detail.raw_decision)}</pre></div>
        </div>
        <div class="block"><h2>Context</h2><pre>${jsonText((detail.request || {}).context)}</pre></div>
        <div class="block"><h2>User Prompt</h2><pre>${esc(detail.user)}</pre></div>
        <div class="block"><h2>System Prompt</h2><pre>${esc(detail.system || "mock 模式下不会构造 system prompt")}</pre></div>
      `;
    }

    window.loadDetail = loadDetail;
    refreshEvents();
    setInterval(refreshEvents, 1000);
  </script>
</body>
</html>
"""


# ---------- session lifecycle ----------

class SessionStartReq(BaseModel):
    theme: str = "Sarkaz"
    mode: int = 30001
    difficulty: int = 0
    goal_hint: str = "通关"
    client_version: Optional[str] = None


class SessionStartResp(BaseModel):
    session_id: str
    vlm_model: str


@app.post("/session/start", response_model=SessionStartResp)
def session_start(req: SessionStartReq) -> SessionStartResp:
    if req.theme != "Sarkaz":
        raise HTTPException(400, f"VLM agent v1 only supports Sarkaz, got {req.theme}")
    s = store.create(req.theme, req.mode, req.difficulty, req.goal_hint)
    log.info("session start: %s mode=%d diff=%d", s.session_id, req.mode, req.difficulty)
    return SessionStartResp(session_id=s.session_id, vlm_model=vlm_client.model_name())


class SessionEndReq(BaseModel):
    session_id: str
    outcome: str = "abandon"
    floor_reached: int = 0


@app.post("/session/end")
def session_end(req: SessionEndReq) -> dict:
    ok = store.end(req.session_id)
    log.info("session end: %s outcome=%s floor=%d ok=%s",
             req.session_id, req.outcome, req.floor_reached, ok)
    return {"ok": ok}


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "mock": vlm_client.is_mock(),
        "provider": vlm_client.provider_name(),
        "model": vlm_client.model_name(),
        "active_sessions": len(store.all()),
    }


@app.get("/debug", response_class=HTMLResponse)
def debug_page() -> str:
    return DEBUG_HTML


@app.get("/debug/events")
def debug_events() -> dict:
    return {
        "trace_enabled": debug_io.enabled(),
        "events": debug_io.list_events(),
    }


@app.get("/debug/events/{event_id}")
def debug_event_detail(event_id: int) -> dict:
    detail = debug_io.read_event_detail(event_id)
    if not detail:
        raise HTTPException(404, f"debug event {event_id} not found")
    return detail


@app.get("/debug/events/{event_id}/screenshot/{index}")
def debug_event_screenshot(event_id: int, index: int) -> FileResponse:
    path = debug_io.screenshot_path(event_id, index)
    if not path:
        raise HTTPException(404, f"screenshot {index} for debug event {event_id} not found")
    return FileResponse(path, media_type="image/png")


# ---------- decision endpoints ----------

_HANDLERS = {
    "/decide/squad": SquadHandler(),
    "/decide/recruit": RecruitHandler(),
    "/decide/skill_selection": SkillSelectionHandler(),
    "/decide/pre_battle_team": PreBattleTeamHandler(),
    "/decide/encounter": EncounterHandler(),
    "/decide/shopping": ShoppingHandler(),
    "/decide/map_node": MapNodeHandler(),
    "/decide/level_reward": LevelRewardHandler(),
}


def _dispatch(path: str, req: DecisionRequest) -> dict:
    s = store.get(req.session_id)
    if not s:
        raise HTTPException(404, f"session {req.session_id} not found")
    h = _HANDLERS[path]
    try:
        decision = h.handle(s, req)
        log.info("[%s] %s -> %s (conf=%.2f)", s.session_id, path,
                 decision.get("action"), decision.get("confidence", 0))
        return decision
    except Exception as e:
        log.exception("decision failed: %s", e)
        raise HTTPException(500, str(e))


@app.post("/decide/squad")
def decide_squad(req: DecisionRequest) -> dict:
    return _dispatch("/decide/squad", req)


@app.post("/decide/recruit")
def decide_recruit(req: DecisionRequest) -> dict:
    return _dispatch("/decide/recruit", req)


@app.post("/decide/skill_selection")
def decide_skill(req: DecisionRequest) -> dict:
    return _dispatch("/decide/skill_selection", req)


@app.post("/decide/pre_battle_team")
def decide_team(req: DecisionRequest) -> dict:
    return _dispatch("/decide/pre_battle_team", req)


@app.post("/decide/encounter")
def decide_encounter(req: DecisionRequest) -> dict:
    return _dispatch("/decide/encounter", req)


@app.post("/decide/shopping")
def decide_shopping(req: DecisionRequest) -> dict:
    return _dispatch("/decide/shopping", req)


@app.post("/decide/map_node")
def decide_map(req: DecisionRequest) -> dict:
    return _dispatch("/decide/map_node", req)


@app.post("/decide/level_reward")
def decide_reward(req: DecisionRequest) -> dict:
    return _dispatch("/decide/level_reward", req)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--trace", action="store_true", help="print and save every VLM request/response")
    parser.add_argument("--trace-dir", default=None, help="directory for traced requests")
    args = parser.parse_args()

    import uvicorn
    debug_io.configure(enabled=args.trace or None, out_dir=args.trace_dir)
    log.info("starting on %s:%d (mock=%s, model=%s)",
             args.host, args.port, vlm_client.is_mock(), vlm_client.model_name())
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
