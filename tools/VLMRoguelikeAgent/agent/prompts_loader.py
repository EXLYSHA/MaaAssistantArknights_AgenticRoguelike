"""加载 prompts/ 下的提示词模板。"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


@lru_cache(maxsize=None)
def load(name: str) -> str:
    p = PROMPTS_DIR / f"{name}.md"
    return p.read_text(encoding="utf-8") if p.exists() else ""
