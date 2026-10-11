"""Environment checks.

Each environment check takes a PlatformInfo and returns a list of ToolResults.
A tool marked `required=False` never makes its environment "missing"; it only
downgrades it to "partial".
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path

from .platform_info import PlatformInfo, is_wsl
from .runner import GENERIC_VERSION, first_line, format_version, parse_version, run, which

# Minimum recommended versions; anything older is reported as a warning.
MIN_VERSIONS: dict[str, tuple[int, ...]] = {
    "git": (2, 34),
    "bash": (4, 0),
    "java": (17,),
    "kotlin": (2, 0),
    "python": (3, 11),
    "go": (1, 22),
    "node": (22,),
    "dotnet": (8,),
}


class Status(StrEnum):
    OK = "ok"
    WARN = "warn"
    MISSING = "missing"
    SKIPPED = "skipped"  # hello world test not attempted; never affects the env status


@dataclass
class ToolResult:
    name: str
    status: Status
    version: str | None = None
    path: str | None = None
    detail: str = ""
    required: bool = True
    hint: str | None = None  # key into install_hints.HINTS
    provider: str | None = None  # which candidate satisfied a first_available() check
    kind: str = "tool"  # "tool" for installation checks, "hello" for --deep build & run tests
    output: str = ""  # command log of a hello world test
    fix: list[str] = field(default_factory=list)  # tool-specific fix commands (on top of `hint`)


@dataclass
class Settings:
    offline: bool = False  # skip checks that need the network (VS Code / extension updates)


SETTINGS = Settings()


@dataclass
class EnvResult:
    key: str
    title: str
    tools: list[ToolResult] = field(default_factory=list)

    @property
    def status(self) -> Status:
        if any(t.status is Status.MISSING and t.required for t in self.tools):
            return Status.MISSING
        if any(t.status not in (Status.OK, Status.SKIPPED) for t in self.tools):
            return Status.WARN
        return Status.OK

    def to_dict(self) -> dict:
        return {"key": self.key, "title": self.title, "status": self.status, "tools": [asdict(t) for t in self.tools]}


# --------------------------------------------------------------------------- helpers


def _java_legacy(version: tuple[int, ...]) -> tuple[int, ...]:
    """Java 8 and older report themselves as 1.x."""
    return version[1:] if version[0] == 1 and len(version) > 1 else version


def probe(
    name: str,
    args: list[str],
    *,
    pattern: str = GENERIC_VERSION,
    required: bool = True,
    hint: str | None = None,
    min_version: tuple[int, ...] | None = None,
    fix: Callable[[tuple[int, ...]], tuple[int, ...]] | None = None,
    timeout: float = 30,
) -> ToolResult:
    """Locate `args[0]` on PATH, run it and extract its version."""
    path = which(args[0])
    if path is None:
        return ToolResult(name, Status.MISSING, detail=f"'{args[0]}' not found in PATH", required=required, hint=hint)

    result = run([path, *args[1:]], timeout=timeout)
    version = parse_version(result.output, pattern)
    if version and fix:
        version = fix(version)
    if not result.ok and version is None:
        reason = first_line(result.output) or f"exit code {result.returncode}"
        return ToolResult(name, Status.MISSING, path=path, detail=f"found but not working: {reason}", required=required, hint=hint)

    tool = ToolResult(name, Status.OK, version=format_version(version), path=path, required=required, hint=hint)
    if is_wsl() and path.startswith("/mnt/"):
        # WSL appends the Windows PATH, so Windows installs (e.g. npm, gradle) can shadow Linux ones.
        tool.status = Status.WARN
        tool.detail = "Windows installation reached through WSL interop; install a native Linux version"
    elif min_version and version and version < min_version:
        tool.status = Status.WARN
        tool.detail = f"older than recommended {format_version(min_version)}"
    return tool


def first_available(
    name: str,
    candidates: list[Callable[[], ToolResult]],
    *,
    required: bool = True,
    hint: str | None = None,
    missing_detail: str = "",
) -> ToolResult:
    """Return the first candidate that is installed, labelled with `name`."""
    for candidate in candidates:
        tool = candidate()
        if tool.status is not Status.MISSING:
            tool.detail = f"{tool.name}; {tool.detail}" if tool.detail else tool.name
            tool.provider = tool.name
            tool.name, tool.required, tool.hint = name, required, hint
            return tool
    return ToolResult(name, Status.MISSING, detail=missing_detail, required=required, hint=hint)


def _candidate(label: str, args: list[str], pattern: str = GENERIC_VERSION) -> Callable[[], ToolResult]:
    return lambda: probe(label, args, pattern=pattern)


def path_contains(directory: str) -> bool:
    target = os.path.normcase(os.path.normpath(directory))
    return any(
        os.path.normcase(os.path.normpath(entry)) == target
        for entry in os.environ.get("PATH", "").split(os.pathsep)
        if entry
    )


# --------------------------------------------------------------------------- Git


def check_git_identity(git: str) -> ToolResult:
    values = {}
    for key in ("user.name", "user.email"):
        res = run([git, "config", "--global", "--get", key])
        values[key] = res.stdout.strip() if res.ok else ""
    missing = [key for key, value in values.items() if not value]
    if missing:
        return ToolResult("commit identity", Status.WARN, required=False, hint="git_identity",
                          detail=f"{' and '.join(missing)} not set globally (commits will fail or be anonymous)")
    return ToolResult("commit identity", Status.OK, required=False, detail=f"{values['user.name']} <{values['user.email']}>")


def check_git(p: PlatformInfo) -> list[ToolResult]:
    # On macOS /usr/bin/git is a stub that opens an installer dialog without Command Line Tools.
    if p.system == "macos" and which("git") == "/usr/bin/git" and not run(["xcode-select", "-p"]).ok:
        return [ToolResult("git", Status.MISSING, path="/usr/bin/git", detail="Xcode Command Line Tools not installed", hint="git")]
    git = probe("git", ["git", "--version"], pattern=r"git version (\d+)\.(\d+)(?:\.(\d+))?",
                min_version=MIN_VERSIONS["git"], hint="git")
    if git.path and git.status is not Status.MISSING:
        return [git, check_git_identity(git.path)]
    return [git]


# --------------------------------------------------------------------------- Bash scripting

BASH_VERSION = r"version (\d+)\.(\d+)(?:\.(\d+))?"


def find_git_bash() -> str | None:
    """Git for Windows ships bash next to git: <Git>\\cmd\\git.exe -> <Git>\\bin\\bash.exe."""
    candidates = []
    git = which("git")
    if git:
        candidates.append(Path(git).resolve().parent.parent / "bin" / "bash.exe")
    candidates.append(Path(os.environ.get("ProgramFiles", r"C:\Program Files"), "Git", "bin", "bash.exe"))
    return next((str(c) for c in candidates if c.is_file()), None)


def check_bash(p: PlatformInfo) -> list[ToolResult]:
    if p.system == "windows":
        # PATH usually resolves `bash` to System32\bash.exe, the WSL launcher; prefer Git Bash.
        candidates = []
        git_bash = find_git_bash()
        if git_bash:
            candidates.append(_candidate("Git Bash", [git_bash, "--version"], BASH_VERSION))
        path_bash = which("bash")
        if path_bash:
            label = "WSL bash" if "system32" in path_bash.lower() else "bash"
            candidates.append(_candidate(label, ["bash", "--version"], BASH_VERSION))
        bash = first_available("bash", candidates, hint="bash", missing_detail="neither Git Bash nor WSL bash found")
        if bash.version and (parse_version(bash.version) or ()) < MIN_VERSIONS["bash"]:
            bash.status, bash.detail = Status.WARN, f"{bash.detail}; older than recommended 4.0"
    else:
        bash = probe("bash", ["bash", "--version"], pattern=BASH_VERSION, min_version=MIN_VERSIONS["bash"], hint="bash")
        if bash.status is Status.WARN and p.system == "macos":
            bash.detail = "macOS ships bash 3.2; install a current bash"
    return [
        bash,
        probe("shellcheck (linter)", ["shellcheck", "--version"], required=False, hint="shell_tools"),
        probe("shfmt (formatter)", ["shfmt", "--version"], required=False, hint="shell_tools"),
    ]


# --------------------------------------------------------------------------- Java


def detect_java_home(java_path: str) -> str | None:
    """Ask the JVM where it lives. PATH entries can be vendor shims (e.g. Oracle's
    ...\\Common Files\\Oracle\\Java\\javapath), so the executable's folder is not reliable."""
    res = run([java_path, "-XshowSettings:properties", "-version"])
    match = re.search(r"^\s*java\.home\s*=\s*(.+?)\s*$", res.output, re.MULTILINE)
    return match.group(1) if match else None


def _same_dir(a: str, b: str) -> bool:
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def check_java_home(java_home_on_path: str | None = None) -> ToolResult:
    home = os.environ.get("JAVA_HOME")
    if not home:
        detail = "not set (IDEs and some build tools rely on it)"
        if java_home_on_path:
            detail = f"not set; the java on PATH lives in {java_home_on_path}"
        return ToolResult("JAVA_HOME", Status.WARN, detail=detail, required=False, hint="java_home")
    exe = "java.exe" if os.name == "nt" else "java"
    if not Path(home, "bin", exe).is_file():
        detail = f"bin/{exe} not found under {home}"
        # Common mistake: pointing at a parent folder such as Oracle's C:\Program Files\Java\latest.
        nested = sorted(p for p in Path(home).glob(f"*/bin/{exe}") if p.is_file()) if Path(home).is_dir() else []
        if nested:
            detail += f"; did you mean {nested[-1].parent.parent}?"
        return ToolResult("JAVA_HOME", Status.WARN, path=home, detail=detail, required=False, hint="java_home")
    if java_home_on_path and not _same_dir(home, java_home_on_path):
        return ToolResult("JAVA_HOME", Status.WARN, path=home, required=False, hint="java_home",
                          detail=f"points to {home}, but the java on PATH is {java_home_on_path}")
    return ToolResult("JAVA_HOME", Status.OK, path=home, detail=home, required=False)


def check_java(p: PlatformInfo) -> list[ToolResult]:
    # On macOS /usr/bin/java is a stub that may pop up an install dialog when no JDK exists.
    if p.system == "macos" and which("java") == "/usr/bin/java" and not run(["/usr/libexec/java_home"]).ok:
        java = ToolResult("java", Status.MISSING, path="/usr/bin/java", detail="no JDK installed (macOS stub only)", hint="java")
        javac = ToolResult("javac (JDK)", Status.MISSING, detail="no JDK installed", hint="java")
    else:
        java = probe(
            "java", ["java", "-version"],
            pattern=r'version "(\d+)(?:\.(\d+))?(?:\.(\d+))?', fix=_java_legacy,
            min_version=MIN_VERSIONS["java"], hint="java",
        )
        javac = probe(
            "javac (JDK)", ["javac", "-version"],
            pattern=r"javac (\d+)(?:\.(\d+))?(?:\.(\d+))?", fix=_java_legacy, hint="java",
        )
        if javac.status is Status.MISSING and java.status is not Status.MISSING:
            javac.detail = "only a JRE was found; a JDK is needed to compile"

    # `gradle --version` and `kotlinc -version` start a JVM (gradle may also print a first-run banner): allow them time.
    gradle = probe("gradle", ["gradle", "--version"], pattern=r"Gradle (\d+)\.(\d+)(?:\.(\d+))?", hint="gradle", timeout=120)
    # Kotlin is optional on top of the JDK, like TypeScript on top of Node.js.
    kotlinc = probe("kotlinc", ["kotlinc", "-version"], pattern=r"kotlinc-jvm (\d+)\.(\d+)\.(\d+)",
                    min_version=MIN_VERSIONS["kotlin"], required=False, hint="kotlin", timeout=120)
    detected_home = detect_java_home(java.path) if java.path and java.status is not Status.MISSING else None
    return [java, javac, check_java_home(detected_home), gradle, kotlinc, check_intellij(p)]


def check_intellij(p: PlatformInfo) -> ToolResult:
    from .jetbrains import check_intellij as check  # imported lazily: jetbrains builds on this module

    return check(p)


# --------------------------------------------------------------------------- Python

# Runs inside the candidate interpreter; one line of JSON keeps parsing robust.
_PYTHON_INFO = (
    "import json, os, sys, sysconfig; print(json.dumps({"
    "'version': '%d.%d.%d' % tuple(sys.version_info[:3]), 'executable': sys.executable, "
    "'externally_managed': os.path.exists(os.path.join(sysconfig.get_path('stdlib'), 'EXTERNALLY-MANAGED'))}))"
)


def find_python(p: PlatformInfo) -> tuple[dict, str] | None:
    """First working Python 3 as (info, launcher name).

    Each candidate is actually run: on Windows `python`/`python3` may be Microsoft Store
    stubs that only print an install message, and `py` is the Python launcher.
    """
    names = ["python", "py", "python3"] if p.system == "windows" else ["python3", "python"]
    for name in names:
        path = which(name)
        if not path:
            continue
        res = run([path, *(["-3"] if name == "py" else []), "-c", _PYTHON_INFO], timeout=30)
        try:
            info = json.loads(res.stdout.strip().splitlines()[-1]) if res.ok and res.stdout.strip() else None
        except (json.JSONDecodeError, IndexError):
            info = None
        if info and info.get("version", "").startswith("3."):
            return info, name
    return None


def _python_error(result) -> str:
    """Prefer the line that tells the user what to install (e.g. Ubuntu's python3-venv hint)."""
    lines = [line.strip() for line in result.output.splitlines() if line.strip()]
    for marker in ("apt install", "ensurepip"):  # an install command beats an explanation
        for line in lines:
            if marker in line:
                return line
    return lines[-1] if lines else f"exit code {result.returncode}"


def check_venv(python: str) -> ToolResult:
    """Create a throwaway venv: the only reliable test (Ubuntu ships venv without ensurepip)."""
    name = "venv (virtual environments)"
    with tempfile.TemporaryDirectory(prefix="devenv-check-venv-", ignore_cleanup_errors=True) as tmp:
        res = run([python, "-m", "venv", str(Path(tmp, "env"))], timeout=180)
    if res.ok:
        return ToolResult(name, Status.OK, detail="created a virtual environment with pip")
    return ToolResult(name, Status.MISSING, hint="venv", detail=f"cannot create a venv: {_python_error(res)}")


def check_python(p: PlatformInfo) -> list[ToolResult]:
    found = find_python(p)
    if found is None:
        return [ToolResult("python", Status.MISSING, hint="python",
                           detail="no working Python 3 interpreter found (python3 / python / py)")]
    info, launcher = found
    exe = info["executable"]
    python = ToolResult("python", Status.OK, version=info["version"], path=exe, provider=launcher,
                        detail=f"via '{launcher}'", hint="python")
    if (parse_version(info["version"]) or ()) < MIN_VERSIONS["python"]:
        python.status = Status.WARN
        python.detail += f"; older than recommended {format_version(MIN_VERSIONS['python'])}"

    pip_res = run([exe, "-m", "pip", "--version"], timeout=60)
    pip_version = parse_version(pip_res.output, r"pip (\d+)\.(\d+)(?:\.(\d+))?") if pip_res.ok else None
    if pip_version:
        pip = ToolResult("pip", Status.OK, version=format_version(pip_version))
        if info.get("externally_managed"):
            pip.detail = "system Python is externally managed (PEP 668): install packages inside a venv"
    else:
        pip = ToolResult("pip", Status.MISSING, hint="pip", detail=f"'{launcher} -m pip' failed: {_python_error(pip_res)}")

    return [python, pip, check_venv(exe)]


# --------------------------------------------------------------------------- Go


def check_go_bin(go_path: str) -> ToolResult:
    res = run([go_path, "env", "GOBIN", "GOPATH"])
    lines = res.stdout.splitlines() if res.ok else []
    gobin = lines[0].strip() if lines else ""
    gopath = lines[1].strip().split(os.pathsep)[0] if len(lines) > 1 else ""
    bin_dir = gobin or (str(Path(gopath, "bin")) if gopath else "")
    if not bin_dir:
        return ToolResult("Go bin dir in PATH", Status.WARN, detail="could not determine GOPATH", required=False, hint="go_path")
    if not path_contains(bin_dir):
        return ToolResult("Go bin dir in PATH", Status.WARN, path=bin_dir,
                          detail=f"{bin_dir} is not in PATH ('go install'ed tools won't be found)", required=False, hint="go_path")
    return ToolResult("Go bin dir in PATH", Status.OK, path=bin_dir, detail=bin_dir, required=False)


def check_go(p: PlatformInfo) -> list[ToolResult]:
    go = probe("go", ["go", "version"], pattern=r"go(\d+)\.(\d+)(?:\.(\d+))?", min_version=MIN_VERSIONS["go"], hint="go")
    tools = [go]
    if go.path and go.status is not Status.MISSING:
        tools.append(check_go_bin(go.path))
    return tools


# --------------------------------------------------------------------------- JavaScript / TypeScript


def check_node(p: PlatformInfo) -> list[ToolResult]:
    # TypeScript is not checked: projects install it locally (npm install --save-dev typescript), never globally.
    return [
        probe("node", ["node", "--version"], min_version=MIN_VERSIONS["node"], hint="node"),
        probe("npm", ["npm", "--version"], hint="node"),
        probe("npx", ["npx", "--version"], hint="node"),
    ]


# --------------------------------------------------------------------------- C / C++


def probe_msvc(label: str = "MSVC") -> ToolResult:
    """Find Visual Studio / Build Tools with the C++ workload via vswhere."""
    root = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    vswhere = Path(root, "Microsoft Visual Studio", "Installer", "vswhere.exe")
    if not vswhere.is_file():
        return ToolResult(label, Status.MISSING)
    res = run([str(vswhere), "-latest", "-products", "*", "-requires",
               "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-format", "json", "-utf8"])
    try:
        instances = json.loads(res.stdout) if res.ok and res.stdout else []
    except json.JSONDecodeError:
        instances = []
    if not instances:
        return ToolResult(label, Status.MISSING)
    vs = instances[0]
    return ToolResult(
        label, Status.OK,
        version=vs.get("installationVersion"), path=vs.get("installationPath"),
        detail=f"{vs.get('displayName', 'Visual Studio')}; cl.exe is available from a 'Developer PowerShell for VS'",
    )


def check_cpp(p: PlatformInfo) -> list[ToolResult]:
    # On macOS, running gcc/clang/make without Command Line Tools opens an installer dialog.
    if p.system == "macos" and not run(["xcode-select", "-p"]).ok:
        detail = "Xcode Command Line Tools not installed"
        return [
            ToolResult("C compiler", Status.MISSING, detail=detail, hint="cpp"),
            ToolResult("C++ compiler", Status.MISSING, detail=detail, hint="cpp"),
            probe("cmake", ["cmake", "--version"], required=False, hint="build_tools"),
        ]

    c_candidates = [_candidate("gcc", ["gcc", "--version"]), _candidate("clang", ["clang", "--version"])]
    cpp_candidates = [_candidate("g++", ["g++", "--version"]), _candidate("clang++", ["clang++", "--version"])]
    make_candidates = [_candidate("make", ["make", "--version"])]
    if p.system == "windows":
        msvc = [_candidate("cl", ["cl"], pattern=r"Version (\d+)\.(\d+)\.(\d+)"), probe_msvc]
        c_candidates = msvc + c_candidates
        cpp_candidates = msvc + cpp_candidates
        make_candidates.append(_candidate("mingw32-make", ["mingw32-make", "--version"]))
    elif p.system == "macos":
        c_candidates.reverse()
        cpp_candidates.reverse()

    return [
        first_available("C compiler", c_candidates, hint="cpp", missing_detail="no gcc, clang or MSVC found"),
        first_available("C++ compiler", cpp_candidates, hint="cpp", missing_detail="no g++, clang++ or MSVC found"),
        probe("cmake", ["cmake", "--version"], required=False, hint="build_tools"),
        first_available("make", make_candidates, required=False, hint="build_tools", missing_detail="make not found"),
    ]


# --------------------------------------------------------------------------- C# / .NET


def check_dotnet(p: PlatformInfo) -> list[ToolResult]:
    name = ".NET SDK (dotnet)"
    path = which("dotnet")
    if path is None:
        return [ToolResult(name, Status.MISSING, detail="'dotnet' not found in PATH", hint="dotnet")]
    res = run([path, "--list-sdks"])
    versions = [v for v in (parse_version(line, r"^(\d+)\.(\d+)\.(\d+)") for line in res.stdout.splitlines()) if v]
    if not versions:
        return [ToolResult(name, Status.MISSING, path=path, detail="dotnet runtime found, but no SDK installed", hint="dotnet")]
    best = max(versions)
    tool = ToolResult(name, Status.OK, version=format_version(best), path=path,
                      detail=f"{len(versions)} SDK(s) installed" if len(versions) > 1 else "", hint="dotnet")
    if best < MIN_VERSIONS["dotnet"]:
        tool.status = Status.WARN
        tool.detail = f"older than recommended {format_version(MIN_VERSIONS['dotnet'])}"
    return [tool]


# --------------------------------------------------------------------------- Docker


def check_docker_daemon(docker: str) -> ToolResult:
    name = "docker engine (daemon)"
    res = run([docker, "info", "--format", "{{.ServerVersion}}"], timeout=30)
    version = res.stdout.strip()
    if res.ok and version and "error" not in version.lower():
        return ToolResult(name, Status.OK, version=version)
    reason = first_line(res.stderr) or first_line(res.stdout) or "daemon not reachable"
    return ToolResult(name, Status.MISSING, detail=f"not reachable: {reason}", hint="docker_daemon")


def check_docker(p: PlatformInfo) -> list[ToolResult]:
    cli = probe("docker CLI", ["docker", "--version"], hint="docker")
    if cli.status is Status.MISSING and p.wsl and "WSL" in cli.detail:
        # Docker Desktop places a stub in the Windows PATH that only explains how to enable integration.
        cli.detail = "Docker Desktop is installed on Windows, but WSL integration is off for this distro"
    if cli.status is Status.MISSING or not cli.path:
        return [cli]
    return [cli, check_docker_daemon(cli.path)]


# --------------------------------------------------------------------------- Kubernetes


def check_kube_context(kubectl: str) -> ToolResult:
    res = run([kubectl, "config", "current-context"], timeout=15)
    context = res.stdout.strip()
    if res.ok and context:
        return ToolResult("kube context", Status.OK, detail=context, required=False)
    return ToolResult("kube context", Status.WARN, detail="no current context configured (no cluster to talk to)",
                      required=False, hint="kube_context")


def check_kubernetes(p: PlatformInfo) -> list[ToolResult]:
    kubectl = probe("kubectl", ["kubectl", "version", "--client"], pattern=r"v(\d+)\.(\d+)\.(\d+)", hint="kubectl")
    tools = [kubectl]
    if kubectl.path and kubectl.status is not Status.MISSING:
        tools.append(check_kube_context(kubectl.path))
    tools.append(probe("helm", ["helm", "version", "--short"], required=False, hint="helm"))
    tools.append(first_available(
        "local cluster tool",
        [_candidate("kind", ["kind", "version"]),
         _candidate("minikube", ["minikube", "version", "--short"]),
         _candidate("k3d", ["k3d", "version"])],
        required=False, hint="local_cluster",
        missing_detail="none of kind, minikube or k3d found (Docker Desktop's Kubernetes also works)",
    ))
    return tools


# --------------------------------------------------------------------------- registry

def check_vscode(p: PlatformInfo) -> list[ToolResult]:
    from .vscode import check_vscode as check  # imported lazily: vscode builds on this module

    return check(p)


ENVIRONMENTS: dict[str, tuple[str, Callable[[PlatformInfo], list[ToolResult]]]] = {
    "git": ("Git", check_git),
    "bash": ("Bash scripting", check_bash),
    "java": ("Java / Kotlin + Gradle", check_java),
    "go": ("Go", check_go),
    "python": ("Python 3", check_python),
    "node": ("JavaScript / TypeScript (Node.js)", check_node),
    "cpp": ("C / C++", check_cpp),
    "dotnet": ("C# (.NET)", check_dotnet),
    "docker": ("Docker", check_docker),
    "kubernetes": ("Kubernetes", check_kubernetes),
    "vscode": ("Visual Studio Code + extensions", check_vscode),
}


def _check_env(key: str, p: PlatformInfo, deep: bool) -> list[ToolResult]:
    try:
        tools = ENVIRONMENTS[key][1](p)
    except Exception as exc:  # one broken check must not hide the others
        return [ToolResult("check", Status.MISSING, detail=f"internal error: {exc!r}")]
    if deep:
        from .smoke import run_smoke  # imported lazily: smoke builds on this module

        tools += run_smoke(key, p, tools)
    return tools


def run_checks(p: PlatformInfo, keys: list[str] | None = None, *, deep: bool = False) -> list[EnvResult]:
    """Run the selected environment checks in parallel, preserving order.

    With `deep`, each environment also builds and runs a hello world program.
    """
    keys = keys or list(ENVIRONMENTS)
    with ThreadPoolExecutor(max_workers=len(keys)) as pool:
        futures = {key: pool.submit(_check_env, key, p, deep) for key in keys}
    return [EnvResult(key, ENVIRONMENTS[key][0], futures[key].result()) for key in keys]
