"""加载 knowledge/ 下的 Sarkaz 静态知识。启动时一次性读入内存。"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge"


def _read_text(name: str) -> str:
    p = KNOWLEDGE_DIR / name
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _read_json(name: str) -> dict:
    p = KNOWLEDGE_DIR / name
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def sarkaz_overview() -> str:
    return _read_text("sarkaz_overview.md")


@lru_cache(maxsize=1)
def sarkaz_relics() -> dict:
    return _read_json("sarkaz_relics_full.json")


@lru_cache(maxsize=1)
def sarkaz_skills() -> dict:
    return _read_json("sarkaz_skills.json")


@lru_cache(maxsize=1)
def operators_prts() -> dict:
    return _read_json("operators_prts_compact.json")


@lru_cache(maxsize=1)
def sarkaz_group_manifest() -> dict:
    return _read_json("sarkaz_group_manifest.json")


def relic_brief(names: list[str]) -> str:
    """按当前已持有的藏品筛选效果描述，避免全量灌入 prompt。"""
    relics = sarkaz_relics()
    lines = []
    for n in names:
        entry = relics.get(n)
        if entry:
            price = entry.get("price")
            price_text = f"，售价{price}" if price else ""
            lines.append(f"- {n}{price_text}: {entry.get('effect', '')}")
    return "\n".join(lines)


def stage_group_brief(stage_name: str | None) -> str:
    if not stage_name:
        return ""
    manifest = sarkaz_group_manifest()
    groups = manifest.get("per_stage", {}).get(stage_name)
    if not groups:
        return ""
    sorted_groups = sorted(groups.items(), key=lambda item: (-item[1], item[0]))
    return "\n".join(f"- {group}: {count}" for group, count in sorted_groups[:12])


def global_group_brief() -> str:
    manifest = sarkaz_group_manifest()
    groups = manifest.get("global_required_groups", [])
    return ", ".join(groups[:16])


def operator_skill_brief(name: str) -> str:
    return operator_brief(name)


def _select_talents(entry: dict) -> list[dict]:
    selected: dict[str, dict] = {}
    for talent in entry.get("talents", []):
        name = talent.get("name") or "天赋"
        condition = str(talent.get("condition") or "")
        if "模组" in condition or "潜能" in condition:
            continue
        old = selected.get(name)
        if old is None or ("精英2" in condition and "精英2" not in str(old.get("condition") or "")):
            selected[name] = talent
    return list(selected.values())[:3]


def operator_brief(name: str, max_chars: int = 1200) -> str:
    ops = operators_prts()
    entry = ops.get(name)
    if not entry:
        skills = sarkaz_skills()
        legacy = skills.get(name)
        if not legacy:
            return ""
        out = [f"干员 {name}:"]
        for s in legacy.get("skills", []):
            out.append(f"  技能{s['index']} {s.get('name','?')}: {s.get('description') or s.get('desc','')}")
        return "\n".join(out)

    head = (
        f"{name}: {entry.get('rarity') or '?'}星 "
        f"{entry.get('profession') or '?'} / {entry.get('branch') or '?'}，"
        f"{entry.get('position') or '?'}，标签 {entry.get('tags') or '无'}。"
    )
    lines = [head]
    if entry.get("trait"):
        lines.append(f"特性: {entry['trait']}")
    sarkaz = entry.get("sarkaz") or {}
    if sarkaz:
        groups = ", ".join(sarkaz.get("groups") or [])
        skill = sarkaz.get("skill")
        alt = sarkaz.get("alternate_skill")
        marks = []
        if sarkaz.get("is_start"):
            marks.append("开局核心")
        if sarkaz.get("is_key"):
            marks.append("关键干员")
        lines.append(
            f"萨卡兹策略组: {groups or '未配置'}；推荐技能: {skill or '?'}"
            + (f"，未精二备选技能: {alt}" if alt else "")
            + (f"；标记: {', '.join(marks)}" if marks else "")
        )
    talents = _select_talents(entry)
    if talents:
        lines.append("天赋: " + "；".join(
            f"{t.get('name')}({t.get('condition')}): {t.get('effect')}" for t in talents
        ))
    skills = []
    for s in entry.get("skills", []):
        cost = f"初{s.get('initial') or '?'}/费{s.get('cost') or '?'}"
        duration = f"/持续{s.get('duration')}" if s.get("duration") else ""
        skills.append(
            f"S{s.get('index')} {s.get('name')}[{s.get('type') or '?'} {cost}{duration}]: "
            f"{s.get('description')}"
        )
    if skills:
        lines.append("技能: " + "；".join(skills))

    text = "\n".join(lines)
    if len(text) > max_chars:
        return text[: max_chars - 1].rstrip() + "…"
    return text


def operators_brief(names: list[str], limit: int = 10, per_operator_chars: int = 900) -> str:
    lines = []
    seen = set()
    for name in names:
        if not name or name in seen:
            continue
        seen.add(name)
        brief = operator_brief(name, per_operator_chars)
        if brief:
            lines.append("- " + brief.replace("\n", "\n  "))
        if len(lines) >= limit:
            break
    return "\n".join(lines)


def operator_skill_brief_legacy(name: str) -> str:
    skills = sarkaz_skills()
    entry = skills.get(name)
    if not entry:
        return ""
    out = [f"干员 {name}:"]
    for s in entry.get("skills", []):
        out.append(f"  技能{s['index']} {s.get('name','?')}: {s.get('description') or s.get('desc','')}")
    return "\n".join(out)
