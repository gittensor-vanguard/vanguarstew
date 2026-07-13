"""#1493: a valid-JSON artifact with an oversized integer literal must exit cleanly.

Since Python 3.11, ``json.load`` raises a *plain* ``ValueError`` (not ``json.JSONDecodeError``)
when a file contains an integer literal longer than the int-string-conversion limit (4300
digits). That escaped every ``except json.JSONDecodeError`` arm, so the CLIs dumped a raw
traceback. Widening the arm to ``except ValueError`` (``JSONDecodeError`` subclasses it) fixes
every loader; ``benchmark/repo_set.load_repo_set`` gets the same treatment.
"""

import importlib
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.repo_set import RepoSetError, load_repo_set  # noqa: E402

# A byte-for-byte valid JSON object whose only problem is the magnitude of one integer.
_OVERSIZED_INT_JSON = '{"composite_mean": 0.5, "tasks": ' + "9" * 5000 + "}"

# A representative spread of the script CLIs that load an artifact via load_artifact(path).
_LOADER_MODULES = [
    "objective_integrity",
    "win_rate",
    "skip_share",
    "comparability",
    "blend_weights",
    "generalization_gate",
    "composite_spread",
    "disagreement_outlook",
]


@pytest.mark.parametrize("module_name", _LOADER_MODULES)
def test_loader_exits_two_on_oversized_int_literal(module_name, tmp_path, capsys):
    cli = importlib.import_module(f"scripts.{module_name}")
    path = tmp_path / "oversized.json"
    path.write_text(_OVERSIZED_INT_JSON, encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        cli.load_artifact(str(path))
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "Traceback" not in err
    assert str(path) in err


def test_load_repo_set_wraps_oversized_int_as_repo_set_error(tmp_path):
    path = tmp_path / "set.json"
    path.write_text(_OVERSIZED_INT_JSON, encoding="utf-8")
    with pytest.raises(RepoSetError) as excinfo:
        load_repo_set(str(path))
    assert "invalid JSON" in str(excinfo.value)


def test_load_repo_set_still_distinguishes_non_utf8(tmp_path):
    # The widened ValueError arm must not swallow the distinct non-UTF-8 message: UnicodeDecodeError
    # subclasses ValueError but is caught first.
    path = tmp_path / "latin1.json"
    path.write_bytes(b'{"tier": "\xff\xfe not utf-8"}')
    with pytest.raises(RepoSetError) as excinfo:
        load_repo_set(str(path))
    assert "not valid UTF-8" in str(excinfo.value)
