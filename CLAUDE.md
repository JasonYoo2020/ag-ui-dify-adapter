# CLAUDE.md

## Pre-commit checklist

Before committing code changes:

1. **Unit tests** — must pass:
   ```bash
   python -m pytest tests/test_types.py tests/test_translator.py tests/test_client.py tests/test_agent.py
   ```

2. **Verification** — run the app against real Dify (if Dify is reachable):
   ```bash
   python -m pytest tests/test_integration.py
   ```
   Set `DIFY_AGENT_API_KEY`, `DIFY_WORKFLOW_API_KEY`, `DIFY_CHATBOT_API_KEY`, `DIFY_COMPLETION_API_KEY` env vars to enable integration tests.

3. **Build check** — verify wheel and sdist are valid:
   ```bash
   rm -rf dist/ && python -m build && twine check dist/*
   ```

## Security rules

- **Never commit real API keys.** Use environment variables or `config.yaml` (gitignored). Test files must not contain real keys as default values.
- `config.yaml` is gitignored — only commit `config.yaml.example` with placeholder values.
- `.env` is gitignored — only commit `.env.example` if needed.
- Integration test defaults must be empty/None — tests skip when env vars are not set.
- Always verify `grep -r "app-" tests/ ag_ui_dify/` before commit to catch leaked keys.

## Code style

- No comments that describe WHAT the code does — names should be self-explanatory.
- Comments only for WHY (non-obvious constraints, workarounds).
- No docstrings on internal helpers — only on public API.
- Prefer editing existing files over creating new ones.
- Three similar lines > premature abstraction.

## Project structure

```
ag_ui_dify/     — library
  agent.py      — DifyAgent (public API)
  server.py     — Starlette HTTP server (public API)
  dify_client.py — Dify REST client (internal)
  event_translator.py — SSE → AG-UI event translation (internal)
  types.py      — Pydantic models (internal)
tests/          — tests (integration tests require env vars)
config.yaml     — local config with real keys (gitignored)
config.yaml.example — template (committed)
.env            — local env vars (gitignored)
other/          — supplementary docs (gitignored)
```
