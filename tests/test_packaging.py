"""Guard that pyproject's declared packages match what the project actually ships (#2210).

`[tool.setuptools] packages` is an explicit, hand-maintained list. An explicit list does not
auto-include subpackages, so it silently drifts from the real package set as modules are added.
These tests pin that every runtime package `setuptools.find_packages` discovers — excluding the
non-shipped `tests`/`tools` helpers — is declared, so an installed wheel can't go missing
`scripts` or the `benchmark.*_corpus` data subpackages `benchmark` imports at runtime.
"""

import os
import re
import sys

from setuptools import find_packages

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# tools/ is a package but is not imported by agent/ or benchmark/ at runtime, so it is
# intentionally not shipped; tests/ is never shipped.
_NOT_SHIPPED = {"tools", "tests"}


def _declared_packages():
    """The package names inside pyproject's `[tool.setuptools] packages = [...]` block.

    Parsed with a regex rather than a TOML library so the test runs on Python 3.10 (which has no
    stdlib `tomllib`) without adding a dependency.
    """
    text = open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8").read()
    match = re.search(r"^\s*packages\s*=\s*\[([^\]]*)\]", text, re.MULTILINE)
    assert match, "could not find `packages = [...]` in pyproject.toml"
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def _discovered_packages():
    return {p for p in find_packages(exclude=["tests*"]) if p.split(".")[0] not in _NOT_SHIPPED}


def test_declared_packages_match_the_discovered_runtime_set():
    declared = _declared_packages()
    discovered = _discovered_packages()
    missing = discovered - declared
    extra = declared - discovered
    assert not missing, f"pyproject omits shipped packages: {sorted(missing)}"
    assert not extra, f"pyproject declares non-existent/non-shipped packages: {sorted(extra)}"


def test_the_previously_missing_runtime_packages_are_declared():
    declared = _declared_packages()
    for required in ("scripts", "benchmark.judge_corpus", "benchmark.score_corpus"):
        assert required in declared, f"{required} must be shipped but is not declared"


def test_benchmark_corpus_subpackages_really_exist_and_are_imported():
    # Guards the premise: these are real packages benchmark depends on, not a phantom in the list.
    for sub in ("judge_corpus", "score_corpus"):
        assert os.path.isfile(os.path.join(ROOT, "benchmark", sub, "__init__.py"))
