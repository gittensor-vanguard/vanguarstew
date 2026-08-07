"""Configuration for the self-hosted Vanguarstew runtime.

Secrets are intentionally environment-only.  The JSON configuration records
only non-secret operational policy, so it can be inspected and versioned
without leaking an inference credential, GitHub token, webhook secret, or
private-review content.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

DEFAULT_CONFIG_NAME = "vanguarstew.json"
DEFAULT_ENV_NAME = ".env"


class ConfigError(ValueError):
    """Raised when an operator configuration is missing or unsafe."""


def _as_bool(value: object, *, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "on"}:
        return True
    if isinstance(value, str) and value.strip().lower() in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{field} must be a boolean")


def _as_positive_int(value: object, *, field: str, minimum: int = 1) -> int:
    if isinstance(value, bool):
        raise ConfigError(f"{field} must be an integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{field} must be an integer") from exc
    if number < minimum:
        raise ConfigError(f"{field} must be at least {minimum}")
    return number


def _as_string(value: object, *, field: str, default: str | None = None) -> str:
    if value is None and default is not None:
        return default
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field} must be a non-empty string")
    return value.strip()


def _repository_name(value: object) -> str:
    name = _as_string(value, field="repositories[].name")
    parts = name.split("/")
    if len(parts) != 2 or not all(parts):
        raise ConfigError("repositories[].name must be in owner/repository form")
    if any(part in {".", ".."} or " " in part for part in parts):
        raise ConfigError("repositories[].name must be a GitHub owner/repository")
    return name


def load_dotenv(path: Path, environ: dict[str, str] | None = None) -> dict[str, str]:
    """Load a small, predictable dotenv file without evaluating shell syntax.

    Existing environment values always win.  Shell interpolation, command
    substitution, and ``export`` directives are intentionally unsupported:
    configuration should never execute while it is being read.
    """
    target = environ if environ is not None else os.environ
    if not path.exists():
        return target
    if not path.is_file():
        raise ConfigError(f"environment file is not a file: {path}")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ConfigError(f"cannot read environment file: {path}") from exc
    for line_number, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export ") or "=" not in line:
            raise ConfigError(f"invalid dotenv entry on line {line_number}")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or not key.replace("_", "a").isalnum() or not key[0].isalpha() and key[0] != "_":
            raise ConfigError(f"invalid dotenv variable on line {line_number}")
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        target.setdefault(key, value)
    return target


@dataclass(frozen=True)
class RepositoryTarget:
    """A repository which the local runtime may read from GitHub."""

    name: str
    enabled: bool = True


@dataclass(frozen=True)
class RuntimeConfig:
    """Validated non-secret runtime policy plus environment-backed credentials."""

    config_path: Path
    data_dir: Path
    host: str
    port: int
    poll_seconds: int
    max_jobs_per_cycle: int
    poll_enabled: bool
    dry_run: bool
    allow_external_inference: bool
    repositories: tuple[RepositoryTarget, ...]
    github_api_base: str
    github_token: str | None
    webhook_secret: str | None
    model: str | None
    api_base: str | None
    api_key: str | None

    @property
    def database_path(self) -> Path:
        return self.data_dir / "runtime.sqlite3"

    @property
    def private_result_dir(self) -> Path:
        return self.data_dir / "private-review-results"

    @property
    def can_run_inference(self) -> bool:
        return bool(
            self.allow_external_inference
            and self.model
            and self.api_base
            and self.api_key
            and self.api_key != "offline"
        )

    @property
    def enabled_repositories(self) -> tuple[RepositoryTarget, ...]:
        return tuple(repo for repo in self.repositories if repo.enabled)


def _env_string(environ: Mapping[str, str], name: str, default: str | None = None) -> str | None:
    value = environ.get(name, default)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _env_bool(environ: Mapping[str, str], name: str, default: bool) -> bool:
    value = environ.get(name)
    return default if value is None else _as_bool(value, field=name)


def _env_int(environ: Mapping[str, str], name: str, default: int, *, minimum: int = 1) -> int:
    value = environ.get(name)
    return default if value is None else _as_positive_int(value, field=name, minimum=minimum)


def load_runtime_config(
    config_path: str | Path = DEFAULT_CONFIG_NAME,
    *,
    environ: Mapping[str, str] | None = None,
) -> RuntimeConfig:
    """Read and validate a non-secret JSON configuration and environment values."""
    source_env: Mapping[str, str] = os.environ if environ is None else environ
    path = Path(config_path).expanduser().resolve()
    if not path.exists():
        raise ConfigError(
            f"configuration file not found: {path}; run `vanguarstew init --config {path}`"
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"configuration is not valid JSON: {path}") from exc
    except OSError as exc:
        raise ConfigError(f"cannot read configuration file: {path}") from exc
    if not isinstance(raw, dict):
        raise ConfigError("configuration root must be a JSON object")
    if raw.get("version") != 1:
        raise ConfigError("configuration version must be 1")

    runtime = raw.get("runtime", {})
    if not isinstance(runtime, dict):
        raise ConfigError("runtime must be an object")
    configured_data_dir = _as_string(runtime.get("data_dir", "./data"), field="runtime.data_dir")
    env_data_dir = _env_string(source_env, "VANGUARSTEW_DATA_DIR")
    data_dir = Path(env_data_dir or configured_data_dir).expanduser()
    if not data_dir.is_absolute():
        data_dir = (path.parent / data_dir).resolve()

    raw_repositories = raw.get("repositories", [])
    if not isinstance(raw_repositories, list):
        raise ConfigError("repositories must be an array")
    repositories = []
    seen_repositories = set()
    for entry in raw_repositories:
        if not isinstance(entry, dict):
            raise ConfigError("each repository entry must be an object")
        name = _repository_name(entry.get("name"))
        if name.lower() in seen_repositories:
            raise ConfigError(f"repository appears more than once: {name}")
        seen_repositories.add(name.lower())
        repositories.append(
            RepositoryTarget(
                name=name,
                enabled=_as_bool(entry.get("enabled", True), field=f"repositories[{name}].enabled"),
            )
        )

    host = _env_string(source_env, "VANGUARSTEW_HOST") or _as_string(
        runtime.get("host", "127.0.0.1"), field="runtime.host"
    )
    if host != "127.0.0.1":
        raise ConfigError("runtime.host must be 127.0.0.1; private review endpoints are loopback-only")
    port = _env_int(
        source_env,
        "VANGUARSTEW_PORT",
        _as_positive_int(runtime.get("port", 8080), field="runtime.port", minimum=1),
        minimum=1,
    )
    if port > 65535:
        raise ConfigError("runtime.port must be at most 65535")
    poll_seconds = _env_int(
        source_env,
        "VANGUARSTEW_POLL_SECONDS",
        _as_positive_int(runtime.get("poll_seconds", 300), field="runtime.poll_seconds"),
    )
    max_jobs_per_cycle = _env_int(
        source_env,
        "VANGUARSTEW_MAX_JOBS_PER_CYCLE",
        _as_positive_int(
            runtime.get("max_jobs_per_cycle", 1), field="runtime.max_jobs_per_cycle"
        ),
    )
    poll_enabled = _env_bool(
        source_env,
        "VANGUARSTEW_POLL_ENABLED",
        _as_bool(runtime.get("poll_enabled", False), field="runtime.poll_enabled"),
    )
    dry_run = _env_bool(source_env, "VANGUARSTEW_DRY_RUN", True)
    allow_external_inference = _env_bool(source_env, "VANGUARSTEW_ALLOW_EXTERNAL_INFERENCE", False)

    github_api_base = (
        _env_string(source_env, "VANGUARSTEW_GITHUB_API_BASE", "https://api.github.com")
        or "https://api.github.com"
    ).rstrip("/")
    if not github_api_base.startswith("https://"):
        raise ConfigError("VANGUARSTEW_GITHUB_API_BASE must use https")

    return RuntimeConfig(
        config_path=path,
        data_dir=data_dir,
        host=host,
        port=port,
        poll_seconds=poll_seconds,
        max_jobs_per_cycle=max_jobs_per_cycle,
        poll_enabled=poll_enabled,
        dry_run=dry_run,
        allow_external_inference=allow_external_inference,
        repositories=tuple(repositories),
        github_api_base=github_api_base,
        github_token=_env_string(source_env, "VANGUARSTEW_GITHUB_TOKEN"),
        webhook_secret=_env_string(source_env, "VANGUARSTEW_WEBHOOK_SECRET"),
        model=_env_string(source_env, "VANGUARSTEW_MODEL"),
        api_base=_env_string(source_env, "VANGUARSTEW_API_BASE"),
        api_key=_env_string(source_env, "VANGUARSTEW_API_KEY"),
    )


def default_config() -> dict:
    """Return the safe bootstrap configuration written by ``vanguarstew init``."""
    return {
        "version": 1,
        "runtime": {
            "data_dir": "./data",
            "host": "127.0.0.1",
            "port": 8080,
            "poll_seconds": 300,
            "max_jobs_per_cycle": 1,
            "poll_enabled": False,
        },
        "repositories": [
            {
                "name": "openvang/vanguarstew",
                "enabled": True,
            }
        ],
    }
