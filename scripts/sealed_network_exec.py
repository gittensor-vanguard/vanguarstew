"""Verify the fresh network namespace, then exec the fixed sealed bundle entrypoint."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path


def network_namespace_isolated(
    *,
    interfaces_path: Path = Path("/sys/class/net"),
    route_path: Path = Path("/proc/net/route"),
) -> bool:
    """Return true only when the namespace exposes loopback and no non-loopback route."""
    try:
        interfaces = {entry.name for entry in interfaces_path.iterdir()}
        if interfaces != {"lo"}:
            return False
        route_text = route_path.read_text(encoding="ascii")
    except (OSError, UnicodeDecodeError):
        return False
    if len(route_text) > 64 * 1024:
        return False
    lines = [line.split() for line in route_text.splitlines()[1:] if line.strip()]
    return all(parts and parts[0] == "lo" for parts in lines)


def _validated_entrypoint(root_value: str, entrypoint_value: str) -> Path | None:
    try:
        root = Path(root_value).resolve(strict=True)
        entrypoint = Path(entrypoint_value)
        info = entrypoint.lstat()
        resolved_entrypoint = entrypoint.resolve(strict=True)
    except OSError:
        return None
    if entrypoint.is_symlink() or not stat.S_ISREG(info.st_mode):
        return None
    if stat.S_IMODE(info.st_mode) != 0o700:
        return None
    if resolved_entrypoint != root / "payload" / "run":
        return None
    return resolved_entrypoint


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 4 or args[0] != "--root" or args[2] != "--entrypoint":
        return 125
    entrypoint = _validated_entrypoint(args[1], args[3])
    if (
        sys.platform != "linux"
        or getattr(os, "geteuid", lambda: -1)() != 0
        or not network_namespace_isolated()
        or entrypoint is None
    ):
        return 125
    try:
        os.execve(entrypoint, [str(entrypoint)], dict(os.environ))
    except OSError:
        return 125
    return 125


if __name__ == "__main__":
    raise SystemExit(main())
