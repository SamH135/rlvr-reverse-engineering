# RLVR Coding Environment

A standalone Verifiers v1 taskset package for generated Python bug-fix tasks.

Run validation or a rollout locally with Docker:
`uv run vf-validate bugfix --runtime.type docker` or
`uv run vf-run bugfix --env.agent.runtime.type docker`.

Build the keygen checker image locally before validating that taskset:
`docker build -f docker/keygen.Dockerfile -t rlvr-keygen:0.1 .`