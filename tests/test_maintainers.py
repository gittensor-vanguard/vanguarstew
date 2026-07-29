from pathlib import Path

from scripts import benchmark_pr_policy as benchmark_policy
from scripts import pr_gaming_policy as gaming_policy
from scripts.maintainers import MAINTAINERS


def test_maintainer_allowlist_includes_bot_and_human():
    assert MAINTAINERS == frozenset({"matedev01", "vanguarstew"})


def test_policy_scripts_share_the_same_allowlist():
    assert benchmark_policy.MAINTAINERS is MAINTAINERS
    assert gaming_policy.MAINTAINERS is MAINTAINERS


def test_workflows_import_shared_maintainer_policy():
    workflows = Path(__file__).resolve().parents[1] / ".github" / "workflows"
    for name in ("pr-integrity.yml", "pr-limit.yml"):
        text = (workflows / name).read_text(encoding="utf-8")
        assert 'from scripts.maintainers import MAINTAINERS' in text
        assert 'MAINTAINERS = {"matedev01"}' not in text
        assert "actions/checkout@v7" in text
        assert "persist-credentials: false" in text
