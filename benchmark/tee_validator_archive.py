"""Build the deterministic, receipt-bound zipapp used by the TDX validator."""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

from benchmark.polaris import POLARIS_MAX_MOUNTED_FILE_BYTES

VALIDATOR_ARCHIVE_PATH = "/submission/validator.pyz"

_SOURCE_FILES = (
    "benchmark/__init__.py",
    "benchmark/aggregate_integrity.py",
    "benchmark/attestation.py",
    "benchmark/judge_report_integrity.py",
    "benchmark/live_gate.py",
    "benchmark/memory.py",
    "benchmark/objective_integrity.py",
    "benchmark/row_integrity.py",
    "benchmark/score.py",
    "benchmark/score_integrity.py",
    "benchmark/tally_integrity.py",
    "benchmark/tee_benchmark_validator.py",
    "benchmark/transcript.py",
    "benchmark/weight_integrity.py",
    "scripts/__init__.py",
    "scripts/compare_eval.py",
    "scripts/score_pr_delta.py",
)
_MAIN = b"from benchmark.tee_benchmark_validator import main\nraise SystemExit(main())\n"


def _entry(name: str, content: bytes) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def build_validator_archive(source_root=None) -> bytes:
    root = Path(source_root) if source_root is not None else Path(__file__).resolve().parents[1]
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr(_entry("__main__.py", _MAIN), _MAIN)
        for relative in _SOURCE_FILES:
            content = (root / relative).read_bytes()
            archive.writestr(_entry(relative, content), content)
    result = output.getvalue()
    if not 0 < len(result) <= POLARIS_MAX_MOUNTED_FILE_BYTES:
        raise ValueError("TEE validator archive exceeds one Polaris mounted file")
    return result


def validator_archive_sha256(source_root=None) -> str:
    return hashlib.sha256(build_validator_archive(source_root)).hexdigest()
