"""Spec directory numbers must be unique (#2143).

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
