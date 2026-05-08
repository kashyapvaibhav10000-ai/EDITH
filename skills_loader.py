"""
EDITH Skills Loader — O1

Skills live in skills/<name>/SKILL.md.
Each SKILL.md has YAML frontmatter (name, trigger regex, inject position)
followed by skill content injected into the system prompt.
"""

import os
import re
from config import EDITH_PATH, get_logger

log = get_logger("skills_loader")

SKILLS_DIR = os.path.join(EDITH_PATH, "skills")
_skills_cache: list[dict] | None = None


def _parse_skill_md(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as _f:
            raw = _f.read()
        if not raw.startswith("---"):
            return None
        parts = raw.split("---", 2)
        if len(parts) < 3:
            return None
        frontmatter = parts[1].strip()
        content = parts[2].strip()
        meta = {}
        for line in frontmatter.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        if "name" not in meta:
            return None
        return {
            "name": meta["name"],
            "trigger": meta.get("trigger", ""),
            "inject": meta.get("inject", "suffix"),
            "content": content,
        }
    except Exception as e:
        log.debug(f"Failed to parse skill at {path}: {e}")
        return None


def load_skills() -> list[dict]:
    """Scan skills/ dir, parse all SKILL.md files. Cached after first load."""
    global _skills_cache
    if _skills_cache is not None:
        return _skills_cache
    skills = []
    if not os.path.isdir(SKILLS_DIR):
        _skills_cache = skills
        return skills
    for entry in os.scandir(SKILLS_DIR):
        if entry.is_dir():
            skill_file = os.path.join(entry.path, "SKILL.md")
            if os.path.exists(skill_file):
                skill = _parse_skill_md(skill_file)
                if skill:
                    skills.append(skill)
    _skills_cache = skills
    log.debug(f"Loaded {len(skills)} skills: {[s['name'] for s in skills]}")
    return skills


def get_skill_for_intent(intent: str) -> str | None:
    """Return matching skill content for the given intent string, or None."""
    for skill in load_skills():
        trigger = skill.get("trigger", "")
        if trigger:
            try:
                if re.search(trigger, intent, re.IGNORECASE):
                    return skill["content"]
            except re.error:
                log.warning(f"Invalid trigger regex in skill '{skill['name']}' — skipping")
    return None


def list_skills() -> list[str]:
    """Return all loaded skill names."""
    return [s["name"] for s in load_skills()]


def reload_skills() -> int:
    """Force reload of skills cache. Returns count of loaded skills."""
    global _skills_cache
    _skills_cache = None
    return len(load_skills())
