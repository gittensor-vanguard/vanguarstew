"""Operator CLI for the private Vanguarstew runtime."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .config import (
    DEFAULT_CONFIG_NAME,
    DEFAULT_ENV_NAME,
    ConfigError,
    default_config,
    load_dotenv,
    load_runtime_config,
)
from .service import RuntimeService, serve_with_http
from .state import RuntimeState


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vanguarstew",
        description="self-hosted, private maintainer-assist runtime",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    init = subparsers.add_parser("init", help="write a safe starter configuration")
    init.add_argument("--config", default=DEFAULT_CONFIG_NAME)
    init.add_argument("--force", action="store_true", help="replace an existing configuration")
    subparsers.add_parser(
        "factory-policy",
        help="render the static OpenVang role and authority contract",
    )
    for command, help_text in (
        ("doctor", "validate local configuration without a network request"),
        ("run-once", "run one bounded private work cycle"),
        ("serve", "run the private worker and loopback health server"),
    ):
        command_parser = subparsers.add_parser(command, help=help_text)
        command_parser.add_argument("--config", default=DEFAULT_CONFIG_NAME)
        command_parser.add_argument("--env-file", default=DEFAULT_ENV_NAME)
    serve = subparsers.choices["serve"]
    serve.add_argument("--once", action="store_true", help="run one cycle without the HTTP server")
    return parser


def _write_config(path: Path, *, force: bool) -> None:
    if path.exists() and not force:
        raise ConfigError(f"refusing to overwrite existing configuration: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(default_config(), indent=2) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _doctor(config_path: str, env_file: str) -> int:
    environment = dict()
    try:
        # Preserve current process values over dotenv values, while allowing
        # tests and embedding callers to pass an empty environment predictably.
        import os

        environment.update(os.environ)
        load_dotenv(Path(env_file), environment)
        config = load_runtime_config(config_path, environ=environment)
    except ConfigError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, separators=(",", ":")))
        return 1
    checks = {
        "configuration": "ok",
        "data_directory": "ok" if config.data_dir.exists() or config.data_dir.parent.exists() else "will-create",
        "github_read_token": "configured" if config.github_token else "not-configured",
        "inference": "enabled" if config.can_run_inference else "not-enabled",
        "mode": "dry-run" if config.dry_run else "live-private",
        "polling": "enabled" if config.poll_enabled else "disabled",
        "webhook": "configured" if config.webhook_secret else "disabled",
    }
    print(json.dumps({"ok": True, "checks": checks}, separators=(",", ":")))
    return 0


def _load(config_path: str, env_file: str):
    import os

    environment = dict(os.environ)
    load_dotenv(Path(env_file), environment)
    config = load_runtime_config(config_path, environ=environment)
    state = RuntimeState(config.database_path, config.private_result_dir)
    return config, state


def _run_once(config_path: str, env_file: str) -> int:
    try:
        config, state = _load(config_path, env_file)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    try:
        result = RuntimeService(config, state).run_once()
        print(json.dumps(result, separators=(",", ":")))
        return 0
    finally:
        state.close()


def _serve(config_path: str, env_file: str, *, once: bool) -> int:
    try:
        config, state = _load(config_path, env_file)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    service = RuntimeService(config, state)
    try:
        if once:
            print(json.dumps(service.run_once(), separators=(",", ":")))
            return 0
        serve_with_http(service)
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        state.close()


def main(argv: list[str] | None = None) -> int:
    """Run the operator CLI and return a process-compatible exit code."""
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.command == "init":
        try:
            _write_config(Path(args.config), force=args.force)
        except ConfigError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"created {Path(args.config)}")
        return 0
    if args.command == "factory-policy":
        from openvang.factory import FactoryPolicy

        print(json.dumps(FactoryPolicy().public_contract(), sort_keys=True, separators=(",", ":")))
        return 0
    if args.command == "doctor":
        return _doctor(args.config, args.env_file)
    if args.command == "run-once":
        return _run_once(args.config, args.env_file)
    if args.command == "serve":
        return _serve(args.config, args.env_file, once=args.once)
    raise AssertionError("unreachable command")


if __name__ == "__main__":  # pragma: no cover - console entry point
    raise SystemExit(main())
