# edith.py
## Purpose
Interactive CLI menu — entry point for manual module launch and smoke tests.
## Key Functions
- `main()` — numbered menu with 17 module launch options + option 99 smoke tests
- `check_systems()` — quick system health summary
- `run_module(script)` — subprocess launch of any EDITH module
- `open_dashboard()` — launch dashboard in browser
- `run_doctor()` — run validator.validate_all()
- `run_smoke_tests()` — execute test_harness.run_all_tests()
## Imports From
config
## Imported By
none (top-level entry point)
## Status
OK
## Notes
Not used in production daemon mode. For manual diagnostics and development.
