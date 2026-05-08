# skills_loader.py
## Purpose
Loads SKILL.md files from skills/ directory — inject skill context into matching intents.
## Key Functions
- `load_skills()` — scan skills/*/SKILL.md, parse YAML frontmatter, return skill list
- `get_skill_for_intent(intent)` — return injection text for matching skill (by trigger regex)
- `list_skills()` — return skill name list
- `reload_skills()` — hot-reload all skills, return count
- `_parse_skill_md(path)` — parse YAML frontmatter + body from SKILL.md file
## Imports From
config
## Imported By
orchestrator (skill context injection pre-prompt)
## Status
OK
## Notes
O1 module. Skills in skills/<name>/SKILL.md with frontmatter: name, trigger (regex), inject_position.
