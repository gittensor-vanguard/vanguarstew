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

# `test_spec_042_...`: a contract-test file a spec's prose points a reader at. Its number should
# be the spec's own — a renumbered spec that keeps the old reference sends the reader to a file
# that no longer exists (or that now belongs to a different spec).
_TEST_REF_RE = re.compile(r"test_spec_(\d+)_")

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


# `tests/test_spec_042_...py`: a contract-test file, named for the spec it verifies.
_TEST_FILE_RE = re.compile(r"^test_spec_(\d+)_")

TESTS = os.path.join(ROOT, "tests")


def test_spec_test_files_map_to_an_existing_spec_directory():
    """Every ``tests/test_spec_NNN_*.py`` names a spec directory that still exists.

    The reverse of the check above: that one guards a *spec* pointing at the wrong test; this
    guards a *test file* left stranded when its spec is renumbered or removed — a ``test_spec_042``
    still on disk after ``042`` became ``087`` announces a contract for a number no spec owns,
    the same ambiguity from the other side.
    """
    numbered_dirs = set(_spec_dirs_by_number())
    orphans = []
    for name in sorted(os.listdir(TESTS)):
        match = _TEST_FILE_RE.match(name)
        if match and match.group(1) not in numbered_dirs:
            orphans.append(name)
    assert not orphans, (
        "contract-test files with no matching spec directory: "
        + ", ".join(orphans)
        + " — rename or remove the test when its spec is renumbered or dropped"
    )
