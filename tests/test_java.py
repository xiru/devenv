"""Java + Gradle: java, javac, JAVA_HOME, gradle and the javac / Gradle hello worlds."""

import os
import unittest
from pathlib import Path
from unittest import mock

from devenv_check import checks, install_hints
from devenv_check.checks import Status, ToolResult
from devenv_check.runner import parse_version
from tests.helpers import FAMILIES, LINUX, MACOS, WINDOWS, TempDirMixin, fail, fake_system, ok, platform_for, run_smoke, tool

JAVA_VERSION = r'version "(\d+)(?:\.(\d+))?(?:\.(\d+))?'
JAVA_EXE = "java.exe" if os.name == "nt" else "java"
ORACLE_SETTINGS = (
    "Property settings:\n    file.encoding = UTF-8\n"
    "    java.home = C:\\Program Files\\Java\\jdk-27\n    java.version = 27\n"
    'java version "27" 2026-09-15\n'
)
INTELLIJ = ToolResult("IntelliJ IDEA (IDE)", Status.OK, required=False)


def make_jdk(root: Path) -> Path:
    (root / "bin").mkdir(parents=True)
    (root / "bin" / JAVA_EXE).touch()
    return root


class VersionTest(unittest.TestCase):
    def test_java_formats(self):
        self.assertEqual(parse_version('openjdk version "21" 2023-09-19', JAVA_VERSION), (21,))
        self.assertEqual(parse_version('openjdk version "17.0.12" 2024-07-16', JAVA_VERSION), (17, 0, 12))
        self.assertEqual(parse_version(ORACLE_SETTINGS, JAVA_VERSION), (27,))

    def test_legacy_1_x_versions(self):
        self.assertEqual(checks._java_legacy(parse_version('java version "1.8.0_381"', JAVA_VERSION)), (8, 0))
        self.assertEqual(checks._java_legacy((21, 0, 1)), (21, 0, 1))
        self.assertEqual(checks._java_legacy((1,)), (1,))


class DetectJavaHomeTest(unittest.TestCase):
    def test_home_behind_a_vendor_shim(self):
        with mock.patch.object(checks, "run", return_value=ok("", ORACLE_SETTINGS)) as run:
            home = checks.detect_java_home(r"C:\Program Files\Common Files\Oracle\Java\javapath\java.exe")
        self.assertEqual(home, r"C:\Program Files\Java\jdk-27")
        self.assertIn("-XshowSettings:properties", run.call_args.args[0])

    def test_unknown(self):
        with mock.patch.object(checks, "run", return_value=fail("Error: could not create the JVM")):
            self.assertIsNone(checks.detect_java_home("/usr/bin/java"))


class JavaHomeTest(TempDirMixin, unittest.TestCase):
    def check(self, java_home, detected=None):
        environ = {"JAVA_HOME": str(java_home)} if java_home else {}
        with mock.patch.dict("os.environ", environ, clear=True):
            return checks.check_java_home(str(detected) if detected else None)

    def test_unset(self):
        self.assertIn("not set (IDEs", self.check(None).detail)
        tool_ = self.check(None, r"C:\Program Files\Java\jdk-27")
        self.assertEqual((tool_.status, tool_.hint, tool_.required), (Status.WARN, "java_home", False))
        self.assertIn("jdk-27", tool_.detail)

    def test_valid(self):
        jdk = make_jdk(self.tmp / "jdk-21")
        tool_ = self.check(jdk, jdk)
        self.assertEqual((tool_.status, tool_.path), (Status.OK, str(jdk)))

    def test_pointing_to_another_jdk(self):
        old, new = make_jdk(self.tmp / "jdk-17"), make_jdk(self.tmp / "jdk-21")
        tool_ = self.check(old, new)
        self.assertIs(tool_.status, Status.WARN)
        self.assertIn("but the java on PATH is", tool_.detail)

    def test_parent_folder_suggests_the_jdk_inside(self):
        make_jdk(self.tmp / "Java" / "jdk-21")
        tool_ = self.check(self.tmp / "Java")
        self.assertIs(tool_.status, Status.WARN)
        self.assertIn(f"did you mean {self.tmp / 'Java' / 'jdk-21'}?", tool_.detail)

    def test_folder_that_does_not_exist(self):
        tool_ = self.check(self.tmp / "nowhere")
        self.assertIs(tool_.status, Status.WARN)
        self.assertNotIn("did you mean", tool_.detail)


class CheckJavaTest(unittest.TestCase):
    def check(self, outputs, platform=LINUX):
        with fake_system(outputs), mock.patch.object(checks, "check_intellij", return_value=INTELLIJ), \
             mock.patch.object(checks, "detect_java_home", return_value=None):
            return {t.name: t for t in checks.check_java(platform)}

    def test_full_jdk_with_gradle(self):
        tools = self.check({"java": 'openjdk version "21.0.5" 2024-10-15', "javac": "javac 21.0.5",
                            "gradle": "\n------\nGradle 8.11.1\n------\n"})
        self.assertEqual((tools["java"].version, tools["javac (JDK)"].version, tools["gradle"].version),
                         ("21.0.5", "21.0.5", "8.11.1"))
        self.assertEqual(list(tools), ["java", "javac (JDK)", "JAVA_HOME", "gradle", "IntelliJ IDEA (IDE)"])

    def test_old_java_warns(self):
        self.assertIs(self.check({"java": 'java version "1.8.0_381"', "javac": "javac 1.8.0_381"})["java"].status, Status.WARN)

    def test_jre_only(self):
        tools = self.check({"java": 'openjdk version "21.0.5"'})
        self.assertIs(tools["javac (JDK)"].status, Status.MISSING)
        self.assertIn("only a JRE", tools["javac (JDK)"].detail)

    def test_nothing_installed(self):
        tools = self.check({})
        self.assertNotIn("only a JRE", tools["javac (JDK)"].detail)
        self.assertIs(tools["gradle"].status, Status.MISSING)

    def test_detected_home_is_compared_with_java_home(self):
        with fake_system({"java": 'openjdk version "21"', "javac": "javac 21"}), \
             mock.patch.object(checks, "check_intellij", return_value=INTELLIJ), \
             mock.patch.object(checks, "detect_java_home", return_value="/usr/lib/jvm/21") as detect, \
             mock.patch.object(checks, "check_java_home", return_value=ToolResult("JAVA_HOME", Status.OK)) as java_home:
            checks.check_java(LINUX)
        detect.assert_called_once_with("/usr/bin/java")
        java_home.assert_called_once_with("/usr/lib/jvm/21")

    def test_macos_stub_without_a_jdk_is_never_run(self):
        tools = self.check({"java": "would open a dialog", "java_home": fail("Unable to find any JVMs")}, MACOS)
        self.assertIs(tools["java"].status, Status.MISSING)
        self.assertIn("macOS stub", tools["java"].detail)


class JavaSmokeTest(unittest.TestCase):
    def output(self, args):
        return "hello from Gradle" if "run" in args else "hello from Java"

    def test_javac_and_gradle(self):
        smoke_run = run_smoke("java", [tool("java"), tool("javac (JDK)"), tool("gradle")], self.output)
        javac, gradle = smoke_run.results
        self.assertEqual((javac.status, gradle.status), (Status.OK, Status.OK))
        self.assertEqual(smoke_run.commands[0], ["/usr/bin/javac", "Hello.java"])
        self.assertEqual(smoke_run.commands[1], ["/usr/bin/java", "-cp", ".", "Hello"])
        self.assertIn("--offline", smoke_run.commands[2])
        self.assertIn("--no-daemon", smoke_run.commands[2])  # no JVM left running afterwards
        self.assertIn("mainClass = 'Hello'", smoke_run.written["build.gradle"])

    def test_without_a_jdk_or_gradle(self):
        javac, gradle = run_smoke("java", [tool("java"), tool("javac (JDK)", status=Status.MISSING)]).results
        self.assertEqual((javac.status, gradle.status), (Status.SKIPPED, Status.SKIPPED))


class JavaHintsTest(unittest.TestCase):
    def test_gradle_on_windows_uses_scoop_or_choco(self):
        self.assertTrue(install_hints.needs_scoop_or_choco("gradle", WINDOWS))

    def test_jvm_hints_never_suggest_vscode(self):
        for family in FAMILIES:
            platform = platform_for(family)
            for key in ("java", "java_home", "gradle", "kotlin", "intellij", "intellij_update"):
                hint = " ".join(install_hints.hint_for(key, platform)).lower()
                with self.subTest(family=family, key=key):
                    self.assertNotIn("code --install-extension", hint)
                    self.assertNotIn("visual studio code", hint)


if __name__ == "__main__":
    unittest.main()
