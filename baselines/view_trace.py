"""Render outputs/*/traces.jsonl episodes as readable transcripts.

Usage:
    py baselines/view_trace.py outputs/<run-dir>            # all episodes
    py baselines/view_trace.py outputs/<run-dir> -i 2       # one episode
    py baselines/view_trace.py outputs/                     # every run dir
    --full         untruncated tool output and edit diffs
    --reasoning    include assistant reasoning_content
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

TOOL_LINES = 12
TOOL_CHARS = 3000
PROMPT_LINES = 14


def _clip(text: str, max_lines: int, max_chars: int) -> str:
    lines = text.splitlines()
    clipped = text[:max_chars] if len(text) > max_chars else text
    if len(lines) > max_lines:
        clipped = "\n".join(lines[:max_lines])
    if clipped != text:
        clipped += f"\n… ({len(lines)} lines, {len(text)} chars)"
    return clipped


def _tool_args(call: dict) -> tuple[str, dict]:
    fn = call.get("function", call)
    try:
        args = json.loads(fn.get("arguments") or "{}")
    except json.JSONDecodeError:
        args = {"raw": fn.get("arguments")}
    return fn.get("name", "?"), args


def _episode(ep: dict, idx: int, *, full: bool, reasoning: bool) -> str:
    out = []
    tr = ep["traces"][0]
    task_id = ep["task"]["data"]["id"]
    run = ep["run"]["name"]
    out.append(f"===== [{idx}] {task_id}  ({run}) =====")

    for node in tr.get("nodes", []):
        msg = node.get("message") or {}
        role = msg.get("role")
        if role == "system":
            continue
        if role == "user":
            body = msg.get("content") or ""
            out.append(f"[prompt]\n{_clip(body, PROMPT_LINES, TOOL_CHARS)}")
            continue
        if role == "assistant":
            if reasoning and msg.get("reasoning_content"):
                out.append(f"[reasoning] {_clip(msg['reasoning_content'], 8, 1200)}")
            if msg.get("content"):
                out.append(f"[assistant] {_clip(msg['content'], 8, 1200)}")
            for call in msg.get("tool_calls") or []:
                name, args = _tool_args(call)
                if name == "bash":
                    out.append(f"$ {args.get('command', '')}")
                elif name == "edit":
                    line = f"[edit {args.get('path', '?')}]"
                    if full:
                        line += (
                            f"\n- {_clip(args.get('old_str', ''), 20, 2000)}"
                            f"\n+ {_clip(args.get('new_str', ''), 20, 2000)}"
                        )
                    out.append(line)
                else:
                    out.append(f"[{name}] {json.dumps(args)[:300]}")
            continue
        if role == "tool":
            body = msg.get("content") or ""
            if not full:
                body = _clip(body, TOOL_LINES, TOOL_CHARS)
            out.append(f"> {body}")
    verdict = [f"verdict: ok={ep['ok']}"]
    for name, r in (tr.get("rewards") or {}).items():
        verdict.append(f"{name}={r.get('score')}")
    verdict += [f"{k}={v}" for k, v in (tr.get("metrics") or {}).items()]
    verdict.append(f"stop={tr.get('stop_condition')}")
    if ep.get("errors"):
        verdict.append(f"errors={[e.get('type') for e in ep['errors']]}")
    timing = tr.get("timing", {}).get("agent", {})
    if "start" in timing:
        verdict.append(f"agent={timing['end'] - timing['start']:.0f}s")
    verdict.append(
        f"{len(tr.get('calls', []))} calls "
        f"{ep.get('num_input_tokens', 0)}+{ep.get('num_output_tokens', 0)} tok"
    )
    out.append(" | ".join(verdict))
    return "\n".join(out)


def _episodes(path: Path) -> list[dict]:
    eps = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            eps.append(json.loads(line))
    return eps


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="+", type=Path)
    ap.add_argument("-i", "--index", type=int, default=None)
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--reasoning", action="store_true")
    ns = ap.parse_args()

    files = []
    for p in ns.paths:
        files.extend(p.rglob("traces.jsonl") if p.is_dir() else [p])
    for path in sorted(files):
        for i, ep in enumerate(_episodes(path)):
            if ns.index is not None and i != ns.index:
                continue
            print(_episode(ep, i, full=ns.full, reasoning=ns.reasoning))
            print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
