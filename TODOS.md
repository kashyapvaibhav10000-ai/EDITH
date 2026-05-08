# EDITH TODOs

## Skill Management Commands

**What:** Add `/skills list` and `/skills delete <name>` Telegram commands to `telegram_bot.py`.

**Why:** `_maybe_create_skill` auto-generates skills on agent task completion. No visibility or deletion mechanism exists — only way to manage is direct filesystem access to `skills/`. A runaway LLM could accumulate low-quality skills with no way to review from Telegram.

**How to apply:**
- `/skills list` → call `list_skills()` from `skills_loader.py`, format as Telegram message
- `/skills delete <name>` → remove `skills/<name>/` dir, call `reload_skills()`
- Wire in `telegram_bot.py` intent dispatch

**Context:** `skills_loader.SKILLS_DIR = EDITH_PATH/skills/`. `list_skills()` and `reload_skills()` already exist. Only the Telegram command handlers need adding.

**Depends on:** Nothing — `_maybe_create_skill` already shipped (Item 16).
