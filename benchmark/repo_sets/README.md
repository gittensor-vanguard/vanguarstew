# Repo-set configs

Benchmark replay repos are declared as checked-in JSON configs, loaded via
`benchmark.repo_set.load_repo_set(path)`. A path is **always required** — there is no implicit
default — so every run deliberately chooses a config.

## Files

| File | Purpose |
| ---- | ------- |
| `example.json` | Schema starter with `OWNER/...` placeholders — **not operational** |
| `curated.json` | Vetted operational set with real public repositories |

## Vetting criteria

Each entry in `curated.json` was chosen against the leakage strategy in
`docs/architecture.md`:

### `recent` tier

- Public repository with sustained maintainer activity **after** a model training cutoff
  (freeze windows use `after` dates in late 2025+ and `recent_bias: true`).
- Enough first-parent history for replay (`min_history` ≥ 30 where noted).
- Not a placeholder; the `source` is a real `https://github.com/owner/repo` URL.

### `obscure` tier

- Public repository with a long but **low-traffic** maintenance surface — unlikely to appear
  verbatim in model training corpora.
- Obscurity is the primary leakage defense; freeze windows rely on `min_history` and
  `rotation_seed` rather than recency alone.

### `held_out`

- Same tier rules as above, but `held_out: true` — reserved for generalization scoring and
  excluded from tuning runs unless explicitly requested.

## Running a curated replay

Clone the listed repositories locally, then point `run_eval` at the config:

```bash
VANGUARSTEW_OFFLINE=1 python -m scripts.run_eval \
  --repo-set benchmark/repo_sets/curated.json \
  --tasks 2 --horizon 5
```

Use `--repo-set-partition held_out` to score only held-out entries, or `all` for every repo
in the config.
