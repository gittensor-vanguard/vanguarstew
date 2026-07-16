"""Alignment guard for the two forward-reference scrubbers.

`benchmark/leakage.py` `strip_forward_refs` (scored replay path) and `agent/context.py`
`_mask_forward_refs` (git-only fallback the agent sees) must neutralize the same forward
references identically. Both modules say so in-code and the invariant has been fixed
repeatedly (#946, #1003, #916/#937). They deliberately do NOT share code (the `agent/` split
must not depend on `benchmark/`), so nothing structurally forces them to agree; this test does.

If a future change touches one scrubber's link/ref/SHA handling but not the other, this fails.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest  # noqa: E402

from agent.context import _mask_forward_refs  # noqa: E402
from benchmark.leakage import strip_forward_refs  # noqa: E402

# One representative battery covering every branch both scrubbers implement.
_CASES = [
    # issue/PR back-references
    "part of #512 and closes #7",
    "the #1 requested feature stays",
    # GitHub deep-links: scheme, scheme-less, www, bare owner/repo, look-alike host
    "see https://github.com/o/r/pull/900 next",
    "tracked at github.com/o/r/issues/900",
    "cut in github.com/o/r/releases/tag/v9.9.9",
    "see www.github.com/o/r/pull/900 next",
    "clone from github.com/o/r to start",
    "notgithub.com/o/r/pull/900 is fine",
    # trailing punctuation around a link
    "see https://github.com/o/r/issues/5, next",
    "see https://github.com/o/r/pull/9.",
    # SHA-1: abbreviated + full, mixed case
    "commit 1a2b3c4 landed",
    "see " + "a" * 40 + " now",
    "See AbC1234 and deadBEEF1234 here",
    # SHA-256: full with a hex letter (masked) + full all-numeric (preserved)
    "regressed by " + "abc123" + "0" * 58 + " upstream",
    "processed " + "1" * 64 + " events",
    # boundary lengths that are NOT real hash lengths
    "blob " + "a" * 41 + " and " + "b" * 63 + " and " + "c" * 65,
    # plain numeric prose (never a SHA)
    "supports 2500000 requests, 1234567 users, year 2024",
    # markdown / bracket delimiters
    "[x](https://github.com/o/r/pull/7) and (github.com/o/r/issues/3)",
    # empty / whitespace
    "",
    "   ",
    # combined
    "Fixes #512 via github.com/o/r/pull/900 at commit deadbeef1234, up 2500000",
]

# Non-string inputs: both scrubbers must fail soft to "" (never raise).
_NON_STRING = [None, 123, 12.5, True, ["#900"], {"x": 1}, b"bytes"]


@pytest.mark.parametrize("text", _CASES)
def test_scrubbers_agree_on_text(text):
    assert strip_forward_refs(text) == _mask_forward_refs(text), text


@pytest.mark.parametrize("value", _NON_STRING)
def test_scrubbers_agree_on_non_string_input(value):
    # Both treat a non-string as empty scrubbable text and return "" rather than raising.
    assert strip_forward_refs(value) == _mask_forward_refs(value) == ""
