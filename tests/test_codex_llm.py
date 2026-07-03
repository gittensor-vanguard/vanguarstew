"""Unit tests for the codex dev backend — the `codex` CLI is fully mocked (never invoked)."""

from unittest import mock

from tools.codex_llm import CodexError, CodexLLM


def _writer(content):
    """A subprocess.run replacement that writes `content` to the -o output file."""
    def _run(args, **kwargs):
        out = args[args.index("-o") + 1]
        with open(out, "w", encoding="utf-8") as f:
            f.write(content)
        return mock.Mock(returncode=0, stdout="", stderr="")
    return _run


def test_offline_attr_is_false():
    # duck-types agent.llm.LLM but is never an offline stub
    assert CodexLLM().offline is False


def test_chat_builds_args_and_reads_last_message():
    seen = {}

    def _run(args, **kwargs):
        seen["args"] = args
        out = args[args.index("-o") + 1]
        with open(out, "w", encoding="utf-8") as f:
            f.write("  hello world  ")
        return mock.Mock(returncode=0)

    with mock.patch("tools.codex_llm.shutil.which", return_value="/usr/bin/codex"), \
         mock.patch("tools.codex_llm.subprocess.run", _run):
        got = CodexLLM(model="gpt-5.5", effort="medium").chat("sys", "user")

    assert got == "hello world"  # trimmed content of the output file
    a = seen["args"]
    assert a[:2] == ["codex", "exec"]
    assert "--ephemeral" in a
    assert a[a.index("-s") + 1] == "read-only"           # never mutates the workspace
    assert a[a.index("-m") + 1] == "gpt-5.5"
    assert "model_reasoning_effort=medium" in a


def test_chat_json_parses_object():
    with mock.patch("tools.codex_llm.shutil.which", return_value="/usr/bin/codex"), \
         mock.patch("tools.codex_llm.subprocess.run", _writer('{"action": "merge"}')):
        assert CodexLLM().chat_json("s", "u") == {"action": "merge"}


def test_missing_codex_raises_clear_error():
    with mock.patch("tools.codex_llm.shutil.which", return_value=None):
        try:
            CodexLLM().chat("s", "u")
            raise AssertionError("expected CodexError when codex is absent")
        except CodexError as exc:
            assert "codex" in str(exc).lower()
