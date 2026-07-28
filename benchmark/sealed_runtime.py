"""Deterministic Python zipapp containing only the public sealed executor runtime."""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import re
import stat
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from benchmark.sealed_aggregate import SEALED_AGGREGATE_CONTRACT
from benchmark.sealed_bundle import SEALED_BUNDLE_VERSION

SEALED_RUNTIME_VERSION = 1
SEALED_RUNTIME_MAX_BYTES = 2 * 1024 * 1024
SEALED_RUNTIME_MAX_MEMBER_BYTES = 1024 * 1024
SEALED_RUNTIME_MANIFEST = "sealed-runtime-manifest.json"

_RUNTIME_SOURCE_FILES = (
    "benchmark/__init__.py",
    "benchmark/sealed_aggregate.py",
    "benchmark/sealed_bundle.py",
    "benchmark/sealed_execution.py",
    "scripts/__init__.py",
    "scripts/sealed_network_exec.py",
)
_FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_MANIFEST_KEYS = {
    "bundle_version",
    "entrypoint",
    "files",
    "result_contract",
    "source_revision",
    "version",
}
_FILE_KEYS = {"bytes", "path", "sha256"}
_REVISION_RE = re.compile(r"[0-9a-f]{40}")


class SealedRuntimeError(ValueError):
    """A runtime source, archive, or manifest failed validation."""


def _canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _read_regular_file(path: Path, *, label: str, max_bytes: int, private: bool) -> bytes:
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or not 0 <= info.st_size <= max_bytes:
            raise SealedRuntimeError(f"{label} is not a bounded regular file")
        if private and os.name != "nt" and info.st_mode & 0o077:
            raise SealedRuntimeError(f"{label} must not be accessible by group or others")
        chunks = []
        remaining = info.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise SealedRuntimeError(f"{label} changed while reading")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise SealedRuntimeError(f"{label} changed while reading")
        return b"".join(chunks)
    except SealedRuntimeError:
        raise
    except OSError as exc:
        raise SealedRuntimeError(f"cannot read {label}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _restricted_output_parent(path: Path) -> Path:
    try:
        info = path.lstat()
    except OSError as exc:
        raise SealedRuntimeError("cannot inspect runtime output directory") from exc
    if not stat.S_ISDIR(info.st_mode) or path.is_symlink():
        raise SealedRuntimeError("runtime output directory must be a directory")
    if os.name != "nt" and info.st_mode & 0o077:
        raise SealedRuntimeError("runtime output directory permissions are too broad")
    try:
        return path.resolve(strict=True)
    except OSError as exc:
        raise SealedRuntimeError("cannot resolve runtime output directory") from exc


def _safe_member_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or len(value) > 240:
        raise SealedRuntimeError("runtime member path is malformed")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or str(path) != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise SealedRuntimeError("runtime member path is malformed")
    return value


def _launcher_source(helper_sha256: str) -> bytes:
    source = f'''"""Fixed entrypoint for the content-addressed sealed executor runtime."""

import argparse
import hashlib
import os
import sys
import tempfile
import zipfile
from pathlib import Path

from benchmark.sealed_execution import SealedExecutionPlan, SealedExecutor

HELPER_MEMBER = "scripts/sealed_network_exec.py"
HELPER_SHA256 = "{helper_sha256}"


def _parser():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--runtime-sha256", required=True)
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--challenge", required=True)
    parser.add_argument("--timeout-seconds", required=True, type=int)
    parser.add_argument("--max-output-bytes", required=True, type=int)
    parser.add_argument("--max-memory-bytes", required=True, type=int)
    parser.add_argument("--approved-request-sha256", required=True)
    return parser


def _read_runtime(path, expected_sha256):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        digest = hashlib.sha256()
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    finally:
        os.close(descriptor)
    if digest.hexdigest() != expected_sha256:
        raise ValueError("runtime digest mismatch")


def _write_helper(runtime_path, destination):
    with zipfile.ZipFile(runtime_path, "r") as archive:
        helper = archive.read(HELPER_MEMBER)
    if hashlib.sha256(helper).hexdigest() != HELPER_SHA256:
        raise ValueError("runtime helper digest mismatch")
    descriptor = os.open(
        destination,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        view = memoryview(helper)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short write")
            view = view[written:]
        os.fchmod(descriptor, 0o600)
    finally:
        os.close(descriptor)


def main(argv=None):
    try:
        args = _parser().parse_args(argv)
        runtime_path = Path(sys.argv[0])
        _read_runtime(runtime_path, args.runtime_sha256)
        bundle_path = Path(args.bundle)
        with tempfile.TemporaryDirectory(prefix=".sealed-launch-", dir=bundle_path.parent) as root:
            helper_path = Path(root) / "sealed_network_exec.py"
            _write_helper(runtime_path, helper_path)
            plan = SealedExecutionPlan(
                bundle_path=bundle_path,
                challenge=args.challenge,
                timeout_seconds=args.timeout_seconds,
                max_output_bytes=args.max_output_bytes,
                max_memory_bytes=args.max_memory_bytes,
            )
            envelope = SealedExecutor(helper_path=helper_path).execute_approved(
                plan,
                approved_request_sha256=args.approved_request_sha256,
            )
    except BaseException:
        print("sealed runtime execution failed", file=sys.stderr)
        return 1
    sys.stdout.write(envelope)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''
    return source.encode("utf-8")


def _source_entries(source_root: Path) -> list[tuple[str, bytes]]:
    try:
        root = source_root.resolve(strict=True)
    except OSError as exc:
        raise SealedRuntimeError("cannot resolve runtime source root") from exc
    if not root.is_dir():
        raise SealedRuntimeError("runtime source root must be a directory")
    entries = []
    for name in _RUNTIME_SOURCE_FILES:
        path = root.joinpath(*PurePosixPath(name).parts)
        data = _read_regular_file(
            path,
            label="runtime source file",
            max_bytes=SEALED_RUNTIME_MAX_MEMBER_BYTES,
            private=False,
        )
        entries.append((name, data))
    helper = dict(entries)["scripts/sealed_network_exec.py"]
    entries.append(("__main__.py", _launcher_source(hashlib.sha256(helper).hexdigest())))
    return sorted(entries)


def _source_revision(source_root: Path) -> str:
    try:
        root = source_root.resolve(strict=True)
    except OSError as exc:
        raise SealedRuntimeError("cannot resolve runtime source root") from exc
    commands = (
        ("rev-parse", "--show-toplevel"),
        ("rev-parse", "--verify", "HEAD"),
        ("ls-files", "--error-unmatch", "--", *_RUNTIME_SOURCE_FILES),
        ("diff", "--no-ext-diff", "--quiet", "--", *_RUNTIME_SOURCE_FILES),
        ("diff", "--cached", "--no-ext-diff", "--quiet", "--", *_RUNTIME_SOURCE_FILES),
    )
    outputs = []
    for command in commands:
        try:
            result = subprocess.run(
                ["git", "-C", str(root), *command],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SealedRuntimeError("cannot verify runtime source revision") from exc
        if result.returncode != 0:
            raise SealedRuntimeError("runtime source allowlist is not clean and tracked")
        outputs.append(result.stdout.strip())
    try:
        top_level = Path(outputs[0].decode("utf-8")).resolve(strict=True)
        revision = outputs[1].decode("ascii")
    except (OSError, UnicodeDecodeError) as exc:
        raise SealedRuntimeError("runtime source revision is malformed") from exc
    if top_level != root or not _REVISION_RE.fullmatch(revision):
        raise SealedRuntimeError("runtime source revision is malformed")
    return revision


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=_FIXED_TIMESTAMP)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.create_version = 20
    info.extract_version = 20
    info.external_attr = (stat.S_IFREG | 0o600) << 16
    info.internal_attr = 0
    info.extra = b""
    info.comment = b""
    return info


def build_sealed_runtime(source_root, output_path) -> dict:
    """Build a deterministic, mode-0600 zipapp from the fixed public-runtime allowlist."""
    output = Path(output_path)
    if output.name in {"", ".", ".."}:
        raise SealedRuntimeError("runtime output path is malformed")
    output = _restricted_output_parent(output.parent) / output.name
    source_root = Path(source_root)
    try:
        source_resolved = source_root.resolve(strict=True)
    except OSError as exc:
        raise SealedRuntimeError("cannot resolve runtime source root") from exc
    if output == source_resolved or source_resolved in output.parents:
        raise SealedRuntimeError("runtime output must be outside the source tree")
    source_revision = _source_revision(source_root)
    entries = _source_entries(source_root)
    records = [
        {"path": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
        for name, data in entries
    ]
    manifest = {
        "version": SEALED_RUNTIME_VERSION,
        "entrypoint": "__main__.py",
        "bundle_version": SEALED_BUNDLE_VERSION,
        "result_contract": SEALED_AGGREGATE_CONTRACT,
        "source_revision": source_revision,
        "files": records,
    }
    manifest_bytes = _canonical_json(manifest).encode("utf-8")
    descriptor = None
    created = False
    try:
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            with zipfile.ZipFile(handle, "w", allowZip64=False) as archive:
                archive.writestr(_zip_info(SEALED_RUNTIME_MANIFEST), manifest_bytes)
                for name, data in entries:
                    archive.writestr(_zip_info(name), data)
        os.chmod(output, 0o600)
        info = inspect_sealed_runtime(output, source_root=source_root)
    except Exception as exc:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if created:
            try:
                output.unlink()
            except OSError:
                pass
        if isinstance(exc, SealedRuntimeError):
            raise
        raise SealedRuntimeError("cannot build sealed runtime") from exc
    return {
        "runtime_sha256": info.runtime_sha256,
        "runtime_bytes": info.runtime_bytes,
        "file_count": info.file_count,
        "source_revision": info.source_revision,
    }


def _validate_record(value) -> dict:
    if not isinstance(value, dict) or set(value) != _FILE_KEYS:
        raise SealedRuntimeError("runtime manifest file record is malformed")
    path = _safe_member_path(value.get("path"))
    sha256 = value.get("sha256")
    size = value.get("bytes")
    if not isinstance(sha256, str) or len(sha256) != 64:
        raise SealedRuntimeError("runtime manifest file digest is malformed")
    try:
        int(sha256, 16)
    except ValueError as exc:
        raise SealedRuntimeError("runtime manifest file digest is malformed") from exc
    if (
        isinstance(size, bool)
        or not isinstance(size, int)
        or not 0 <= size <= SEALED_RUNTIME_MAX_MEMBER_BYTES
    ):
        raise SealedRuntimeError("runtime manifest file size is malformed")
    return {"path": path, "sha256": sha256, "bytes": size}


def _validate_member(info: zipfile.ZipInfo, expected_name: str) -> None:
    mode = (info.external_attr >> 16) & 0xFFFF
    if (
        info.filename != expected_name
        or info.is_dir()
        or not stat.S_ISREG(mode)
        or stat.S_IMODE(mode) != 0o600
        or info.date_time != _FIXED_TIMESTAMP
        or info.compress_type != zipfile.ZIP_STORED
        or info.create_system != 3
        or info.create_version != 20
        or info.extract_version != 20
        or info.flag_bits != 0
        or info.internal_attr != 0
        or info.volume != 0
        or info.external_attr & 0xFFFF
        or info.extra
        or info.comment
        or info.file_size > SEALED_RUNTIME_MAX_MEMBER_BYTES
    ):
        raise SealedRuntimeError("runtime archive member is malformed")


@dataclass(frozen=True)
class SealedRuntimeInfo:
    runtime_sha256: str
    runtime_bytes: int
    file_count: int
    source_revision: str

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(runtime_sha256=<redacted>, "
            f"runtime_bytes={self.runtime_bytes}, file_count={self.file_count}, "
            f"source_revision={self.source_revision!r})"
        )


def inspect_sealed_runtime(runtime_path, *, source_root=None) -> SealedRuntimeInfo:
    """Validate the complete runtime archive and optionally require an exact local-source match."""
    raw = _read_regular_file(
        Path(runtime_path),
        label="sealed runtime",
        max_bytes=SEALED_RUNTIME_MAX_BYTES,
        private=True,
    )
    eocd = raw.rfind(b"PK\x05\x06")
    if eocd < 0 or eocd + 22 != len(raw) or raw[eocd + 20 : eocd + 22] != b"\x00\x00":
        raise SealedRuntimeError("sealed runtime archive ending is malformed")
    try:
        with zipfile.ZipFile(io.BytesIO(raw), "r") as archive:
            if archive.comment:
                raise SealedRuntimeError("runtime archive comment is forbidden")
            members = archive.infolist()
            if len(members) != len(_RUNTIME_SOURCE_FILES) + 2:
                raise SealedRuntimeError("runtime archive member count is malformed")
            _validate_member(members[0], SEALED_RUNTIME_MANIFEST)
            manifest_bytes = archive.read(members[0])
            try:
                manifest = json.loads(manifest_bytes.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise SealedRuntimeError("runtime manifest is invalid JSON") from exc
            if not isinstance(manifest, dict) or set(manifest) != _MANIFEST_KEYS:
                raise SealedRuntimeError("runtime manifest shape is malformed")
            if _canonical_json(manifest).encode("utf-8") != manifest_bytes:
                raise SealedRuntimeError("runtime manifest is not canonical JSON")
            if (
                manifest.get("version") != SEALED_RUNTIME_VERSION
                or manifest.get("entrypoint") != "__main__.py"
                or manifest.get("bundle_version") != SEALED_BUNDLE_VERSION
                or manifest.get("result_contract") != SEALED_AGGREGATE_CONTRACT
                or not isinstance(manifest.get("source_revision"), str)
                or not _REVISION_RE.fullmatch(manifest["source_revision"])
            ):
                raise SealedRuntimeError("runtime manifest contract is unsupported")
            raw_records = manifest.get("files")
            if not isinstance(raw_records, list):
                raise SealedRuntimeError("runtime manifest files are malformed")
            records = [_validate_record(record) for record in raw_records]
            paths = [record["path"] for record in records]
            expected_paths = sorted((*_RUNTIME_SOURCE_FILES, "__main__.py"))
            if paths != expected_paths:
                raise SealedRuntimeError("runtime manifest allowlist does not match")
            loaded = []
            for member, record in zip(members[1:], records):
                _validate_member(member, record["path"])
                data = archive.read(member)
                if len(data) != record["bytes"] or not hmac.compare_digest(
                    hashlib.sha256(data).hexdigest(), record["sha256"]
                ):
                    raise SealedRuntimeError("runtime member does not match the manifest")
                loaded.append((record["path"], data))
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise SealedRuntimeError("sealed runtime archive is malformed") from exc

    if source_root is not None:
        source_revision = _source_revision(Path(source_root))
        expected = _source_entries(Path(source_root))
        if (
            not hmac.compare_digest(source_revision, manifest["source_revision"])
            or len(expected) != len(loaded)
            or any(
                name != loaded_name or not hmac.compare_digest(data, loaded_data)
                for (name, data), (loaded_name, loaded_data) in zip(expected, loaded)
            )
        ):
            raise SealedRuntimeError("sealed runtime does not match the local executor source")
    return SealedRuntimeInfo(
        runtime_sha256=hashlib.sha256(raw).hexdigest(),
        runtime_bytes=len(raw),
        file_count=len(loaded),
        source_revision=manifest["source_revision"],
    )
