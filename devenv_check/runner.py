"""Thin helpers around subprocess / PATH lookup and version parsing."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass


@dataclass
class CommandResult:
    ok: bool
    stdout: str
    stderr: str
    returncode: int | None

    @property
    def output(self) -> str:
        """stdout followed by stderr (many tools print versions on stderr)."""
        return "\n".join(part for part in (self.stdout, self.stderr) if part)


def which(name: str) -> str | None:
    return shutil.which(name)


def run(
    args: list[str],
    timeout: float = 30,
    *,
    cwd: str | os.PathLike | None = None,
    env: dict[str, str] | None = None,
) -> CommandResult:
    """Run a command without a shell, never raising.

    Callers pass the absolute path returned by `which()` as args[0], so that
    Windows wrappers such as npm.cmd are resolved through PATHEXT. `env` holds
    extra variables layered on top of the current environment.
    """
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=timeout,
            cwd=cwd,
            env={**os.environ, **env} if env else None,
        )
    except subprocess.TimeoutExpired:
        return CommandResult(False, "", f"timed out after {timeout:g}s", None)
    except OSError as exc:
        return CommandResult(False, "", str(exc), None)
    # Only trailing whitespace is stripped: leading blank lines are meaningful for
    # multi-value output such as `go env GOBIN GOPATH` with an empty GOBIN.
    return CommandResult(proc.returncode == 0, proc.stdout.rstrip(), proc.stderr.strip(), proc.returncode)


GENERIC_VERSION = r"(\d+)\.(\d+)(?:\.(\d+))?"


def parse_version(text: str, pattern: str = GENERIC_VERSION) -> tuple[int, ...] | None:
    """Return the first version matched by `pattern` as a tuple of ints."""
    match = re.search(pattern, text or "")
    if not match:
        return None
    return tuple(int(group) for group in match.groups() if group is not None)


def format_version(version: tuple[int, ...] | None) -> str | None:
    return ".".join(map(str, version)) if version else None


def first_line(text: str) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""
