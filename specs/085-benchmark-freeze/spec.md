# Spec 085 — git freeze pipeline (snapshot export + knowable-at-T context)

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #2010
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/freeze.py`](../../benchmark/freeze.py) (the module this spec binds),
  [`benchmark/runner.py`](../../benchmark/runner.py) (the call site: `write_frozen` once per
  task), [`agent/context.py`](../../agent/context.py) (`CONTEXT_FILE` and `README_PROBE_NAMES`,
  the constants this module imports, plus the agent-side git fallback that mirrors it),
  [`benchmark/leakage.py`](../../benchmark/leakage.py) (`scrub_context`, applied inside
  `write_frozen`), [`benchmark/github_context.py`](../../benchmark/github_context.py) (the
  enrichment layer that consumes `frozen_at` and `origin_url` and whose GitHub-API record
  shapes this module's git-only records diverge from),
  [`specs/003-leakage-integrity`](../003-leakage-integrity/spec.md) (owns the policy-level
  freeze SHALLs — T = the freeze commit's committer `%ct`, the knowable-at-T tag filter with
  its chronological ordering and lightweight-tag limitation, and the forward-reference scrub
  rules; this spec cross-references those clauses rather than re-owning them),
  [`specs/021-benchmark-freeze-path-parse`](../021-benchmark-freeze-path-parse/spec.md) (owns
  `parse_path_list`, the one other bound slice of this module), and
  [`specs/032-benchmark-freeze-coverage`](../032-benchmark-freeze-coverage/spec.md) /
  [`specs/053-benchmark-freeze-digest`](../053-benchmark-freeze-digest/spec.md) (bind the
  sibling audit modules `benchmark/freeze_coverage.py` / `benchmark/freeze_digest.py`, which
  summarize freeze pins in run artifacts *after* a replay — not this module's surface)

This spec makes the **existing, implicit** freeze-pipeline contract explicit. It describes the
as-built behavior of `benchmark/freeze.py`; it introduces **no behavior change**. Spec 003
already pins this module's headline knowable-at-T policy (committer-time T, the creator-date
tag filter — #332 fixing #245 — and chronological release ordering — #107 fixing #90), and
spec 021 pins `parse_path_list`; what no spec yet binds is the rest of the module at function
granularity: the `_git` wrapper's error contract (#1188), the exact git argv shapes, the
uniform tar extraction policy (#173 closing #156), `export_tree`'s error surface (#355 fixing
#201), the exact context key set and record shapes — including the date-less `{"tag": ...}`
release records — README probing (#937), `origin_url`/`file_at` degradation, and the
`write_frozen` composition. That is this spec's scope; where a clause is owned by 003 or 021
it is cross-referenced, not restated.

## Why

`write_frozen` produces the material every replay task starts from: `run_replay` calls it once
per task (`benchmark/runner.py`), the challenger agent and the baseline both read the exported
tree and its `.vanguarstew_context.json`, and the GitHub enrichment layer keys off the
`frozen_at.date` and `origin_url` this module emits. What the agent can know at T — which
commits, which releases (and that git-only release records carry **no dates**), which README,
in what shape — is decided here, so the exact record shapes and error surfaces are
scoring-critical. The extraction policy is likewise integrity-critical: it is what makes a
frozen tree byte- and mode-identical across runtimes and keeps an untrusted repository archive
from planting links or escaping the sandbox. Writing the contract down lets reviewers check
freeze changes against intent instead of re-deriving it from code.

## User stories

1. **As a benchmark operator**, I know exactly which git commands a freeze runs, what
   `.vanguarstew_context.json` contains key by key, and how the pipeline degrades (empty-string
   fallbacks vs. raised `RuntimeError`s) — so I can debug a failed or suspicious freeze from
   the spec.
2. **As a reviewer**, the record shapes are written down — the 10-char SHA abbreviation, the
   tag-only release records, the constant-empty placeholder lists — so a change to what the
   agent can see at T is checked against the spec, not discovered downstream.
3. **As a security-minded maintainer**, the tar extraction policy (regular files and
   directories only, traversal rejection, deterministic modes) is pinned so a "simplification"
   back to stdlib `extractall` semantics is a visible contract change.

## Constants

- `CONTEXT_FILE` SHALL be `".vanguarstew_context.json"` and `README_PROBE_NAMES` SHALL be
  `("README.md", "README.rst", "README.txt", "README", "docs/README.md")` — both imported from
  `agent/context.py` so freeze and the agent-side git fallback stay aligned (#937).
- `build_context` and `write_frozen` SHALL default `lookback` to `50`; `write_frozen` SHALL
  default `scrub` to `True`.
- Commit SHAs in context records SHALL be abbreviated to 10 characters; the README excerpt
  SHALL be capped at 4000 characters; `releases` SHALL keep the last 10 tags.
- Extracted directories SHALL be mode `0o755`; extracted files SHALL be `0o644`, or `0o755`
  when the member's owner-execute bit is set.
- The context file SHALL be JSON with `indent=1`, UTF-8.

## Acceptance criteria (EARS)

### Git wrapper (`_git`)

- `_git(repo, *args, check=True)` SHALL run exactly `["git", "-C", repo, *args]` with captured
  text output and SHALL return the process stdout.
- WHEN git exits non-zero AND `check` is true THEN it SHALL raise
  `RuntimeError(f"git {' '.join(args)} failed: {stderr.strip()}")` — e.g.
  `git log deadbeef123 failed: fatal: ambiguous argument ...`.
- WHEN git exits non-zero AND `check` is false THEN it SHALL return the (possibly empty)
  stdout without raising.
- WHEN the `git` binary is not on `PATH` THEN the spawn-site `FileNotFoundError` SHALL be
  translated into a `RuntimeError` naming git and `not found on PATH` with an install hint
  (#1188, fixing #1187) — never a raw `OSError` traceback.

### Origin remote (`origin_url`)

- `origin_url(repo)` SHALL return the stripped stdout of `git remote get-url origin`.
- WHEN the repo has no `origin` remote THEN it SHALL return `""` (the call runs with
  `check=False`), never raise.

### File snapshot (`file_at`)

- `file_at(repo, commit, path)` SHALL return the exact stdout of `git show {commit}:{path}`
  on success.
- WHEN the path does not exist at that commit, or the commit is unknown, THEN it SHALL return
  `""` — degradation is silent and undifferentiated (no error, no distinction between the two
  failure causes).

### Tree export (`export_tree`)

- `export_tree(repo, commit, dest)` SHALL create `dest` (`exist_ok`) and run exactly
  `["git", "-C", repo, "archive", "--format=tar", commit]` in bytes mode.
- WHEN git archive exits non-zero THEN it SHALL raise
  `RuntimeError("git archive failed for {commit}: {stderr}")`, with the `: {stderr}` suffix
  omitted when stderr is empty (#355, fixing #201 — previously an opaque
  `tarfile.ReadError`).
- WHEN git archive exits zero with empty stdout THEN it SHALL raise
  `RuntimeError("git archive failed for {commit}: empty archive")` — a defensive guard; real
  git emits a non-empty tar even for an empty tree.
- The archive SHALL be extracted with the module's own uniform policy below — never
  `tarfile.extractall(filter='data')` or unfiltered `extractall`, whose availability and
  semantics differ across Python 3.10–3.12 (#173, closing #156).

### Tar member resolution (`_safe_target`)

- Member names SHALL have backslashes normalized to `/`, leading slashes stripped (absolute
  names are neutralized under `dest`, not written to the filesystem root), and empty and `"."`
  components dropped — so `sub\file.txt`, `./a//b`, and `/abs.txt` all resolve under `dest`.
- WHEN no path components remain (names like `""`, `"/"`, `"."`) or any component is `".."`
  THEN it SHALL raise `tarfile.TarError("unsafe path in archive: ...")`.
- A resolved target outside `dest` SHALL raise `tarfile.TarError("path escapes destination:
  ...")` (residual containment check).

### Extraction policy (`_safe_extractall`)

- The archive SHALL be walked in a single forward pass (so non-seekable streams work), with
  each member resolved through `_safe_target`.
- Directory members SHALL be created with mode `0o755` regardless of the recorded mode; only
  regular-file members SHALL be extracted, with mode `0o755` iff the member's owner-execute
  bit (`mode & 0o100`) is set, else `0o644` — deterministic across runtimes and umasks.
- Symlinks, hard links, devices, and FIFOs SHALL be skipped silently — never materialized.
- **As-built:** a regular member whose `extractfile` returns `None` is skipped — a defensive
  branch not reachable through `git archive` output.

### Context assembly (`build_context`) — git calls

- `build_context(repo, commit, lookback=50)` SHALL issue exactly, in order:
  1. `git -C {repo} log --pretty=format:%H%x09%cI%x09%s -n {lookback} {commit}` (checked);
  2. `git -C {repo} show -s --format=%ct {commit}` (unchecked — T for the tag filter,
     spec 003);
  3. `git -C {repo} tag --merged {commit} --sort=creatordate
     --format=%(creatordate:unix)%09%(refname:strip=2)` (unchecked);
  4. one `git -C {repo} show {commit}:{name}` per README probe name, stopping at the first
     non-empty content.
- WHEN `commit` is unknown THEN the checked log call SHALL raise `RuntimeError` — the
  function raises rather than returning a partial context.

### Context assembly — record shapes

- The result SHALL carry exactly the keys `frozen_at`, `recent_commits`, `open_issues`,
  `open_prs`, `labels`, `milestones`, `releases`, `readme_excerpt`, `_source`; `_source`
  SHALL be `"git-freeze"`.
- `recent_commits` SHALL list up to `lookback` commits, newest first, each exactly
  `{"sha": <full sha>[:10], "date": <%cI committer ISO>, "subject": ...}`. The log line parse
  SHALL split on at most two tabs (`split("\t", 2)`), so a subject containing tabs survives
  intact; lines with fewer than three fields SHALL be dropped. (`%cI` output MAY be
  `Z`-suffixed depending on the git build.)
- `frozen_at` SHALL be `{"commit": commit[:10], "date": <newest commit's date>}`, with `date`
  `None` when the log parse yields no commits (a defensive branch — a valid commit always
  logs itself). **As-built:** the `commit` field is the *caller's argument* truncated to 10
  characters, never resolved — `build_context(repo, "HEAD")` records `"HEAD"` verbatim. The
  runner always passes a full task `freeze_commit` SHA, so production contexts carry a
  10-char SHA prefix, but symbolic names pass through untranslated.
- `open_issues`, `open_prs`, `labels`, and `milestones` SHALL be constant `[]`. **As-built:**
  the in-code comment says "populated from the GitHub API in M2", but this module never
  populates them — enrichment happens in `benchmark/github_context.py::enrich_context` at the
  runner call site (and only when enabled), and `labels` is not among the keys enrichment
  copies, so `labels` remains `[]` on the enriched path too.
- `releases` SHALL be `[{"tag": t}, ...]` for the **last 10** filtered tags. **As-built
  (headline):** a git-only release record carries exactly one key, `tag` — no `published_at`,
  no `name` — diverging from the GitHub-API path, whose release records are
  `{tag, published_at}`. Downstream consumers see releases without dates on the git-only
  path; `scrub_context` already special-cases this (it scrubs `tag` *and* `name` because the
  tag is a release's only identifier here).
- Tag-line parsing (the policy itself — creator date `<= T`, chronological order, the
  lightweight-tag limitation — is owned by spec 003): each line SHALL be partitioned on the
  first tab into `(creatordate:unix, refname)`; empty-name lines SHALL be skipped; a
  non-numeric creator-date field, or an unparsable `%ct` (T unknown), SHALL disable the date
  comparison and keep the tag — the parse level fails open, with `--merged` reachability
  still applying.
- `readme_excerpt` SHALL be the content of the first `README_PROBE_NAMES` entry whose
  `file_at` result is non-empty, capped at exactly 4000 characters; a README that exists but
  is empty SHALL be skipped in favor of later probes (truthiness test); with no hit it SHALL
  be `""`.

### Frozen write (`write_frozen`)

- `write_frozen(repo, commit, dest, lookback=50, scrub=True)` SHALL run, in order:
  `export_tree`, `build_context`, then `scrub_context` iff `scrub` (#24), and SHALL write the
  resulting dict as JSON (`indent=1`, UTF-8) to `dest/.vanguarstew_context.json` — inside the
  exported tree, where the agent reads it — returning exactly the dict it wrote.
- WHEN `scrub` is left at its default THEN the returned/written context SHALL additionally
  carry `_forward_signal_scrubbed: True` with text fields scrubbed (semantics owned by
  spec 003); WHEN `scrub` is `False` THEN the raw git-only context SHALL be written, with no
  `_forward_signal_scrubbed` key.
- **As-built:** the module docstring says "We export the working tree at T", but the export
  is the *committed tree* of `commit` via `git archive` under the uniform extraction policy —
  untracked or uncommitted files never appear, and symlinks recorded in the tree are dropped
  rather than materialized.

## Out of scope

- `parse_path_list` — owned by
  [`specs/021-benchmark-freeze-path-parse`](../021-benchmark-freeze-path-parse/spec.md).
- The freeze-point-T definition, the knowable-at-T tag policy and its lightweight-tag
  limitation, and the forward-reference scrub semantics — owned by
  [`specs/003-leakage-integrity`](../003-leakage-integrity/spec.md) (audited after the fact by
  [`specs/022-benchmark-leakage-audit`](../022-benchmark-leakage-audit/spec.md)).
- GitHub enrichment over the frozen context (`benchmark/github_context.py`) and the choice of
  freeze points / revealed windows (`benchmark/taskgen.py`).
- Post-run freeze summaries — `benchmark/freeze_coverage.py`
  ([spec 032](../032-benchmark-freeze-coverage/spec.md)) and `benchmark/freeze_digest.py`
  ([spec 053](../053-benchmark-freeze-digest/spec.md)) consume replay artifacts, not this
  module.
- Changing any freeze behavior — code changes follow the SDD loop in their own PRs.

## Verification

- `tests/test_spec_085_freeze.py` (this PR) pins the contract with **literal** expected
  values, never re-derived from the module: the exact git argv sequences (as full list
  literals, including `--sort=creatordate` and `-n 50`), the exact `RuntimeError` message
  shapes, the exact context key set and record shapes (10-char SHAs, tab-holding subjects,
  the date-less `{"tag": ...}` release records), the README probe/cap/empty-skip rules, the
  `_safe_target` resolutions and rejections, the directory-mode normalization, the
  `frozen_at.commit` pass-through quirk, and the `write_frozen` composition (scrub default,
  on-disk-equals-returned, `indent=1` layout). Real throwaway git repos are used for
  end-to-end truth; the degenerate branches real git cannot produce (empty archive with exit
  0, malformed log/tag lines, unparsable `%ct`) are driven through a stubbed process runner.
- Clause→test claims were spot-checked by mutation: boundary (`>` vs `>=` on the tag filter),
  key drops/additions on release records, SHA-prefix and README-cap off-by-ones, `split`
  maxsplit removal, scrub-default flip, sort-flag and lookback changes to the argv, and
  check-flag semantics each flip at least one test in this file or `tests/test_freeze.py`.
- Three branches have no discriminating test and are documented instead: the
  `extractfile(member) is None` skip (not reachable through `git archive`-produced tar
  members); the `FileNotFoundError` translation's exact URL text (the reachable part —
  type and `not found on PATH` message — is pinned by
  `existing::test_git_translates_a_missing_binary_into_a_clean_runtimeerror`); and
  `_safe_target`'s residual `"path escapes destination"` message, dead after the leading-slash
  strip and the `..`-component rejection already neutralize every escape — so only the
  reachable `"unsafe path in archive"` message is asserted (with `match=`), and the two
  messages are pinned as distinct rather than interchangeable.
- Chronological release ordering, the 10-tag window, the creator-date filter on real
  repos, the extraction policy's file modes / link skips / traversal rejection, and the
  archive-failure error remain covered by `tests/test_freeze.py`
  (#107/#332/#173/#355/#1188 et al.) and are mapped per clause in [`plan.md`](./plan.md)
  rather than re-asserted.
