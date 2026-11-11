"""Render verifiers trace outputs to a single self-contained HTML transcript viewer.

Usage:
    py -m uv run python tools/view_transcripts.py [path] [-o out.html] [--open]

`path` may be a run dir (outputs/<run>), a traces.jsonl file, or the outputs/
root (all `*/traces.jsonl` are aggregated). Output defaults to `transcripts.html`
inside the given directory (cwd for a file input).
"""

import argparse
import html
import json
import sys
import webbrowser
from pathlib import Path

MAX_FILE_BYTES = 512 * 1024


def find_traces_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    direct = path / "traces.jsonl"
    if direct.exists():
        return [direct]
    return sorted(path.glob("*/traces.jsonl"))


def load_rollouts(traces_file: Path) -> list[dict]:
    """Flatten each line's `traces` list into rollout records."""
    rollouts = []
    for line in traces_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        for i, trace in enumerate(rec.get("traces") or []):
            rollouts.append({"run_dir": traces_file.parent, "rec": rec,
                             "trace": trace, "trace_idx": i})
    return rollouts


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def render_args(arguments: str) -> str:
    """Render tool-call arguments: dict values as <pre>, raw fallback."""
    try:
        args = json.loads(arguments)
    except (TypeError, json.JSONDecodeError):
        return f'<pre class="arg">{esc(arguments)}</pre>'
    if not isinstance(args, dict):
        return f'<pre class="arg">{esc(json.dumps(args, indent=2))}</pre>'
    return "".join(
        f'<div class="argname">{esc(k)}</div><pre class="arg">{esc(v if isinstance(v, str) else json.dumps(v, indent=2))}</pre>'
        for k, v in args.items()
    )


def render_message(node: dict, call: dict | None) -> str:
    msg = node.get("message") or {}
    role = msg.get("role", "?")
    parts = []

    footer = ""
    if call:
        u = call.get("usage") or {}
        dur = (call.get("time") or {}).get("end", 0) - (call.get("time") or {}).get("start", 0)
        usage = " ".join(
            f"{label} {u[key]}"
            for label, key in [("in", "prompt_tokens"), ("out", "completion_tokens"),
                               ("reason", "reasoning_tokens"), ("cached", "cached_input_tokens")]
            if u.get(key)
        )
        footer = (f'<div class="meta">{esc(call.get("model", ""))} · '
                  f'{esc(call.get("finish_reason", ""))} · {usage} · {dur:.1f}s</div>')

    if role == "assistant":
        if msg.get("reasoning_content"):
            parts.append(f'<details class="reasoning"><summary>reasoning</summary>'
                         f'<pre>{esc(msg["reasoning_content"])}</pre></details>')
        if msg.get("content"):
            parts.append(f'<pre>{esc(msg["content"])}</pre>')
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function", tc)
            parts.append(f'<div class="toolcall"><div class="toolname">→ {esc(fn.get("name", "?"))}</div>'
                         f'{render_args(fn.get("arguments"))}</div>')
    elif role == "tool":
        content = msg.get("content") or ""
        if not isinstance(content, str):
            content = json.dumps(content, default=str)
        first = content.split("\n", 1)[0][:120]
        parts.append(f'<details><summary>{esc(msg.get("name", "tool"))}: {esc(first)}'
                     f'{"…" if len(content) > len(first) else ""}</summary>'
                     f'<pre>{esc(content)}</pre></details>')
    elif role in ("system", "user"):
        body = f'<pre>{esc(msg.get("content") or "")}</pre>'
        if role == "system":
            body = f'<details><summary>system prompt</summary>{body}</details>'
        parts.append(body)
    else:
        parts.append(f'<pre>{esc(json.dumps(msg, indent=2, default=str))}</pre>')

    return f'<div class="msg {esc(role)}"><div class="role">{esc(role)}</div>{"".join(parts)}{footer}</div>'


def render_artifacts(artifact_dir: Path) -> str:
    if not artifact_dir.is_dir():
        return ""
    items = []
    for f in sorted(artifact_dir.rglob("*")):
        if not f.is_file() or f.name == "manifest.json":
            continue
        rel = f.relative_to(artifact_dir)
        try:
            raw = f.read_bytes()
            text = None if len(raw) > MAX_FILE_BYTES or b"\x00" in raw[:8192] \
                else raw.decode("utf-8")
        except OSError:
            text = None
        if text is None:
            items.append(f'<div class="argname">{esc(rel)} (binary)</div>')
        else:
            items.append(f'<details><summary>{esc(rel)}</summary><pre>{esc(text)}</pre></details>')
    if not items:
        return ""
    return f'<details class="artifacts"><summary>submitted artifacts</summary>{"".join(items)}</details>'


def render_rollout(anchor: str, r: dict) -> str:
    rec, t = r["rec"], r["trace"]
    data = (rec.get("task") or {}).get("data") or {}
    calls_by_node = {c.get("node"): c for c in t.get("calls") or []}

    rewards = " ".join(
        f'<span class="badge {"ok" if (v or {}).get("score", 0) >= 1 else "fail"}">'
        f'{esc(k)} {(v or {}).get("score")}</span>'
        for k, v in (t.get("rewards") or {}).items()
    )
    status = " ".join(
        f'<span class="badge warn">{esc(s)}</span>'
        for s, cond in [("timeout", t.get("is_timeout")), ("incomplete", not t.get("is_completed"))]
        if cond
    )
    err_parts = ""
    for e in t.get("errors") or []:
        etype = e.get("type", "error") if isinstance(e, dict) else "error"
        emsg = e.get("message", "") if isinstance(e, dict) else str(e)
        status += f'<span class="badge fail">{esc(etype)}</span>'
        err_parts += (f'<details class="info"><summary>{esc(etype)}</summary>'
                      f'<pre>{esc(emsg)}</pre></details>')

    timing = t.get("timing") or {}
    agent_span = timing.get("agent") or {}
    dur = agent_span.get("end", 0) - agent_span.get("start", 0)
    model = ""
    if t.get("calls"):
        model = t["calls"][0].get("model") or ""

    info = t.get("info") or {}
    info_html = (f'<details class="info"><summary>grading info</summary>'
                 f'<pre>{esc(json.dumps(info, indent=2, default=str))}</pre></details>') if info else ""
    ref = data.get("reference_source")
    ref_html = (f'<details class="info"><summary>reference solution</summary>'
                f'<pre>{esc(ref)}</pre></details>') if ref else ""
    artifacts = render_artifacts(r["run_dir"] / "artifacts" / str(t.get("id")))

    nodes = "".join(render_message(n, calls_by_node.get(i))
                    for i, n in enumerate(t.get("nodes") or []))

    header = (
        f'<h2>{esc(data.get("id", rec.get("id", "?")))}'
        f'{"#" + str(r["trace_idx"]) if r["trace_idx"] else ""}</h2>'
        f'<div class="meta">{esc(rec.get("env", {}).get("id", ""))} · seed {esc(data.get("seed", "?"))}'
        f' · level {esc(data.get("level", "?"))} · {esc(model)}'
        f' · tokens {t.get("num_total_tokens", "?")}'
        f'{f" · agent {dur:.1f}s" if dur else ""}</div>'
        f'<div>{rewards} <span class="badge">{esc(t.get("stop_condition", ""))}</span> {status}</div>'
    )
    return f'<section class="rollout" id="{anchor}">{header}{err_parts}{info_html}{ref_html}{artifacts}{nodes}</section>'


def render(runs: list[tuple[str, list[dict]]]) -> str:
    """`runs` is (run_name, rollouts) pairs preserving order."""
    sidebar, sections = [], []
    idx = 0
    for run_name, rollouts in runs:
        sidebar.append(f'<div class="run">{esc(run_name)}</div>')
        for r in rollouts:
            anchor = f"r{idx}"
            idx += 1
            data = (r["rec"].get("task") or {}).get("data") or {}
            solved = any((v or {}).get("score", 0) >= 1
                         for v in (r["trace"].get("rewards") or {}).values())
            mark = "ok" if solved else "fail"
            sidebar.append(
                f'<a href="#{anchor}" onclick="show(\'{anchor}\');return false">'
                f'<span class="dot {mark}"></span>{esc(data.get("id", "?"))} '
                f'<span class="tok">{r["trace"].get("num_total_tokens", "?")}t</span></a>'
            )
            sections.append(render_rollout(anchor, r))

    return TEMPLATE.replace("__SIDEBAR__", "\n".join(sidebar)) \
                   .replace("__SECTIONS__", "\n".join(sections))


TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8"><title>transcripts</title>
<style>
body{margin:0;font:14px/1.5 system-ui,sans-serif;display:flex;background:#fafafa}
#side{width:280px;min-width:280px;height:100vh;overflow-y:auto;position:sticky;top:0;
  background:#1e1e2e;color:#cdd6f4;padding:8px 0;font-size:12px}
#side .run{padding:8px 14px 2px;font-weight:600;color:#89b4fa}
#side a{display:block;padding:3px 14px 3px 26px;color:inherit;text-decoration:none;white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis}
#side a:hover,#side a.sel{background:#313244}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:7px}
.dot.ok{background:#a6e3a1}.dot.fail{background:#f38ba8}
.tok{opacity:.55;float:right}
main{flex:1;padding:16px 24px;max-width:1000px}
.rollout{display:none}.rollout.on{display:block}
h2{margin:0 0 4px}.meta{color:#666;font-size:12px;margin-bottom:6px}
.badge{display:inline-block;padding:1px 8px;border-radius:10px;background:#e0e0e0;font-size:12px;margin:0 4px 8px 0}
.badge.ok{background:#a6e3a1}.badge.fail{background:#f38ba8}.badge.warn{background:#f9e2af}
.msg{margin:8px 0;padding:8px 12px;border-radius:8px;border:1px solid #ddd;background:#fff}
.msg .role{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:#888;margin-bottom:4px}
.msg.user{background:#eff6ff}.msg.assistant{background:#f0fdf4}.msg.tool{background:#fffbeb}
pre{white-space:pre-wrap;word-break:break-word;margin:4px 0;font:12px/1.45 ui-monospace,Consolas,monospace}
details{margin:4px 0}summary{cursor:pointer;color:#555;font-size:12px}
.reasoning summary,.artifacts summary,.info summary{color:#7c3aed}
.toolcall{border-left:3px solid #94a3b8;padding-left:8px;margin:6px 0}
.toolname{font:12px ui-monospace,monospace;font-weight:600}
.argname{font:11px ui-monospace,monospace;color:#64748b}
.arg{background:#f1f5f9;padding:4px 8px;border-radius:4px}
.msg .meta{margin-top:6px;border-top:1px dashed #ddd;padding-top:4px}
</style></head><body>
<nav id="side">__SIDEBAR__</nav>
<main>__SECTIONS__</main>
<script>
function show(id){
  document.querySelectorAll('.rollout').forEach(e=>e.classList.toggle('on',e.id===id));
  document.querySelectorAll('#side a').forEach(a=>a.classList.toggle('sel',a.hash==='#'+id));
  location.hash=id;
}
show(location.hash.slice(1)||document.querySelector('.rollout').id);
window.addEventListener('hashchange',()=>show(location.hash.slice(1)));
</script>
</body></html>
"""


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("path", nargs="?", default="outputs", type=Path)
    p.add_argument("-o", "--output", type=Path)
    p.add_argument("--open", action="store_true", help="open in browser after writing")
    args = p.parse_args()

    files = find_traces_files(args.path)
    if not files:
        print(f"no traces.jsonl found under {args.path}", file=sys.stderr)
        return 1

    runs = [(f.parent.name, load_rollouts(f)) for f in files]
    runs = [(n, rs) for n, rs in runs if rs]
    total = sum(len(rs) for _, rs in runs)
    if not total:
        print(f"no rollouts in {args.path}", file=sys.stderr)
        return 1

    out = args.output
    if out is None:
        base = args.path if args.path.is_dir() else args.path.parent
        out = base / "transcripts.html"
    out.write_text(render(runs), encoding="utf-8")
    print(f"wrote {out} ({total} rollouts, {len(runs)} runs)")
    if args.open:
        webbrowser.open(out.resolve().as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
