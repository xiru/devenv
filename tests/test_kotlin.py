"""Kotlin: kotlinc, the JVM it needs and the runnable-jar hello world."""

import unittest
from unittest import mock

from devenv_check import checks, install_hints
from devenv_check.checks import Status, ToolResult
from devenv_check.runner import parse_version
from tests.helpers import LINUX, WINDOWS, fake_system, run_smoke, tool

INTELLIJ = ToolResult("IntelliJ IDEA (IDE)", Status.OK, required=False)


class CheckKotlinTest(unittest.TestCase):
    def check(self, outputs):
        with fake_system(outputs), mock.patch.object(checks, "check_intellij", return_value=INTELLIJ):
            return checks.check_kotlin(LINUX)

    def test_version_format(self):
        self.assertEqual(parse_version("info: kotlinc-jvm 2.1.0 (JRE 21.0.2+13-LTS)", r"kotlinc-jvm (\d+)\.(\d+)\.(\d+)"), (2, 1, 0))

    def test_installed(self):
        kotlinc, java, intellij = self.check({"kotlinc": "info: kotlinc-jvm 2.1.0 (JRE 21.0.2+13-LTS)",
                                              "java": 'openjdk version "21.0.2"'})
        self.assertEqual((kotlinc.status, kotlinc.version), (Status.OK, "2.1.0"))
        self.assertEqual((java.name, java.version), ("java (JVM for Kotlin)", "21.0.2"))
        self.assertIs(intellij, INTELLIJ)

    def test_old_kotlin_warns(self):
        kotlinc, _, _ = self.check({"kotlinc": "info: kotlinc-jvm 1.9.24 (JRE 17)", "java": 'openjdk version "17"'})
        self.assertIs(kotlinc.status, Status.WARN)

    def test_without_a_jvm(self):
        _, java, _ = self.check({"kotlinc": "info: kotlinc-jvm 2.1.0"})
        self.assertEqual((java.status, java.hint), (Status.MISSING, "java"))


class KotlinSmokeTest(unittest.TestCase):
    def test_builds_a_jar_then_runs_it(self):
        smoke_run = run_smoke("kotlin", [tool("kotlinc"), tool("java (JVM for Kotlin)")], "hello from Kotlin")
        self.assertIs(smoke_run.result.status, Status.OK)
        self.assertEqual(smoke_run.commands[0], ["/usr/bin/kotlinc", "hello.kt", "-include-runtime", "-d", "hello.jar"])
        self.assertEqual(smoke_run.commands[1], ["/usr/bin/java", "-jar", "hello.jar"])

    def test_skipped_without_java(self):
        smoke_run = run_smoke("kotlin", [tool("kotlinc"), tool("java (JVM for Kotlin)", status=Status.MISSING)])
        self.assertIs(smoke_run.result.status, Status.SKIPPED)


class KotlinHintsTest(unittest.TestCase):
    def test_windows_uses_scoop_or_choco(self):
        self.assertTrue(install_hints.needs_scoop_or_choco("kotlin", WINDOWS))
        self.assertIn("JDK", " ".join(install_hints.hint_for("kotlin", WINDOWS)))


if __name__ == "__main__":
    unittest.main()
