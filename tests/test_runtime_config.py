import json

import pytest

from vanguarstew_runtime.config import ConfigError, load_dotenv, load_runtime_config


def _config(path):
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "runtime": {
                    "data_dir": "runtime-data",
                    "host": "127.0.0.1",
                    "port": 8080,
                    "poll_seconds": 60,
                    "max_jobs_per_cycle": 2,
                    "poll_enabled": True,
                },
                "repositories": [{"name": "owner/repository", "enabled": True}],
            }
        )
    )


def test_load_runtime_config_keeps_secrets_out_of_json(tmp_path):
    config_path = tmp_path / "vanguarstew.json"
    _config(config_path)

    config = load_runtime_config(
        config_path,
        environ={
            "VANGUARSTEW_DRY_RUN": "false",
            "VANGUARSTEW_ALLOW_EXTERNAL_INFERENCE": "true",
            "VANGUARSTEW_GITHUB_TOKEN": "token",
            "VANGUARSTEW_MODEL": "model",
            "VANGUARSTEW_API_BASE": "https://example.test/v1",
            "VANGUARSTEW_API_KEY": "key",
        },
    )

    assert config.data_dir == tmp_path / "runtime-data"
    assert config.poll_enabled is True
    assert config.dry_run is False
    assert config.can_run_inference is True
    assert config.enabled_repositories[0].name == "owner/repository"


def test_load_dotenv_does_not_evaluate_or_override_existing_environment(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("VANGUARSTEW_API_KEY='from-file'\nVALUE=$(not-executed)\n")
    environment = {"VANGUARSTEW_API_KEY": "from-process"}

    load_dotenv(env_file, environment)

    assert environment["VANGUARSTEW_API_KEY"] == "from-process"
    assert environment["VALUE"] == "$(not-executed)"


def test_runtime_config_rejects_non_https_github_endpoint(tmp_path):
    config_path = tmp_path / "vanguarstew.json"
    _config(config_path)

    with pytest.raises(ConfigError, match="must use https"):
        load_runtime_config(config_path, environ={"VANGUARSTEW_GITHUB_API_BASE": "http://bad"})


def test_runtime_config_rejects_public_http_bind(tmp_path):
    config_path = tmp_path / "vanguarstew.json"
    _config(config_path)

    with pytest.raises(ConfigError, match="loopback-only"):
        load_runtime_config(config_path, environ={"VANGUARSTEW_HOST": "0.0.0.0"})
