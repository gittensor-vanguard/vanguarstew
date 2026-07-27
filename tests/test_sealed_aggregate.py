"""Tests for the aggregate-only sealed result boundary."""

import io
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from benchmark.sealed_aggregate import (  # noqa: E402
    SEALED_AGGREGATE_CONTRACT,
    SealedAggregateError,
    build_sealed_aggregate,
    verify_sealed_aggregate,
)
from scripts.emit_sealed_aggregate import main as emit_main  # noqa: E402

CHALLENGE = "ab" * 32


def _artifact(**overrides):
    value = {
        "repos": 3,
        "scored_repos": 2,
        "skipped": 1,
        "composite_mean": 0.625,
        "composite_parts": {"judge_mean": 0.75, "objective_mean": 0.5},
        "per_repo": [
            {
                "repo": "forbidden-identity-marker",
                "path": "/sensitive/path",
                "rows": [{"diagnostic": "must-not-cross-boundary"}],
            }
        ],
        "error": "sensitive-provider-detail",
    }
    value.update(overrides)
    return value


def test_builder_emits_only_fixed_aggregate_scalars():
    stdout = build_sealed_aggregate(_artifact(), challenge=CHALLENGE)
    assert stdout == (
        '{"challenge":"' + CHALLENGE + '","composite_micros":625000,'
        '"contract":"sealed-aggregate-v1","judge_micros":750000,'
        '"objective_micros":500000,"scored_repos":2,"skipped_repos":1}'
    )
    assert "forbidden-identity-marker" not in stdout
    assert "sensitive" not in stdout
    assert "per_repo" not in stdout
    assert "rows" not in stdout
    assert verify_sealed_aggregate(stdout, expected_challenge=CHALLENGE)["ok"] is True


def test_builder_does_not_mutate_the_source_artifact():
    artifact = _artifact()
    before = json.loads(json.dumps(artifact))
    build_sealed_aggregate(artifact, challenge=CHALLENGE)
    assert artifact == before


@pytest.mark.parametrize(
    ("change", "match"),
    [
        ({"scored_repos": 0}, "scored_repos"),
        ({"scored_repos": True}, "scored_repos"),
        ({"skipped": -1}, "skipped"),
        ({"composite_mean": float("nan")}, "composite_mean"),
        ({"composite_mean": 1.1}, "composite_mean"),
        ({"composite_mean": 0.1234567}, "composite_mean"),
        ({"composite_parts": None}, "composite parts"),
        ({"composite_parts": {"judge_mean": "0.5", "objective_mean": 0.5}}, "judge_mean"),
    ],
)
def test_builder_rejects_malformed_or_overprecise_aggregates(change, match):
    with pytest.raises(SealedAggregateError, match=match):
        build_sealed_aggregate(_artifact(**change), challenge=CHALLENGE)


@pytest.mark.parametrize("challenge", ["", "AB" * 32, "00" * 31, "not-hex"])
def test_builder_requires_a_fresh_shape_checked_challenge(challenge):
    with pytest.raises(SealedAggregateError, match="challenge"):
        build_sealed_aggregate(_artifact(), challenge=challenge)


def test_verifier_rejects_extra_fields_noncanonical_json_and_replay():
    stdout = build_sealed_aggregate(_artifact(), challenge=CHALLENGE)
    parsed = json.loads(stdout)
    parsed["detail"] = "unexpected"
    extra = json.dumps(parsed, sort_keys=True, separators=(",", ":"))
    assert verify_sealed_aggregate(extra, expected_challenge=CHALLENGE)["ok"] is False

    noncanonical = json.dumps(json.loads(stdout), indent=2)
    result = verify_sealed_aggregate(noncanonical, expected_challenge=CHALLENGE)
    assert result["ok"] is False
    assert result["checks"]["canonical_json"] is False

    replay = verify_sealed_aggregate(stdout, expected_challenge="cd" * 32)
    assert replay["ok"] is False
    assert replay["checks"]["challenge_binding"] is False


def test_verifier_rejects_bool_and_float_wire_scores():
    for value in (True, 0.5):
        envelope = {
            "contract": SEALED_AGGREGATE_CONTRACT,
            "challenge": CHALLENGE,
            "scored_repos": 1,
            "skipped_repos": 0,
            "composite_micros": value,
            "judge_micros": 500000,
            "objective_micros": 500000,
        }
        stdout = json.dumps(envelope, sort_keys=True, separators=(",", ":"))
        result = verify_sealed_aggregate(stdout, expected_challenge=CHALLENGE)
        assert result["ok"] is False
        assert result["checks"]["scores"] is False


def test_stdin_emitter_outputs_only_the_envelope(monkeypatch, capsys):
    raw = json.dumps(_artifact()).encode()
    monkeypatch.setattr(sys, "stdin", type("Input", (), {"buffer": io.BytesIO(raw)})())
    assert emit_main(["--challenge", CHALLENGE]) == 0
    captured = capsys.readouterr()
    assert verify_sealed_aggregate(captured.out, expected_challenge=CHALLENGE)["ok"] is True
    assert "forbidden-identity-marker" not in captured.out
    assert captured.err == ""


def test_stdin_emitter_failure_is_constant(monkeypatch, capsys):
    raw = b'{"forbidden-identity-marker":"sensitive-detail"}'
    monkeypatch.setattr(sys, "stdin", type("Input", (), {"buffer": io.BytesIO(raw)})())
    assert emit_main(["--challenge", CHALLENGE]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "sealed aggregate generation failed\n"
    assert "forbidden-identity-marker" not in captured.err
