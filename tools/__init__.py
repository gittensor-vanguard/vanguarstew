"""Developer & maintenance tooling — NOT part of the scored agent.

Modules here support local development, benchmark exploration, and repository maintenance.
They are deliberately kept out of the `agent` package so they can never end up on the
validator-scored inference path (see `tools/codex_llm.py` and `agent/llm.py`).
"""
