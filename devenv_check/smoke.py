"""--deep: build and run a hello world program for each environment.

Every test works in its own temporary directory, which is removed afterwards.
A test whose toolchain is missing is reported as SKIPPED (the installation
check already explains what is missing); a test that runs and fails is
reported as MISSING, because the environment cannot actually build software.
"""

from __future__ import annotations

import os
import re
import tempfile
import uuid
from collections.abc import Callable
from pathlib import Path

from .checks import Status, ToolResult
from .platform_info import PlatformInfo
from .runner import CommandResult, first_line, parse_version, run

EXE = ".exe" if os.name == "nt" else ""

# Kube contexts that belong to a disposable local cluster. Anything else is only
# validated with a server-side dry run, so the checker never creates objects in
# a shared or production cluster.
LOCAL_KUBE_CONTEXT = re.compile(
    r"^(docker-desktop|docker-for-desktop|minikube|rancher-desktop|orbstack|colima|microk8s|kind-.+|k3d-.+)$"
)

Step = tuple[list[str], float]  # (command, timeout in seconds)


def _find(tools: list[ToolResult], name: str) -> ToolResult | None:
    return next((t for t in tools if t.name == name), None)


def _usable(tool: ToolResult | None) -> bool:
    return tool is not None and tool.status in (Status.OK, Status.WARN) and bool(tool.path)


def _skipped(name: str, reason: str) -> ToolResult:
    return ToolResult(name, Status.SKIPPED, detail=f"skipped: {reason}", kind="hello")


def _error_line(result: CommandResult) -> str:
    """The most informative line of a failed command, kept short."""
    lines = [line.strip() for line in result.output.splitlines() if line.strip()]
    line = next((l for l in lines if re.search(r"\berror\b", l, re.IGNORECASE)), lines[0] if lines else "")
    line = line or f"exit code {result.returncode}"
    return line if len(line) <= 160 else line[:157] + "..."


def _tail(text: str, count: int = 20) -> str:
    return "\n".join(text.strip().splitlines()[-count:])


def build_and_run(
    name: str,
    steps: list[Step],
    expected: str,
    workdir: Path,
    *,
    env: dict[str, str] | None = None,
    detail: str = "built and ran",
) -> ToolResult:
    """Run `steps` in order; the last one must print `expected`."""
    log: list[str] = []
    result = CommandResult(False, "", "no steps", None)
    for index, (args, timeout) in enumerate(steps):
        result = run(args, timeout=timeout, cwd=workdir, env=env)
        log.append(f"$ {' '.join(args)}\n{result.output}".rstrip())
        if not result.ok:
            stage = "run" if index == len(steps) - 1 else "build"
            return ToolResult(name, Status.MISSING, detail=f"{stage} failed: {_error_line(result)}",
                              kind="hello", output=_tail("\n".join(log)))
    if expected not in result.stdout:
        return ToolResult(name, Status.MISSING, detail=f"unexpected output: {first_line(result.output)!r}",
                          kind="hello", output=_tail("\n".join(log)))
    return ToolResult(name, Status.OK, detail=detail, kind="hello", output=_tail("\n".join(log)))


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    # newline="\n": keep LF on Windows too (bash rejects CRLF); .bat content carries its own \r\n.
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


# --------------------------------------------------------------------------- Git


def smoke_git(p: PlatformInfo, tools: list[ToolResult], work: Path) -> list[ToolResult]:
    git = _find(tools, "git")
    if not _usable(git):
        return [_skipped("hello: Git repository", "git not available")]
    _write(work / "hello.txt", "hello from git\n")
    # Isolate the test from the user's global config: no hooks, no signing prompts, fixed identity.
    isolated = [git.path, "-c", "core.hooksPath=.no-hooks", "-c", "commit.gpgsign=false",
                "-c", "user.name=devenv-check", "-c", "user.email=devenv-check@example.invalid"]
    return [build_and_run(
        "hello: Git repository",
        [(isolated + ["init", "-q"], 30), (isolated + ["add", "hello.txt"], 30),
         (isolated + ["commit", "-q", "-m", "hello from git"], 30), (isolated + ["log", "-1", "--format=%s"], 30)],
        "hello from git", work, detail="init, add, commit and log in a temporary repository",
    )]


# --------------------------------------------------------------------------- Bash scripting

BASH_SCRIPT = """#!/usr/bin/env bash
set -euo pipefail

greet() {
    local -a words=("hello" "from" "$1")
    echo "${words[*]}"
}

greet bash
"""


def smoke_bash(p: PlatformInfo, tools: list[ToolResult], work: Path) -> list[ToolResult]:
    bash, shellcheck = _find(tools, "bash"), _find(tools, "shellcheck (linter)")
    if not _usable(bash):
        return [_skipped("hello: Bash script", "bash not available")]
    _write(work / "hello.sh", BASH_SCRIPT)
    steps: list[Step] = []
    detail = f"ran with {bash.provider or 'bash'}"
    if _usable(shellcheck):
        steps.append(([shellcheck.path, "hello.sh"], 60))
        detail = "passed shellcheck, " + detail
    # A relative path works for Git Bash and for WSL's bash.exe (which maps the Windows cwd to /mnt/...).
    steps.append(([bash.path, "hello.sh"], 60))
    return [build_and_run("hello: Bash script", steps, "hello from bash", work, detail=detail)]


# --------------------------------------------------------------------------- Java / Kotlin + Gradle

JAVA_SOURCE = 'public class Hello {{ public static void main(String[] args) {{ System.out.println("hello from {who}"); }} }}\n'


def smoke_java(p: PlatformInfo, tools: list[ToolResult], work: Path) -> list[ToolResult]:
    java, javac, gradle, kotlinc = (_find(tools, name) for name in ("java", "javac (JDK)", "gradle", "kotlinc"))
    results = []

    if _usable(java) and _usable(javac):
        d = work / "javac"
        _write(d / "Hello.java", JAVA_SOURCE.format(who="Java"))
        results.append(build_and_run(
            "hello: Java (javac)",
            [([javac.path, "Hello.java"], 180), ([java.path, "-cp", ".", "Hello"], 60)],
            "hello from Java", d,
        ))
    else:
        results.append(_skipped("hello: Java (javac)", "JDK not available"))

    if _usable(gradle) and _usable(java):
        d = work / "gradle"
        _write(d / "settings.gradle", "rootProject.name = 'hello'\n")
        _write(d / "build.gradle", "plugins { id 'application' }\napplication { mainClass = 'Hello' }\n")
        _write(d / "src" / "main" / "java" / "Hello.java", JAVA_SOURCE.format(who="Gradle"))
        # --offline: the project has no dependencies; --no-daemon: leave no JVM running afterwards.
        results.append(build_and_run(
            "hello: Gradle project",
            [([gradle.path, "run", "--offline", "--no-daemon", "--quiet", "--console=plain"], 600)],
            "hello from Gradle", d, detail="gradle run succeeded",
        ))
    else:
        results.append(_skipped("hello: Gradle project", "gradle or java not available"))

    if _usable(kotlinc) and _usable(java):
        d = work / "kotlin"
        _write(d / "hello.kt", 'fun main() {\n    val who = "Kotlin"\n    println("hello from $who")\n}\n')
        results.append(build_and_run(
            "hello: Kotlin",
            [([kotlinc.path, "hello.kt", "-include-runtime", "-d", "hello.jar"], 600),
             ([java.path, "-jar", "hello.jar"], 60)],
            "hello from Kotlin", d, detail="kotlinc to a runnable jar, ran with java -jar",
        ))
    else:
        results.append(_skipped("hello: Kotlin", "kotlinc or java not available"))
    return results


# --------------------------------------------------------------------------- Python


def smoke_python(p: PlatformInfo, tools: list[ToolResult], work: Path) -> list[ToolResult]:
    python, venv = _find(tools, "python"), _find(tools, "venv (virtual environments)")
    if not _usable(python) or venv is None or venv.status is not Status.OK:
        return [_skipped("hello: Python (venv)", "python with a working venv not available")]
    _write(work / "hello.py", 'import sys\n\nwho = "Python"\nprint(f"hello from {who} {sys.version_info.major}")\n')
    venv_python = work / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    # No network: pip is only asked for its version inside the fresh environment.
    return [build_and_run(
        "hello: Python (venv)",
        [([python.path, "-m", "venv", ".venv"], 180),
         ([str(venv_python), "-m", "pip", "--version"], 60),
         ([str(venv_python), "hello.py"], 30)],
        "hello from Python 3", work, detail="created a venv, ran pip and the script inside it",
    )]


# --------------------------------------------------------------------------- Go


def smoke_go(p: PlatformInfo, tools: list[ToolResult], work: Path) -> list[ToolResult]:
    go = _find(tools, "go")
    if not _usable(go):
        return [_skipped("hello: Go", "go not available")]
    _write(work / "go.mod", "module example.com/hello\n\ngo 1.21\n")
    _write(work / "main.go", 'package main\n\nimport "fmt"\n\nfunc main() { fmt.Println("hello from Go") }\n')
    binary = work / f"hello{EXE}"
    return [build_and_run(
        "hello: Go",
        [([go.path, "build", "-o", binary.name, "."], 300), ([str(binary)], 30)],
        "hello from Go", work,
        env={"GOTOOLCHAIN": "local"},  # never download a different toolchain during the check
    )]


# --------------------------------------------------------------------------- JavaScript / TypeScript


def smoke_node(p: PlatformInfo, tools: list[ToolResult], work: Path) -> list[ToolResult]:
    node = _find(tools, "node")
    if not _usable(node):
        return [_skipped("hello: JavaScript", "node not available"), _skipped("hello: TypeScript", "node not available")]

    _write(work / "hello.js", 'console.log("hello from JavaScript");\n')
    _write(work / "hello.ts", 'const message: string = "hello from TypeScript";\nconsole.log(message);\n')
    results = [build_and_run("hello: JavaScript", [([node.path, "hello.js"], 60)], "hello from JavaScript", work,
                             detail="ran with node")]

    version = parse_version(node.version or "") or ()
    if version >= (23, 6) or (22, 18) <= version < (23,):
        steps, detail = [([node.path, "hello.ts"], 60)], "ran with Node.js built-in type stripping"
    elif version >= (22, 6):
        steps = [([node.path, "--experimental-strip-types", "hello.ts"], 60)]
        detail = "ran with Node.js --experimental-strip-types"
    else:
        results.append(_skipped("hello: TypeScript", "this Node.js cannot run .ts files (needs 22.6+); "
                                "projects compile with their own local TypeScript"))
        return results
    results.append(build_and_run("hello: TypeScript", steps, "hello from TypeScript", work, detail=detail))
    return results


# --------------------------------------------------------------------------- C / C++

C_SOURCE = '#include <stdio.h>\n\nint main(void) {\n    printf("hello from C\\n");\n    return 0;\n}\n'
CPP_SOURCE = '#include <iostream>\n\nint main() {\n    std::cout << "hello from C++" << std::endl;\n    return 0;\n}\n'


def _vcvars_step(p: PlatformInfo, compiler: ToolResult, command: str, workdir: Path) -> list[str]:
    """Run `command` after loading the Visual Studio environment (cl.exe is not on PATH).

    A batch file keeps the quoting of the vcvars path under our control.
    """
    vcvars = Path(compiler.path, "VC", "Auxiliary", "Build",
                  "vcvarsarm64.bat" if p.arch == "arm64" else "vcvars64.bat")
    script = _write(workdir / "build.bat", f'@echo off\r\ncall "{vcvars}" >nul || exit /b 1\r\n{command}\r\n')
    return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(script)]


def _compile_step(p: PlatformInfo, compiler: ToolResult, source: str, workdir: Path) -> list[str]:
    if compiler.provider == "MSVC":
        return _vcvars_step(p, compiler, f"cl /nologo /EHsc {source} /Fe:hello.exe", workdir)
    if compiler.provider == "cl":
        return [compiler.path, "/nologo", "/EHsc", source, "/Fe:hello.exe"]
    return [compiler.path, source, "-o", f"hello{EXE}"]


def smoke_cpp(p: PlatformInfo, tools: list[ToolResult], work: Path) -> list[ToolResult]:
    results = []
    for label, tool_name, filename, source, expected in (
        ("hello: C", "C compiler", "hello.c", C_SOURCE, "hello from C"),
        ("hello: C++", "C++ compiler", "hello.cpp", CPP_SOURCE, "hello from C++"),
    ):
        compiler = _find(tools, tool_name)
        if not _usable(compiler):
            results.append(_skipped(label, f"no {tool_name.lower()}"))
            continue
        d = work / filename.replace(".", "_")
        _write(d / filename, source)
        results.append(build_and_run(
            label,
            [(_compile_step(p, compiler, filename, d), 300), ([str(d / f"hello{EXE}")], 30)],
            expected, d,
            detail=f"compiled with {compiler.provider}",
        ))
    results.append(_smoke_make(p, tools, work / "make"))
    return results


# A tab starts every recipe line; the quotes keep a compiler path with spaces in one piece.
MAKEFILE = 'hello{exe}: hello.c\n\t"$(CC)" hello.c -o hello{exe}\n'
# cl.exe accepts "-" as well as "/" options; "-" survives a recipe run through an MSYS sh,
# which would rewrite "/nologo" into a file path.
MAKEFILE_MSVC = 'hello.exe: hello.c\n\t"$(CC)" -nologo hello.c -Fehello.exe\n'

GNU_LIKE = ("gcc", "clang")
MSVC_LIKE = ("MSVC", "cl")


def _smoke_make(p: PlatformInfo, tools: list[ToolResult], d: Path) -> ToolResult:
    name = "hello: make"
    make, compiler = _find(tools, "make"), _find(tools, "C compiler")
    if not _usable(make):
        return _skipped(name, "make not available")
    if not _usable(compiler) or compiler.provider not in GNU_LIKE + MSVC_LIKE:
        return _skipped(name, "make is tested with gcc, clang or MSVC; none available")
    _write(d / "hello.c", C_SOURCE)
    if compiler.provider == "MSVC":
        _write(d / "Makefile", MAKEFILE_MSVC)
        build = _vcvars_step(p, compiler, f'"{make.path}" CC=cl', d)
    elif compiler.provider == "cl":
        _write(d / "Makefile", MAKEFILE_MSVC)
        build = [make.path, f"CC={compiler.path}"]
    else:
        _write(d / "Makefile", MAKEFILE.format(exe=EXE))
        build = [make.path, f"CC={compiler.path}"]
    return build_and_run(
        name,
        [(build, 300), ([str(d / f"hello{EXE}")], 30)],
        "hello from C", d, detail=f"{make.provider} built hello.c with {compiler.provider}",
    )


# --------------------------------------------------------------------------- C#


def smoke_dotnet(p: PlatformInfo, tools: list[ToolResult], work: Path) -> list[ToolResult]:
    dotnet = _find(tools, ".NET SDK (dotnet)")
    if not _usable(dotnet):
        return [_skipped("hello: C#", ".NET SDK not available")]
    major = (parse_version(dotnet.version or "") or (8,))[0]
    _write(work / "hello.csproj",
           '<Project Sdk="Microsoft.NET.Sdk">\n  <PropertyGroup>\n    <OutputType>Exe</OutputType>\n'
           f"    <TargetFramework>net{major}.0</TargetFramework>\n  </PropertyGroup>\n</Project>\n")
    _write(work / "Program.cs", 'System.Console.WriteLine("hello from C#");\n')
    env = {"DOTNET_NOLOGO": "1", "DOTNET_CLI_TELEMETRY_OPTOUT": "1", "DOTNET_SKIP_FIRST_TIME_EXPERIENCE": "1"}
    return [build_and_run(
        "hello: C#",
        [([dotnet.path, "build", "--nologo", "-v", "quiet"], 600), ([dotnet.path, "run", "--no-build"], 120)],
        "hello from C#", work, env=env, detail=f"dotnet build + run (net{major}.0)",
    )]


# --------------------------------------------------------------------------- Docker


def smoke_docker(p: PlatformInfo, tools: list[ToolResult], work: Path) -> list[ToolResult]:
    cli, daemon = _find(tools, "docker CLI"), _find(tools, "docker engine (daemon)")
    if not _usable(cli) or daemon is None or daemon.status is not Status.OK:
        return [_skipped("hello: Docker image", "Docker engine not reachable")]
    tag = f"devenv-check-hello:{uuid.uuid4().hex[:8]}"
    _write(work / "Dockerfile", "FROM hello-world\n")
    try:
        return [build_and_run(
            "hello: Docker image",
            [([cli.path, "build", "-q", "-t", tag, "."], 600), ([cli.path, "run", "--rm", tag], 180)],
            "Hello from Docker!", work, detail="docker build + run (pulls hello-world)",
        )]
    finally:
        run([cli.path, "rmi", "-f", tag], timeout=60)


# --------------------------------------------------------------------------- Kubernetes


def smoke_kubernetes(p: PlatformInfo, tools: list[ToolResult], work: Path) -> list[ToolResult]:
    kubectl, context_tool = _find(tools, "kubectl"), _find(tools, "kube context")
    name = "hello: Kubernetes pod"
    if not _usable(kubectl):
        return [_skipped(name, "kubectl not available")]
    if context_tool is None or context_tool.status is not Status.OK:
        return [_skipped(name, "no current kube context")]

    context = context_tool.detail
    pod = f"devenv-check-hello-{uuid.uuid4().hex[:6]}"
    base = [kubectl.path, "--context", context]
    if not LOCAL_KUBE_CONTEXT.match(context):
        return [build_and_run(
            name,
            [(base + ["--request-timeout=30s", "run", pod, "--image=busybox:1.36", "--restart=Never",
                      "--dry-run=server", "-o", "name"], 60)],
            f"pod/{pod}", work,
            detail=f"server-side dry run only: '{context}' is not a known local cluster, nothing was created",
        )]
    try:
        return [build_and_run(
            name,
            [(base + ["run", pod, "--image=busybox:1.36", "--restart=Never", "--rm", "-i", "--quiet",
                      "--pod-running-timeout=3m", "--command", "--", "echo", "hello from Kubernetes"], 300)],
            "hello from Kubernetes", work, detail=f"busybox pod ran on '{context}'",
        )]
    finally:
        run(base + ["delete", "pod", pod, "--ignore-not-found", "--wait=false"], timeout=60)


# --------------------------------------------------------------------------- registry

SMOKE_TESTS: dict[str, Callable[[PlatformInfo, list[ToolResult], Path], list[ToolResult]]] = {
    "git": smoke_git,
    "bash": smoke_bash,
    "java": smoke_java,
    "go": smoke_go,
    "python": smoke_python,
    "node": smoke_node,
    "cpp": smoke_cpp,
    "dotnet": smoke_dotnet,
    "docker": smoke_docker,
    "kubernetes": smoke_kubernetes,
}


def run_smoke(key: str, p: PlatformInfo, tools: list[ToolResult]) -> list[ToolResult]:
    test = SMOKE_TESTS.get(key)
    if test is None:
        return []
    with tempfile.TemporaryDirectory(prefix=f"devenv-check-{key}-", ignore_cleanup_errors=True) as tmp:
        try:
            return test(p, tools, Path(tmp))
        except Exception as exc:  # a broken test must not hide the other results
            return [ToolResult(f"hello: {key}", Status.MISSING, detail=f"internal error: {exc!r}", kind="hello")]
