# coding_style.py
## Purpose
Extracts personal coding style from git repos and answers questions in that style.
## Key Functions
- `extract_style()` — analyze REPOS, build style profile JSON + text
- `analyze_python_style(filepath)` — AST walk for naming, spacing, docstring patterns
- `ask_code_like_vaibhav(question)` — generate code answer using extracted style
## Imports From
config
## Imported By
agent.py (loads style for code generation)
## Status
OK
## Notes
Writes to CODING_PERSONALITY_JSON and CODING_PERSONALITY_TXT. One-time setup + periodic refresh.
