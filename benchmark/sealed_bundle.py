"""Deterministic, fail-closed bundle format for a staged sealed workload.

The archive contains one canonical ``manifest.json`` followed by regular files below ``payload/``.
There are no links, devices, directory entries, ownership metadata, timestamps, or caller-selected
entrypoint names.  ``payload/run`` is the only entrypoint.  Extraction writes members itself and
never calls ``tarfile.extract``.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import re
import shutil
import stat
import tarfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from benchmark.sealed_aggregate import SEALED_AGGREGATE_CONTRACT

SEALED_BUNDLE_VERSION = 1
SEALED_BUNDLE_ENTRYPOINT = "payload/run"
SEALED_BUNDLE_MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
SEALED_BUNDLE_MAX_PAYLOAD_BYTES = 48 * 1024 * 1024
SEALED_BUNDLE_MAX_FILE_BYTES = 48 * 1024 * 1024
SEALED_BUNDLE_MAX_FILES = 1024
SEALED_BUNDLE_MAX_MANIFEST_BYTES = 256 * 1024
SEALED_BUNDLE_MAX_PATH_BYTES = 240

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_MANIFEST_KEYS = {"entrypoint", "files", "result_contract", "version"}
_FILE_KEYS = {"bytes", "mode", "path", "sha256"}
_ALLOWED_FILE_MODES = {0o600, 0o700}


class SealedBundleError(ValueError):
    """A source tree, manifest, archive, or extraction target failed validation."""


def _canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _safe_path(value: str, *, require_payload: bool = True) -> PurePosixPath:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > SEALED_BUNDLE_MAX_PATH_BYTES
    ):
        raise SealedBundleError("bundle member path is malformed")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise SealedBundleError("bundle member path is malformed")
    if "\\" in value:
        raise SealedBundleError("bundle member path is malformed")
    path = PurePosixPath(value)
    if path.is_absolute() or str(path) != value:
        raise SealedBundleError("bundle member path is malformed")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise SealedBundleError("bundle member path is malformed")
    if require_payload and (not path.parts or path.parts[0] != "payload"):
        raise SealedBundleError("bundle member must be below payload")
    return path


def _restricted_directory(path, *, label: str) -> Path:
    candidate = Path(path)
    try:
        info = candidate.lstat()
    except OSError as exc:
        raise SealedBundleError(f"cannot read {label}") from exc
    if not stat.S_ISDIR(info.st_mode) or candidate.is_symlink():
        raise SealedBundleError(f"{label} must be a directory")
    if os.name != "nt" and info.st_mode & 0o077:
        raise SealedBundleError(f"{label} must not be accessible by group or others")
    return candidate


def _read_restricted_file(path, *, label: str, max_bytes: int) -> tuple[bytes, int]:
    candidate = Path(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(candidate, flags)
    except OSError as exc:
        raise SealedBundleError(f"cannot read {label}") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise SealedBundleError(f"{label} must be a regular file")
        if os.name != "nt" and info.st_mode & 0o077:
            raise SealedBundleError(f"{label} must not be accessible by group or others")
        if not 0 < info.st_size <= max_bytes:
            raise SealedBundleError(f"{label} is outside the size limit")
        chunks = []
        remaining = info.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise SealedBundleError(f"{label} changed while reading")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise SealedBundleError(f"{label} changed while reading")
        return b"".join(chunks), stat.S_IMODE(info.st_mode)
    finally:
        os.close(descriptor)


def _tar_info(name: str, data: bytes, mode: int) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = mode
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    return info


def _source_files(source: Path) -> list[tuple[dict, bytes]]:
    records = []
    total_bytes = 0
    try:
        candidates = sorted(
            source.rglob("*"), key=lambda value: value.relative_to(source).as_posix()
        )
    except OSError as exc:
        raise SealedBundleError("cannot enumerate bundle source") from exc
    for candidate in candidates:
        try:
            info = candidate.lstat()
        except OSError as exc:
            raise SealedBundleError("cannot inspect bundle source") from exc
        if candidate.is_symlink():
            raise SealedBundleError("bundle source contains a link")
        if stat.S_ISDIR(info.st_mode):
            if os.name != "nt" and info.st_mode & 0o077:
                raise SealedBundleError("bundle source directory permissions are too broad")
            continue
        if not stat.S_ISREG(info.st_mode):
            raise SealedBundleError("bundle source contains a non-regular file")
        relative = candidate.relative_to(source).as_posix()
        archive_path = f"payload/{relative}"
        _safe_path(archive_path)
        data, source_mode = _read_restricted_file(
            candidate,
            label="bundle source file",
            max_bytes=SEALED_BUNDLE_MAX_FILE_BYTES,
        )
        mode = 0o700 if source_mode & stat.S_IXUSR else 0o600
        total_bytes += len(data)
        if total_bytes > SEALED_BUNDLE_MAX_PAYLOAD_BYTES:
            raise SealedBundleError("bundle payload exceeds the size limit")
        records.append(
            (
                {
                    "path": archive_path,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "bytes": len(data),
                    "mode": mode,
                },
                data,
            )
        )
    if not records or len(records) > SEALED_BUNDLE_MAX_FILES:
        raise SealedBundleError("bundle source file count is outside the limit")
    paths = [record["path"] for record, _ in records]
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise SealedBundleError("bundle source paths are not unique and sorted")
    entrypoint = next(
        (record for record, _ in records if record["path"] == SEALED_BUNDLE_ENTRYPOINT), None
    )
    if entrypoint is None or entrypoint["mode"] != 0o700:
        raise SealedBundleError("bundle source requires an executable run entrypoint")
    return records


def build_sealed_bundle(source_dir, output_path) -> dict:
    """Create one deterministic mode-0600 tar archive without overwriting an existing path."""
    source = _restricted_directory(source_dir, label="bundle source")
    output = Path(output_path)
    if output.name in {"", ".", ".."}:
        raise SealedBundleError("bundle output path is malformed")
    output_parent = _restricted_directory(output.parent, label="bundle output directory")
    try:
        source_resolved = source.resolve(strict=True)
        output_absolute = output_parent.resolve(strict=True) / output.name
    except OSError as exc:
        raise SealedBundleError("cannot resolve bundle paths") from exc
    if output_absolute == source_resolved or source_resolved in output_absolute.parents:
        raise SealedBundleError("bundle output must be outside the source tree")
    output = output_absolute

    records = _source_files(source)
    manifest = {
        "version": SEALED_BUNDLE_VERSION,
        "entrypoint": SEALED_BUNDLE_ENTRYPOINT,
        "result_contract": SEALED_AGGREGATE_CONTRACT,
        "files": [record for record, _ in records],
    }
    manifest_bytes = _canonical_json(manifest).encode("utf-8")
    if len(manifest_bytes) > SEALED_BUNDLE_MAX_MANIFEST_BYTES:
        raise SealedBundleError("bundle manifest exceeds the size limit")

    descriptor = None
    output_created = False
    try:
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        output_created = True
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            with tarfile.open(fileobj=handle, mode="w", format=tarfile.USTAR_FORMAT) as archive:
                archive.addfile(
                    _tar_info("manifest.json", manifest_bytes, 0o600), io.BytesIO(manifest_bytes)
                )
                for record, data in records:
                    archive.addfile(
                        _tar_info(record["path"], data, record["mode"]),
                        io.BytesIO(data),
                    )
        os.chmod(output, 0o600)
        archive_bytes, _ = _read_restricted_file(
            output,
            label="sealed bundle",
            max_bytes=SEALED_BUNDLE_MAX_ARCHIVE_BYTES,
        )
    except Exception as exc:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if output_created:
            try:
                output.unlink()
            except OSError:
                pass
        raise SealedBundleError("cannot create sealed bundle") from exc

    return {
        "bundle_sha256": hashlib.sha256(archive_bytes).hexdigest(),
        "bundle_bytes": len(archive_bytes),
        "file_count": len(records),
        "payload_bytes": sum(record["bytes"] for record, _ in records),
    }


def _validate_file_record(value) -> dict:
    if not isinstance(value, dict) or set(value) != _FILE_KEYS:
        raise SealedBundleError("bundle manifest file record is malformed")
    path = str(_safe_path(value.get("path")))
    sha256 = value.get("sha256")
    size = value.get("bytes")
    mode = value.get("mode")
    if not isinstance(sha256, str) or not _SHA256_RE.fullmatch(sha256):
        raise SealedBundleError("bundle manifest file digest is malformed")
    if (
        isinstance(size, bool)
        or not isinstance(size, int)
        or not 0 <= size <= SEALED_BUNDLE_MAX_FILE_BYTES
    ):
        raise SealedBundleError("bundle manifest file size is malformed")
    if isinstance(mode, bool) or mode not in _ALLOWED_FILE_MODES:
        raise SealedBundleError("bundle manifest file mode is malformed")
    return {"path": path, "sha256": sha256, "bytes": size, "mode": mode}


def _load_bundle(bundle_path) -> tuple[bytes, dict, list[tuple[dict, bytes]]]:
    archive_bytes, _ = _read_restricted_file(
        bundle_path,
        label="sealed bundle",
        max_bytes=SEALED_BUNDLE_MAX_ARCHIVE_BYTES,
    )
    try:
        with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:") as archive:
            members = archive.getmembers()
            if not 2 <= len(members) <= SEALED_BUNDLE_MAX_FILES + 1:
                raise SealedBundleError("sealed bundle member count is outside the limit")
            manifest_member = members[0]
            if (
                manifest_member.name != "manifest.json"
                or not manifest_member.isreg()
                or manifest_member.size > SEALED_BUNDLE_MAX_MANIFEST_BYTES
                or stat.S_IMODE(manifest_member.mode) != 0o600
                or manifest_member.mtime != 0
                or manifest_member.uid != 0
                or manifest_member.gid != 0
                or manifest_member.uname
                or manifest_member.gname
                or manifest_member.pax_headers
            ):
                raise SealedBundleError("sealed bundle manifest member is malformed")
            manifest_file = archive.extractfile(manifest_member)
            manifest_bytes = manifest_file.read() if manifest_file is not None else b""
            if len(manifest_bytes) != manifest_member.size:
                raise SealedBundleError("sealed bundle manifest is truncated")
            try:
                manifest = json.loads(manifest_bytes.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise SealedBundleError("sealed bundle manifest is invalid JSON") from exc
            if not isinstance(manifest, dict) or set(manifest) != _MANIFEST_KEYS:
                raise SealedBundleError("sealed bundle manifest shape is malformed")
            if _canonical_json(manifest).encode("utf-8") != manifest_bytes:
                raise SealedBundleError("sealed bundle manifest is not canonical JSON")
            if (
                manifest.get("version") != SEALED_BUNDLE_VERSION
                or manifest.get("entrypoint") != SEALED_BUNDLE_ENTRYPOINT
                or manifest.get("result_contract") != SEALED_AGGREGATE_CONTRACT
            ):
                raise SealedBundleError("sealed bundle manifest contract is unsupported")
            raw_records = manifest.get("files")
            if (
                not isinstance(raw_records, list)
                or not 1 <= len(raw_records) <= SEALED_BUNDLE_MAX_FILES
            ):
                raise SealedBundleError("sealed bundle manifest file count is outside the limit")
            records = [_validate_file_record(record) for record in raw_records]
            paths = [record["path"] for record in records]
            if paths != sorted(paths) or len(paths) != len(set(paths)):
                raise SealedBundleError("sealed bundle manifest paths are not unique and sorted")
            entrypoint = next(
                (record for record in records if record["path"] == SEALED_BUNDLE_ENTRYPOINT), None
            )
            if entrypoint is None or entrypoint["mode"] != 0o700:
                raise SealedBundleError("sealed bundle entrypoint is missing or not executable")
            if len(members[1:]) != len(records):
                raise SealedBundleError("sealed bundle members do not match the manifest")

            loaded = []
            total_bytes = 0
            for member, record in zip(members[1:], records):
                if (
                    member.name != record["path"]
                    or not member.isreg()
                    or member.linkname
                    or member.pax_headers
                    or member.mtime != 0
                    or member.uid != 0
                    or member.gid != 0
                    or member.uname
                    or member.gname
                    or stat.S_IMODE(member.mode) != record["mode"]
                    or member.size != record["bytes"]
                ):
                    raise SealedBundleError("sealed bundle member does not match the manifest")
                extracted = archive.extractfile(member)
                data = extracted.read() if extracted is not None else b""
                if len(data) != record["bytes"] or not hmac.compare_digest(
                    hashlib.sha256(data).hexdigest(), record["sha256"]
                ):
                    raise SealedBundleError(
                        "sealed bundle member content does not match the manifest"
                    )
                total_bytes += len(data)
                if total_bytes > SEALED_BUNDLE_MAX_PAYLOAD_BYTES:
                    raise SealedBundleError("sealed bundle payload exceeds the size limit")
                loaded.append((record, data))
    except (tarfile.TarError, OSError) as exc:
        raise SealedBundleError("sealed bundle archive is malformed") from exc
    return archive_bytes, manifest, loaded


@dataclass(frozen=True)
class SealedBundleInfo:
    bundle_sha256: str
    bundle_bytes: int
    file_count: int
    payload_bytes: int

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(bundle_sha256=<redacted>, bundle_bytes={self.bundle_bytes}, "
            f"file_count={self.file_count}, payload_bytes={self.payload_bytes})"
        )


def inspect_sealed_bundle(bundle_path) -> SealedBundleInfo:
    """Validate every manifest/member/content binding without extracting the archive."""
    archive_bytes, _, loaded = _load_bundle(bundle_path)
    return SealedBundleInfo(
        bundle_sha256=hashlib.sha256(archive_bytes).hexdigest(),
        bundle_bytes=len(archive_bytes),
        file_count=len(loaded),
        payload_bytes=sum(len(data) for _, data in loaded),
    )


def extract_sealed_bundle(bundle_path, destination, *, expected_bundle_sha256: str) -> Path:
    """Validate and write regular payload files beneath a new mode-0700 directory."""
    if not isinstance(expected_bundle_sha256, str) or not _SHA256_RE.fullmatch(
        expected_bundle_sha256
    ):
        raise SealedBundleError("expected bundle digest is malformed")
    archive_bytes, _, loaded = _load_bundle(bundle_path)
    actual_sha256 = hashlib.sha256(archive_bytes).hexdigest()
    if not hmac.compare_digest(actual_sha256, expected_bundle_sha256):
        raise SealedBundleError("sealed bundle digest does not match the approved value")
    root = Path(destination)
    try:
        root.mkdir(mode=0o700, parents=False, exist_ok=False)
        os.chmod(root, 0o700)
        for record, data in loaded:
            relative = _safe_path(record["path"])
            target = root.joinpath(*relative.parts)
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(target.parent, 0o700)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(target, flags, record["mode"])
            try:
                view = memoryview(data)
                while view:
                    written = os.write(descriptor, view)
                    if written <= 0:
                        raise OSError("short write")
                    view = view[written:]
                os.fchmod(descriptor, record["mode"])
            finally:
                os.close(descriptor)
    except (OSError, SealedBundleError) as exc:
        shutil.rmtree(root, ignore_errors=True)
        if isinstance(exc, SealedBundleError):
            raise
        raise SealedBundleError("cannot extract sealed bundle") from exc
    return root / SEALED_BUNDLE_ENTRYPOINT
