"""SWE-2 OpenAI-compatible relay: turns POST /v1/chat/completions into queue files
that a human or subagent worker answers with tools/swe2_worker.py.

    py tools/swe2_proxy.py --queue tmp_swe2/q8399 --port 8399

Point vf-run at it like any provider:

    py -m uv run vf-run formats -n 5 -c 2 -m swe2 \
      --client.base-url http://127.0.0.1:8399 --client.api-key-var SWE2_DUMMY \
      --env.agent.runtime.type docker --env.taskset.level 1 \
      --env.taskset.seed-offset 700 --env.agent.max-turns 30

Queue layout: pending/ (unclaimed), claimed/ (worker has it), responses/
(worker's assistant message). A request's key is sha256(model+tools+messages),
so client retries collapse onto the same pending item — a stalled turn just
re-asks and gets the response whenever it appears. Corollary: byte-identical
requests always get identical responses, so -r >1 rollouts of one seed would
clone; keep -r 1.

The agent's httpx read timeout is 600s/request, so we emit `: keep-alive`
comment lines every HEARTBEAT_S seconds to hold the stream open while queued.
Workers must still answer well inside ~25min total or the client's retries
exhaust and the episode dies as a provider error (scored separately, see
baselines/AGENTS.md).
"""

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HEARTBEAT_S = 25
# Unserviced requests fail after this long so abandoned runs don't hang forever.
TTL_S = int(os.environ.get("SWE2_TTL_S", "1800"))
QUEUE: Path = Path("tmp_swe2/q")


def key_for(body: dict) -> str:
    subset = {k: body.get(k) for k in ("model", "tools", "messages", "tool_choice")}
    return hashlib.sha256(
        json.dumps(subset, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]


def resp_path(key: str) -> Path:
    return QUEUE / "responses" / f"{key}.json"


def sse(payload: dict) -> bytes:
    return b"data: " + json.dumps(payload).encode() + b"\n\n"


def chunk(cid: str, model: str, delta: dict, finish: str | None = None) -> dict:
    return {
        "id": cid,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }


def to_message(raw: dict) -> dict:
    """Worker response file -> OpenAI assistant message."""
    msg = {"role": "assistant", "content": raw.get("content") or ""}
    calls = []
    for i, tc in enumerate(raw.get("tool_calls") or []):
        args = tc.get("arguments", {})
        calls.append(
            {
                "id": f"call_{i:02d}_{uuid.uuid4().hex[:20]}",
                "type": "function",
                "function": {
                    "name": tc["name"],
                    "arguments": args if isinstance(args, str) else json.dumps(args),
                },
            }
        )
    if calls:
        msg["tool_calls"] = calls
    return msg


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("[proxy] " + fmt % args + "\n")

    def _json(self, code: int, obj: dict):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.endswith("/models"):
            self._json(
                200,
                {
                    "object": "list",
                    "data": [
                        {
                            "id": "swe2",
                            "object": "model",
                            "created": 0,
                            "owned_by": "swe2",
                        }
                    ],
                },
            )
        elif self.path == "/status":
            counts = {
                d: len(list((QUEUE / d).glob("*.json"))) if (QUEUE / d).exists() else 0
                for d in ("pending", "claimed", "responses")
            }
            counts["stop"] = (QUEUE / "STOP").exists()
            self._json(200, counts)
        else:
            self._json(200, {"ok": True})

    def do_POST(self):
        if not self.path.endswith("/chat/completions"):
            self._json(404, {"error": {"message": f"no route {self.path}"}})
            return
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        key = key_for(body)
        model = body.get("model", "swe2")
        stream = bool(body.get("stream"))

        # First writer wins; retries see the file exists and just wait on it.
        pending = QUEUE / "pending" / f"{key}.json"
        claimed = QUEUE / "claimed" / f"{key}.json"
        if not resp_path(key).exists() and not claimed.exists():
            try:
                fd = os.open(pending, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w", encoding="utf8") as f:
                    json.dump({"key": key, "ts": time.time(), "request": body}, f)
            except FileExistsError:
                pass

        if not stream:
            msg = self._await_response(key, model, stream=False)
            if msg is None:
                return  # client went away
            self._json(
                200,
                {
                    "id": f"chatcmpl-{key}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "message": msg,
                            "finish_reason": "tool_calls"
                            if msg.get("tool_calls")
                            else "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                    },
                },
            )
            return

        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("cache-control", "no-cache")
        # No length and no chunked encoding: the body is delimited by closing
        # the connection, so intermediaries see end-of-stream at [DONE].
        self.send_header("connection", "close")
        self.end_headers()
        self.close_connection = True
        msg = self._await_response(key, model, stream=True)
        if msg is None:
            return
        cid = f"chatcmpl-{key}"
        try:
            self.wfile.write(sse(chunk(cid, model, {"role": "assistant"})))
            if msg.get("content"):
                self.wfile.write(
                    sse(chunk(cid, model, {"content": msg["content"]}))
                )
            for i, tc in enumerate(msg.get("tool_calls") or []):
                self.wfile.write(
                    sse(
                        chunk(
                            cid,
                            model,
                            {
                                "tool_calls": [
                                    {
                                        "index": i,
                                        "id": tc["id"],
                                        "type": "function",
                                        "function": tc["function"],
                                    }
                                ]
                            },
                        )
                    )
                )
            finish = "tool_calls" if msg.get("tool_calls") else "stop"
            self.wfile.write(sse(chunk(cid, model, {}, finish=finish)))
            self.wfile.write(
                sse(
                    {
                        "id": cid,
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": model,
                        "choices": [],
                        "usage": {
                            "prompt_tokens": 0,
                            "completion_tokens": 0,
                            "total_tokens": 0,
                        },
                    }
                )
            )
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _await_response(self, key: str, model: str, stream: bool) -> dict | None:
        """Poll for the worker's response file; heartbeat to hold the stream open.
        Returns the assistant message, or None if the client disconnected or the
        request sat unserviced past TTL_S (an abandoned run fails instead of
        hanging forever — heartbeats otherwise defeat the agent's read timeout)."""
        rp = resp_path(key)
        deadline = time.time() + TTL_S
        while True:
            if time.time() > deadline:
                return None
            if rp.exists():
                try:
                    raw = json.loads(rp.read_text(encoding="utf8"))
                except json.JSONDecodeError:
                    time.sleep(0.2)  # worker is mid-write
                    continue
                return to_message(raw)
            if stream:
                try:
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    return None
            else:
                # Non-stream clients get no heartbeat; bound the wait anyway.
                time.sleep(0.5)
            time.sleep(HEARTBEAT_S if stream else 0.5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", default="tmp_swe2/q8399")
    ap.add_argument("--port", type=int, default=8399)
    a = ap.parse_args()
    global QUEUE
    QUEUE = Path(a.queue)
    for d in ("pending", "claimed", "responses"):
        (QUEUE / d).mkdir(parents=True, exist_ok=True)
    (QUEUE / "STOP").unlink(missing_ok=True)
    print(f"[proxy] queue={QUEUE} http://127.0.0.1:{a.port}/v1", flush=True)
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
