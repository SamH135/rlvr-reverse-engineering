import types

import pytest

GRADER_ROOT = "/grader"


class FakeRuntime:
    """Scripted stand-in for vf.Runtime, dispatching on argv like grade_function."""

    def __init__(
        self,
        *,
        scope_exit: int = 0,
        scope_stdout: str = '{"scope_ok": true}',
        run_exit: int = 0,
        result: bytes | None = b"{}",
        result_exists: bool = True,
        result_size: int | None = None,
    ):
        self.scope_exit = scope_exit
        self.scope_stdout = scope_stdout
        self.run_exit = run_exit
        self.result = result
        self.result_exists = result_exists
        self.result_size = result_size
        self.calls: list[list[str]] = []
        self.runner_invoked = False

    async def run(self, argv: list[str], env: dict[str, str]) -> types.SimpleNamespace:
        argv = list(argv)
        self.calls.append(argv)
        if argv[:3] == ["python3", f"{GRADER_ROOT}/runner.py", "--scope"]:
            return types.SimpleNamespace(
                exit_code=self.scope_exit, stdout=self.scope_stdout, stderr=""
            )
        if argv[:2] == ["sh", "-c"] and "--run" in argv[2]:
            self.runner_invoked = True
            return types.SimpleNamespace(
                exit_code=self.run_exit, stdout="", stderr=""
            )
        if argv[:2] == ["test", "-f"]:
            return types.SimpleNamespace(
                exit_code=0 if self.result_exists else 1, stdout="", stderr=""
            )
        if argv[:2] == ["sh", "-c"] and argv[2].startswith("wc -c"):
            size = (
                self.result_size
                if self.result_size is not None
                else len(self.result or b"")
            )
            return types.SimpleNamespace(exit_code=0, stdout=str(size), stderr="")
        raise AssertionError(f"unexpected argv: {argv}")

    async def read(self, path: str, max_bytes: int = 1_000_000) -> bytes:
        return (self.result or b"")[:max_bytes]


@pytest.fixture
def fake_runtime():
    return FakeRuntime
