"""Worker CLI for the swe2_proxy queue. One worker = one agent answering
chat.completions requests parked by the proxy.

    py tools/swe2_worker.py --queue tmp_swe2/q8399 status
    py tools/swe2_worker.py --queue tmp_swe2/q8399 claim --wait 600 --worker sam
    py tools/swe2_worker.py --queue tmp_swe2/q8399 respond <key> --bash "ls /app/repo"
    py tools/swe2_worker.py --queue tmp_swe2/q8399 respond <key> --say "done"
    py tools/swe2_worker.py --queue tmp_swe2/q8399 respond <key> --file resp.json
    py tools/swe2_worker.py --queue tmp_swe2/q8399 release <key>
    py tools/swe2_worker.py --queue tmp_swe2/q8399 gc --stale 900

`claim` prints the key and a transcript tail; answer with `respond`. A turn is
either tool calls (repeat --bash/--tool-call) or a final text answer (--say /
no calls = episode end). To do several calls in one turn, pass --file with
{"content": ..., "tool_calls": [{"name": "bash", "arguments": {...}}]}.

A worker only needs filesystem access to the queue — no Docker, no repo.
Subagent loop: claim --wait -> solve -> respond -> repeat, until claim exits 3
(queue STOPped or wait timed out).
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

CLIP = 2000


def clip(s: str, n: int = CLIP) -> str:
    s = str(s)
    return s if len(s) <= n else s[: n // 2] + "\n...[clipped]...\n" + s[-n // 2 :]


def load_req(q: Path, key: str) -> dict:
    for d in ("claimed", "pending"):
        p = q / d / f"{key}.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf8"))
    sys.exit(f"no request {key} in {q}")


def render(req: dict) -> str:
    body = req["request"]
    msgs = body.get("messages", [])
    out = [f"# key={req['key']} model={body.get('model')} messages={len(msgs)}",
           f"# tools={[t.get('function', {}).get('name') for t in body.get('tools', [])]}"]
    shown = msgs[-14:]
    if len(msgs) > len(shown):
        out.append(f"# ... {len(msgs) - len(shown)} earlier messages omitted ...")
    for m in shown:
        role = m.get("role")
        if role == "assistant" and m.get("tool_calls"):
            for tc in m["tool_calls"]:
                fn = tc.get("function", {})
                out.append(f"[assistant -> {fn.get('name')}] {clip(fn.get('arguments', ''))}")
            if m.get("content"):
                out.append(f"[assistant] {clip(m['content'])}")
        elif role == "tool":
            out.append(f"[tool {m.get('name', '')}] {clip(m.get('content'))}")
        else:
            out.append(f"[{role}] {clip(m.get('content'), 4000)}")
    return "\n\n".join(out)


def cmd_status(q: Path, a):
    for d in ("pending", "claimed", "responses"):
        files = sorted((q / d).glob("*.json"), key=lambda p: p.stat().st_mtime)
        print(f"{d}: {len(files)}")
        for p in files[: a.limit]:
            age = int(time.time() - p.stat().st_mtime)
            print(f"  {p.stem}  age={age}s")


def cmd_claim(q: Path, a):
    deadline = time.time() + (a.wait or 0)
    while True:
        if (q / "STOP").exists():
            print("queue STOPped", file=sys.stderr)
            sys.exit(3)
        pend = sorted((q / "pending").glob("*.json"), key=lambda p: p.stat().st_mtime)
        if pend:
            src = pend[0]
            dst = q / "claimed" / src.name
            try:
                os.replace(src, dst)
            except OSError:
                continue  # another worker got it
            (q / "claimed" / f"{src.stem}.owner").write_text(
                f"{a.worker} {time.time()}", encoding="utf8"
            )
            req = json.loads(dst.read_text(encoding="utf8"))
            print(render(req))
            print(f"\n>>> respond {req['key']}")
            return
        if a.wait is None or time.time() > deadline:
            print("no pending requests", file=sys.stderr)
            sys.exit(3)
        time.sleep(2)


def cmd_respond(q: Path, a):
    load_req(q, a.key)  # validates the key exists
    if a.file:
        raw = json.loads(Path(a.file).read_text(encoding="utf8"))
    else:
        calls = [{"name": "bash", "arguments": {"command": c}} for c in a.bash]
        calls += [json.loads(tc) for tc in a.tool_call]
        raw = {"content": a.say, "tool_calls": calls}
    tmp = q / "responses" / f"{a.key}.tmp"
    tmp.write_text(json.dumps(raw), encoding="utf8")
    os.replace(tmp, tmp.with_suffix(".json"))
    for p in (q / "claimed" / f"{a.key}.json", q / "claimed" / f"{a.key}.owner"):
        p.unlink(missing_ok=True)
    print(f"answered {a.key}")


def cmd_release(q: Path, a):
    src = q / "claimed" / f"{a.key}.json"
    os.replace(src, q / "pending" / src.name)
    (q / "claimed" / f"{a.key}.owner").unlink(missing_ok=True)
    print(f"requeued {a.key}")


def cmd_gc(q: Path, a):
    n = 0
    for p in (q / "claimed").glob("*.json"):
        if p.suffix != ".json":
            continue
        if time.time() - p.stat().st_mtime > a.stale:
            os.replace(p, q / "pending" / p.name)
            (q / "claimed" / f"{p.stem}.owner").unlink(missing_ok=True)
            n += 1
    print(f"requeued {n}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", default="tmp_swe2/q8399")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("status")
    s.add_argument("--limit", type=int, default=10)
    s.set_defaults(f=cmd_status)
    s = sub.add_parser("claim")
    s.add_argument("--wait", type=int, default=None)
    s.add_argument("--worker", default="worker")
    s.set_defaults(f=cmd_claim)
    s = sub.add_parser("respond")
    s.add_argument("key")
    s.add_argument("--say", default=None)
    s.add_argument("--bash", action="append", default=[])
    s.add_argument("--tool-call", action="append", default=[])
    s.add_argument("--file", default=None)
    s.set_defaults(f=cmd_respond)
    s = sub.add_parser("release")
    s.add_argument("key")
    s.set_defaults(f=cmd_release)
    s = sub.add_parser("gc")
    s.add_argument("--stale", type=int, default=900)
    s.set_defaults(f=cmd_gc)
    a = ap.parse_args()
    q = Path(a.queue)
    for d in ("pending", "claimed", "responses"):
        (q / d).mkdir(parents=True, exist_ok=True)
    a.f(q, a)


if __name__ == "__main__":
    main()
