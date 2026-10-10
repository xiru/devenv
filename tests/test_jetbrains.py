import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from devenv_check import checks, install_hints, jetbrains
from devenv_check.checks import Status
from devenv_check.platform_info import PlatformInfo

LINUX = PlatformInfo("linux", "debian", "Ubuntu", "amd64")


def write_product_info(root: Path, folder: str, version: str, code: str = "IU", name: str = "IntelliJ IDEA") -> Path:
    install = root / folder
    install.mkdir(parents=True)
    (install / "product-info.json").write_text(json.dumps(
        {"name": name, "version": version, "buildNumber": "262.1", "productCode": code}))
    return install


class FindInstallationsTest(unittest.TestCase):
    def test_newest_intellij_wins_and_other_ides_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_product_info(root, "IntelliJ IDEA 2025.3", "2025.3", "IC")
            newest = write_product_info(root, "IntelliJ IDEA", "2026.2.3")
            write_product_info(root, "PyCharm", "2026.3", "PY", name="PyCharm")
            with mock.patch.object(jetbrains, "_search_patterns", return_value=[str(root / "*" / "product-info.json")]):
                installs = jetbrains.find_installations(LINUX)
        self.assertEqual([i["version"] for i in installs], ["2026.2.3", "2025.3"])
        self.assertEqual(installs[0]["path"], str(newest))


class CheckIntellijTest(unittest.TestCase):
    def run_check(self, installs, latest="2026.2.3", offline=False):
        with mock.patch.object(jetbrains, "find_installations", return_value=installs), \
             mock.patch.object(jetbrains, "latest_release", return_value=latest), \
             mock.patch.object(jetbrains.SETTINGS, "offline", offline):
            return jetbrains.check_intellij(LINUX)

    def test_missing_is_an_optional_recommendation(self):
        tool = self.run_check([])
        self.assertIs(tool.status, Status.WARN)
        self.assertFalse(tool.required)
        self.assertEqual(tool.hint, "intellij")

    def test_up_to_date(self):
        tool = self.run_check([{"name": "IntelliJ IDEA", "version": "2026.2.3", "productCode": "IU", "path": "/opt/idea"}])
        self.assertIs(tool.status, Status.OK)
        self.assertIn("Ultimate", tool.detail)
        self.assertIn("up to date", tool.detail)

    def test_outdated(self):
        tool = self.run_check([{"name": "IntelliJ IDEA", "version": "2026.1", "productCode": "IU", "path": "/opt/idea"}])
        self.assertIs(tool.status, Status.WARN)
        self.assertEqual(tool.hint, "intellij_update")

    def test_network_failure_and_offline_never_fail(self):
        install = [{"name": "IntelliJ IDEA", "version": "2026.1", "productCode": "IU", "path": "/opt/idea"}]
        with mock.patch.object(jetbrains, "find_installations", return_value=install), \
             mock.patch.object(jetbrains, "latest_release", side_effect=OSError("offline")):
            self.assertIs(jetbrains.check_intellij(LINUX).status, Status.OK)
        self.assertIs(self.run_check(install, offline=True).status, Status.OK)


class JvmEnvironmentsTest(unittest.TestCase):
    def test_java_and_kotlin_include_intellij(self):
        marker = checks.ToolResult("IntelliJ IDEA (IDE)", Status.OK, required=False)
        with mock.patch.object(checks, "check_intellij", return_value=marker), \
             mock.patch.object(checks, "which", return_value=None):
            java_tools = checks.check_java(LINUX)
            kotlin_tools = checks.check_kotlin(LINUX)
        self.assertIn(marker, java_tools)
        self.assertIn(marker, kotlin_tools)

    def test_hints_never_suggest_vscode_for_jvm(self):
        for family in ("windows", "macos", "debian", "linux"):
            platform = PlatformInfo("windows" if family == "windows" else "macos" if family == "macos" else "linux",
                                    family, family, "amd64")
            for key in ("java", "java_home", "gradle", "kotlin", "intellij", "intellij_update"):
                text = " ".join(install_hints.hint_for(key, platform)).lower()
                self.assertNotIn("code --install-extension", text, (family, key))
                self.assertNotIn("visual studio code", text, (family, key))


if __name__ == "__main__":
    unittest.main()
