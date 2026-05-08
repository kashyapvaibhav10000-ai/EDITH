# data_analyst.py
## Purpose
Pandas-powered file analysis with matplotlib chart generation and AI insights.
## Key Functions
- `analyze_file(filepath, question, chart_type)` — full pipeline: load → analyze → chart → AI insight
- `load_file(filepath)` — load CSV/Excel/JSON into DataFrame
- `summarize_data(df)` — shape, dtypes, nulls, basic stats
- `generate_chart(df, chart_type, x_col, y_col, title)` — save chart PNG to CHARTS_DIR
- `smart_chart_suggestion(df)` — LLM picks best chart type for data
- `ai_analyze(df, question)` — LLM narrative insight on DataFrame
## Imports From
config, smart_router, errors
## Imported By
orchestrator, intent_dispatch
## Status
OK
## Notes
Uses `matplotlib.use('Agg')` — non-interactive backend for headless operation.
