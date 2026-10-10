"""IntelliJ IDEA: the recommended IDE for Java and Kotlin, found through product-info.json."""

import io
import json
import os
import unittest
from pathlib import Path
from unittest import mock

from devenv_check import checks, jetbrains
from devenv_check.checks import Status
from tests.helpers import LINUX, MACOS, WINDOWS, WSL, TempDirMixin

IDEA = {"name": "IntelliJ IDEA", "version": "2026.2.3", "productCode": "IU", "path": "/opt/idea"}


def write_product_info(root: Path, folder: str, version: str, code: str = "IU", name: str = "IntelliJ IDEA") -> Path:
    install = root / folder
    install.mkdir(parents=True)
    (install / "product-info.json").write_text(json.dumps(
        {"name": name, "version": version, "buildNumber": "262.1", "productCode": code}))
    return install


class SearchPatternsTest(TempDirMixin, unittest.TestCase):
    def test_windows(self):
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.tmp), "ProgramFiles": r"C:\PF"}):
            patterns = jetbrains._search_patterns(WINDOWS)
        self.assertTrue(patterns[0].startswith(str(self.tmp)))
        self.assertTrue(any("Toolbox" in p for p in patterns))
        self.assertTrue(any(p.startswith(r"C:\PF") for p in patterns))

    def test_macos(self):
        self.assertTrue(all("IntelliJ IDEA*.app" in p for p in jetbrains._search_patterns(MACOS)))

    def test_linux_and_wsl(self):
        linux = jetbrains._search_patterns(LINUX)
        self.assertIn("/opt/idea*/product-info.json", linux)
        self.assertFalse(any(p.startswith("/mnt/c") for p in linux))
        self.assertTrue(any(p.startswith("/mnt/c") for p in jetbrains._search_patterns(WSL)))  # IntelliJ on Windows


class FindInstallationsTest(TempDirMixin, unittest.TestCase):
    def find(self):
        with mock.patch.object(jetbrains, "_search_patterns", return_value=[str(self.tmp / "*" / "product-info.json")]):
            return jetbrains.find_installations(LINUX)

    def test_newest_intellij_wins_and_other_ides_are_ignored(self):
        write_product_info(self.tmp, "IntelliJ IDEA 2025.3", "2025.3", "IC")
        newest = write_product_info(self.tmp, "IntelliJ IDEA", "2026.2.3")
        write_product_info(self.tmp, "PyCharm", "2026.3", "PY", name="PyCharm")
        broken = self.tmp / "Broken"
        broken.mkdir()
        (broken / "product-info.json").write_text("{not json")
        installs = self.find()
        self.assertEqual([i["version"] for i in installs], ["2026.2.3", "2025.3"])
        self.assertEqual(installs[0]["path"], str(newest))

    def test_nothing_installed(self):
        self.assertEqual(self.find(), [])


class LatestReleaseTest(unittest.TestCase):
    def setUp(self):
        jetbrains.latest_release.cache_clear()
        self.addCleanup(jetbrains.latest_release.cache_clear)

    def latest(self, payload):
        body = io.BytesIO(json.dumps(payload).encode())
        with mock.patch.object(jetbrains.urllib.request, "urlopen", return_value=body) as urlopen:
            return jetbrains.latest_release("IIU"), urlopen

    def test_reads_the_newest_release(self):
        version, urlopen = self.latest({"IIU": [{"version": "2026.2.3"}, {"version": "2026.2.2"}]})
        self.assertEqual(version, "2026.2.3")
        self.assertIn("code=IIU", urlopen.call_args.args[0].full_url)

    def test_no_releases(self):
        self.assertIsNone(self.latest({})[0])


class CheckIntellijTest(unittest.TestCase):
    def check(self, installs, latest="2026.2.3", offline=False, platform=LINUX):
        side_effect = latest if isinstance(latest, Exception) else None
        with mock.patch.object(jetbrains, "find_installations", return_value=installs), \
             mock.patch.object(jetbrains, "latest_release", return_value=latest, side_effect=side_effect) as latest_release, \
             mock.patch.object(jetbrains.SETTINGS, "offline", offline):
            return jetbrains.check_intellij(platform), latest_release

    def test_missing_is_an_optional_recommendation(self):
        tool, _ = self.check([])
        self.assertEqual((tool.status, tool.required, tool.hint), (Status.WARN, False, "intellij"))

    def test_up_to_date(self):
        tool, latest_release = self.check([IDEA])
        self.assertEqual((tool.status, tool.version, tool.path), (Status.OK, "2026.2.3", "/opt/idea"))
        self.assertEqual(tool.detail, "IntelliJ IDEA Ultimate; up to date")
        latest_release.assert_called_once_with("IIU")

    def test_outdated(self):
        tool, _ = self.check([{**IDEA, "version": "2026.1"}])
        self.assertEqual((tool.status, tool.hint), (Status.WARN, "intellij_update"))
        self.assertIn("update available: 2026.2.3", tool.detail)

    def test_community_edition(self):
        tool, latest_release = self.check([{**IDEA, "productCode": "IC"}])
        self.assertIn("Community", tool.detail)
        latest_release.assert_called_once_with("IIC")

    def test_unknown_product_code_skips_the_update_check(self):
        tool, latest_release = self.check([{"name": "IntelliJ IDEA", "path": "/opt/idea"}])
        latest_release.assert_not_called()
        self.assertEqual((tool.status, tool.version, tool.detail), (Status.OK, None, "IntelliJ IDEA"))

    def test_network_failure_and_offline_never_fail(self):
        broken, _ = self.check([{**IDEA, "version": "2026.1"}], latest=OSError("offline"))
        self.assertIs(broken.status, Status.OK)
        self.assertIn("could not check for updates (offline)", broken.detail)
        offline, latest_release = self.check([{**IDEA, "version": "2026.1"}], offline=True)
        self.assertIs(offline.status, Status.OK)
        self.assertIn("--offline", offline.detail)
        latest_release.assert_not_called()

    def test_windows_install_seen_from_wsl(self):
        tool, _ = self.check([{**IDEA, "path": "/mnt/c/Program Files/JetBrains/IntelliJ IDEA"}], platform=WSL)
        self.assertIn("on Windows (open WSL projects via its WSL support)", tool.detail)


class JvmEnvironmentsTest(unittest.TestCase):
    def test_java_and_kotlin_show_intellij(self):
        marker = checks.ToolResult("IntelliJ IDEA (IDE)", Status.OK, required=False)
        with mock.patch.object(jetbrains, "check_intellij", return_value=marker), mock.patch.object(checks, "which", return_value=None):
            self.assertIn(marker, checks.check_java(LINUX))
            self.assertIn(marker, checks.check_kotlin(LINUX))


if __name__ == "__main__":
    unittest.main()
