"""#1493: a byte-valid JSON artifact whose integer literal exceeds Python 3.11's 4300-digit
int-string-conversion limit makes ``json.load`` raise a *plain* ``ValueError`` — not a
``json.JSONDecodeError``. Every ``scripts/`` CLI loader caught only ``json.JSONDecodeError``, so
such an artifact escaped the handler and dumped a raw traceback (exit 1) instead of the clean
"artifact is not valid JSON" message and exit 2 that malformed artifacts are supposed to get.

The loaders now catch the ``ValueError`` base (``JSONDecodeError`` is a subclass), covering both
the ordinary-bad-JSON and oversized-int cases in one arm. This pins the behavior on a
representative loader from each shape family; ``benchmark.repo_set.load_repo_set`` is covered in
``test_repo_set.py``.
"""

import importlib
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# One representative loader from each shape family: a guardrail integrity gate, a win/loss rate,
# a comparability check, a promotion gate, and a decisive-rate summary. All share the load_artifact
# helper whose except-arm was widened.
_LOADER_MODULES = [
    "objective_integrity",
    "win_rate",
    "comparability",
    "generalization_gate",
    "decisive_rate",
]

# Byte-for-byte valid JSON; only the magnitude of one integer literal (5000 digits > the 4300-digit
# limit) makes json.load raise. Kept small enough to stay well under any parser recursion limit.
_OVERSIZED_INT_ARTIFACT = '{"composite_mean": 0.5, "n": ' + "9" * 5000 + "}"


@pytest.fixture
def oversized_artifact(tmp_path):
    path = tmp_path / "oversized.json"
    path.write_text(_OVERSIZED_INT_ARTIFACT, encoding="utf-8")
    return str(path)


@pytest.mark.parametrize("module_name", _LOADER_MODULES)
def test_loader_exits_two_on_oversized_int_literal(module_name, oversized_artifact, capsys):
    module = importlib.import_module(f"scripts.{module_name}")
    with pytest.raises(SystemExit) as excinfo:
        module.load_artifact(oversized_artifact)
    assert excinfo.value.code == 2
    assert "not valid JSON" in capsys.readouterr().err
