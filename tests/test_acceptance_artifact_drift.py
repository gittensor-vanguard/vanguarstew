"""Guard: a checked-in acceptance artifact must describe the repo set it claims to.

`m3_acceptance_result.json` is the evidence ROADMAP cites for M3 (and again for M4's
acceptance bullet). It records a `repo_set.path`, so the repos it scored should be the repos
that config defines — otherwise the published figure describes a selection the repository no
longer contains, and a reader cannot reproduce it from the tree.

That is what happened in #2058: #1741 replaced `curated.json` and the artifact was not re-run.
Nothing connected the two, so the drift was invisible until someone compared them by hand.
These tests make it machine-visible.

The real-artifact assertion is `xfail` because the drift is still open — the fix is a
maintainer-side re-run (`run_eval --generalization`), which needs validator inference a
contributor cannot invoke. It flips to `xpass` the moment that lands, which is the signal to
drop the marker. The checker itself is exercised on synthetic artifacts below, so this file
proves the rule works even while the real artifact violates it.
"""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ["VANGUARSTEW_OFFLINE"] = "1"

from benchmark.repo_set import load_repo_set  # noqa: E402

ACCEPTANCE_ARTIFACT = os.path.join(ROOT, "m3_acceptance_result.json")
PARTITIONS = ("tuned", "held_out")


def _scored_repo_names(partition: dict) -> set:
    """Repo names a partition actually scored, including entries that errored out.

    A repo the run skipped still names the config it came from, so it counts toward "which
    selection was this artifact produced against" even though it contributed no score.
    """
    if not isinstance(partition, dict):
        return set()
    names = set()
    for entry in partition.get("per_repo") or []:
        if isinstance(entry, dict) and isinstance(entry.get("repo_name"), str):
            names.add(entry["repo_name"])
    return names


def _configured_repo_names(repo_set, selection: str) -> set:
    entries = repo_set.held_out() if selection == "held_out" else repo_set.tuned()
    return {entry.name for entry in entries}


def drifted_partitions(artifact: dict, repo_set) -> dict:
    """Map partition -> repos it scored that its declared config does not define.

    Empty means the artifact and the config agree. Only extra repos are reported: a config
    may legitimately gain a repo after an artifact was produced without invalidating it,
    but an artifact scoring a repo the config never listed cannot be reproduced from it.
    """
    out = {}
    for name in PARTITIONS:
        partition = artifact.get(name)
        if not isinstance(partition, dict):
            continue
        extra = _scored_repo_names(partition) - _configured_repo_names(repo_set, name)
        if extra:
            out[name] = sorted(extra)
    return out


def _load_acceptance():
    with open(ACCEPTANCE_ARTIFACT, "r", encoding="utf-8") as handle:
        return json.load(handle)


# --- the real artifact ---------------------------------------------------------------------

def test_acceptance_artifact_declares_the_repo_set_it_used():
    """Whatever else is true, the artifact must say which config produced it."""
    artifact = _load_acceptance()
    declared = artifact.get("repo_set")
    assert isinstance(declared, str) and declared, (
        "acceptance artifact must record the repo-set path it was produced against"
    )
    assert os.path.isfile(os.path.join(ROOT, declared)), (
        f"acceptance artifact names a repo set that does not exist: {declared}"
    )


def test_acceptance_artifact_marks_repo_set_drift_as_historical():
    """#2058: the file must signal that its repo_set.path no longer describes what it scored."""
    drift = _load_acceptance().get("repo_set_drift")
    assert isinstance(drift, dict), "acceptance artifact must record repo_set_drift metadata"
    assert drift.get("status") == "historical"
    assert drift.get("issue") == 2058
    note = drift.get("note")
    assert isinstance(note, str) and note.strip(), "repo_set_drift must explain the supersession"


@pytest.mark.xfail(
    strict=False,
    reason=(
        "#2058: m3_acceptance_result.json predates #1741's curated.json replacement. Fixing it "
        "requires re-running run_eval --generalization with validator inference. Remove this "
        "marker when the re-run lands."
    ),
)
def test_acceptance_artifact_matches_its_declared_repo_set():
    artifact = _load_acceptance()
    repo_set = load_repo_set(os.path.join(ROOT, artifact["repo_set"]))
    drift = drifted_partitions(artifact, repo_set)
    assert not drift, (
        f"acceptance artifact scored repos its declared config does not define: {drift}. "
        f"The published figure cannot be reproduced from {artifact['repo_set']}."
    )


def test_the_known_drift_is_exactly_what_2058_documents():
    """Characterization: pin today's drift so an unrelated change cannot alter it unnoticed.

    This is the counterpart to the xfail above — it asserts the drift is still the *known*
    one (`hatch` in tuned, `httpx` in held_out) rather than silently becoming something else.
    """
    artifact = _load_acceptance()
    repo_set = load_repo_set(os.path.join(ROOT, artifact["repo_set"]))
    assert drifted_partitions(artifact, repo_set) == {
        "tuned": ["hatch"],
        "held_out": ["httpx"],
    }


# --- the checker itself, on synthetic artifacts ---------------------------------------------

class _Entry:
    def __init__(self, name, held_out):
        self.name = name
        self._held_out = held_out


class _RepoSet:
    def __init__(self, names_held_out):
        self._entries = [_Entry(n, h) for n, h in names_held_out]

    def tuned(self):
        return [e for e in self._entries if not e._held_out]

    def held_out(self):
        return [e for e in self._entries if e._held_out]


def _artifact(tuned, held_out):
    return {
        "tuned": {"per_repo": [{"repo_name": n} for n in tuned]},
        "held_out": {"per_repo": [{"repo_name": n} for n in held_out]},
    }


def test_checker_reports_no_drift_when_artifact_matches_config():
    rs = _RepoSet([("a", False), ("b", False), ("c", True)])
    assert drifted_partitions(_artifact(["a", "b"], ["c"]), rs) == {}


def test_checker_flags_a_repo_the_config_does_not_define():
    rs = _RepoSet([("a", False), ("c", True)])
    assert drifted_partitions(_artifact(["a", "gone"], ["c"]), rs) == {"tuned": ["gone"]}


def test_checker_flags_each_partition_independently():
    rs = _RepoSet([("a", False), ("c", True)])
    drift = drifted_partitions(_artifact(["x"], ["y"]), rs)
    assert drift == {"tuned": ["x"], "held_out": ["y"]}


def test_checker_allows_the_config_to_gain_repos():
    """A config that grew since the run is not drift — the artifact is still reproducible."""
    rs = _RepoSet([("a", False), ("b", False), ("new", False), ("c", True)])
    assert drifted_partitions(_artifact(["a"], ["c"]), rs) == {}


def test_checker_counts_a_repo_that_errored_out():
    """A skipped/errored repo still identifies the selection the run used."""
    rs = _RepoSet([("a", False)])
    artifact = {"tuned": {"per_repo": [
        {"repo_name": "a"},
        {"repo_name": "boom", "error": "no usable tasks"},
    ]}}
    assert drifted_partitions(artifact, rs) == {"tuned": ["boom"]}


def test_checker_tolerates_malformed_partitions():
    rs = _RepoSet([("a", False)])
    for bad in (None, 42, "nope", [], {"per_repo": None}, {"per_repo": [7, None, {}]}):
        assert drifted_partitions({"tuned": bad}, rs) == {}
