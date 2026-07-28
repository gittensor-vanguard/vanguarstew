"""Public Git/transcript packaging tests for Polaris mounted-input runs."""

from __future__ import annotations

import gzip
import io
import os
import pathlib
import subprocess
import sys
import tarfile

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from benchmark.polaris import mounted_files_sha256  # noqa: E402
from benchmark.transcript import TranscriptStore  # noqa: E402
from scripts import package_attested_inputs as packaging  # noqa: E402
from scripts import prepare_attested_inputs as preparation  # noqa: E402

PUBLIC_REPO = "example/public-replay"


def _git(repo, *args):
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _public_repo(tmp_path):
    repo = tmp_path / "source"
    repo.mkdir()
    _git(repo, "init", "--quiet")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "remote", "add", "origin", f"https://github.com/{PUBLIC_REPO}.git")
    for index in range(3):
        (repo / "history.txt").write_text(f"history {index}\n", encoding="utf-8")
        _git(repo, "add", "history.txt")
        _git(repo, "commit", "--quiet", "-m", f"history {index}")
    return repo, _git(repo, "rev-parse", "HEAD")


def _transcript(tmp_path):
    store = TranscriptStore()
    store.record(
        {
            "model": "judge-2026-07-01",
            "temperature": 0,
            "messages": [{"role": "user", "content": "public prompt"}],
        },
        '{"winner":"tie"}',
    )
    path = tmp_path / "transcript.json"
    store.save(str(path))
    return path


def test_package_and_prepare_round_trip_public_git_and_transcript(tmp_path):
    source, commit = _public_repo(tmp_path)
    transcript = _transcript(tmp_path)
    parts_dir = tmp_path / "parts"
    result = packaging.package_inputs(
        repo=str(source),
        public_repo=PUBLIC_REPO,
        ref="HEAD",
        depth=16,
        transcript_path=str(transcript),
        out_dir=str(parts_dir),
    )

    assert result["commit"] == commit
    assert 1 <= len(result["parts"]) <= packaging.MAX_PARTS
    part_paths = [str(parts_dir / row["name"]) for row in result["parts"]]
    assert all(os.path.getsize(path) <= packaging.PART_BYTES for path in part_paths)
    mounted = {
        row["target"]: (parts_dir / row["name"]).read_bytes() for row in result["parts"]
    }
    assert result["files_sha256"] == mounted_files_sha256(mounted)

    second = packaging.package_inputs(
        repo=str(source),
        public_repo=PUBLIC_REPO,
        ref="HEAD",
        depth=16,
        transcript_path=str(transcript),
        out_dir=str(tmp_path / "parts-again"),
    )
    assert second["package_sha256"] == result["package_sha256"]
    assert second["files_sha256"] == result["files_sha256"]

    prepared = preparation.prepare_inputs(
        part_paths=part_paths,
        out_dir=str(tmp_path / "prepared"),
        expected_public_repo=PUBLIC_REPO,
        expected_commit=commit,
    )
    checkout = pathlib.Path(prepared["repo"])
    assert _git(checkout, "rev-parse", "HEAD") == commit
    assert _git(checkout, "remote", "get-url", "origin") == (
        f"https://github.com/{PUBLIC_REPO}.git"
    )
    rebuilt = TranscriptStore.load(prepared["transcript"])
    original = TranscriptStore.load(str(transcript))
    assert rebuilt.digest() == original.digest()


def test_packager_rejects_wrong_origin_empty_transcript_and_oversize(tmp_path, monkeypatch):
    source, _ = _public_repo(tmp_path)
    transcript = _transcript(tmp_path)
    with pytest.raises(packaging.InputPackageError, match="does not match"):
        packaging.package_inputs(
            repo=str(source),
            public_repo="other/repo",
            ref="HEAD",
            depth=16,
            transcript_path=str(transcript),
            out_dir=str(tmp_path / "wrong"),
        )

    empty = tmp_path / "empty.json"
    TranscriptStore().save(str(empty))
    with pytest.raises(packaging.InputPackageError, match="at least one"):
        packaging.package_inputs(
            repo=str(source),
            public_repo=PUBLIC_REPO,
            ref="HEAD",
            depth=16,
            transcript_path=str(empty),
            out_dir=str(tmp_path / "empty-out"),
        )

    monkeypatch.setattr(
        packaging,
        "_build_archive",
        lambda *args, **kwargs: b"x" * (packaging.MAX_PACKAGE_BYTES + 1),
    )
    with pytest.raises(packaging.InputPackageError, match="eight-file"):
        packaging.package_inputs(
            repo=str(source),
            public_repo=PUBLIC_REPO,
            ref="HEAD",
            depth=16,
            transcript_path=str(transcript),
            out_dir=str(tmp_path / "oversize"),
        )
    assert not (tmp_path / "oversize").exists()


def _malicious_archive(name: str, *, symlink: bool = False) -> bytes:
    tar_output = io.BytesIO()
    with tarfile.open(fileobj=tar_output, mode="w") as archive:
        info = tarfile.TarInfo(name)
        if symlink:
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            archive.addfile(info)
        else:
            content = b"bad"
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    return gzip.compress(tar_output.getvalue(), mtime=0)


@pytest.mark.parametrize(
    "archive",
    [
        _malicious_archive("../escape"),
        _malicious_archive("/absolute"),
        _malicious_archive("repo.git/link", symlink=True),
        _malicious_archive("unexpected.txt"),
    ],
)
def test_preparer_rejects_traversal_links_and_unexpected_members(tmp_path, archive):
    destination = tmp_path / "prepared"
    with pytest.raises(preparation.InputPreparationError, match="unsafe"):
        preparation._extract_archive(archive, destination)
    assert not destination.exists()


def test_preparer_rejects_missing_reordered_and_oversize_parts(tmp_path):
    first = tmp_path / "input.part00"
    second = tmp_path / "input.part01"
    first.write_bytes(b"a")
    second.write_bytes(b"b")
    with pytest.raises(preparation.InputPreparationError, match="consecutive"):
        preparation._read_parts([str(second), str(first)])
    noncanonical = tmp_path / "input.part0"
    noncanonical.write_bytes(b"a")
    with pytest.raises(preparation.InputPreparationError, match="consecutive"):
        preparation._read_parts([str(noncanonical)])
    first.write_bytes(b"")
    with pytest.raises(preparation.InputPreparationError, match="invalid size"):
        preparation._read_parts([str(first)])
    first.write_bytes(b"x" * (packaging.PART_BYTES + 1))
    with pytest.raises(preparation.InputPreparationError, match="invalid size"):
        preparation._read_parts([str(first)])


def test_preparer_checks_expected_manifest_identity(tmp_path):
    source, commit = _public_repo(tmp_path)
    transcript = _transcript(tmp_path)
    parts_dir = tmp_path / "parts"
    result = packaging.package_inputs(
        repo=str(source),
        public_repo=PUBLIC_REPO,
        ref="HEAD",
        depth=16,
        transcript_path=str(transcript),
        out_dir=str(parts_dir),
    )
    parts = [str(parts_dir / row["name"]) for row in result["parts"]]
    with pytest.raises(preparation.InputPreparationError, match="does not match"):
        preparation.prepare_inputs(
            part_paths=parts,
            out_dir=str(tmp_path / "prepared"),
            expected_public_repo=PUBLIC_REPO,
            expected_commit="ab" * 20,
        )
    assert commit != "ab" * 20


def test_cli_failures_are_sanitized(monkeypatch, capsys):
    monkeypatch.setattr(
        packaging,
        "package_inputs",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("private path")),
    )
    code = packaging.main(
        [
            "--repo",
            "/local/path",
            "--public-repo",
            PUBLIC_REPO,
            "--transcript",
            "/local/transcript",
            "--out-dir",
            "/local/output",
        ]
    )
    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert captured.err == "attested input packaging failed\n"
    assert "private path" not in captured.err and "/local/path" not in captured.err
