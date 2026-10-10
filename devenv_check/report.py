"""Text and JSON rendering of check results."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict

from .checks import EnvResult, Status, ToolResult
from .install_hints import DOCS, hint_for, manager_label, prerequisite_notes
from .platform_info import PlatformInfo


def enable_windows_ansi() -> bool:
    """Turn on VT escape processing for the Windows console; True on success."""
    if os.name != "nt":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except (AttributeError, OSError):
        return False


class Style:
    def __init__(self, color: bool, unicode: bool):
        self.color = color
        if unicode:
            self.ok, self.warn, self.missing, self.optional, self.skipped = "✔", "!", "✘", "○", "·"
        else:
            self.ok, self.warn, self.missing, self.optional, self.skipped = "+", "!", "x", "-", "."

    def paint(self, text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.color else text

    def status(self, text: str, status: Status) -> str:
        codes = {Status.OK: "32", Status.WARN: "33", Status.MISSING: "31", Status.SKIPPED: "2"}
        return self.paint(text, codes[status])

    def dim(self, text: str) -> str:
        return self.paint(text, "2")

    def bold(self, text: str) -> str:
        return self.paint(text, "1")


def make_style(no_color: bool) -> Style:
    stream = sys.stdout
    color = not no_color and "NO_COLOR" not in os.environ and stream.isatty() and enable_windows_ansi()
    unicode = (stream.encoding or "").lower().replace("-", "").startswith("utf")
    return Style(color, unicode)


ENV_LABEL = {Status.OK: "READY", Status.WARN: "PARTIAL", Status.MISSING: "MISSING"}


def _tool_symbol(tool: ToolResult, style: Style) -> str:
    if tool.status is Status.OK:
        return style.status(style.ok, Status.OK)
    if tool.status is Status.SKIPPED:
        return style.status(style.skipped, Status.SKIPPED)
    if tool.status is Status.MISSING and not tool.required:
        return style.status(style.optional, Status.WARN)
    return style.status(style.missing if tool.status is Status.MISSING else style.warn, tool.status)


def _hello_tests(env: EnvResult) -> list[ToolResult]:
    return [t for t in env.tools if t.kind == "hello"]


def hello_summary(env: EnvResult) -> tuple[int, int, int]:
    """(passed, failed, skipped) hello world tests of an environment."""
    tests = _hello_tests(env)
    passed = sum(t.status is Status.OK for t in tests)
    skipped = sum(t.status is Status.SKIPPED for t in tests)
    return passed, len(tests) - passed - skipped, skipped


def _hello_label(env: EnvResult, style: Style) -> str:
    passed, failed, skipped = hello_summary(env)
    if failed:
        return style.status(f"hello world: {failed} failed", Status.MISSING)
    if passed:
        extra = f", {skipped} skipped" if skipped else ""
        return style.status(f"hello world: {passed}/{passed + skipped} passed{extra}", Status.OK if not skipped else Status.WARN)
    return style.dim("hello world: skipped")


def _hint_groups(env: EnvResult) -> list[tuple[str, list[ToolResult]]]:
    """Distinct hint keys for the env's non-OK tools, in order of appearance."""
    groups: dict[str, list[ToolResult]] = {}
    for tool in env.tools:
        if tool.status not in (Status.OK, Status.SKIPPED) and tool.hint:
            groups.setdefault(tool.hint, []).append(tool)
    return list(groups.items())


def _failed_hello(env: EnvResult) -> list[ToolResult]:
    return [t for t in _hello_tests(env) if t.status is Status.MISSING and not t.hint]


def _fix_tools(env: EnvResult) -> list[ToolResult]:
    """Non-OK tools that carry their own fix commands (e.g. VS Code extensions)."""
    return [t for t in env.tools if t.fix and t.status not in (Status.OK, Status.SKIPPED)]


def _tool_row(tool: ToolResult, style: Style, verbose: bool) -> list[str]:
    name = tool.name + ("" if tool.required or tool.kind == "hello" else " (optional)")
    version = tool.version or "-"
    info = tool.detail
    if verbose and tool.path and tool.path not in info:
        info = f"{info}  [{tool.path}]" if info else tool.path
    rows = [f"    {_tool_symbol(tool, style)} {name:<32} {version:<14} {style.dim(info)}".rstrip()]
    if verbose and tool.output and tool.status is Status.MISSING:
        rows += [style.dim(f"        | {line}") for line in tool.output.splitlines()]
    return rows


def render_text(platform: PlatformInfo, results: list[EnvResult], style: Style, *, verbose: bool, hints: bool) -> str:
    out: list[str] = []
    py = ".".join(map(str, sys.version_info[:3]))
    deep = any(_hello_tests(env) for env in results)
    out.append(style.bold("Development environment check" + (" (deep: hello world build & run)" if deep else "")))
    out.append(style.dim(f"{platform.name} · {platform.arch} · Python {py}"))
    out.append("")

    for env in results:
        label = ENV_LABEL[env.status]
        symbol = {Status.OK: style.ok, Status.WARN: style.warn, Status.MISSING: style.missing}[env.status]
        header = f"{style.status(symbol, env.status)} {style.bold(f'{env.title:<38}')} {style.status(f'{label:<8}', env.status)}"
        if deep and _hello_tests(env):
            header += f" {_hello_label(env, style)}"
        out.append(header.rstrip())
        tests_started = False
        for tool in env.tools:
            if tool.kind == "hello" and not tests_started:
                out.append(style.dim("    -- hello world: build & run --"))
                tests_started = True
            out += _tool_row(tool, style, verbose)
        out.append("")

    counts = {status: sum(1 for env in results if env.status is status) for status in Status}
    out.append(style.bold(
        f"Summary: {counts[Status.OK]} of {len(results)} environments ready, "
        f"{counts[Status.WARN]} partial, {counts[Status.MISSING]} missing."
    ))
    if deep:
        tested = [env for env in results if _hello_tests(env)]
        built = sum(1 for env in tested if hello_summary(env)[0] and hello_summary(env)[1:] == (0, 0))
        out.append(style.bold(f"Hello world: {built} of {len(tested)} environments built and ran every program."))

    pending = [(env, _hint_groups(env), _failed_hello(env), _fix_tools(env)) for env in results]
    pending = [item for item in pending if item[1] or item[2] or item[3]]
    if hints and pending:
        out.append("")
        out.append(style.bold(f"How to fix ({platform.name}, using {manager_label(platform)}):"))
        for note in prerequisite_notes(platform):
            out.append(style.status(f"  {style.warn} {note}", Status.WARN))
        for env, groups, failures, fixable in pending:
            out.append("")
            out.append(f"  {style.bold(env.title)}")
            for key, tools in groups:
                required = any(t.required for t in tools)
                names = ", ".join(t.name for t in tools) + ("" if required else " (optional)")
                out.append(f"    {style.status(names, Status.MISSING if required else Status.WARN)}")
                for line in hint_for(key, platform):
                    out.append(f"      {style.dim(line) if line.startswith('#') else line}")
                if key in DOCS:
                    out.append(style.dim(f"      docs: {DOCS[key]}"))
            for tool in failures:
                out.append(f"    {style.status(tool.name, Status.MISSING)}")
                out.append(f"      {tool.detail}")
                out.append(style.dim("      the tools are installed but could not build/run it; re-run with -v for the full log"))
            for tool in fixable:
                label = tool.name + ("" if tool.required else " (optional)")
                out.append(f"    {style.status(label, Status.MISSING if tool.required and tool.status is Status.MISSING else Status.WARN)}")
                for line in tool.fix:
                    out.append(f"      {style.dim(line) if line.startswith('#') else line}")
        out.append("")
        out.append(style.dim("Open a new terminal after installing so PATH changes take effect, then re-run the check."))

    return "\n".join(out)


def render_json(platform: PlatformInfo, results: list[EnvResult]) -> str:
    environments = []
    for env in results:
        data = env.to_dict()
        if _hello_tests(env):
            passed, failed, skipped = hello_summary(env)
            data["hello_world"] = {"passed": passed, "failed": failed, "skipped": skipped}
        data["fix"] = [
            {"hint": key, "tools": [t.name for t in tools], "commands": hint_for(key, platform), "docs": DOCS.get(key)}
            for key, tools in _hint_groups(env)
        ]
        environments.append(data)
    payload = {
        "platform": asdict(platform),
        "python": ".".join(map(str, sys.version_info[:3])),
        "environments": environments,
        "notes": prerequisite_notes(platform),
    }
    return json.dumps(payload, indent=2)
