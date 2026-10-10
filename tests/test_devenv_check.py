import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from devenv_check import checks, cli, install_hints
from devenv_check.checks import ENVIRONMENTS, EnvResult, Status, ToolResult
from devenv_check.platform_info import PlatformInfo, linux_family
from devenv_check.runner import CommandResult, parse_version

FAMILIES = ["windows", "macos", "debian", "fedora", "arch", "suse", "linux"]


def platform_for(family: str) -> PlatformInfo:
    system = family if family in ("windows", "macos") else "linux"
    return PlatformInfo(system, family, family, "amd64")


class ParseVersionTest(unittest.TestCase):
    def test_generic(self):
        self.assertEqual(parse_version("cmake version 3.29.3"), (3, 29, 3))
        self.assertEqual(parse_version("v22.3.0"), (22, 3, 0))
        self.assertIsNone(parse_version("no digits here"))

    def test_java_formats(self):
        pattern = r'version "(\d+)(?:\.(\d+))?(?:\.(\d+))?'
        self.assertEqual(parse_version('openjdk version "21" 2023-09-19', pattern), (21,))
        self.assertEqual(parse_version('openjdk version "17.0.12" 2024-07-16', pattern), (17, 0, 12))
        legacy = parse_version('java version "1.8.0_381"', pattern)
        self.assertEqual(checks._java_legacy(legacy), (8, 0))

    def test_go(self):
        self.assertEqual(parse_version("go version go1.22.4 linux/amd64", r"go(\d+)\.(\d+)(?:\.(\d+))?"), (1, 22, 4))


class JavaHomeTest(unittest.TestCase):
    ORACLE_SETTINGS = (
        "Property settings:\n    file.encoding = UTF-8\n"
        "    java.home = C:\\Program Files\\Java\\jdk-27\n    java.version = 27\n"
        'java version "27" 2026-09-15\n'
    )

    def test_detects_home_behind_vendor_shim(self):
        result = CommandResult(True, "", self.ORACLE_SETTINGS, 0)
        with mock.patch.object(checks, "run", return_value=result):
            home = checks.detect_java_home(r"C:\Program Files\Common Files\Oracle\Java\javapath\java.exe")
        self.assertEqual(home, r"C:\Program Files\Java\jdk-27")

    def test_oracle_version_without_dots(self):
        pattern = r'version "(\d+)(?:\.(\d+))?(?:\.(\d+))?'
        self.assertEqual(parse_version(self.ORACLE_SETTINGS, pattern), (27,))

    def test_unset_java_home_mentions_detected_home(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            tool = checks.check_java_home(r"C:\Program Files\Java\jdk-27")
        self.assertIs(tool.status, Status.WARN)
        self.assertIn("jdk-27", tool.detail)

    def test_java_home_pointing_to_another_jdk_warns(self):
        with tempfile.TemporaryDirectory() as old_jdk, tempfile.TemporaryDirectory() as new_jdk:
            exe = "java.exe" if os.name == "nt" else "java"
            Path(old_jdk, "bin").mkdir()
            Path(old_jdk, "bin", exe).touch()
            with mock.patch.dict("os.environ", {"JAVA_HOME": old_jdk}):
                mismatch = checks.check_java_home(new_jdk)
                match = checks.check_java_home(old_jdk)
        self.assertIs(mismatch.status, Status.WARN)
        self.assertIn("on PATH", mismatch.detail)
        self.assertIs(match.status, Status.OK)


class LinuxFamilyTest(unittest.TestCase):
    def test_families(self):
        self.assertEqual(linux_family({"ID": "ubuntu", "ID_LIKE": "debian"}), "debian")
        self.assertEqual(linux_family({"ID": "rocky", "ID_LIKE": "rhel centos fedora"}), "fedora")
        self.assertEqual(linux_family({"ID": "opensuse-tumbleweed", "ID_LIKE": "opensuse suse"}), "suse")
        self.assertEqual(linux_family({"ID": "garuda", "ID_LIKE": "arch"}), "arch")
        self.assertEqual(linux_family({"ID": "alpine"}), "linux")


class HintsTest(unittest.TestCase):
    def all_hint_keys(self, family="linux"):
        """Every hint key that applies to `family` (some keys are platform-specific)."""
        return {key for key in install_hints.DOCS
                if family in install_hints.PLATFORM_ONLY.get(key, {family})}

    def test_every_key_has_a_hint_on_every_family(self):
        for family in FAMILIES:
            for key in self.all_hint_keys(family):
                with self.subTest(family=family, key=key):
                    self.assertTrue(install_hints.hint_for(key, platform_for(family)))

    def test_wsl_ubuntu_prefers_wsl_then_debian_then_generic(self):
        wsl = PlatformInfo("linux", "debian", "Ubuntu 24.04 (WSL)", "amd64", wsl=True)
        self.assertTrue(any("WSL integration" in line for line in install_hints.hint_for("docker_daemon", wsl)))
        self.assertTrue(any("apt" in line for line in install_hints.hint_for("cpp", wsl)))
        self.assertTrue(any("get-helm-3" in line or "snap" in line for line in install_hints.hint_for("helm", wsl)))
        native = PlatformInfo("linux", "debian", "Ubuntu 24.04", "amd64")
        self.assertFalse(any("WSL" in line for line in install_hints.hint_for("docker_daemon", native)))

    def test_every_key_has_a_hint_under_wsl(self):
        wsl = PlatformInfo("linux", "debian", "Ubuntu (WSL)", "amd64", wsl=True)
        for key in self.all_hint_keys():
            with self.subTest(key=key):
                self.assertTrue(install_hints.hint_for(key, wsl))

    def test_platform_only_keys_are_covered_where_they_apply(self):
        for key, families in install_hints.PLATFORM_ONLY.items():
            for family in families:
                with self.subTest(key=key, family=family):
                    self.assertTrue(install_hints.hint_for(key, platform_for(family)))

    def test_arch_placeholder_is_filled(self):
        lines = install_hints.hint_for("kubectl", PlatformInfo("linux", "linux", "x", "arm64"))
        self.assertTrue(any("linux/arm64/kubectl" in line for line in lines))
        self.assertFalse(any("{arch}" in line for line in lines))


class ScoopOrChocoTest(unittest.TestCase):
    WINDOWS = platform_for("windows")

    def hints_with(self, installed, key="gradle"):
        def fake_which(name):
            return f"C:\\bin\\{name}.exe" if name in installed else None
        with mock.patch.object(install_hints, "which", side_effect=fake_which):
            return install_hints.hint_for(key, self.WINDOWS), install_hints.prerequisite_notes(
                self.WINDOWS, ["gradle", "kotlin", "go", "gradle"])

    def test_scoop_installed(self):
        lines, notes = self.hints_with({"winget", "scoop", "choco"})
        self.assertEqual(lines[0], "scoop install gradle")
        self.assertFalse(any("Scoop" in note for note in notes))

    def test_only_choco_installed(self):
        lines, notes = self.hints_with({"winget", "choco"}, key="kotlin")
        self.assertTrue(lines[0].startswith("choco install kotlinc -y"))
        self.assertFalse(any("Scoop" in note for note in notes))

    def test_neither_installed_bootstraps_scoop_once(self):
        lines, notes = self.hints_with({"winget"})
        self.assertEqual(lines[0], "scoop install gradle")
        (note,) = notes
        self.assertIn("gradle, kotlin need one", note)
        self.assertIn("get.scoop.sh", note)

    def test_no_note_when_nothing_needs_it(self):
        with mock.patch.object(install_hints, "which", return_value=None):
            notes = install_hints.prerequisite_notes(self.WINDOWS, ["go", "node"])
        self.assertFalse(any("Scoop" in note for note in notes))

    def test_other_platforms_untouched(self):
        self.assertFalse(install_hints.needs_scoop_or_choco("gradle", platform_for("macos")))


class ProbeTest(unittest.TestCase):
    def test_missing_tool(self):
        with mock.patch.object(checks, "which", return_value=None):
            tool = checks.probe("go", ["go", "version"], hint="go")
        self.assertIs(tool.status, Status.MISSING)

    def test_found_but_broken(self):
        with mock.patch.object(checks, "which", return_value="/usr/bin/java"), \
             mock.patch.object(checks, "run", return_value=CommandResult(False, "", "Unable to locate a Java Runtime", 1)):
            tool = checks.probe("java", ["java", "-version"])
        self.assertIs(tool.status, Status.MISSING)
        self.assertIn("Unable to locate", tool.detail)

    def test_old_version_warns(self):
        with mock.patch.object(checks, "which", return_value="/usr/bin/node"), \
             mock.patch.object(checks, "run", return_value=CommandResult(True, "v18.19.0", "", 0)):
            tool = checks.probe("node", ["node", "--version"], min_version=(22,))
        self.assertIs(tool.status, Status.WARN)
        self.assertEqual(tool.version, "18.19.0")

    def test_first_available_picks_installed(self):
        missing = lambda: ToolResult("gcc", Status.MISSING)
        found = lambda: ToolResult("clang", Status.OK, version="17.0.6")
        tool = checks.first_available("C compiler", [missing, found], hint="cpp")
        self.assertEqual((tool.name, tool.detail, tool.version), ("C compiler", "clang", "17.0.6"))


class EnvStatusTest(unittest.TestCase):
    def test_aggregation(self):
        ok = ToolResult("a", Status.OK)
        optional_missing = ToolResult("b", Status.MISSING, required=False)
        required_missing = ToolResult("c", Status.MISSING)
        self.assertIs(EnvResult("x", "X", [ok]).status, Status.OK)
        self.assertIs(EnvResult("x", "X", [ok, optional_missing]).status, Status.WARN)
        self.assertIs(EnvResult("x", "X", [ok, optional_missing, required_missing]).status, Status.MISSING)


class CliTest(unittest.TestCase):
    def fake_results(self, status):
        return [EnvResult(key, title, [ToolResult("t", status, hint="go")]) for key, (title, _) in ENVIRONMENTS.items()]

    def run_cli(self, argv, status):
        with mock.patch.object(cli, "run_checks", return_value=self.fake_results(status)), \
             mock.patch("builtins.print") as printed:
            code = cli.main(argv)
        return code, printed.call_args.args[0]

    def test_exit_codes(self):
        self.assertEqual(self.run_cli(["--no-color"], Status.OK)[0], 0)
        self.assertEqual(self.run_cli(["--no-color"], Status.WARN)[0], 0)
        self.assertEqual(self.run_cli(["--no-color", "--strict"], Status.WARN)[0], 1)
        self.assertEqual(self.run_cli(["--no-color"], Status.MISSING)[0], 1)

    def test_json_output(self):
        _, output = self.run_cli(["--json"], Status.MISSING)
        data = json.loads(output)
        self.assertEqual(len(data["environments"]), len(ENVIRONMENTS))
        self.assertEqual(data["environments"][0]["status"], "missing")
        self.assertEqual(data["environments"][0]["fix"][0]["hint"], "go")

    def test_unknown_env_rejected(self):
        with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
            cli.parse_args(["--only", "cobol"])


if __name__ == "__main__":
    unittest.main()
