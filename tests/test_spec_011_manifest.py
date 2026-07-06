"""Contract tests for specs/011-miner-manifest — assert vanguarstew_agent_files.json and the
repository tree satisfy the spec's EARS criteria: manifest shape, on-disk presence, harness
isolation, entrypoint linkage, and file cap. Static checks only; no network is used.
"""

import ast
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

MANIFEST_PATH = os.path.join(ROOT, "vanguarstew_agent_files.json")

_REQUIRED_KEYS = frozenset({
    "entrypoint", "entrypoint_symbol", "files", "max_files",
})

_ORCHESTRATION_MODULES = frozenset({
    "agent.py",
    "agent/__init__.py",
    "agent/llm.py",
    "agent/context.py",
    "agent/philosophy.py",
    "agent/planner.py",
    "agent/decider.py",
})


def _load_manifest() -> dict:
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        return json.load(f)


# --- Manifest document shape ---------------------------------------------------------------

def test_manifest_is_valid_json_object():
    manifest = _load_manifest()
    assert isinstance(manifest, dict)


def test_manifest_has_required_keys():
    manifest = _load_manifest()
    assert _REQUIRED_KEYS <= set(manifest)


def test_entrypoint_names_agent_module():
    assert _load_manifest()["entrypoint"] == "agent.py"


def test_entrypoint_symbol_names_solve():
    assert _load_manifest()["entrypoint_symbol"] == "solve"


def test_files_is_non_empty_string_list():
    files = _load_manifest()["files"]
    assert isinstance(files, list)
    assert files
    assert all(isinstance(path, str) and path for path in files)
    assert all("\\" not in path for path in files)
    assert all(not path.startswith("/") for path in files)


def test_max_files_is_positive_integer():
    max_files = _load_manifest()["max_files"]
    assert isinstance(max_files, int) and not isinstance(max_files, bool)
    assert max_files > 0


# --- On-disk presence and hygiene ----------------------------------------------------------

def test_manifest_files_exist_on_disk():
    for path in _load_manifest()["files"]:
        full = os.path.join(ROOT, path.replace("/", os.sep))
        assert os.path.isfile(full), f"missing manifest file: {path}"


def test_manifest_files_have_no_duplicates():
    files = _load_manifest()["files"]
    assert len(files) == len(set(files))


def test_no_benchmark_paths_in_manifest():
    for path in _load_manifest()["files"]:
        assert not path.startswith("benchmark/"), path
        assert path != "benchmark"


def test_review_module_is_not_part_of_scored_surface():
    assert "agent/review.py" not in _load_manifest()["files"]


# --- Entrypoint linkage --------------------------------------------------------------------

def test_entrypoint_defines_solve_callable():
    manifest = _load_manifest()
    entry_path = os.path.join(ROOT, manifest["entrypoint"])
    with open(entry_path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=manifest["entrypoint"])
    names = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }
    assert manifest["entrypoint_symbol"] in names


def test_manifest_includes_orchestration_modules():
    files = set(_load_manifest()["files"])
    assert _ORCHESTRATION_MODULES <= files


# --- File cap ------------------------------------------------------------------------------

def test_files_within_max_files_cap():
    manifest = _load_manifest()
    assert len(manifest["files"]) <= manifest["max_files"]


# --- Robustness ----------------------------------------------------------------------------

def test_manifest_json_reloads_without_error():
    raw = open(MANIFEST_PATH, encoding="utf-8").read()
    parsed = json.loads(raw)
    assert isinstance(parsed.get("files"), list)


def test_manifest_required_keys_are_non_null():
    manifest = _load_manifest()
    for key in _REQUIRED_KEYS:
        assert manifest.get(key) is not None
