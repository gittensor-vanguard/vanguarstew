from pathlib import Path


def test_private_runtime_files_are_excluded_from_git_and_docker_contexts():
    root = Path(__file__).resolve().parents[1]
    gitignore = (root / ".gitignore").read_text()
    dockerignore = (root / ".dockerignore").read_text()

    for entry in (".env", "data/", "*.sqlite3", "private-review-results/"):
        assert entry in gitignore
        assert entry in dockerignore


def test_product_context_ships_runtime_packages():
    """The product image (`./Dockerfile`, `COPY . /app`) must be able to see the runtime
    packages. The root .dockerignore is a deny-list, so a stray deny rule -- or a leftover
    deny-all-then-allowlist -- silently dropping openvang/ or vanguarstew_runtime/ would ship
    a product image that can't import its own entrypoint."""
    root = Path(__file__).resolve().parents[1]
    # Only actual rules matter -- skip comments and blanks so the packages named in the file's
    # own explanatory prose don't read as deny rules.
    rules = [ln.strip() for ln in (root / ".dockerignore").read_text().splitlines()
             if ln.strip() and not ln.lstrip().startswith("#")]
    # A deny-all-then-allowlist (`**` on its own line) belongs to the eval image, not here:
    # if it ever reappears at the root it means the eval allowlist leaked back and the product
    # context is empty except for what someone remembered to re-include.
    assert "**" not in rules
    for pkg in ("openvang/", "vanguarstew_runtime/", "openvang", "vanguarstew_runtime"):
        assert pkg not in rules, f"{pkg} must not be excluded from the product image"


def test_eval_context_is_a_deny_all_allowlist():
    """The attested eval image keeps its own tight allowlist at
    docker/eval.Dockerfile.dockerignore (BuildKit uses it in place of the root .dockerignore
    when building `-f docker/eval.Dockerfile`). It must stay a deny-all-then-allowlist so the
    TCB can only ever contain files explicitly re-included -- and the private runtime state must
    not be on the allowlist."""
    root = Path(__file__).resolve().parents[1]
    eval_ignore = (root / "docker" / "eval.Dockerfile.dockerignore").read_text()
    assert "\n**\n" in ("\n" + eval_ignore + "\n"), "eval allowlist must start deny-all with **"
    for private in (".env", "data/", "*.sqlite3", "private-review-results/", "openvang/",
                    "vanguarstew_runtime/"):
        assert f"!{private}" not in eval_ignore, f"{private} must not be allowlisted into the TCB"
