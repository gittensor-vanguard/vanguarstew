# Contributing to vanguarstew

Thanks for your interest in improving vanguarstew. This guide covers how the repo is
organized, how to set up a dev environment, and what a good pull request looks like.

## Powered by Gittensor

This repository is built and continuously improved through **[Gittensor](https://gittensor.io)** — a
[Bittensor](https://bittensor.com) subnet (**SN74**) that directs and rewards a network of contributors
to make real, merged improvements to open-source repositories. Development here is **powered by
Gittensor**: contributors are rewarded through the subnet for merged work, and that incentive network is
what drives the project forward.

- **Get involved (and earn) through Gittensor** — see [how OSS contributions
  work](https://docs.gittensor.io/oss-contributions.html) and the [Gittensor docs](https://docs.gittensor.io).
- You can also open a PR the normal way (below); everything that lands here flows through the same
  Gittensor-scored review process either way.

## Project layout

Two halves with different rules:

- **`agent/` + `agent.py` — the maintainer agent.** This is the part a miner edits and
  submits: the `solve()` entrypoint and the philosophy → plan → decide → implement steps.
  Improvements here are the main event.
- **`benchmark/` — the evaluation harness.** Freeze a repo at a point in time, generate
  replay tasks from GitHub history, run agents, and judge them pairwise. This is
  validator-owned; changes here affect how *everyone* is scored, so they get extra scrutiny.

See [README.md](README.md) for the architecture and [ROADMAP.md](ROADMAP.md) for milestones.

## Development setup

Requires Python 3.10+.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"     # installs pytest + ruff
```

## Running things

```bash
# lint
ruff check .

# tests (offline, no network or API key needed)
VANGUARSTEW_OFFLINE=1 python -m pytest -q

# an end-to-end replay against a local git repo, offline
VANGUARSTEW_OFFLINE=1 python -m scripts.run_eval --repo /path/to/git/repo --tasks 2 --horizon 5
```

`VANGUARSTEW_OFFLINE=1` swaps in a deterministic stub for the LLM so you can exercise the
full loop without an inference endpoint.

## Coding standards

- Keep it `ruff`-clean (`ruff check .` must pass — CI enforces it).
- Match the style of the surrounding code; prefer small, focused modules.
- Add or update a test in `tests/` for behavior changes.

## Pull requests

1. Branch off **`test`** and **target `test`** — never `main` (see [Branches](#branches) below). Keep the change focused and small.
2. Make sure `ruff check .` and the offline test suite pass locally.
3. Reference the issue you're addressing (e.g. `Fixes #12`).
4. Fill in the PR template; describe what you changed and how you verified it.

CI must be green before a PR can merge. See [REVIEW.md](REVIEW.md) for exactly how
contributions are gated, reviewed, and scored — the process is designed to be predictable and
reproducible.

## Branches

**Open every PR against `test`, never `main`.** This is a strong rule (see #221).

- **`test`** — staging and validation for `main`. Branch off `test`, target `test`; requires a PR and green CI.
- **`main`** — production, **maintainer-only**. A CI check (`pr-source-check`) rejects any PR into `main` that doesn't come from `test`, and the maintainer (**@matedev01**) promotes `test` → `main`.

This mirrors how [Gittensor](https://gittensor.io) itself runs its repository (`entrius/gittensor`).

## Reporting bugs and security issues

- Bugs and feature ideas: open an issue using the templates.
- Security vulnerabilities: **do not** open a public issue — see [SECURITY.md](SECURITY.md).

## License

By contributing, you agree that your contributions are licensed under the
[MIT License](LICENSE).
