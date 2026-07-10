"""A directory artifact path must exit cleanly (code 2), never dump a traceback (#1376).

Every ``scripts/`` CLI that reads a JSON artifact/task file caught ``FileNotFoundError`` but
not other ``OSError`` subclasses, so ``open(a_directory)`` (``IsADirectoryError`` on Linux,
``PermissionError`` on Windows) escaped the handler as an unhandled traceback. Each loader now
catches ``OSError`` and exits 2.
"""

import importlib
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# The 20 CLIs hardened here. (objective_integrity has its own in-flight PR; review_pr and
# leaderboard_feed do not read a user-supplied artifact path.)
CLIS = [
    "artifact_snapshot", "blend_weights", "comparability", "decisive_rate",
    "disagreement_outlook", "freeze_digest", "gap_outlook", "generalization_gate",
    "improvement", "judge_wlt", "margin_outlook", "repeatability_gate", "repo_task_mean",
    "run_clean", "skip_budget", "skip_share", "task_independence", "task_integrity",
    "task_uniformity", "win_rate",
]


@pytest.mark.parametrize("name", CLIS)
def test_loader_exits_cleanly_on_directory_path(name, tmp_path, capsys):
    module = importlib.import_module(f"scripts.{name}")
    loader = getattr(module, "load_artifact", None) or getattr(module, "load_tasks", None)
    assert loader is not None, f"scripts.{name} has no load_artifact/load_tasks"

    # tmp_path is an existing directory: open() raises IsADirectoryError/PermissionError,
    # both OSError -> the loader must convert it to a clean SystemExit(2), not let it escape.
    with pytest.raises(SystemExit) as exc:
        loader(str(tmp_path))
    assert exc.value.code == 2
    assert "cannot read" in capsys.readouterr().err
