"""The hook's rewrite has to look like the tool's own output.

Claude Code validates updatedToolOutput against the tool's output schema and,
on a mismatch, logs an error and hands the model the original output. A
rewrite shaped {"type": "text", "content": ...} matches neither Bash nor Read,
so the hook used to compress, write the sidecar and record savings while the
model still received every byte. The tool_response shapes below are the ones
Claude Code 2.1.299 passes to PostToolUse hooks.
"""
import io
import json
import random

import pytest

from densely import hook


def _log(lines=400):
    rnd = random.Random(7)
    return "\n".join(
        f"2026-10-23T12:00:{i % 60:02d}Z {rnd.choice(['INFO', 'WARN', 'ERROR'])} "
        f"request_id={rnd.getrandbits(32):08x} latency_ms={rnd.randint(1, 900)}"
        for i in range(lines)
    )


def _bash(text):
    return {"tool_name": "Bash", "tool_input": {"command": "cat app.log"},
            "tool_response": {"stdout": text, "stderr": "", "interrupted": False,
                              "isImage": False, "noOutputExpected": False}}


def _read(text, path="/tmp/app.log"):
    n = text.count("\n") + 1
    return {"tool_name": "Read", "tool_input": {"file_path": path},
            "tool_response": {"type": "text", "file": {
                "filePath": path, "content": text, "numLines": n,
                "startLine": 1, "totalLines": n}}}


def _powershell(text):
    return {"tool_name": "PowerShell", "tool_input": {"command": "Get-Content app.log"},
            "tool_response": {"stdout": text, "stderr": "", "interrupted": False,
                              "isImage": False, "noOutputExpected": False}}


def _grep(text):
    return {"tool_name": "Grep", "tool_input": {"pattern": "ERROR", "output_mode": "content"},
            "tool_response": {"mode": "content", "numFiles": 0, "filenames": [],
                              "content": text, "numLines": text.count("\n") + 1}}


def _run(event, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(hook, "STATE_DIR", str(tmp_path))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"hook_event_name": "PostToolUse", **event})))
    hook.main()
    out = capsys.readouterr().out
    return json.loads(out)["hookSpecificOutput"]["updatedToolOutput"] if out else None


def test_bash_rewrite_keeps_bash_output_shape(monkeypatch, capsys, tmp_path):
    event = _bash(_log())
    got = _run(event, monkeypatch, capsys, tmp_path)
    want = event["tool_response"]
    assert set(got) == set(want)
    assert got["stdout"].startswith("[densely] output auto-compressed")
    assert {k: got[k] for k in want if k != "stdout"} == {k: want[k] for k in want if k != "stdout"}


def test_read_rewrite_keeps_read_output_shape(monkeypatch, capsys, tmp_path):
    event = _read(_log())
    got = _run(event, monkeypatch, capsys, tmp_path)
    want = event["tool_response"]
    assert set(got) == set(want) and got["type"] == "text"
    assert set(got["file"]) == set(want["file"])
    assert got["file"]["content"].startswith("[densely] output auto-compressed")
    assert got["file"]["numLines"] == got["file"]["content"].count("\n") + 1
    for k in ("filePath", "startLine", "totalLines"):
        assert got["file"][k] == want["file"][k]


@pytest.mark.parametrize("make, key", [(_powershell, "stdout"), (_grep, "content")])
def test_output_tools_rewrite_keeps_output_shape(make, key, monkeypatch, capsys, tmp_path):
    event = make(_log())
    got = _run(event, monkeypatch, capsys, tmp_path)
    want = event["tool_response"]
    assert set(got) == set(want)
    assert got[key].startswith("[densely] output auto-compressed")
    assert {k: got[k] for k in want if k != key} == {k: want[k] for k in want if k != key}


@pytest.mark.parametrize("make", [_bash, _powershell])
def test_truncated_shell_output_passes_through(make, monkeypatch, capsys, tmp_path):
    text = (_log(2000) * 2)[:hook.SHELL_MAX_OUTPUT]
    assert _run(make(text), monkeypatch, capsys, tmp_path) is None


def test_other_tools_pass_through(monkeypatch, capsys, tmp_path):
    event = {"tool_name": "mcp__codegraph__codegraph_explore", "tool_input": {"query": "x"},
             "tool_response": _log()}
    assert _run(event, monkeypatch, capsys, tmp_path) is None


@pytest.mark.parametrize("event", [_bash("short output"), _read(_log(), path="/tmp/app.py")])
def test_small_output_and_code_pass_through(event, monkeypatch, capsys, tmp_path):
    assert _run(event, monkeypatch, capsys, tmp_path) is None


def test_small_saving_passes_through(monkeypatch, capsys, tmp_path):
    """The preview replaces the output, so a needed expand costs preview + original:
    a thin saving is a net loss. _log() compresses ~70%, so demand more."""
    monkeypatch.setattr(hook, "MIN_SAVING", 0.8)
    assert _run(_bash(_log()), monkeypatch, capsys, tmp_path) is None


@pytest.mark.parametrize("cmd", ["gh pr diff 5893", "git diff master...HEAD"])
def test_diff_output_passes_through(cmd, monkeypatch, capsys, tmp_path):
    """Diffs are read in full, so a preview never carries the task."""
    event = _bash(_log())
    event["tool_input"]["command"] = cmd
    assert _run(event, monkeypatch, capsys, tmp_path) is None


# Cursor: preToolUse rewrites the Shell command; densely-filter compresses its output.
# tool_input is the shape Cursor CLI 2026.10.22 passes for Shell.

def _cursor_pre(command, tool="Shell", monkeypatch=None, capsys=None):
    event = {"hook_event_name": "preToolUse", "tool_name": tool,
             "tool_input": {"command": command, "cwd": "", "timeout": 30000}}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(event)))
    hook.main()
    out = capsys.readouterr().out
    return json.loads(out)["updated_input"] if out else None


def test_cursor_shell_command_is_wrapped(monkeypatch, capsys):
    got = _cursor_pre("cat app.log", monkeypatch=monkeypatch, capsys=capsys)
    assert got["cwd"] == "" and got["timeout"] == 30000
    assert "\ncat app.log\n}" in got["command"]
    assert hook.FILTER in got["command"]


@pytest.mark.parametrize("command, tool", [
    ("cat app.log", "Read"),
    ("", "Shell"),
    ('x; "/env/bin/densely-filter" "$f"', "Shell"),
    ("make test || exit 1", "Shell"),
    ("exec bash", "Shell"),
])
def test_cursor_pre_tool_use_passes_through(command, tool, monkeypatch, capsys):
    assert _cursor_pre(command, tool, monkeypatch, capsys) is None


def test_wrapped_command_keeps_shell_state_output_and_exit_code(monkeypatch, capsys, tmp_path):
    import os
    import subprocess
    import sys
    filt = tmp_path / "densely-filter"
    checkout = os.path.dirname(os.path.dirname(os.path.abspath(hook.__file__)))
    filt.write_text(f"#!{sys.executable}\nimport sys\nsys.path.insert(0, {checkout!r})\n"
                    "from densely import hook\nhook.filter_entry()\n")
    filt.chmod(0o755)
    monkeypatch.setattr(hook, "FILTER", str(filt))
    cmd = f"cd {tmp_path} && echo out; echo err >&2; false # trailing comment"
    wrapped = _cursor_pre(cmd, monkeypatch=monkeypatch, capsys=capsys)["command"]
    run = subprocess.run(["bash", "-c", wrapped + '\necho "rc=$? pwd=$PWD"'],
                         capture_output=True, text=True,
                         env={**os.environ, "DENSELY_STATE_DIR": str(tmp_path)})
    assert run.stdout == f"out\nerr\nrc=1 pwd={tmp_path}\n"


def _filter(path, monkeypatch, capsysbinary, tmp_path):
    monkeypatch.setattr(hook, "STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr("sys.argv", ["densely-filter", str(path)])
    hook.filter_entry()
    return capsysbinary.readouterr().out.decode()


def test_hook_sidecar_honours_state_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("DENSELY_STATE_DIR", str(tmp_path))
    got = hook.shrink(_log())
    sidecar = got.split('payload_file="')[1].split('"')[0]
    assert sidecar.startswith(str(tmp_path / "outputs") + "/")


def test_filter_small_output_is_unchanged(monkeypatch, capsysbinary, tmp_path):
    f = tmp_path / "out"
    f.write_bytes(b"short output\nno trailing newline")
    assert _filter(f, monkeypatch, capsysbinary, tmp_path) == "short output\nno trailing newline"


def test_filter_large_output_is_compressed(monkeypatch, capsysbinary, tmp_path):
    f = tmp_path / "out"
    f.write_text(_log())
    got = _filter(f, monkeypatch, capsysbinary, tmp_path)
    assert got.startswith("[densely] output auto-compressed")
    sidecar = got.split('payload_file="')[1].split('"')[0]
    from densely import decompress
    assert decompress(open(sidecar, encoding="utf-8").read()) == _log()


def test_filter_error_falls_back_to_original(monkeypatch, capsysbinary, tmp_path):
    f = tmp_path / "out"
    f.write_text(_log())
    monkeypatch.setattr(hook, "shrink", lambda text: 1 / 0)
    assert _filter(f, monkeypatch, capsysbinary, tmp_path) == _log()


def test_filter_binary_output_is_unchanged(monkeypatch, capsysbinary, tmp_path):
    f = tmp_path / "out"
    f.write_bytes(b"\xff\xfe binary \x00")
    monkeypatch.setattr(hook, "STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr("sys.argv", ["densely-filter", str(f)])
    hook.filter_entry()
    assert capsysbinary.readouterr().out == b"\xff\xfe binary \x00"
