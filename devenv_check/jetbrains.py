"""IntelliJ IDEA, the recommended IDE for Java and Kotlin development.

Installations are found through their product-info.json (written by every
JetBrains IDE install, including JetBrains Toolbox ones), so the IDE is never
launched. Updates are checked against JetBrains' public releases API, skipped
with --offline, and network problems never fail the check.
"""

from __future__ import annotations

import functools
import glob
import json
import os
import urllib.request
from pathlib import Path

from .checks import SETTINGS, Status, ToolResult
from .platform_info import PlatformInfo
from .runner import parse_version

RELEASES_API = "https://data.services.jetbrains.com/products/releases?code={code}&latest=true&type=release"
HTTP_TIMEOUT = 15
# product-info.json productCode -> releases API code
RELEASE_CODES = {"IU": "IIU", "IC": "IIC"}


def _search_patterns(p: PlatformInfo) -> list[str]:
    home = Path.home()
    if p.system == "windows":
        local = os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local"))
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        return [
            os.path.join(local, "Programs", "IntelliJ IDEA*", "product-info.json"),  # Toolbox 2.x
            os.path.join(local, "JetBrains", "Toolbox", "apps", "*", "**", "product-info.json"),  # older Toolbox
            os.path.join(program_files, "JetBrains", "IntelliJ IDEA*", "product-info.json"),  # standalone installer
        ]
    if p.system == "macos":
        app = os.path.join("IntelliJ IDEA*.app", "Contents", "Resources", "product-info.json")
        return [os.path.join("/Applications", app), os.path.join(str(home), "Applications", app)]
    patterns = [
        str(home / ".local" / "share" / "JetBrains" / "Toolbox" / "apps" / "*" / "**" / "product-info.json"),
        str(home / ".local" / "share" / "JetBrains" / "Toolbox" / "apps" / "intellij-idea*" / "product-info.json"),
        "/opt/idea*/product-info.json",
        "/opt/intellij*/product-info.json",
        "/snap/intellij-idea*/current/product-info.json",
    ]
    if p.wsl:
        # Java/Kotlin projects inside WSL are usually opened by IntelliJ installed on Windows.
        patterns += [
            "/mnt/c/Users/*/AppData/Local/Programs/IntelliJ IDEA*/product-info.json",
            "/mnt/c/Program Files/JetBrains/IntelliJ IDEA*/product-info.json",
        ]
    return patterns


def find_installations(p: PlatformInfo) -> list[dict]:
    """IntelliJ IDEA installations as product-info dicts (plus "path"), newest first."""
    found = {}
    for pattern in _search_patterns(p):
        for file in glob.glob(pattern, recursive=True):
            try:
                info = json.loads(Path(file).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if "IntelliJ IDEA" not in info.get("name", ""):
                continue
            info["path"] = str(Path(file).parent)
            found[os.path.normcase(info["path"])] = info
    return sorted(found.values(), key=lambda i: parse_version(i.get("version", "")) or (), reverse=True)


@functools.cache
def latest_release(release_code: str) -> str | None:
    request = urllib.request.Request(RELEASES_API.format(code=release_code), headers={"User-Agent": "devenv-check"})
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
        releases = json.load(response).get(release_code) or []
    return releases[0].get("version") if releases else None


def check_intellij(p: PlatformInfo) -> ToolResult:
    """The optional IDE row of the Java / Kotlin + Gradle environment."""
    name = "IntelliJ IDEA (IDE)"
    installs = find_installations(p)
    if not installs:
        return ToolResult(name, Status.WARN, required=False, hint="intellij",
                          detail="not found; IntelliJ IDEA is the recommended IDE for Java and Kotlin")
    ide = installs[0]
    version = ide.get("version", "")
    edition = {"IU": "Ultimate", "IC": "Community"}.get(ide.get("productCode", ""), "")
    tool = ToolResult(name, Status.OK, version=version or None, path=ide["path"], required=False,
                      detail=" ".join(filter(None, [ide.get("name"), edition])) or "IntelliJ IDEA")
    if p.wsl and ide["path"].startswith("/mnt/"):
        tool.detail += " on Windows (open WSL projects via its WSL support)"
    if SETTINGS.offline:
        tool.detail += "; update check skipped (--offline)"
        return tool
    code = RELEASE_CODES.get(ide.get("productCode", ""))
    if code is None:
        return tool
    try:
        latest = latest_release(code)
    except Exception as exc:
        tool.detail += f"; could not check for updates ({exc})"
        return tool
    if latest and (parse_version(latest) or ()) > (parse_version(version) or ()):
        tool.status, tool.hint = Status.WARN, "intellij_update"
        tool.detail += f"; update available: {latest}"
    else:
        tool.detail += "; up to date"
    return tool
