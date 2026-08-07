import json

from vanguarstew_runtime.cli import main


def test_init_and_doctor_are_local_and_secret_free(tmp_path, capsys):
    config_path = tmp_path / "vanguarstew.json"

    assert main(["init", "--config", str(config_path)]) == 0
    assert config_path.exists()
    assert main(["doctor", "--config", str(config_path), "--env-file", str(tmp_path / "missing.env")]) == 0

    output = capsys.readouterr().out.splitlines()
    result = json.loads(output[-1])
    assert result["ok"] is True
    assert result["checks"]["mode"] == "dry-run"
    assert "api_key" not in json.dumps(result).lower()


def test_factory_policy_command_is_static_and_has_no_owner_execution(capsys):
    assert main(["factory-policy"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["automatic_owner_execution"] is False
    assert result["automatic_publication"] is False
    assert len(result["roles"]) == 8
