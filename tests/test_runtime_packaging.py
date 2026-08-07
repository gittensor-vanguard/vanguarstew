from pathlib import Path


def test_private_runtime_files_are_excluded_from_git_and_docker_contexts():
    root = Path(__file__).resolve().parents[1]
    gitignore = (root / ".gitignore").read_text()
    dockerignore = (root / ".dockerignore").read_text()

    for entry in (".env", "data/", "*.sqlite3", "private-review-results/"):
        assert entry in gitignore
        assert entry in dockerignore
