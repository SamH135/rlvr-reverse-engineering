"""Live terminal view of recent rollout runs: uv run python tools/watch_runs.py [--since-min 120] [--every 5] [--once]

Reads outputs/*/traces.jsonl (one line per FINISHED episode), so in-flight episodes show only as running containers.
"""
import argparse
import json
import os
import subprocess
import time
from pathlib import Path


def scan(since):
    rows = []
    for d in Path("outputs").glob("*--bash--*"):
        t = d / "traces.jsonl"
        if not t.exists() or t.stat().st_mtime < since and d.stat().st_mtime < since:
            continue
        n = solved = prov = harn = cap = 0
        lvl = "?"
        for line in t.read_text(encoding="utf8", errors="replace").splitlines():
            try:
                e = json.loads(line)
                x = e["traces"][0]
            except (ValueError, KeyError, IndexError):
                continue
            n += 1
            lvl = x["task"]["data"].get("level", "?")
            sc = x["rewards"].get("solved", {}).get("score", 0)
            stop = str(x.get("stop_condition"))
            solved += sc == 1.0
            prov += "provider" in stop.lower()
            harn += stop.lower() in ("sandbox_error", "harness_error") or "attributeerror" in stop.lower()
            cap += stop == "max_turns"
        fam, model = d.name.split("--bash--")[0].split("--", 1)
        rows.append((max(t.stat().st_mtime, d.stat().st_mtime), fam, lvl, model, n, solved, cap, prov + harn, d.name[-8:]))
    return sorted(rows)


def sh(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10, shell=True, check=False).stdout.strip()
    except subprocess.SubprocessError:
        return "?"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since-min", type=int, default=120)
    ap.add_argument("--every", type=int, default=5)
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    while True:
        rows = scan(time.time() - a.since_min * 60)
        out = [time.strftime("%H:%M:%S") + f"  runs touched in last {a.since_min} min  (episodes = finished only)", ""]
        out.append(f"{'family':9}{'L':>2} {'model':38}{'done':>5}{'solved':>7}{'cap':>5}{'err':>4}  {'last write':>10}  run")
        for mt, fam, lvl, model, n, s, cap, err, rid in rows:
            ago = int(time.time() - mt)
            out.append(f"{fam:9}{lvl!s:>2} {model[:38]:38}{n:>5}{s:>7}{cap:>5}{err:>4}  {ago // 60:>4}m{ago % 60:02d}s   {rid}")
        out += ["", "containers up: " + (sh('docker ps --format "{{.Names}} {{.RunningFor}}"').replace("\n", " | ") or "none")]
        out.append("ollama: " + (sh("ollama ps").replace("\n", " | ") or "n/a"))
        if not a.once:
            os.system("cls" if os.name == "nt" else "clear")
        print("\n".join(out), flush=True)
        if a.once:
            return
        time.sleep(a.every)


if __name__ == "__main__":
    main()
