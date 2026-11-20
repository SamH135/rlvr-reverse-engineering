import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "baselines"))
from summarize import _infra_kind, _rows, classify_command


def test_sandbox_error_is_harness_not_attempted(tmp_path):
    ep = {
        "run": {"name": "decompile--deepseek-flash--bash--x"},
        "task": {"data": {"id": "decompile-l2-0"}},
        "traces": [
            {
                "stop_condition": "sandbox_error",
                "errors": [
                    {
                        "type": "SandboxError",
                        "message": "runtime died under harness 'bash' (exit 137)",
                    }
                ],
                "rewards": {},
            }
        ],
        "errors": [],
        "num_input_tokens": 1,
        "num_output_tokens": 1,
    }
    f = tmp_path / "traces.jsonl"
    f.write_text(json.dumps(ep) + "\n")
    (row,) = _rows(f)
    assert row["harness_error"] is True
    assert row["provider_error"] is False
    assert row["completed"] is False
    # attempted = eps - prov - harn = 0 for this episode
    assert 1 - row["provider_error"] - row["harness_error"] == 0
    assert _infra_kind(ep, ep["traces"][0]) == "harness_error"


def test_context_overflow_is_attempted_not_infra(tmp_path):
    msg = "upstream 400: request (20317 tokens) exceeds the available context size (8192 tokens)"
    ep = {
        "run": {"name": "decompile--re-tmp-a--bash--x"},
        "task": {"data": {"id": "decompile-l0-0"}},
        "traces": [
            {
                "stop_condition": "provider_error",
                "errors": [{"type": "ProviderError", "message": msg}],
                "rewards": {},
            }
        ],
        "errors": [],
    }
    f = tmp_path / "traces.jsonl"
    f.write_text(json.dumps(ep) + "\n")
    (row,) = _rows(f)
    assert row["ctx_overflow"] is True
    assert row["provider_error"] is False and row["harness_error"] is False
    assert row["solved"] is False


def test_heredoc_strings_variable_not_disasm():
    cmd = "cd /app/repo && python3 - <<'PY'\nstrings = ['a','b']\nprint(strings)\nPY\n"
    assert classify_command(cmd)["disasm"] is False


def test_plain_objdump_is_disasm():
    assert classify_command("objdump -d reader | head")["disasm"] is True


def test_wrapped_gdb_is_disasm():
    assert classify_command("cd /app/repo && gdb -batch -ex x reader")["disasm"] is True


def test_oracle_direct():
    assert classify_command("for i in $(seq 5); do ./prog $i; done")["oracle_direct"] is True


def test_oracle_scripted_not_direct():
    cmd = "python3 - <<'PY'\nimport subprocess\nsubprocess.run(['./prog','1'])\nPY\n"
    c = classify_command(cmd)
    assert c["oracle_scripted"] is True and c["oracle_direct"] is False


def test_quoted_wrapper_is_known_miss():
    # shortcut: program names inside quoting wrappers like bash -c "..." are stripped
    # with the quoted contents — accepted miss; upgrade = proper shell lexer.
    assert classify_command('bash -c "objdump -d x"')["disasm"] is False


def test_absolute_path_oracle():
    assert classify_command("/app/repo/reader samples/a.bin")["oracle_direct"] is True


def test_no_disasm_no_oracle():
    c = classify_command("cat > keygen.py <<'EOF'\nprint(1)\nEOF")
    assert not (c["disasm"] or c["oracle_direct"] or c["oracle_scripted"])
