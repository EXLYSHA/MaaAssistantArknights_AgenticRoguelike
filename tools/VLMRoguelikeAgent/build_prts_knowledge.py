#!/usr/bin/env python3
"""Build compact VLM knowledge from a local PRTS wikitext cache.

Runtime code only reads generated local files. This script also avoids network by
default: run with --download only when you intentionally refresh the local raw
cache from PRTS.

Local raw cache:
- knowledge/prts_raw/pages.json
- knowledge/prts_raw/operator_titles.json
- knowledge/prts_raw/meta.json

Generated summaries/indexes:
- knowledge/operators_prts_compact.json
- knowledge/sarkaz_relics_full.json
- knowledge/sarkaz_skills.json
- knowledge/prts_sources.md
"""
from __future__ import annotations

import argparse
import html
import json
import re
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
AGENT_DIR = Path(__file__).resolve().parent
KNOWLEDGE_DIR = AGENT_DIR / "knowledge"
RAW_CACHE_DIR = KNOWLEDGE_DIR / "prts_raw"
RAW_PAGES_FILE = RAW_CACHE_DIR / "pages.json"
RAW_OPERATOR_TITLES_FILE = RAW_CACHE_DIR / "operator_titles.json"
RAW_META_FILE = RAW_CACHE_DIR / "meta.json"
PRTS_API = "https://prts.wiki/api.php"
UA = "MAA-VLMAgent-KnowledgeBuilder/0.1 (https://github.com/MaaAssistantArknights/MaaAssistantArknights)"
SARKAZ_THEME_TITLE = "萨卡兹的无终奇语"
SARKAZ_RELICS_TITLE = "萨卡兹的无终奇语/想象实体图鉴"
SPECIAL_PAGES = {SARKAZ_THEME_TITLE, SARKAZ_RELICS_TITLE}


def read_json_file(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_file(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def api_get(params: dict[str, Any], sleep_s: float = 0.15) -> dict[str, Any]:
    query = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{PRTS_API}?{query}", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if sleep_s > 0:
        time.sleep(sleep_s)
    return data


def clean_wiki(text: str | None, max_len: int = 280) -> str:
    if not text:
        return ""
    out = html.unescape(text)
    out = re.sub(r"<!--.*?-->", "", out, flags=re.S)
    out = re.sub(r"<br\s*/?>", "；", out, flags=re.I)
    out = re.sub(r"<ref[^>]*>.*?</ref>", "", out, flags=re.S | re.I)
    out = re.sub(r"<[^>]+>", "", out)
    out = out.replace("'''", "").replace("''", "")

    # Common inline templates: keep the display text where possible.
    replacements = [
        (r"\{\{color\|[^|{}]+\|([^{}]+?)\}\}", r"\1"),
        (r"\{\{术语\|[^|{}]+\|([^{}]+?)\}\}", r"\1"),
        (r"\{\{异常效果\|([^{}|]+?)\}\}", r"\1"),
        (r"\{\{修正\|([^|{}]+).*?\}\}", r"\1"),
        (r"\{\{[+*]\|[^|{}]*\|([^{}]+?)\}\}", r"\1"),
        (r"\{\{mdi\|[^{}]*?\}\}", ""),
        (r"\{\{fa\|[^{}]*?\}\}", ""),
        (r"\{\{#var:[^{}]*?\}\}", ""),
    ]
    previous = None
    while previous != out:
        previous = out
        for pattern, repl in replacements:
            out = re.sub(pattern, repl, out, flags=re.S)

    out = re.sub(r"\[\[[^|\]]+\|([^\]]+)\]\]", r"\1", out)
    out = re.sub(r"\[\[([^\]]+)\]\]", r"\1", out)
    out = re.sub(r"\{\{[^{}]*\}\}", "", out)
    out = re.sub(r"\s+", " ", out).strip(" ;，,")
    if len(out) > max_len:
        out = out[: max_len - 1].rstrip() + "…"
    return out


def extract_template_blocks(raw: str, template_prefixes: tuple[str, ...]) -> list[str]:
    blocks: list[str] = []
    starts = []
    for prefix in template_prefixes:
        starts.extend(match.start() for match in re.finditer(re.escape("{{" + prefix), raw))
    for start in sorted(set(starts)):
        depth = 0
        i = start
        while i < len(raw) - 1:
            pair = raw[i : i + 2]
            if pair == "{{":
                depth += 1
                i += 2
                continue
            if pair == "}}":
                depth -= 1
                i += 2
                if depth == 0:
                    blocks.append(raw[start:i])
                    break
                continue
            i += 1
    return blocks


def parse_fields(block: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    current_key = ""
    current_value: list[str] = []
    for line in block.splitlines()[1:]:
        if line.strip().startswith("}}"):
            continue
        if line.startswith("|") and "=" in line:
            if current_key:
                fields[current_key] = "\n".join(current_value).strip()
            key, value = line[1:].split("=", 1)
            current_key = key.strip()
            current_value = [value.strip()]
        elif current_key:
            current_value.append(line.rstrip())
    if current_key:
        fields[current_key] = "\n".join(current_value).strip()
    return fields


def skill_rank(key: str) -> int:
    if key.startswith("技能专精"):
        match = re.search(r"技能专精(\d+)描述", key)
        return 70 + int(match.group(1)) if match else 70
    match = re.search(r"技能(\d+)描述", key)
    return int(match.group(1)) if match else 0


def best_skill_field(fields: dict[str, str], suffix: str) -> str:
    candidates = []
    for key, value in fields.items():
        if key.endswith(suffix):
            candidates.append((skill_rank(key.replace(suffix, "描述")), value))
    if not candidates:
        return ""
    return max(candidates, key=lambda item: item[0])[1]


def parse_operator(raw: str, title: str, sarkaz_meta: dict[str, Any]) -> dict[str, Any] | None:
    char_blocks = extract_template_blocks(raw, ("CharinfoV2",))
    if not char_blocks:
        return None
    char = parse_fields(char_blocks[0])
    attr_blocks = extract_template_blocks(raw, ("属性",))
    attrs = parse_fields(attr_blocks[0]) if attr_blocks else {}

    name = clean_wiki(char.get("干员名"), 80) or title
    entry: dict[str, Any] = {
        "name": name,
        "source": f"https://prts.wiki/w/{urllib.parse.quote(title)}",
        "rarity": int(char.get("稀有度", "-1")) + 1 if char.get("稀有度", "").lstrip("-").isdigit() else None,
        "profession": clean_wiki(char.get("职业"), 40),
        "branch": clean_wiki(char.get("分支"), 40),
        "position": clean_wiki(char.get("位置"), 40),
        "tags": clean_wiki(char.get("标签"), 80),
        "trait": clean_wiki(char.get("特性"), 220),
        "cost": clean_wiki(attrs.get("部署费用"), 40),
        "redeploy": clean_wiki(attrs.get("再部署"), 40),
        "block": clean_wiki(attrs.get("阻挡数"), 40),
        "attack_interval": clean_wiki(attrs.get("攻击速度"), 40),
        "elite2_max": {
            "hp": clean_wiki(attrs.get("精英2_满级_生命上限"), 30),
            "atk": clean_wiki(attrs.get("精英2_满级_攻击"), 30),
            "def": clean_wiki(attrs.get("精英2_满级_防御"), 30),
            "res": clean_wiki(attrs.get("精英2_满级_法术抗性"), 30),
        },
    }

    talents = []
    for block in extract_template_blocks(raw, ("天赋列表",)):
        fields = parse_fields(block)
        for key, effect in fields.items():
            if not re.fullmatch(r"天赋\d*效果", key):
                continue
            prefix = key[: -len("效果")]
            talents.append(
                {
                    "name": clean_wiki(fields.get(prefix, fields.get("天赋")), 80),
                    "condition": clean_wiki(fields.get(prefix + "条件"), 80),
                    "effect": clean_wiki(effect, 240),
                }
            )
    entry["talents"] = talents[:6]

    skills = []
    for idx, block in enumerate(extract_template_blocks(raw, ("技能\n", "技能2", "技能3")), start=1):
        fields = parse_fields(block)
        if not fields.get("技能名"):
            continue
        skills.append(
            {
                "index": idx,
                "name": clean_wiki(fields.get("技能名"), 80),
                "type": " / ".join(
                    part
                    for part in (
                        clean_wiki(fields.get("技能类型1"), 40),
                        clean_wiki(fields.get("技能类型2"), 40),
                    )
                    if part
                ),
                "initial": clean_wiki(best_skill_field(fields, "初始"), 30),
                "cost": clean_wiki(best_skill_field(fields, "消耗"), 30),
                "duration": clean_wiki(best_skill_field(fields, "持续"), 30),
                "description": clean_wiki(best_skill_field(fields, "描述"), 300),
            }
        )
    entry["skills"] = skills[:3]

    if name in sarkaz_meta:
        entry["sarkaz"] = sarkaz_meta[name]
    return entry


def load_sarkaz_meta() -> dict[str, dict[str, Any]]:
    path = ROOT / "resource" / "roguelike" / "Sarkaz" / "recruitment.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    meta: dict[str, dict[str, Any]] = defaultdict(lambda: {"groups": []})
    for group in data.get("priority", []):
        group_name = group.get("name")
        for op in group.get("opers", []):
            name = op.get("name")
            if not name or name.startswith("预备干员"):
                continue
            item = meta[name]
            if group_name and group_name not in item["groups"]:
                item["groups"].append(group_name)
            for key in (
                "skill",
                "alternate_skill",
                "is_key",
                "is_start",
                "is_alternate",
                "recruit_priority",
                "promote_priority",
                "recruit_priority_when_team_full",
                "promote_priority_when_team_full",
            ):
                if key in op:
                    item[key] = op[key]
    return dict(meta)


def category_operator_titles() -> list[str]:
    titles: list[str] = []
    cont: dict[str, Any] = {}
    while True:
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": "分类:干员",
            "cmlimit": "500",
            "format": "json",
            "formatversion": "2",
        }
        params.update(cont)
        data = api_get(params)
        titles.extend(item["title"] for item in data.get("query", {}).get("categorymembers", []))
        if "continue" not in data:
            break
        cont = data["continue"]
    return titles


def fetch_wikitext(titles: list[str]) -> dict[str, str]:
    pages: dict[str, str] = {}
    for i in range(0, len(titles), 45):
        batch = titles[i : i + 45]
        data = api_get(
            {
                "action": "query",
                "prop": "revisions",
                "rvprop": "content",
                "rvslots": "main",
                "redirects": "1",
                "titles": "|".join(batch),
                "format": "json",
                "formatversion": "2",
            }
        )
        for page in data.get("query", {}).get("pages", []):
            if page.get("missing"):
                continue
            revisions = page.get("revisions") or []
            if not revisions:
                continue
            content = revisions[0].get("slots", {}).get("main", {}).get("content", "")
            if content:
                pages[page["title"]] = content
    return pages


def raw_cache_exists() -> bool:
    return RAW_PAGES_FILE.exists() and RAW_META_FILE.exists()


def download_raw_cache(include_all: bool) -> dict[str, Any]:
    """Download PRTS raw wikitext into knowledge/prts_raw.

    This is the only networked path in this script. Generation itself consumes
    the local cache, so normal dev/test runs do not depend on PRTS availability.
    """
    RAW_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    sarkaz_meta = load_sarkaz_meta()
    operator_titles = category_operator_titles() if include_all else sorted(sarkaz_meta)

    titles = {
        name
        for name in operator_titles
        if name and not name.startswith("预备干员")
    }
    titles.update(SPECIAL_PAGES)
    pages = fetch_wikitext(sorted(titles))

    meta = {
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "source_api": PRTS_API,
        "include_all": include_all,
        "requested_titles": len(titles),
        "downloaded_pages": len(pages),
        "special_pages": sorted(SPECIAL_PAGES),
    }
    write_json_file(RAW_PAGES_FILE, pages)
    write_json_file(RAW_OPERATOR_TITLES_FILE, sorted(operator_titles))
    write_json_file(RAW_META_FILE, meta)
    print(
        "downloaded_raw_cache="
        f"{len(pages)} pages dir={RAW_CACHE_DIR.relative_to(AGENT_DIR)}"
    )
    return meta


def load_raw_cache() -> tuple[dict[str, str], dict[str, Any]]:
    if not raw_cache_exists():
        raise SystemExit(
            "Missing local PRTS raw cache. Run:\n"
            "  python build_prts_knowledge.py --download\n"
            "Then subsequent runs can generate knowledge fully offline."
        )
    pages = read_json_file(RAW_PAGES_FILE, {})
    meta = read_json_file(RAW_META_FILE, {})
    if not isinstance(pages, dict):
        raise SystemExit(f"Invalid raw cache file: {RAW_PAGES_FILE}")
    if not isinstance(meta, dict):
        meta = {}
    return {str(k): str(v) for k, v in pages.items()}, meta


def parse_relics(raw: str) -> dict[str, dict[str, Any]]:
    relics: dict[str, dict[str, Any]] = {}
    for block in extract_template_blocks(raw, ("收藏品",)):
        fields = parse_fields(block)
        name = clean_wiki(fields.get("名称"), 100)
        effect = clean_wiki(fields.get("效果"), 500)
        if not name or not effect:
            continue
        relics[name] = {
            "id": clean_wiki(fields.get("ID"), 20),
            "rarity": clean_wiki(fields.get("稀有度"), 20),
            "price": clean_wiki(fields.get("售价"), 20),
            "effect": effect,
            "source": "https://prts.wiki/w/萨卡兹的无终奇语/想象实体图鉴",
        }
    return relics


def build_outputs(include_all: bool, pages: dict[str, str], cache_meta: dict[str, Any]) -> None:
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    sarkaz_meta = load_sarkaz_meta()

    titles = {
        title
        for title in pages
        if title not in SPECIAL_PAGES and not title.startswith("预备干员")
    }
    if include_all:
        parsed_titles = titles
    else:
        parsed_titles = titles.intersection(sarkaz_meta)

    operators: dict[str, Any] = {}
    skills: dict[str, Any] = {}
    for title in sorted(parsed_titles):
        raw = pages.get(title, "")
        entry = parse_operator(raw, title, sarkaz_meta)
        if not entry:
            continue
        name = entry["name"]
        operators[name] = entry
        skills[name] = {"skills": entry.get("skills", []), "source": entry.get("source", "")}

    relic_raw = pages.get(SARKAZ_RELICS_TITLE, "")
    relics = parse_relics(relic_raw)

    write_json_file(KNOWLEDGE_DIR / "operators_prts_compact.json", operators)
    write_json_file(KNOWLEDGE_DIR / "sarkaz_skills.json", skills)
    write_json_file(KNOWLEDGE_DIR / "sarkaz_relics_full.json", relics)
    (KNOWLEDGE_DIR / "prts_sources.md").write_text(
        "\n".join(
            [
                "# PRTS Knowledge Sources",
                "",
                "Generated from local raw cache under `knowledge/prts_raw/`.",
                "Runtime VLM agent code reads only local generated files.",
                "",
                "- Operator pages: https://prts.wiki/w/分类:干员",
                "- Sarkaz IS theme: https://prts.wiki/w/萨卡兹的无终奇语",
                "- Sarkaz collectibles: https://prts.wiki/w/萨卡兹的无终奇语/想象实体图鉴",
                "",
                f"Raw cache downloaded at: {cache_meta.get('downloaded_at', 'unknown')}",
                f"Raw cached pages: {cache_meta.get('downloaded_pages', len(pages))}",
                f"Generated operator entries: {len(operators)}",
                "Note: reserve-operator pages and non-standard pages without CharinfoV2 are skipped.",
                f"Generated collectible entries: {len(relics)}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"operators={len(operators)} relics={len(relics)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sarkaz-only",
        action="store_true",
        help="generate only operators referenced by resource/roguelike/Sarkaz/recruitment.json",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="refresh the local PRTS raw cache before generating; this is the only networked mode",
    )
    args = parser.parse_args()
    include_all = not args.sarkaz_only
    if args.download:
        download_raw_cache(include_all=True)
    pages, meta = load_raw_cache()
    build_outputs(include_all=include_all, pages=pages, cache_meta=meta)


if __name__ == "__main__":
    main()
