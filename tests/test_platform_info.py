"""platform_info: operating system, distro family, architecture and WSL detection."""

import unittest
from unittest import mock

from devenv_check import platform_info
from devenv_check.platform_info import PlatformInfo, detect, linux_family


class LinuxFamilyTest(unittest.TestCase):
    def test_id_and_id_like(self):
        self.assertEqual(linux_family({"ID": "ubuntu", "ID_LIKE": "debian"}), "debian")
        self.assertEqual(linux_family({"ID": "rocky", "ID_LIKE": "rhel centos fedora"}), "fedora")
        self.assertEqual(linux_family({"ID": "garuda", "ID_LIKE": "arch"}), "arch")
        self.assertEqual(linux_family({"ID": "Fedora"}), "fedora")

    def test_any_opensuse_flavour_is_suse(self):
        self.assertEqual(linux_family({"ID": "opensuse-tumbleweed", "ID_LIKE": "opensuse suse"}), "suse")
        self.assertEqual(linux_family({"ID": "opensuse-leap"}), "suse")

    def test_unknown_distro_falls_back_to_generic_linux(self):
        self.assertEqual(linux_family({"ID": "alpine"}), "linux")
        self.assertEqual(linux_family({}), "linux")


class DetectTest(unittest.TestCase):
    def detect_on(self, sys_platform, machine="x86_64", os_release=None, wsl=False):
        os_release_mock = (mock.patch.object(platform_info.platform, "freedesktop_os_release", return_value=os_release)
                           if os_release is not None else
                           mock.patch.object(platform_info.platform, "freedesktop_os_release", side_effect=OSError))
        with mock.patch.object(platform_info.sys, "platform", sys_platform), \
             mock.patch.object(platform_info.platform, "machine", return_value=machine), \
             mock.patch.object(platform_info.platform, "release", return_value="11"), \
             mock.patch.object(platform_info.platform, "version", return_value="10.0.26300"), \
             mock.patch.object(platform_info.platform, "mac_ver", return_value=("15.1", ("", "", ""), "")), \
             mock.patch.object(platform_info, "is_wsl", return_value=wsl), \
             os_release_mock:
            return detect()

    def test_windows(self):
        self.assertEqual(self.detect_on("win32", "AMD64"),
                         PlatformInfo("windows", "windows", "Windows 11 (10.0.26300)", "amd64"))

    def test_macos(self):
        self.assertEqual(self.detect_on("darwin", "arm64"), PlatformInfo("macos", "macos", "macOS 15.1", "arm64"))

    def test_ubuntu(self):
        info = self.detect_on("linux", "aarch64", {"ID": "ubuntu", "ID_LIKE": "debian", "PRETTY_NAME": "Ubuntu 24.04.1 LTS"})
        self.assertEqual(info, PlatformInfo("linux", "debian", "Ubuntu 24.04.1 LTS", "arm64"))

    def test_ubuntu_under_wsl(self):
        info = self.detect_on("linux", os_release={"ID": "ubuntu", "PRETTY_NAME": "Ubuntu 24.04"}, wsl=True)
        self.assertTrue(info.wsl)
        self.assertEqual(info.name, "Ubuntu 24.04 (WSL)")

    def test_linux_without_os_release(self):
        info = self.detect_on("linux")
        self.assertEqual((info.family, info.name), ("linux", "Linux"))

    def test_other_systems_keep_their_own_names(self):
        info = self.detect_on("freebsd14", "riscv64")
        self.assertEqual((info.system, info.family, info.arch), ("freebsd14", "freebsd14", "riscv64"))

    def test_unknown_machine(self):
        self.assertEqual(self.detect_on("win32", "").arch, "unknown")


class IsWslTest(unittest.TestCase):
    def is_wsl(self, sys_platform, release, environ):
        platform_info.is_wsl.cache_clear()
        self.addCleanup(platform_info.is_wsl.cache_clear)
        with mock.patch.object(platform_info.sys, "platform", sys_platform), \
             mock.patch.object(platform_info.platform, "release", return_value=release), \
             mock.patch.dict("os.environ", environ, clear=True):
            return platform_info.is_wsl()

    def test_detection(self):
        self.assertTrue(self.is_wsl("linux", "5.15.167.4-microsoft-standard-WSL2", {}))
        self.assertTrue(self.is_wsl("linux", "6.6.0", {"WSL_DISTRO_NAME": "Ubuntu"}))
        self.assertFalse(self.is_wsl("linux", "6.8.0-49-generic", {}))
        self.assertFalse(self.is_wsl("win32", "11", {"WSL_DISTRO_NAME": "Ubuntu"}))


if __name__ == "__main__":
    unittest.main()
