# Task: Raw HTTP trace + ShareGPT export

Log full upstream HTTP request/response (including headers), grouped by `?session_id=` query param. Provide a script to convert raw logs → ShareGPT JSONL.

**Source of truth:** `tests/acceptance/test_raw_http_trace.py`

```bash
pytest tests/acceptance/test_raw_http_trace.py -q
```

Fixture sample: `tests/fixtures/raw_http_demo-sess-001.jsonl`
