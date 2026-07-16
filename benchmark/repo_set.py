"""Leakage-safe repo-set config + loader (M3).

A *repo set* is a curated JSON config listing the repositories the benchmark replays, with
per-repo **freeze-window hints**, chosen per the leakage strategy: a mix of **recent** repos
(commit windows past a model's training cutoff) and **obscure** ones (unlikely to be
memorized). See the starter `benchmark/repo_sets/example.json` and docs/architecture.md.

The loader validates the config strictly — unknown or mistyped fields are errors, not silent
passes — because a leakage-safe set is only as trustworthy as the config that defines it. It
then hands the runner a typed view: tuned vs held-out, per tier, with freeze hints that map
onto `run_replay`'s knobs (`recent_bias`, `rotation_seed`, plus `after`/`before`/`min_history`
window bounds).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date

TIERS = ("recent", "obscure")

# Allowed freeze-window hint keys and their required types. `recent_bias` is a bool;
# `rotation_seed`/`min_history`/`horizon_days` are ints (and must NOT be bools). `after`/`before`
# are date-ish strings the curator uses to bound freeze-point selection.
#
# `horizon_days` switches the revealed window from "the next N commits" to "everything landing in
# the next N days", and is set PER REPO from one uniform rule: the repo's own median release-cycle
# length, clamped to [14, 90] days. A fixed commit count is uniform in a dimension that carries no
# meaning and wildly non-uniform in the one that does — `horizon=5` is ~24 minutes of work on a
# repo doing ~290 commits/day and ~46 days on one doing ~40/year. Over so short a span the ground
# truth is dominated by which maintainer happened to be at the keyboard, not by where the project
# was going. A release-cycle window makes the task mean the same thing everywhere ("what lands
# before the next release?") and takes the release signal from degenerate (~24% of windows contain
# one, so a no-op predictor wins) to discriminating (~42-48%).
_FREEZE_KEYS = {
    "after": "str",
    "before": "str",
    "recent_bias": "bool",
    "rotation_seed": "int",
    "min_history": "int",
    "horizon_days": "int",
}

# A checked-in *starter* config with placeholder sources — replace with vetted repos before
# real scoring. Named "example" (not "default") so it can't be mistaken for an operational set.
EXAMPLE_REPO_SET = os.path.join(os.path.dirname(__file__), "repo_sets", "example.json")
CURATED_REPO_SET = os.path.join(os.path.dirname(__file__), "repo_sets", "curated.json")

# Starter configs use this exact GitHub owner placeholder — not a substring search, so real
# repos whose names happen to contain "OWNER" are not misclassified.
PLACEHOLDER_SOURCE_PREFIX = "https://github.com/OWNER/"


def is_placeholder_source(source: str) -> bool:
    """Return True when ``source`` is the shipped starter's ``OWNER/...`` placeholder URL."""
    return isinstance(source, str) and source.startswith(PLACEHOLDER_SOURCE_PREFIX)


class RepoSetError(ValueError):
    """Raised when a repo-set config is malformed."""


@dataclass(frozen=True)
class RepoEntry:
    name: str
    source: str
    tier: str
    held_out: bool = False
    freeze_window: dict = field(default_factory=dict)
    notes: str = ""


class RepoSet:
    """A validated repo set: iterable of entries plus tuned/held-out/by-tier views."""

    def __init__(self, name, description, strategy, entries):
        self.name = name
        self.description = description
        self.strategy = strategy
        self.entries = list(entries)

    def __len__(self):
        return len(self.entries)

    def __iter__(self):
        return iter(self.entries)

    def names(self):
        return [e.name for e in self.entries]

    def sources(self):
        return [e.source for e in self.entries]

    def tuned(self):
        return [e for e in self.entries if not e.held_out]

    def held_out(self):
        return [e for e in self.entries if e.held_out]

    def by_tier(self, tier):
        if tier not in TIERS:
            raise RepoSetError(f"unknown tier {tier!r}; expected one of {TIERS}")
        return [e for e in self.entries if e.tier == tier]

    def partition(self, which: str = "tuned"):
        """Return entries for ``tuned``, ``held_out``, or ``all``."""
        if which == "tuned":
            return self.tuned()
        if which == "held_out":
            return self.held_out()
        if which == "all":
            return list(self.entries)
        raise RepoSetError(f"unknown partition {which!r}; expected 'tuned', 'held_out', or 'all'")


def replay_kwargs(entry: RepoEntry) -> dict:
    """Map a repo-set entry's freeze_window hints onto ``run_replay`` keyword args."""
    fw = entry.freeze_window or {}
    kwargs = {}
    if "recent_bias" in fw:
        kwargs["recent_bias"] = fw["recent_bias"]
    if "rotation_seed" in fw:
        kwargs["rotation_seed"] = fw["rotation_seed"]
    if "min_history" in fw:
        kwargs["min_history"] = fw["min_history"]
    if "after" in fw:
        kwargs["after"] = fw["after"]
    if "before" in fw:
        kwargs["before"] = fw["before"]
    if "horizon_days" in fw:
        kwargs["horizon_days"] = fw["horizon_days"]
    return kwargs


def _require(cond, message):
    if not cond:
        raise RepoSetError(message)


def _validate_freeze_window(fw, where):
    _require(isinstance(fw, dict), f"{where}: 'freeze_window' must be an object")
    for key, value in fw.items():
        _require(key in _FREEZE_KEYS,
                 f"{where}: unknown freeze_window key {key!r}; allowed: {sorted(_FREEZE_KEYS)}")
        expected = _FREEZE_KEYS[key]
        if expected == "str":
            _require(isinstance(value, str), f"{where}: freeze_window.{key} must be a string")
            _require(value.strip(), f"{where}: freeze_window.{key} must be non-empty")
            # `after`/`before` bound freeze-point selection and are parsed with
            # `date.fromisoformat(value[:10])` in taskgen. A non-empty-but-unparseable value
            # (a typo like "2023-13-01", a non-ISO format) passes the string check but then
            # crashes task generation with an opaque ValueError mid-run, so validate that it
            # parses as an ISO date here — fail-fast at config load, like every other field.
            if key in ("after", "before"):
                try:
                    date.fromisoformat(value[:10])
                except ValueError:
                    _require(
                        False,
                        f"{where}: freeze_window.{key} must be an ISO date (YYYY-MM-DD), "
                        f"got {value!r}",
                    )
        elif expected == "bool":
            _require(isinstance(value, bool), f"{where}: freeze_window.{key} must be a boolean")
        elif expected == "int":
            _require(isinstance(value, int) and not isinstance(value, bool),
                     f"{where}: freeze_window.{key} must be an integer")
            if key == "min_history":
                _require(value >= 1, f"{where}: freeze_window.min_history must be >= 1")
    # Cross-field: a window whose `after` is later than its `before` can never contain a
    # commit, so taskgen silently yields zero tasks and the repo is quietly dropped from the
    # (leakage-safe, curated) benchmark with no error — a config typo that erodes the set
    # instead of failing loudly. Reject reversed bounds at load time.
    after, before = fw.get("after"), fw.get("before")
    if isinstance(after, str) and isinstance(before, str):
        try:
            lo, hi = date.fromisoformat(after[:10]), date.fromisoformat(before[:10])
        except ValueError:
            lo = hi = None  # already reported field-by-field above
        if lo is not None and hi is not None:
            _require(
                lo <= hi,
                f"{where}: freeze_window.after ({after!r}) must be on or before "
                f"freeze_window.before ({before!r})",
            )
    return dict(fw)


def _validate_entry(raw, index, seen_names):
    where = f"repos[{index}]"
    _require(isinstance(raw, dict), f"{where}: each repo must be an object")

    name = raw.get("name")
    _require(isinstance(name, str) and name.strip(), f"{where}: 'name' is required and non-empty")
    _require(name not in seen_names, f"{where}: duplicate repo name {name!r}")
    seen_names.add(name)

    source = raw.get("source")
    _require(isinstance(source, str) and source.strip(),
             f"{where} ({name}): 'source' is required and non-empty")

    tier = raw.get("tier")
    _require(tier in TIERS, f"{where} ({name}): 'tier' must be one of {TIERS}, got {tier!r}")

    held_out = raw.get("held_out", False)
    _require(isinstance(held_out, bool), f"{where} ({name}): 'held_out' must be a boolean")

    notes = raw.get("notes", "")
    _require(isinstance(notes, str), f"{where} ({name}): 'notes' must be a string")

    freeze_window = _validate_freeze_window(raw.get("freeze_window", {}), f"{where} ({name})")

    unknown = set(raw) - {"name", "source", "tier", "held_out", "notes", "freeze_window"}
    _require(not unknown, f"{where} ({name}): unknown keys {sorted(unknown)}")

    return RepoEntry(name=name, source=source, tier=tier, held_out=held_out,
                     freeze_window=freeze_window, notes=notes)


def validate_repo_set(data) -> RepoSet:
    """Validate an already-parsed config object and return a RepoSet, or raise RepoSetError."""
    _require(isinstance(data, dict), "repo set must be a JSON object")

    # Strict top level: 'repos' is required; the metadata fields are optional strings; any
    # other key is a typo we refuse rather than silently drop.
    unknown = set(data) - {"name", "description", "strategy", "repos"}
    _require(not unknown, f"unknown top-level keys {sorted(unknown)}; "
                          "allowed: ['description', 'name', 'repos', 'strategy']")
    for key in ("name", "description", "strategy"):
        if key in data:
            _require(isinstance(data[key], str), f"top-level '{key}' must be a string")

    repos = data.get("repos")
    _require(isinstance(repos, list) and repos, "'repos' must be a non-empty list")

    seen = set()
    entries = [_validate_entry(raw, i, seen) for i, raw in enumerate(repos)]
    return RepoSet(
        name=data.get("name", ""),
        description=data.get("description", ""),
        strategy=data.get("strategy", ""),
        entries=entries,
    )


def load_repo_set(path) -> RepoSet:
    """Load and validate a repo-set config from `path`. Raises RepoSetError on any problem.

    `path` is required — there is no implicit default, so a config is always chosen on purpose
    (never the placeholder starter by accident). Pass `EXAMPLE_REPO_SET` to load the shipped
    example, or `CURATED_REPO_SET` / a custom path for operational scoring runs.
    """
    _require(os.path.exists(path), f"repo-set config not found: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except UnicodeDecodeError as exc:
        # A file that exists and is readable but is not valid UTF-8 (e.g. saved as UTF-16/latin-1,
        # or a binary file passed by mistake) makes json.load raise UnicodeDecodeError while
        # decoding the stream. UnicodeDecodeError subclasses ValueError, so this arm must come
        # before the general ValueError arm below to keep the "not valid UTF-8" wording distinct.
        raise RepoSetError(f"repo-set config {path} is not valid UTF-8: {exc}") from exc
    except ValueError as exc:
        # json.JSONDecodeError subclasses ValueError, and json.load also raises a *plain*
        # ValueError for an integer literal beyond the int-string-conversion digit limit
        # (Python 3.11+), which would otherwise escape a JSONDecodeError-only arm as a raw
        # traceback instead of a clean RepoSetError.
        raise RepoSetError(f"invalid JSON in {path}: {exc}") from exc
    except FileNotFoundError as exc:
        # FileNotFoundError is an OSError subclass, so it must be caught before the general
        # OSError branch below to keep the "not found" wording (the file was removed between
        # the exists() check and open() — a TOCTOU race) distinct from the unreadable case.
        raise RepoSetError(f"repo-set config not found: {path}") from exc
    except OSError as exc:
        # os.path.exists is true for a directory, and a file can exist but be unreadable
        # (permission denied), so open() can still raise IsADirectoryError/PermissionError.
        # Wrap it as RepoSetError so every caller gets a clean error, not a raw traceback.
        raise RepoSetError(f"cannot read repo-set config {path}: {exc}") from exc
    return validate_repo_set(data)
