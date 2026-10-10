"""Operating system detection, used to pick installation instructions."""

from __future__ import annotations

import functools
import os
import platform
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class PlatformInfo:
    system: str  # "windows" | "macos" | "linux" | anything else platform reports
    family: str  # install-hint family: windows, macos, debian, fedora, arch, suse, linux
    name: str  # human readable description
    arch: str  # "amd64", "arm64" or the raw machine name
    wsl: bool = False  # Linux running under Windows Subsystem for Linux


@functools.cache
def is_wsl() -> bool:
    return sys.platform.startswith("linux") and (
        "microsoft" in platform.release().lower() or "WSL_DISTRO_NAME" in os.environ
    )


_ARCH_ALIASES = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}

_LINUX_FAMILIES = {
    "debian": "debian",
    "ubuntu": "debian",
    "linuxmint": "debian",
    "pop": "debian",
    "elementary": "debian",
    "fedora": "fedora",
    "rhel": "fedora",
    "centos": "fedora",
    "rocky": "fedora",
    "almalinux": "fedora",
    "arch": "arch",
    "manjaro": "arch",
    "endeavouros": "arch",
    "suse": "suse",
    "sles": "suse",
}


def linux_family(os_release: dict[str, str]) -> str:
    """Map /etc/os-release ID / ID_LIKE to a package-manager family."""
    ids = [os_release.get("ID", "")] + os_release.get("ID_LIKE", "").split()
    for distro_id in ids:
        distro_id = distro_id.lower()
        if distro_id in _LINUX_FAMILIES:
            return _LINUX_FAMILIES[distro_id]
        if distro_id.startswith("opensuse"):
            return "suse"
    return "linux"


def detect() -> PlatformInfo:
    machine = platform.machine().lower()
    arch = _ARCH_ALIASES.get(machine, machine or "unknown")

    if sys.platform == "win32":
        return PlatformInfo("windows", "windows", f"Windows {platform.release()} ({platform.version()})", arch)

    if sys.platform == "darwin":
        return PlatformInfo("macos", "macos", f"macOS {platform.mac_ver()[0]}", arch)

    if sys.platform.startswith("linux"):
        try:
            os_release = platform.freedesktop_os_release()
        except OSError:
            os_release = {}
        name = os_release.get("PRETTY_NAME", "Linux")
        wsl = is_wsl()
        if wsl:
            name += " (WSL)"
        return PlatformInfo("linux", linux_family(os_release), name, arch, wsl)

    return PlatformInfo(sys.platform, sys.platform, platform.platform(), arch)
