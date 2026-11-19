"""Aggregate solved/attempted/provider-error counts plus tokens/cost from run outputs.

Usage:
    py baselines/summarize.py outputs/                 # one row per run dir
    py baselines/summarize.py outputs/ --group model   # or family | level

Counting definitions (numbers here are publishable — read before quoting):
- episode: one line of traces.jsonl.
- infra errors (NOT agent failures, DESIGN decision 11): stop_condition is
  "provider_error", "harness_error" or "sandbox_error", or a recorded error has
  "provider", "harness" or "sandbox" in its type. Shown split as prov_err /
  harness_err (sandbox failures count under harness_err). A harness_error can in
  principle reflect agent output the harness could not parse; observed cases
  were a provider/tooling crash after 1 step or a dead runtime (exit 137).
- attempted: episodes minus infra errors (the agent really ran).
- completed: attempted episodes whose stop_condition is "agent_completed".
- solved: rewards["solved"].score == 1.0.
- tokens: episode num_input_tokens / num_output_tokens, summed per group.
- cost: tokens x PRICES below. PRICES are list prices in USD per 1M tokens;
  verify before publishing (cached input is billed cheaper on some providers).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

PRICES = {  # USD per 1M tokens (input, output) — verify before publishing
    "deepseek-flash": (0.27, 1.10),
    "gemini-3.1-flash-lite": (0.0, 0.0),
}

_INFRA_STOPS = {"provider_error", "harness_error", "sandbox_error"}


def _infra_kind(ep: dict, tr: dict) -> str | None:
    stop = tr.get("stop_condition")
    types = " ".join(
        str(e.get("type", ""))
        for e in list(ep.get("errors") or []) + list(tr.get("errors") or [])
    ).lower()
    if stop == "provider_error" or "provider" in types:
        return "provider_error"
    if stop == "harness_error" or "harness" in types:
        return "harness_error"
    if stop == "sandbox_error" or "sandbox" in types:
        return "harness_error"
    return None


def _rows(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        ep = json.loads(line)
        tr = ep["traces"][0]
        task_id = ep["task"]["data"]["id"]
        infra = _infra_kind(ep, tr)
        rows.append(
            {
                "run": ep["run"]["name"],
                "model": ep["run"]["name"].split("--")[1],
                "family": task_id.split("-")[0],
                "level": task_id.split("-")[1],
                "provider_error": infra == "provider_error",
                "harness_error": infra == "harness_error",
                "completed": infra is None and tr.get("stop_condition") == "agent_completed",
                "solved": (tr.get("rewards") or {}).get("solved", {}).get("score") == 1.0,
                "tok_in": ep.get("num_input_tokens") or 0,
                "tok_out": ep.get("num_output_tokens") or 0,
            }
        )
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="+", type=Path)
    ap.add_argument("--group", choices=["run", "model", "family", "level"], default="run")
    ns = ap.parse_args()

    groups: dict[str, list[dict]] = defaultdict(list)
    for p in ns.paths:
        for f in sorted(p.rglob("traces.jsonl") if p.is_dir() else [p]):
            for row in _rows(f):
                groups[row[ns.group]].append(row)

    header = (
        f"{'group':48s} {'eps':>4s} {'solved':>6s} {'completed':>9s} {'attempted':>9s} "
        f"{'prov':>5s} {'harn':>5s} {'tok_in':>9s} {'tok_out':>9s} {'~cost':>8s}"
    )
    print(header)
    print("-" * len(header))
    totals = defaultdict(int)
    for name in sorted(groups):
        rows = groups[name]
        s = {
            "eps": len(rows),
            "solved": sum(r["solved"] for r in rows),
            "completed": sum(r["completed"] for r in rows),
            "prov": sum(r["provider_error"] for r in rows),
            "harn": sum(r["harness_error"] for r in rows),
            "tok_in": sum(r["tok_in"] for r in rows),
            "tok_out": sum(r["tok_out"] for r in rows),
        }
        s["attempted"] = s["eps"] - s["prov"] - s["harn"]
        cost = (
            sum(
                r["tok_in"] * PRICES[r["model"]][0] + r["tok_out"] * PRICES[r["model"]][1]
                for r in rows
            )
            / 1_000_000
            if all(r["model"] in PRICES for r in rows)
            else float("nan")
        )
        print(
            f"{name:48s} {s['eps']:4d} {s['solved']:6d} {s['completed']:9d} "
            f"{s['attempted']:9d} {s['prov']:5d} {s['harn']:5d} "
            f"{s['tok_in']:9d} {s['tok_out']:9d} {cost:8.3f}"
        )
        for k, v in s.items():
            totals[k] += v
    print("-" * len(header))
    print(
        f"{'TOTAL':48s} {totals['eps']:4d} {totals['solved']:6d} {totals['completed']:9d} "
        f"{totals['attempted']:9d} {totals['prov']:5d} {totals['harn']:5d} "
        f"{totals['tok_in']:9d} {totals['tok_out']:9d}"
    )
    return 0


_HEREDOC_RE = re.compile(r"<<-?['\"]?(\w+)['\"]?")
_DISASM_TOOLS = {"objdump", "gdb", "readelf", "strings", "nm", "ndisasm", "r2", "radare2"}
_ORACLE_NAMES = {"./prog", "./reader", "./check", "/app/repo/prog", "/app/repo/reader", "/app/repo/check"}
_WRAP = {"sudo", "env", "timeout", "cd", "nohup", "command"}
_SCRIPTED_RE = re.compile(r"(subprocess|os\.system|Popen|check_output)")
_BINPATH_RE = re.compile(r"(\./|/app/repo/)(prog|reader|check)\b")


def _strip_heredocs_and_quotes(text: str) -> str:
    """Return text minus heredoc bodies and quoted-string contents."""
    out_lines = []
    term = None
    for line in text.splitlines():
        if term is not None:
            if line.strip() == term:
                term = None
            continue
        m = _HEREDOC_RE.search(line)
        out_lines.append(_HEREDOC_RE.sub("<<", line) if m else line)
        if m:
            term = m.group(1)
    head = "\n".join(out_lines)
    # drop contents of quoted strings (keeps the quoting words themselves)
    head = re.sub(r"'[^']*'", "''", head)
    head = re.sub(r'"[^"]*"', '""', head)
    return head


def _simple_commands(head_text: str) -> list[str]:
    parts = re.split(r";|&&|\|\||\||\n|\$\(|`|\bdo\b|\bthen\b", head_text)
    return [p.strip() for p in parts if p.strip()]


def _prog_name(simple: str) -> str | None:
    words = simple.split()
    i = 0
    while i < len(words) and (
        "=" in words[i] and not words[i].startswith("./")
        or words[i] in _WRAP
        or words[i] in {"time", "\\"}
    ):
        i += 1
    return words[i] if i < len(words) else None


def classify_command(cmd_text: str) -> dict:
    """Classify one bash command: disasm tool? oracle exec? oracle via script?

    shortcut: program names inside quoting wrappers like `bash -c "objdump ..."`
    are not detected (quoted contents are stripped) — accepted miss.
    """
    head = _strip_heredocs_and_quotes(cmd_text)
    disasm = oracle_direct = False
    for simple in _simple_commands(head):
        name = _prog_name(simple)
        if name in _DISASM_TOOLS:
            disasm = True
        if name in _ORACLE_NAMES:
            oracle_direct = True
    oracle_scripted = (
        not oracle_direct
        and bool(_BINPATH_RE.search(cmd_text))
        and bool(_SCRIPTED_RE.search(cmd_text))
    )
    return {"disasm": disasm, "oracle_direct": oracle_direct, "oracle_scripted": oracle_scripted}


if __name__ == "__main__":
    sys.exit(main())
