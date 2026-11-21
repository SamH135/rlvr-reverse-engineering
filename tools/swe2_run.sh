#!/bin/sh
# SWE-2 teacher run: proxy + vf-run, serviced by swe2_worker workers.
# Usage: UV="py -m uv" FAM=formats LEVEL=1 N=5 C=2 OFFSET=700 sh tools/swe2_run.sh
# Workers: py tools/swe2_worker.py --queue tmp_swe2/q$PORT claim --wait 3600
UV=${UV:-uv}
# Each worker session owns one run: no shared queues. PORT unset -> pick a free
# port so concurrent sessions can't collide; the queue derives from it.
if [ -z "$PORT" ]; then
  PORT=$($UV run python -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1]);s.close()')
fi
Q=${Q:-tmp_swe2/q$PORT}
mkdir -p "$Q"
rm -f "$Q/STOP"
echo "[swe2] run owns port=$PORT queue=$Q -> service with: py tools/swe2_worker.py --queue $Q claim --wait 3600"
$UV run python tools/swe2_proxy.py --queue "$Q" --port "$PORT" &
PROXY=$!
trap 'kill $PROXY 2>/dev/null' EXIT
sleep 1
$UV run vf-run "${FAM:-formats}" -n "${N:-5}" -r 1 -c "${C:-2}" -m "${MODEL:-swe2}" \
  --client.base-url "http://127.0.0.1:$PORT" --client.api-key-var SWE2_DUMMY \
  --env.agent.runtime.type docker --env.taskset.level "${LEVEL:-1}" \
  --env.taskset.seed-offset "${OFFSET:-700}" --env.agent.max-turns "${TURNS:-30}"
STATUS=$?
touch "$Q/STOP"
exit $STATUS
