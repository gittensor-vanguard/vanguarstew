"""Spec directory numbers must be unique, and each module must have one canonical spec (#2143).

Specs are referenced by number in commit messages, PR bodies, and contract-test docstrings,
so a number used by two specs makes every such reference ambiguous and leaves the affected
module with no single document to review a change against.

Numbers were being allocated by scanning for the highest existing prefix, so two spec
branches opened around the same time always collided — six pairs had accumulated, the most
recent appearing a day after the previous batch was catalogued. This test turns the
convention into something CI enforces at the point the collision is introduced.
"""

import os
import re
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

SPECS = os.path.join(ROOT, "specs")

# `NNN-slug`: a zero-padded number, a hyphen, then the spec's slug.
_SPEC_DIR_RE = re.compile(r"^(\d+)-(.+)$")

# `# Spec 042 — ...` / `# Plan 042 — ...`: the document's own number, from its first heading.
_DOC_HEADING_RE = re.compile(r"^#\s+(?:Spec|Plan)\s+(\d+)\b")

# `test_spec_042_...`: a contract-test file a spec's prose points a reader at. Its number should
# be the spec's own — a renumbered spec that keeps the old reference sends the reader to a file
# that no longer exists (or that now belongs to a different spec).
_TEST_REF_RE = re.compile(r"test_spec_(\d+)_")

# `- **Status:** superseded by [`specs/088-benchmark-repo-task-mean`](...)`: a spec that has been
# retired in favor of another one, naming the directory that replaced it.
_SUPERSEDED_RE = re.compile(r"^-\s+\*\*Status:\*\*\s+superseded by \[`specs/([^`]+)`\]")

# Any `- **Status:** ...` line, so a spec that carries none at all is reported rather than
# silently counted as canonical.
_STATUS_RE = re.compile(r"^-\s+\*\*Status:\*\*")

DOCS = ("spec.md", "plan.md")


def _spec_dirs_by_number() -> dict:
    by_number = defaultdict(list)
    for name in sorted(os.listdir(SPECS)):
        if not os.path.isdir(os.path.join(SPECS, name)):
            continue
        match = _SPEC_DIR_RE.match(name)
        if match:
            by_number[match.group(1)].append(name)
    return by_number


def _specs_by_slug() -> dict:
    """Spec directories grouped by the slug after their number — one group per module."""
    by_slug = defaultdict(list)
    for name in sorted(os.listdir(SPECS)):
        if not os.path.isdir(os.path.join(SPECS, name)):
            continue
        match = _SPEC_DIR_RE.match(name)
        if match:
            by_slug[match.group(2)].append(name)
    return by_slug


def _superseded_by(name: str):
    """The spec directory `name` says it was superseded by, or `None` when it is canonical."""
    path = os.path.join(SPECS, name, "spec.md")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if _STATUS_RE.match(line):
                match = _SUPERSEDED_RE.match(line)
                return match.group(1) if match else None
    return None


def test_spec_directories_are_numbered():
    """Every directory under specs/ follows the `NNN-slug` convention."""
    unnumbered = [
        name for name in sorted(os.listdir(SPECS))
        if os.path.isdir(os.path.join(SPECS, name)) and not _SPEC_DIR_RE.match(name)
    ]
    assert not unnumbered, f"spec directories without a numeric prefix: {unnumbered}"


def test_spec_numbers_are_unique():
    """No two specs share a number, so a reference by number is unambiguous."""
    collisions = {
        number: names
        for number, names in _spec_dirs_by_number().items()
        if len(names) > 1
    }
    assert not collisions, (
        "spec numbers used by more than one spec: "
        + "; ".join(f"{number}: {names}" for number, names in sorted(collisions.items()))
        + " — allocate the next unused number instead of reusing one"
    )


def test_spec_documents_declare_their_directory_number():
    """Each spec.md / plan.md heading carries the number of the directory it lives in.

    Renumbering a directory without rewriting its headings leaves the document announcing a
    number another spec now owns, which is the same ambiguity a duplicate directory number
    creates — and it is invisible to the uniqueness check above.
    """
    mismatches = []
    for name, number in sorted(
        (name, number)
        for number, names in _spec_dirs_by_number().items()
        for name in names
    ):
        for doc in DOCS:
            path = os.path.join(SPECS, name, doc)
            if not os.path.isfile(path):
                continue
            with open(path, encoding="utf-8") as handle:
                heading = handle.readline().strip()
            match = _DOC_HEADING_RE.match(heading)
            if match is None:
                mismatches.append(f"{name}/{doc}: heading does not start with a number: {heading!r}")
            elif match.group(1) != number:
                mismatches.append(f"{name}/{doc}: heading says {match.group(1)}, directory says {number}")
    assert not mismatches, (
        "spec documents whose number disagrees with their directory: "
        + "; ".join(mismatches)
        + " — rewrite the heading when a spec is renumbered"
    )


def test_spec_documents_reference_their_own_test_file():
    """Each spec.md / plan.md points at its OWN ``tests/test_spec_NNN_*.py`` file.

    The heading check above catches a renumbered directory whose *heading* was not rewritten;
    this catches the same drift in the in-body ``test_spec_NNN`` cross-reference, which is exactly
    what #2346 had to repair after the 087-092 renumbering (each spec still named the test file it
    had before the renumber, a number another spec now owns).
    """
    mismatches = []
    for name, number in sorted(
        (name, number)
        for number, names in _spec_dirs_by_number().items()
        for name in names
    ):
        for doc in DOCS:
            path = os.path.join(SPECS, name, doc)
            if not os.path.isfile(path):
                continue
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
            for ref in _TEST_REF_RE.findall(text):
                if int(ref) != int(number):
                    mismatches.append(
                        f"{name}/{doc}: references test_spec_{ref}_*, directory says {number}")
    assert not mismatches, (
        "spec documents referencing a test file whose number disagrees with their directory: "
        + "; ".join(mismatches)
        + " — repoint the reference when a spec is renumbered"
    )


def test_each_specified_module_has_one_canonical_spec():
    """A module specified more than once names exactly one spec that is not superseded.

    Unique numbers stop two specs from answering to the same *reference*; they do not stop two
    specs from describing the same *module*, which is the other half of #2143 — three documents
    covered `benchmark/repo_task_mean.py` and two covered `benchmark/tie_order_share.py` with
    nothing marking which one a change is reviewed against. Specs for one module share a slug
    (`NNN-benchmark-repo-task-mean`), so a second one shows up as a second group member here; a
    duplicate written under a *different* slug is outside what this can see.
    """
    ambiguous = []
    for slug, names in sorted(_specs_by_slug().items()):
        if len(names) < 2:
            continue
        canonical = [name for name in names if _superseded_by(name) is None]
        if len(canonical) != 1:
            ambiguous.append(f"{slug}: {len(canonical)} canonical of {names}")
    assert not ambiguous, (
        "modules whose specs do not leave exactly one canonical document: "
        + "; ".join(ambiguous)
        + " — give every spec but one a `- **Status:** superseded by [`specs/NNN-slug`](...)` line"
    )


def test_superseded_specs_point_at_a_canonical_spec():
    """A superseded spec names the spec that replaced it, and that spec exists and is canonical."""
    dangling = []
    for name in sorted(name for names in _specs_by_slug().values() for name in names):
        target = _superseded_by(name)
        if target is None:
            continue
        if not os.path.isdir(os.path.join(SPECS, target)):
            dangling.append(f"{name} → {target}, which does not exist")
        elif target == name:
            dangling.append(f"{name} → itself")
        elif _superseded_by(target) is not None:
            dangling.append(f"{name} → {target}, which is itself superseded")
    assert not dangling, (
        "superseded specs that do not point at a canonical spec: "
        + "; ".join(dangling)
        + " — point at the directory that replaced it"
    )
