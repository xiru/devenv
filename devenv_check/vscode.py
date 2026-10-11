"""Visual Studio Code: the editor itself and the main extension per language.

Installed extensions are read from VS Code's extensions folder (no editor is
launched). Update checks query the public Visual Studio Marketplace and the VS
Code release feed; they are skipped with --offline and never fail the check
when the network is unavailable.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from .checks import SETTINGS, Status, ToolResult
from .platform_info import PlatformInfo
from .runner import first_line, format_version, parse_version, run, which

MARKETPLACE_LATEST = "https://marketplace.visualstudio.com/_apis/public/gallery/vscode/{publisher}/{name}/latest"
VSCODE_RELEASES = "https://update.code.visualstudio.com/api/releases/stable"
HTTP_TIMEOUT = 15


@dataclass(frozen=True)
class ExtensionSpec:
    label: str
    ids: tuple[str, ...]  # accepted extension ids, preferred first
    required: bool = True
    note: str = ""
    windows_only: bool = False


EXTENSIONS: list[ExtensionSpec] = [
    ExtensionSpec("Bash", ("mads-hartmann.bash-ide-vscode", "timonwong.shellcheck"), required=False,
                  note="language server + ShellCheck integration"),
    # Java, Gradle and Kotlin are deliberately absent: IntelliJ IDEA is the recommended IDE for
    # JVM development and is checked in those environments instead (see jetbrains.py).
    ExtensionSpec("Go", ("golang.go",)),
    ExtensionSpec("Python", ("ms-python.python",), note="includes Pylance and the debugger"),
    ExtensionSpec("ESLint (JS/TS)", ("dbaeumer.vscode-eslint",), required=False,
                  note="JavaScript/TypeScript language support is built into VS Code"),
    ExtensionSpec("C/C++", ("ms-vscode.cpptools-extension-pack", "ms-vscode.cpptools")),
    ExtensionSpec("CMake", ("ms-vscode.cmake-tools",), required=False),
    ExtensionSpec("C#", ("ms-dotnettools.csdevkit", "ms-dotnettools.csharp")),
    ExtensionSpec("Docker / containers", ("ms-azuretools.vscode-containers", "ms-azuretools.vscode-docker")),
    ExtensionSpec("Kubernetes", ("ms-kubernetes-tools.vscode-kubernetes-tools",)),
    ExtensionSpec("WSL", ("ms-vscode-remote.remote-wsl",), required=False, windows_only=True,
                  note="develop inside WSL from Windows"),
]


@dataclass
class InstalledExtension:
    id: str
    version: str
    prerelease: bool = False


# --------------------------------------------------------------------------- locating VS Code


def _known_locations(p: PlatformInfo) -> list[Path]:
    home = Path.home()
    if p.system == "windows":
        roots = [os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local")) + r"\Programs",
                 os.environ.get("ProgramFiles", r"C:\Program Files")]
        return [Path(root, "Microsoft VS Code", "bin", "code.cmd") for root in roots]
    if p.system == "macos":
        app = Path("Visual Studio Code.app", "Contents", "Resources", "app", "bin", "code")
        return [Path("/Applications") / app, home / "Applications" / app]
    return [Path("/usr/share/code/bin/code"), Path("/snap/bin/code"), Path("/usr/bin/code")]


def find_code(p: PlatformInfo) -> tuple[str | None, bool]:
    """Return (path to the `code` launcher, whether it is on PATH)."""
    on_path = which("code")
    if on_path:
        return on_path, True
    for candidate in _known_locations(p):
        if candidate.is_file():
            return str(candidate), False
    return None, False


def extensions_dir(p: PlatformInfo) -> Path:
    if os.environ.get("VSCODE_EXTENSIONS"):
        return Path(os.environ["VSCODE_EXTENSIONS"])
    if p.wsl:
        # VS Code on Windows keeps the extensions used inside WSL on the Linux side.
        return Path.home() / ".vscode-server" / "extensions"
    return Path.home() / ".vscode" / "extensions"


_DIR_NAME = re.compile(r"^(?P<id>[^.]+\.[^-]+(?:-[^\d][^-]*)*)-(?P<version>\d+\.\d+\.\d+[^-]*)")


def installed_extensions(directory: Path) -> dict[str, InstalledExtension]:
    """Installed extensions by lower-case id (newest version wins)."""
    found: dict[str, InstalledExtension] = {}

    def add(ext: InstalledExtension) -> None:
        current = found.get(ext.id)
        if current is None or (parse_version(ext.version) or ()) > (parse_version(current.version) or ()):
            found[ext.id] = ext

    manifest = directory / "extensions.json"
    try:
        entries = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        entries = None
    if isinstance(entries, list):
        for entry in entries:
            try:
                ext_id = entry["identifier"]["id"].lower()
                metadata = entry.get("metadata") or {}
                add(InstalledExtension(ext_id, entry["version"],
                                       bool(metadata.get("isPreReleaseVersion") or metadata.get("preRelease"))))
            except (KeyError, TypeError, AttributeError):
                continue
        return found

    # Older VS Code versions have no extensions.json: fall back to folder names.
    if directory.is_dir():
        for child in directory.iterdir():
            match = _DIR_NAME.match(child.name)
            if child.is_dir() and match:
                add(InstalledExtension(match["id"].lower(), match["version"]))
    return found


# --------------------------------------------------------------------------- update information


def _get_json(url: str):
    request = urllib.request.Request(url, headers={
        "Accept": "application/json;api-version=3.0-preview.1",
        "User-Agent": "devenv-check",
    })
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
        return json.load(response)


def latest_versions(ext_id: str) -> tuple[str | None, str | None]:
    """(newest stable, newest pre-release) version of a Marketplace extension."""
    publisher, name = ext_id.split(".", 1)
    data = _get_json(MARKETPLACE_LATEST.format(publisher=publisher, name=name))
    stable: tuple[int, ...] = ()
    prerelease: tuple[int, ...] = ()
    for version in data.get("versions", []):
        parsed = parse_version(version.get("version", ""), r"(\d+)\.(\d+)\.(\d+)")
        if not parsed:
            continue
        is_pre = any(prop.get("key") == "Microsoft.VisualStudio.Code.PreRelease" and prop.get("value") == "true"
                     for prop in version.get("properties", []))
        if is_pre:
            prerelease = max(prerelease, parsed)
        else:
            stable = max(stable, parsed)
    return format_version(stable or None), format_version(prerelease or None)


def fetch_latest(ext_ids: list[str]) -> dict[str, tuple[str | None, str | None] | Exception]:
    if not ext_ids:
        return {}

    def safe(ext_id: str):
        try:
            return latest_versions(ext_id)
        except Exception as exc:  # network errors only downgrade the detail text
            return exc

    with ThreadPoolExecutor(max_workers=min(8, len(ext_ids))) as pool:
        return dict(zip(ext_ids, pool.map(safe, ext_ids)))


# --------------------------------------------------------------------------- checks


def check_vscode_app(p: PlatformInfo) -> ToolResult:
    name = "VS Code"
    path, on_path = find_code(p)
    if path is None:
        return ToolResult(name, Status.MISSING, detail="not installed ('code' not found)", hint="vscode")

    if p.wsl and path.startswith("/mnt/"):
        # The Windows editor reached through interop; running it would start the WSL server setup.
        return ToolResult(name, Status.OK, path=path, detail="VS Code on Windows; run 'code .' here to open folders via WSL")

    res = run([path, "--version"], timeout=30)
    version = first_line(res.stdout) if res.ok else ""
    if not parse_version(version):
        return ToolResult(name, Status.MISSING, path=path, hint="vscode",
                          detail=f"found but not working: {first_line(res.output) or 'no output'}")
    tool = ToolResult(name, Status.OK, version=version, path=path)
    if not on_path:
        tool.status, tool.hint = Status.WARN, "vscode_path"
        tool.detail = "installed, but the 'code' command is not on PATH"
        return tool
    if SETTINGS.offline:
        tool.detail = "update check skipped (--offline)"
        return tool
    try:
        latest = _get_json(VSCODE_RELEASES)[0]
    except Exception as exc:
        tool.detail = f"could not check for updates: {exc}"
        return tool
    if (parse_version(latest) or ()) > (parse_version(version) or ()):
        tool.status, tool.hint = Status.WARN, "vscode_update"
        tool.detail = f"update available: {latest}"
    else:
        tool.detail = "up to date"
    return tool


def check_extensions(p: PlatformInfo, code_path: str | None) -> list[ToolResult]:
    specs = [spec for spec in EXTENSIONS if not spec.windows_only or (p.system == "windows" and which("wsl"))]
    installed = installed_extensions(extensions_dir(p))
    chosen = {spec.label: next((installed[i] for i in spec.ids if i in installed), None) for spec in specs}
    latest = {} if SETTINGS.offline else fetch_latest([ext.id for ext in chosen.values() if ext])
    code = "code"  # the fix commands are meant to be typed by the user

    results = []
    for spec in specs:
        name = f"ext: {spec.label}"
        ext = chosen[spec.label]
        if ext is None:
            fix = [f"{code} --install-extension {spec.ids[0]}"]
            if p.wsl:
                fix.append("# run it in this WSL terminal so the extension is installed on the WSL side")
            results.append(ToolResult(name, Status.MISSING, required=spec.required, fix=fix,
                                      detail=f"{spec.ids[0]} not installed" + (f" ({spec.note})" if spec.note else "")))
            continue

        tool = ToolResult(name, Status.OK, version=ext.version, required=spec.required, provider=ext.id, detail=ext.id)
        info = latest.get(ext.id)
        if SETTINGS.offline:
            tool.detail += "; update check skipped (--offline)"
        elif isinstance(info, Exception) or info is None:
            tool.detail += f"; could not check for updates ({info})" if info else ""
        else:
            stable, prerelease = info
            target = (prerelease or stable) if ext.prerelease else (stable or prerelease)
            if target and (parse_version(target) or ()) > (parse_version(ext.version) or ()):
                tool.status = Status.WARN
                tool.detail = f"{ext.id}; update available: {target}"
                tool.fix = [f"{code} --install-extension {ext.id}" + (" --pre-release" if ext.prerelease else "") + " --force"]
            else:
                tool.detail = f"{ext.id}; up to date" + (" (pre-release)" if ext.prerelease else "")
        results.append(tool)
    return results


def check_vscode(p: PlatformInfo) -> list[ToolResult]:
    app = check_vscode_app(p)
    if app.status is Status.MISSING:
        return [app, ToolResult("extensions", Status.SKIPPED, detail="skipped: VS Code not installed", required=False)]
    return [app, *check_extensions(p, app.path)]
