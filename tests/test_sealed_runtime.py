"""Tests for the deterministic public sealed-executor runtime artifact."""

import pathlib
import stat
import subprocess
import sys
import zipfile

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from benchmark.sealed_runtime import (  # noqa: E402
    SEALED_RUNTIME_MANIFEST,
    SealedRuntimeError,
    build_sealed_runtime,
    inspect_sealed_runtime,
)
from scripts.package_sealed_runtime import main as package_main  # noqa: E402

SOURCE_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _runtime(tmp_path, name="runtime.pyz"):
    output = tmp_path / name
    result = build_sealed_runtime(SOURCE_ROOT, output)
    return output, result


def test_runtime_is_deterministic_private_and_matches_local_source(tmp_path):
    first, first_result = _runtime(tmp_path, "first.pyz")
    second, second_result = _runtime(tmp_path, "second.pyz")
    assert first.read_bytes() == second.read_bytes()
    assert first_result == second_result
    assert stat.S_IMODE(first.stat().st_mode) == 0o600
    info = inspect_sealed_runtime(first, source_root=SOURCE_ROOT)
    assert info.runtime_sha256 == first_result["runtime_sha256"]
    assert info.file_count == 7
    assert len(info.source_revision) == 40
    assert first_result["source_revision"] == info.source_revision
    assert info.runtime_sha256 not in repr(info)
    assert "<redacted>" in repr(info)


def test_runtime_contains_only_the_fixed_manifest_launcher_and_allowlist(tmp_path):
    runtime, _ = _runtime(tmp_path)
    with zipfile.ZipFile(runtime, "r") as archive:
        names = archive.namelist()
    assert names == [
        SEALED_RUNTIME_MANIFEST,
        "__main__.py",
        "benchmark/__init__.py",
        "benchmark/sealed_aggregate.py",
        "benchmark/sealed_bundle.py",
        "benchmark/sealed_execution.py",
        "scripts/__init__.py",
        "scripts/sealed_network_exec.py",
    ]


def test_runtime_packager_refuses_overwrite_and_preserves_existing_file(tmp_path):
    output = tmp_path / "runtime.pyz"
    output.write_bytes(b"keep")
    output.chmod(0o600)
    with pytest.raises(SealedRuntimeError):
        build_sealed_runtime(SOURCE_ROOT, output)
    assert output.read_bytes() == b"keep"


@pytest.mark.parametrize("mutation", ["extra", "content", "traversal"])
def test_runtime_inspector_rejects_unmanifested_or_changed_content(tmp_path, mutation):
    runtime, _ = _runtime(tmp_path, "valid.pyz")
    target = tmp_path / f"{mutation}.pyz"
    with zipfile.ZipFile(runtime, "r") as source, zipfile.ZipFile(target, "w") as destination:
        for info in source.infolist():
            data = source.read(info)
            if mutation == "content" and info.filename == "benchmark/sealed_execution.py":
                data += b"\n# changed\n"
            destination.writestr(info, data)
        if mutation == "extra":
            destination.writestr("extra.py", b"pass\n")
        if mutation == "traversal":
            destination.writestr("../escape.py", b"pass\n")
    target.chmod(0o600)
    with pytest.raises(SealedRuntimeError):
        inspect_sealed_runtime(target)


def test_runtime_package_cli_failure_is_constant(tmp_path, capsys):
    output = tmp_path / "existing.pyz"
    output.write_bytes(b"forbidden-identity-marker")
    output.chmod(0o600)
    assert package_main(["--output", str(output)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "sealed runtime packaging failed\n"
    assert "forbidden-identity-marker" not in captured.err


def test_runtime_zipapp_starts_and_fails_with_a_constant_diagnostic(tmp_path):
    runtime, result = _runtime(tmp_path)
    process = subprocess.run(
        [
            sys.executable,
            str(runtime),
            "--runtime-sha256",
            result["runtime_sha256"],
            "--bundle",
            str(tmp_path / "missing.tar"),
            "--challenge",
            "ab" * 32,
            "--timeout-seconds",
            "1",
            "--max-output-bytes",
            "1024",
            "--max-memory-bytes",
            str(128 * 1024 * 1024),
            "--approved-request-sha256",
            "00" * 32,
        ],
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert process.returncode == 1
    assert process.stdout == b""
    assert process.stderr == b"sealed runtime execution failed\n"
