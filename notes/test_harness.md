# test_harness.py
## Purpose
20 pre-written smoke test scenarios covering intent, memory, council, search, and more.
## Key Functions
- `run_all_tests()` — execute all test cases, return results list
- `print_report(results)` — format pass/fail report
- `_test(name, fn)` — single test runner with timing and exception capture
## Imports From
none (imports tested modules dynamically)
## Imported By
edith.py (option 99)
## Status
OK
## Notes
Phase 8.3. 20 scenarios across intent detection, memory recall, council debate, decision sim, search. Not pytest — manual invocation only.
