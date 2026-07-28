"""Contract tests for specs/011-miner-manifest — assert vanguarstew_agent_files.json and the
repository tree satisfy the spec's EARS criteria: manifest shape, on-disk presence, scored-surface
confinement, entrypoint linkage, and file cap. The entrypoint-linkage check derives the expected
module set by parsing agent.py's actual import graph with ast, rather than a hand-maintained list,
so it cannot silently drift from what agent.py really imports. Static checks only; no network.
"""

import ast
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

MANIFEST_PATH = os.path.join(ROOT, "vanguarstew_agent_files.json")

_AGENT_PACKAGE = "agent"

_SCHEMA = {
    "entrypoint": str,
    "entrypoint_symbol": str,
    "files": list,
    "max_files": int,
}


def _load_manifest() -> dict:
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        return json.load(f)


def _agent_submodule_imports(source_path: str) -> set:
    """Dotted `agent[.sub]*` module names imported directly by the file at source_path."""
    with open(os.path.join(ROOT, source_path), encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=source_path)
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == _AGENT_PACKAGE or node.module.startswith(_AGENT_PACKAGE + "."):
                found.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == _AGENT_PACKAGE or alias.name.startswith(_AGENT_PACKAGE + "."):
                    found.add(alias.name)
    return found


def _module_to_source_path(module: str) -> str:
    if module == _AGENT_PACKAGE:
        return f"{_AGENT_PACKAGE}/__init__.py"
    return module.replace(".", "/") + ".py"


def _implicit_package_inits(module: str) -> set:
    """__init__.py files Python executes implicitly when importing a dotted submodule."""
    parts = module.split(".")
    return {"/".join(parts[:i]) + "/__init__.py" for i in range(1, len(parts))}


def _resolve_agent_import_graph(entrypoint: str) -> set:
    """BFS the `agent` package import graph transitively reachable from entrypoint.

    Follows only same-package (`agent.*`) imports. External imports — stdlib or harness-side
    helpers such as `benchmark.score`, which `agent/decider.py` reads from — are not part of the
    miner-editable surface and are intentionally not followed.
    """
    resolved = {entrypoint}
    visited_modules = set()
    frontier = _agent_submodule_imports(entrypoint)
    while frontier:
        module = frontier.pop()
        if module in visited_modules:
            continue
        visited_modules.add(module)
        path = _module_to_source_path(module)
        resolved.add(path)
        resolved |= _implicit_package_inits(module)
        frontier |= _agent_submodule_imports(path) - visited_modules
    return resolved


# --- Manifest document shape ---------------------------------------------------------------


def test_manifest_is_valid_json_object():
    assert isinstance(_load_manifest(), dict)


def test_manifest_matches_schema():
    manifest = _load_manifest()
    for key, expected_type in _SCHEMA.items():
        assert key in manifest, f"manifest missing required key: {key}"
        value = manifest[key]
        if expected_type is int:
            assert isinstance(value, int) and not isinstance(value, bool), key
        else:
            assert isinstance(value, expected_type), key
    assert manifest["files"], "files must be non-empty"
    assert all(isinstance(path, str) and path for path in manifest["files"])
    assert all("\\" not in path and not path.startswith("/") for path in manifest["files"])


def test_entrypoint_names_agent_module():
    assert _load_manifest()["entrypoint"] == "agent.py"


def test_entrypoint_symbol_names_solve():
    assert _load_manifest()["entrypoint_symbol"] == "solve"


# --- On-disk presence and hygiene ----------------------------------------------------------


def test_manifest_files_exist_on_disk():
    for path in _load_manifest()["files"]:
        full = os.path.join(ROOT, path.replace("/", os.sep))
        assert os.path.isfile(full), f"missing manifest file: {path}"


def test_manifest_files_have_no_duplicates():
    files = _load_manifest()["files"]
    assert len(files) == len(set(files))


# --- Scored-surface confinement (harness isolation) -----------------------------------------


def test_manifest_files_are_confined_to_agent_surface():
    manifest = _load_manifest()
    entrypoint = manifest["entrypoint"]
    for path in manifest["files"]:
        assert path == entrypoint or path.startswith(f"{_AGENT_PACKAGE}/"), (
            f"{path} is outside the scored agent surface "
            f"(must be {entrypoint!r} or under {_AGENT_PACKAGE}/)"
        )


def test_review_module_is_not_part_of_scored_surface():
    assert f"{_AGENT_PACKAGE}/review.py" not in _load_manifest()["files"]


# --- Entrypoint linkage (import-graph derived) ----------------------------------------------


def test_entrypoint_defines_declared_symbol():
    manifest = _load_manifest()
    entry_path = os.path.join(ROOT, manifest["entrypoint"])
    with open(entry_path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=manifest["entrypoint"])
    names = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert manifest["entrypoint_symbol"] in names


def test_manifest_includes_full_agent_import_graph():
    manifest = _load_manifest()
    scored_surface = _resolve_agent_import_graph(manifest["entrypoint"])
    missing = scored_surface - set(manifest["files"])
    assert not missing, f"manifest is missing agent.py's actual dependencies: {sorted(missing)}"


# --- File cap ------------------------------------------------------------------------------


def test_files_within_max_files_cap():
    manifest = _load_manifest()
    assert len(manifest["files"]) <= manifest["max_files"]


# --- Robustness ----------------------------------------------------------------------------


def test_manifest_json_reloads_without_error():
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        raw = f.read()
    parsed = json.loads(raw)
    assert isinstance(parsed.get("files"), list)


def test_manifest_required_keys_are_non_null():
    manifest = _load_manifest()
    for key in _SCHEMA:
        assert manifest.get(key) is not None
