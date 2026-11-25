"""Truncate solve-then-loop keygen L0 traces into clean-stop SFT rows.

Usage: py -m uv run python tools/truncate_stop.py [-o sft/train_v6_trunc.jsonl]

Candidates: keygen L0 train-seed episodes with rewards.solved.score == 1.0 and
stop_condition == "max_turns" (solved, then looped until the harness killed the
episode). For each, the episode's bash calls are replayed verbatim in a fresh
rlvr-keygen:0.2 container staged with the regenerated task files (same as
KeygenTask.setup: task files + the keygen.py stub). /app/repo is tarred out
after every assistant turn and each snapshot is graded on the host with the
real families/common/runner.py in host mode (RLVR_REPO_ROOT=<snapshot>),
comparing canonical-JSON outputs to expected values exec'd from the host-side
reference_source — the same check the env performs.

Cut rule: k = first turn of the final all-pass streak (the last stable pass),
v = the first later assistant turn that runs the checker or a test on the
solution and shows success (an ACCEPTED line, or a command exercising
keygen/check.py whose output shows no failure markers). The trace is cut
after v and a plain-text "done" turn is appended, its wording drawn with
random.Random(seed) from real clean-stop final messages. Episodes with a
non-bash tool call, no stable pass (replay did not reproduce the solve), no
verification turn after k, or a row over --max-chars are dropped and reported.
"""

import argparse
import collections
import glob
import io
import json
import os
import random
import re
import subprocess
import sys
import tarfile
import tempfile
from importlib.resources import files as pkg_files
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from build_sft import convert

from rlvr_coding_env.families.common.grading import _canonical_json
from rlvr_coding_env.families.keygen.generator import generate

EVAL_SEED_BASE = 1_000_000
DEFAULT_GLOBS = [
    "outputs/keygen--re-v5--*/traces.jsonl",
    "outputs/keygen--re-dpo-v5--bash--73cf9632/traces.jsonl",
]
IMAGE = "rlvr-keygen:0.2"
REPO_ROOT = "/app/repo"
CMD_TIMEOUT = 120
NONCE = "truncate-stop"
STUB = b"def keygen(name: str) -> str:\n    raise NotImplementedError\n"
RUNNER = str(pkg_files("rlvr_coding_env.families.common").joinpath("runner.py"))

# Real clean-stop final messages (train_v6_cleanstop.jsonl + keygen L0 rows in
# train_v5.jsonl), restricted to wordings with no seed-specific values and no
# numeric verification claims (the truncated prefix rarely verifies 100+ names).
STOP_WORDINGS = [
    (
        "Implemented `keygen.py` with the exact checker logic from `check.py`. "
        "Verified against the example and multiple edge cases."
    ),
    (
        "Implemented `keygen` in `/app/repo/keygen.py` to reproduce the "
        "checker's hash algorithm. Verified against the example and random "
        "names."
    ),
]

_TESTS_SOLUTION = re.compile(
    r"keygen\s*\(|from\s+keygen\b|import\s+keygen|\bcheck\.py\b|\./check\b"
    r"|python[\w.]*\s+[^\s;&|]*keygen\.py"
)
_ACCEPTED = re.compile(r"(?:^|\s)ACCEPTED\s*$")
_FAILURE = re.compile(
    r"REJECTED|Traceback|AssertionError|\bError\b|\bFAIL(?:ED)?\b|\bFalse\b|\bmismatch\b"
)


def iter_turns(nodes):
    """Yield (start, end, assistant_msg, tool_msgs) per assistant turn."""
    i = 0
    while i < len(nodes):
        if nodes[i]["message"]["role"] == "assistant":
            j = i + 1
            while j < len(nodes) and nodes[j]["message"]["role"] == "tool":
                j += 1
            yield i, j - 1, nodes[i]["message"], [n["message"] for n in nodes[i + 1 : j]]
            i = j
        else:
            i += 1


def bash_commands(msg):
    """Tool-call command strings; None if any call isn't a replayable bash call."""
    cmds = []
    for c in msg.get("tool_calls") or []:
        if c.get("name") != "bash":
            return None
        args = c.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                return None
        if not isinstance(args, dict) or not isinstance(args.get("command"), str):
            return None
        cmds.append(args["command"])
    return cmds


def turn_is_verification(commands, outputs):
    """A command exercised keygen/the checker and the output shows success."""
    for cmd, out in zip(commands, outputs):
        if not _TESTS_SOLUTION.search(cmd):
            continue
        if any(_ACCEPTED.search(line.strip()) for line in out.splitlines()):
            return True
        if not _FAILURE.search(out):
            return True
    return False


def verified_flags(turns):
    return [
        turn_is_verification(
            bash_commands(m) or [], [str(o.get("content") or "") for o in outs]
        )
        for _, _, m, outs in turns
    ]


def last_stable_pass(passes):
    """First turn of the final all-pass streak; None if the last turn fails."""
    k = len(passes)
    while k and passes[k - 1]:
        k -= 1
    return k if k < len(passes) else None


def choose_cut(passes, verified):
    """(turn_index, reason): cut after the first verification turn past the
    last stable pass. None + reason when the episode must be dropped."""
    if last_stable_pass(passes) is None:
        return None, "replay_did_not_reproduce_solve"
    for v in range(last_stable_pass(passes) + 1, len(passes)):
        if verified[v]:
            return v, None
    return None, "no_verification_after_solve"


def truncate_messages(nodes, end, stop_text):
    """convert() on nodes through `end`, plus the plain-text done turn."""
    msgs = convert(nodes[: end + 1])
    msgs.append({"role": "assistant", "content": stop_text})
    return msgs


def _docker(*args, data=None, timeout=None):
    return subprocess.run(
        ["docker", *args], input=data, capture_output=True,
        check=False, timeout=timeout,
    )


def snapshot_repo(cid):
    """{path: bytes} of regular files under /app/repo; None on tar failure or
    non-regular members (a symlink would fail the real scope check anyway)."""
    r = _docker("exec", cid, "tar", "cf", "-", "-C", "/app", "repo")
    if r.returncode:
        return None
    files = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(r.stdout)) as tf:
            for m in tf.getmembers():
                if m.isdir():
                    continue
                if not m.isreg():
                    return None
                files[m.name.removeprefix("repo/")] = tf.extractfile(m).read()
    except (tarfile.TarError, OSError, EOFError):
        return None
    return files


def replay(turn_cmds, inst, image):
    """Snapshot /app/repo after each turn in one fresh container.

    Staging mirrors KeygenTask.setup for L0: task files plus the stub. Returns
    (snapshots, None) or (None, drop_reason)."""
    cid = (
        _docker("run", "-d", "--rm", image, "tail", "-f", "/dev/null")
        .stdout.decode()
        .strip()
    )
    if not cid:
        return None, "container_start_failed"
    try:
        r = _docker("exec", cid, "mkdir", "-p", REPO_ROOT)
        if r.returncode:
            return None, "stage_failed"
        for path, content in inst.files.items():
            r = _docker(
                "exec", "-i", cid, "sh", "-c", f"cat > {REPO_ROOT}/{path}",
                data=content.encode(),
            )
            if r.returncode:
                return None, "stage_failed"
        r = _docker(
            "exec", "-i", cid, "sh", "-c", f"cat > {REPO_ROOT}/keygen.py",
            data=STUB,
        )
        if r.returncode:
            return None, "stage_failed"
        snaps = []
        for cmds in turn_cmds:
            for cmd in cmds or []:
                try:
                    r = _docker(
                        "exec", "-w", REPO_ROOT, cid, "bash", "-c", cmd,
                        timeout=CMD_TIMEOUT,
                    )
                except subprocess.TimeoutExpired:
                    return None, "replay_timeout"
                if r.returncode and b"is not running" in (r.stderr or b""):
                    return None, "container_died"
            snaps.append(snaps[-1] if snaps and not cmds else snapshot_repo(cid))
        return snaps, None
    finally:
        _docker("rm", "-f", cid)


def _expected_outputs(inst):
    ns = {}
    exec(  # noqa: S102 - same trusted path as taskset._compute_grading
        compile(inst.reference_source, "<trusted-keygen-reference>", "exec"), ns
    )
    serial = ns["serial"]
    return [{"ok": True, "value": inst.example_serial}] + [
        {"ok": True, "value": serial(n)} for n in inst.hidden_names
    ]


def grade_snapshot(files, repo_dir, work, expected):
    """Real runner.py in host mode: scope check then hidden run; all cases."""
    if files is None:
        return False
    repo_dir.mkdir(parents=True, exist_ok=True)
    for rel, data in files.items():
        p = repo_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    env = {**os.environ, "RLVR_REPO_ROOT": str(repo_dir)}
    scope = subprocess.run(
        [sys.executable, RUNNER, "--scope", str(work / "protected.json")],
        check=False, env=env, capture_output=True, text=True,
    )
    try:
        if scope.returncode or json.loads(scope.stdout).get("scope_ok") is not True:
            return False
    except ValueError:
        return False
    result = work / "result.json"
    result.unlink(missing_ok=True)
    subprocess.run(
        [sys.executable, RUNNER, "--run", str(work / "cases.json"), str(result)],
        check=False, env=env, capture_output=True,
    )
    try:
        payload = json.loads(result.read_bytes())
    except (ValueError, OSError):
        return False
    outputs = payload.get("outputs")
    if (
        payload.get("nonce") != NONCE
        or not isinstance(outputs, list)
        or len(outputs) != len(expected)
    ):
        return False
    return all(
        _canonical_json(a) == _canonical_json(e)
        for a, e in zip(outputs, expected)
    )


def _write_grading_files(inst, work):
    work.mkdir(parents=True, exist_ok=True)
    cases = {
        "nonce": NONCE,
        "deliverable": "keygen.py",
        "function_name": "keygen",
        "return_type": "str",
        "cases": [[n] for n in [inst.example_name, *inst.hidden_names]],
    }
    protected = {
        "deliverable": "keygen.py",
        "expected_files": inst.expected_files,
        "hashes": inst.protected_hashes,
    }
    (work / "cases.json").write_text(json.dumps(cases, allow_nan=False))
    (work / "protected.json").write_text(json.dumps(protected, sort_keys=True))


def process_episode(t, work_root, *, image=IMAGE, max_chars=16000):
    """(row, info) or (None, {"drop": reason, ...}) for one candidate trace."""
    d = t["task"]["data"]
    seed = d["seed"]
    inst = generate(seed, 0)
    work = work_root / f"seed{seed}"
    _write_grading_files(inst, work)
    expected = _expected_outputs(inst)
    turns = list(iter_turns(t["nodes"]))
    cmds = [bash_commands(m) for _, _, m, _ in turns]
    if any(c is None for c in cmds):
        return None, {"drop": "non_bash_tool_call"}
    snaps, err = replay(cmds, inst, image)
    if err:
        return None, {"drop": err}
    verified = verified_flags(turns)
    passes = []
    for i, s in enumerate(snaps):
        if i and s is not None and s == snaps[i - 1]:
            passes.append(passes[-1])
        else:
            passes.append(grade_snapshot(s, work / f"turn{i:03d}", work, expected))
    v, reason = choose_cut(passes, verified)
    if v is None:
        return None, {"drop": reason, "passes": passes}
    stop = random.Random(seed).choice(STOP_WORDINGS)
    msgs = truncate_messages(t["nodes"], turns[v][1], stop)
    chars = sum(len(json.dumps(m)) for m in msgs)
    if chars > max_chars:
        return None, {"drop": "too_long", "cut_turn": v, "chars": chars}
    row = {
        "messages": msgs,
        "tools": [
            {"type": "function", "function": {k: v for k, v in x.items() if k != "type"}}
            for x in t["tools"]
        ],
        "meta": {
            "family": "keygen",
            "level": 0,
            "seed": seed,
            "source": "truncated",
            "cut_turn": v,
        },
    }
    return row, {"cut_turn": v, "total_turns": len(turns), "chars": chars}


def is_candidate(e, t):
    if e["env"]["id"] != "keygen":
        return False
    d = t["task"]["data"]
    return (
        d.get("level") == 0
        and (d.get("access") or "default") == "default"
        and d.get("seed") is not None
        and d["seed"] < EVAL_SEED_BASE
        and t["rewards"].get("solved", {}).get("score") == 1.0
        and t.get("stop_condition") == "max_turns"
        and not t.get("errors")
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", default="sft/train_v6_trunc.jsonl")
    ap.add_argument("--glob", action="append")
    ap.add_argument("--max-chars", type=int, default=16000)
    ap.add_argument("--image", default=IMAGE)
    a = ap.parse_args()
    kept, stats, report = [], collections.Counter(), []
    seen = set()
    paths = sorted(
        p for g in (a.glob or DEFAULT_GLOBS) for p in glob.glob(g)
    )
    with tempfile.TemporaryDirectory(prefix="trunc-stop-") as tmp:
        work_root = Path(tmp)
        for p in paths:
            run = Path(p).parent.name
            for line in Path(p).read_text(encoding="utf8").splitlines():
                try:
                    e = json.loads(line)
                    t = e["traces"][0]
                except (ValueError, KeyError, IndexError):
                    continue
                if not is_candidate(e, t):
                    continue
                seed = t["task"]["data"]["seed"]
                stats["candidates"] += 1
                if seed in seen:
                    stats["dup_seed"] += 1
                    continue
                seen.add(seed)
                row, info = process_episode(
                    t, work_root, image=a.image, max_chars=a.max_chars
                )
                if row is None:
                    stats[f"drop:{info['drop']}"] += 1
                    report.append((run, seed, info))
                    print(run, "seed", seed, "DROP", info, flush=True)
                else:
                    stats["cut"] += 1
                    info["run"] = run
                    report.append((run, seed, info))
                    kept.append(row)
                    print(run, "seed", seed, "CUT", info, flush=True)
    os.makedirs(os.path.dirname(a.o) or ".", exist_ok=True)
    with open(a.o, "w", encoding="utf8") as f:
        f.writelines(json.dumps(r) + "\n" for r in kept)
    print(len(kept), "truncated rows ->", a.o)
    for k, v in sorted(stats.items(), key=str):
        print(k, v)


if __name__ == "__main__":
    main()
