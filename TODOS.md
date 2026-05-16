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

## Cloud Dead Code: Diagnostic shell=True Calls

**What:** Remove cloud-irrelevant diagnostic functions from `intent_dispatch.py` — `_handle_network_status`, `_handle_who_am_i`, and similar functions that use `shell=True` for local system introspection.

**Why:** After post-migration Fix 2 adds `EDITH_NODE_TYPE` guards, these functions become dead code on cloud. They're guarded (won't execute) but still compiled and present. Clean removal reduces attack surface and removes confusion.

**How to apply:**
- Identify all diagnostic handlers that make no sense on a headless cloud server
- Remove the functions entirely (not guard — they're local-only by design)
- Remove corresponding entries from `INTENT_HANDLERS` dict if applicable

**Context:** 13 `shell=True` calls exist in `intent_dispatch.py`. Post-migration the env guard disables them on cloud. This TODO is cleanup after the guard is stable. Verify `edith.service` (local) still works before removing.

**Depends on:** Fix 2 (EDITH_NODE_TYPE guard) must be stable first.
