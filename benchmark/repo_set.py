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

TIERS = ("recent", "obscure")

# Allowed freeze-window hint keys and their required types. `recent_bias` is a bool;
# `rotation_seed`/`min_history` are ints (and must NOT be bools). `after`/`before` are
# date-ish strings the curator uses to bound freeze-point selection.
_FREEZE_KEYS = {
    "after": "str",
    "before": "str",
    "recent_bias": "bool",
    "rotation_seed": "int",
    "min_history": "int",
}

# A checked-in *starter* config with placeholder sources — replace with vetted repos before
# real scoring. Named "example" (not "default") so it can't be mistaken for an operational set.
EXAMPLE_REPO_SET = os.path.join(os.path.dirname(__file__), "repo_sets", "example.json")


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
        elif expected == "bool":
            _require(isinstance(value, bool), f"{where}: freeze_window.{key} must be a boolean")
        elif expected == "int":
            _require(isinstance(value, int) and not isinstance(value, bool),
                     f"{where}: freeze_window.{key} must be an integer")
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
    example, or a curated config's path for a real scoring run.
    """
    _require(os.path.exists(path), f"repo-set config not found: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise RepoSetError(f"invalid JSON in {path}: {exc}") from exc
    return validate_repo_set(data)
