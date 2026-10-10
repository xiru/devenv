import tempfile
import unittest
from pathlib import Path
from unittest import mock

from devenv_check import checks, smoke
from devenv_check.checks import Status, ToolResult
from devenv_check.platform_info import PlatformInfo
from devenv_check.runner import CommandResult, parse_version

LINUX = PlatformInfo("linux", "debian", "Ubuntu", "amd64")
MACOS = PlatformInfo("macos", "macos", "macOS 15", "arm64")
WINDOWS = PlatformInfo("windows", "windows", "Windows 11", "amd64")


def ok(stdout="", stderr=""):
    return CommandResult(True, stdout, stderr, 0)


class VersionPatternTest(unittest.TestCase):
    def test_tool_version_formats(self):
        self.assertEqual(parse_version("GNU bash, version 5.2.21(1)-release (x86_64-pc-linux-gnu)", checks.BASH_VERSION), (5, 2, 21))
        self.assertEqual(parse_version("info: kotlinc-jvm 2.1.0 (JRE 21.0.2+13-LTS)", r"kotlinc-jvm (\d+)\.(\d+)\.(\d+)"), (2, 1, 0))
        self.assertEqual(parse_version("rustc 1.83.0 (90b35a623 2024-11-26)", r"rustc (\d+)\.(\d+)\.(\d+)"), (1, 83, 0))


class BashCheckTest(unittest.TestCase):
    def test_windows_prefers_git_bash_over_wsl_launcher(self):
        def fake_which(name):
            return {"bash": r"C:\Windows\System32\bash.exe"}.get(name, name if name.endswith("bash.exe") else None)

        with mock.patch.object(checks, "find_git_bash", return_value=r"C:\Program Files\Git\bin\bash.exe"), \
             mock.patch.object(checks, "which", side_effect=fake_which), \
             mock.patch.object(checks, "run", return_value=ok("GNU bash, version 5.2.37(1)-release")):
            bash = checks.check_bash(WINDOWS)[0]
        self.assertIs(bash.status, Status.OK)
        self.assertEqual(bash.provider, "Git Bash")

    def test_macos_system_bash_is_too_old(self):
        with mock.patch.object(checks, "which", side_effect=lambda n: "/bin/bash" if n == "bash" else None), \
             mock.patch.object(checks, "run", return_value=ok("GNU bash, version 3.2.57(1)-release")):
            bash = checks.check_bash(MACOS)[0]
        self.assertIs(bash.status, Status.WARN)
        self.assertIn("3.2", bash.detail)
        self.assertEqual(bash.hint, "bash")


class RustLinkerTest(unittest.TestCase):
    def test_msvc_toolchain_without_build_tools(self):
        with mock.patch.object(checks, "run", return_value=ok("rustc 1.83.0\nhost: x86_64-pc-windows-msvc\n")), \
             mock.patch.object(checks, "probe_msvc", return_value=ToolResult("MSVC", Status.MISSING)):
            linker = checks.check_rust_linker(WINDOWS, r"C:\rustc.exe")
        self.assertIs(linker.status, Status.MISSING)
        self.assertEqual(linker.hint, "cpp")
        self.assertIn("Build Tools", linker.detail)

    def test_linux_uses_cc(self):
        with mock.patch.object(checks, "run", return_value=ok("host: x86_64-unknown-linux-gnu\n")), \
             mock.patch.object(checks, "which", return_value="/usr/bin/cc"):
            linker = checks.check_rust_linker(LINUX, "/usr/bin/rustc")
        self.assertIs(linker.status, Status.OK)

    def test_missing_rustup_is_optional(self):
        def fake_which(name):
            return None if name == "rustup" else f"/usr/bin/{name}"

        outputs = {"rustc": "rustc 1.83.0 (x)", "cargo": "cargo 1.83.0 (x)"}
        with mock.patch.object(checks, "which", side_effect=fake_which), \
             mock.patch.object(checks, "run", side_effect=lambda args, **_: ok(
                 outputs.get(Path(args[0]).name, "host: x86_64-unknown-linux-gnu\nclippy 0.1.83 rustfmt 1.8.0"))):
            tools = {t.name: t for t in checks.check_rust(LINUX)}
        self.assertIs(tools["rustup"].status, Status.MISSING)
        self.assertFalse(tools["rustup"].required)
        self.assertIn("without rustup", tools["rustup"].detail)


class SmokeTest(unittest.TestCase):
    def capture(self, key, tools, stdout):
        calls = []

        def fake_run(args, timeout=30, cwd=None, **kwargs):
            calls.append((args, Path(cwd)))
            return ok(stdout)

        with mock.patch.object(smoke, "run", side_effect=fake_run):
            results = smoke.run_smoke(key, LINUX, tools)
        return results, calls

    def test_bash_script_has_lf_endings_and_is_linted(self):
        tools = [ToolResult("bash", Status.OK, path="/bin/bash", provider=None),
                 ToolResult("shellcheck (linter)", Status.OK, path="/usr/bin/shellcheck", required=False)]
        written = {}
        real_write = smoke._write

        def spy(path, text):
            written[path.name] = text
            return real_write(path, text)

        with mock.patch.object(smoke, "_write", side_effect=spy):
            (result,), calls = self.capture("bash", tools, "hello from bash")
        self.assertIs(result.status, Status.OK)
        self.assertEqual(calls[0][0][0], "/usr/bin/shellcheck")
        self.assertNotIn("\r", written["hello.sh"])

    def test_lf_written_on_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = smoke._write(Path(tmp, "x.sh"), "a\nb\n")
            self.assertEqual(path.read_bytes(), b"a\nb\n")

    def test_kotlin_builds_jar_then_runs_it(self):
        tools = [ToolResult("kotlinc", Status.OK, path="/opt/kotlinc"),
                 ToolResult("java (JVM for Kotlin)", Status.OK, path="/usr/bin/java")]
        (result,), calls = self.capture("kotlin", tools, "hello from Kotlin")
        self.assertIs(result.status, Status.OK)
        self.assertIn("-include-runtime", calls[0][0])
        self.assertEqual(calls[1][0], ["/usr/bin/java", "-jar", "hello.jar"])

    def test_kotlin_skipped_without_java(self):
        (result,), _ = self.capture("kotlin", [ToolResult("kotlinc", Status.OK, path="/opt/kotlinc"),
                                               ToolResult("java (JVM for Kotlin)", Status.MISSING)], "")
        self.assertIs(result.status, Status.SKIPPED)

    def test_rust_cargo_build_offline(self):
        (result,), calls = self.capture("rust", [ToolResult("cargo", Status.OK, path="/usr/bin/cargo")], "hello from Rust")
        self.assertIs(result.status, Status.OK)
        self.assertIn("--offline", calls[0][0])
        self.assertTrue(calls[1][0][0].endswith(str(Path("target", "debug", "hello" + smoke.EXE))))


if __name__ == "__main__":
    unittest.main()
