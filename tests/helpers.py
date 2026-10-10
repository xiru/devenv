"""Shared fixtures for the test suite.

Every check talks to the system only through `which` and `run`, so tests patch those two
functions in the module under test and describe the fake system as plain data.
"""

from __future__ import annotations

import contextlib
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from unittest import mock

from devenv_check import checks, smoke
from devenv_check.checks import ToolResult
from devenv_check.platform_info import PlatformInfo
from devenv_check.runner import CommandResult

LINUX = PlatformInfo("linux", "debian", "Ubuntu", "amd64")
WSL = PlatformInfo("linux", "debian", "Ubuntu (WSL)", "amd64", wsl=True)
MACOS = PlatformInfo("macos", "macos", "macOS 15", "arm64")
WINDOWS = PlatformInfo("windows", "windows", "Windows 11", "amd64")

FAMILIES = ["windows", "macos", "debian", "fedora", "arch", "suse", "linux"]


def platform_for(family: str, *, arch: str = "amd64", wsl: bool = False) -> PlatformInfo:
    system = family if family in ("windows", "macos") else "linux"
    return PlatformInfo(system, family, family, arch, wsl)


def ok(stdout: str = "", stderr: str = "") -> CommandResult:
    return CommandResult(True, stdout, stderr, 0)


def fail(stderr: str = "", stdout: str = "", returncode: int = 1) -> CommandResult:
    return CommandResult(False, stdout, stderr, returncode)


def tool_name(arg: str) -> str:
    """'C:\\bin\\php.exe' or '/usr/bin/php' -> 'php'."""
    return Path(arg.replace("\\", "/")).stem if arg.lower().endswith(".exe") else Path(arg.replace("\\", "/")).name


@contextlib.contextmanager
def fake_system(outputs: dict, module=checks, *, where: str = "/usr/bin"):
    """Patch `which` and `run` in `module`: each tool in `outputs` is installed in `where`.

    A value is the CommandResult (or stdout) of any command that tool runs, or a callable taking
    the command line and returning one. Yields the list of executed commands for assertions.
    """
    calls: list[list[str]] = []

    def which(name):
        return f"{where}/{tool_name(name)}" if tool_name(name) in outputs else None

    def run(args, **kwargs):
        calls.append(list(args))
        value = outputs.get(tool_name(args[0]), fail(f"{args[0]}: not faked"))
        value = value(list(args)) if callable(value) else value
        return ok(value) if isinstance(value, str) else value

    with mock.patch.object(module, "which", side_effect=which), mock.patch.object(module, "run", side_effect=run):
        yield calls


def tool(name: str, path: str | None = None, *, status=checks.Status.OK, **kwargs) -> ToolResult:
    """A ToolResult as produced by a check; `path` defaults to /usr/bin/<name> for usable tools."""
    if path is None and status is not checks.Status.MISSING:
        path = f"/usr/bin/{name.split()[0]}"
    return ToolResult(name, status, path=path, **kwargs)


@dataclass
class Call:
    args: list[str]
    cwd: Path | None
    env: dict[str, str]
    timeout: float


@dataclass
class SmokeRun:
    results: list[ToolResult]
    calls: list[Call]
    written: dict[str, str] = field(default_factory=dict)  # file name -> content

    @property
    def result(self) -> ToolResult:
        (only,) = self.results
        return only

    @property
    def commands(self) -> list[list[str]]:
        return [call.args for call in self.calls]


def run_smoke(key: str, tools: list[ToolResult], output="", platform: PlatformInfo = LINUX) -> SmokeRun:
    """Run a hello world test with a fake `run`.

    `output` is the stdout of every command, or a callable(args) returning stdout or a CommandResult.
    """
    calls: list[Call] = []
    written: dict[str, str] = {}
    real_write = smoke._write

    def fake_run(args, timeout=30, *, cwd=None, env=None):
        calls.append(Call(list(args), Path(cwd) if cwd else None, env or {}, timeout))
        value = output(args) if callable(output) else output
        return value if isinstance(value, CommandResult) else ok(value)

    def spy_write(path, text):
        written[path.name] = text
        return real_write(path, text)

    with mock.patch.object(smoke, "run", side_effect=fake_run), mock.patch.object(smoke, "_write", side_effect=spy_write):
        results = smoke.run_smoke(key, platform, tools)
    return SmokeRun(results, calls, written)


class TempDirMixin:
    """Gives each test a fresh temporary directory as `self.tmp` (a Path)."""

    def setUp(self):
        super().setUp()
        handle = tempfile.TemporaryDirectory()
        self.addCleanup(handle.cleanup)
        self.tmp = Path(handle.name)
