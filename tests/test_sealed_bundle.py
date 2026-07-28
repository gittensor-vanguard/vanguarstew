"""Adversarial tests for the deterministic sealed workload bundle."""

import io
import json
import pathlib
import stat
import sys
import tarfile

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from benchmark.sealed_bundle import (  # noqa: E402
    SEALED_BUNDLE_ENTRYPOINT,
    SealedBundleError,
    build_sealed_bundle,
    extract_sealed_bundle,
    inspect_sealed_bundle,
)
from scripts.package_sealed_bundle import main as package_main  # noqa: E402


def _source(tmp_path):
    source = tmp_path / "source"
    source.mkdir(mode=0o700)
    source.chmod(0o700)
    run = source / "run"
    run.write_bytes(b"#!/bin/sh\necho ok\n")
    run.chmod(0o700)
    data_dir = source / "data"
    data_dir.mkdir(mode=0o700)
    data_dir.chmod(0o700)
    data = data_dir / "input.json"
    data.write_bytes(b'{"identity":"forbidden-identity-marker"}\n')
    data.chmod(0o600)
    return source


def _bundle(tmp_path, name="bundle.tar"):
    source = _source(tmp_path)
    output = tmp_path / name
    result = build_sealed_bundle(source, output)
    return source, output, result


def _tar_info(name, data=b"", mode=0o600, type_=tarfile.REGTYPE):
    info = tarfile.TarInfo(name)
    info.size = len(data) if type_ == tarfile.REGTYPE else 0
    info.mode = mode
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.type = type_
    return info


def _read_valid(bundle):
    with tarfile.open(bundle, "r:") as archive:
        members = archive.getmembers()
        manifest = json.loads(archive.extractfile(members[0]).read())
        payloads = [
            (member.name, archive.extractfile(member).read(), member.mode) for member in members[1:]
        ]
    return manifest, payloads


def _write_archive(path, manifest_bytes, payloads):
    with tarfile.open(path, "w", format=tarfile.USTAR_FORMAT) as archive:
        archive.addfile(_tar_info("manifest.json", manifest_bytes), io.BytesIO(manifest_bytes))
        for item in payloads:
            name, data, mode = item[:3]
            type_ = item[3] if len(item) > 3 else tarfile.REGTYPE
            info = _tar_info(name, data, mode, type_)
            if type_ == tarfile.SYMTYPE:
                info.linkname = "payload/run"
                archive.addfile(info)
            else:
                archive.addfile(info, io.BytesIO(data))
    path.chmod(0o600)


def test_bundle_is_deterministic_private_and_fully_bound(tmp_path):
    source = _source(tmp_path)
    first = tmp_path / "first.tar"
    second = tmp_path / "second.tar"
    first_result = build_sealed_bundle(source, first)
    second_result = build_sealed_bundle(source, second)
    assert first.read_bytes() == second.read_bytes()
    assert first_result == second_result
    assert stat.S_IMODE(first.stat().st_mode) == 0o600
    info = inspect_sealed_bundle(first)
    assert info.bundle_sha256 == first_result["bundle_sha256"]
    assert info.file_count == 2
    assert "forbidden-identity-marker" not in repr(info)
    assert first_result["bundle_sha256"] not in repr(info)


def test_extraction_writes_only_manifested_regular_files_with_normalized_modes(tmp_path):
    _, bundle, result = _bundle(tmp_path)
    destination = tmp_path / "extracted"
    entrypoint = extract_sealed_bundle(
        bundle,
        destination,
        expected_bundle_sha256=result["bundle_sha256"],
    )
    assert entrypoint == destination / SEALED_BUNDLE_ENTRYPOINT
    assert entrypoint.read_bytes() == b"#!/bin/sh\necho ok\n"
    assert stat.S_IMODE(entrypoint.stat().st_mode) == 0o700
    data = destination / "payload" / "data" / "input.json"
    assert stat.S_IMODE(data.stat().st_mode) == 0o600
    assert not (destination / "manifest.json").exists()


def test_packager_refuses_to_overwrite_an_existing_output(tmp_path):
    source = _source(tmp_path)
    output = tmp_path / "bundle.tar"
    output.write_bytes(b"keep")
    output.chmod(0o600)
    with pytest.raises(SealedBundleError):
        build_sealed_bundle(source, output)
    assert output.read_bytes() == b"keep"


def test_packager_rejects_links_broad_permissions_and_output_inside_source(tmp_path):
    source = _source(tmp_path)
    (source / "link").symlink_to("run")
    with pytest.raises(SealedBundleError, match="link"):
        build_sealed_bundle(source, tmp_path / "link.tar")
    (source / "link").unlink()
    (source / "data" / "input.json").chmod(0o644)
    with pytest.raises(SealedBundleError, match="group or others"):
        build_sealed_bundle(source, tmp_path / "mode.tar")
    (source / "data" / "input.json").chmod(0o600)
    with pytest.raises(SealedBundleError, match="outside"):
        build_sealed_bundle(source, source / "nested.tar")

    output_dir = source / "output"
    output_dir.mkdir(mode=0o700)
    output_dir.chmod(0o700)
    alias = tmp_path / "source-alias"
    alias.symlink_to(source, target_is_directory=True)
    with pytest.raises(SealedBundleError, match="outside"):
        build_sealed_bundle(source, alias / "output" / "nested.tar")


def test_packager_requires_the_fixed_executable_run_entrypoint(tmp_path):
    source = _source(tmp_path)
    (source / "run").chmod(0o600)
    with pytest.raises(SealedBundleError, match="entrypoint"):
        build_sealed_bundle(source, tmp_path / "bundle.tar")


@pytest.mark.parametrize("mutation", ["traversal", "symlink", "extra", "content", "noncanonical"])
def test_inspector_rejects_malformed_or_unmanifested_archive_content(tmp_path, mutation):
    _, valid, _ = _bundle(tmp_path, "valid.tar")
    manifest, payloads = _read_valid(valid)
    target = tmp_path / f"{mutation}.tar"
    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    if mutation == "traversal":
        manifest["files"][0]["path"] = "payload/../escape"
        manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    elif mutation == "symlink":
        payloads[0] = (payloads[0][0], b"", payloads[0][2], tarfile.SYMTYPE)
    elif mutation == "extra":
        payloads.append(("payload/extra", b"extra", 0o600))
    elif mutation == "content":
        payloads[0] = (payloads[0][0], b"changed", payloads[0][2])
    elif mutation == "noncanonical":
        manifest_bytes = json.dumps(manifest, indent=2).encode()
    _write_archive(target, manifest_bytes, payloads)
    with pytest.raises(SealedBundleError):
        inspect_sealed_bundle(target)


def test_extractor_rejects_wrong_digest_before_creating_destination(tmp_path):
    _, bundle, _ = _bundle(tmp_path)
    destination = tmp_path / "extracted"
    with pytest.raises(SealedBundleError, match="digest"):
        extract_sealed_bundle(bundle, destination, expected_bundle_sha256="00" * 32)
    assert not destination.exists()


def test_package_cli_failure_is_constant_and_does_not_render_source(tmp_path, capsys):
    source = tmp_path / "forbidden-identity-marker"
    assert package_main(["--source", str(source), "--output", str(tmp_path / "bundle.tar")]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "sealed bundle packaging failed\n"
    assert "forbidden-identity-marker" not in captured.err
