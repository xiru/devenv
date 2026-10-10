"""Rust: rustc, cargo, rustup, the linker, clippy / rustfmt and the cargo hello world."""

import os
import unittest
from pathlib import Path
from unittest import mock

from devenv_check import checks
from devenv_check.checks import Status, ToolResult
from devenv_check.runner import parse_version
from tests.helpers import LINUX, MACOS, WINDOWS, fail, fake_system, ok, run_smoke, tool

RUST_TOOLS = {"rustc": "rustc 1.83.0 (90b35a623 2024-11-26)\nhost: x86_64-unknown-linux-gnu",
              "cargo": "cargo 1.83.0 (5ffbef321 2024-10-29)", "rustup": "rustup 1.27.1 (54dd3d00f 2024-04-24)"}


class CheckRustTest(unittest.TestCase):
    def check(self, outputs):
        with fake_system(outputs), mock.patch.object(checks, "check_rust_linker",
                                                     return_value=ToolResult("linker", Status.OK)):
            return {t.name: t for t in checks.check_rust(LINUX)}

    def test_version_format(self):
        self.assertEqual(parse_version("rustc 1.83.0 (90b35a623 2024-11-26)", r"rustc (\d+)\.(\d+)\.(\d+)"), (1, 83, 0))

    def test_full_toolchain(self):
        tools = self.check(RUST_TOOLS)
        self.assertEqual(list(tools), ["rustc", "cargo", "rustup", "linker", "clippy (linter)", "rustfmt (formatter)"])
        self.assertEqual((tools["rustc"].version, tools["cargo"].version, tools["rustup"].version), ("1.83.0", "1.83.0", "1.27.1"))
        self.assertFalse(tools["clippy (linter)"].required)

    def test_missing_rustup_is_optional(self):
        tools = self.check({k: v for k, v in RUST_TOOLS.items() if k != "rustup"})
        self.assertEqual((tools["rustup"].status, tools["rustup"].required), (Status.MISSING, False))
        self.assertIn("without rustup", tools["rustup"].detail)

    def test_nothing_installed(self):
        tools = self.check({})
        self.assertEqual(list(tools), ["rustc", "cargo", "rustup"])
        self.assertNotIn("without rustup", tools["rustup"].detail)


class RustLinkerTest(unittest.TestCase):
    def linker(self, platform, host, *, msvc=Status.MISSING, which=None, xcode=True):
        def run(args, **kwargs):
            if args[0] == "xcode-select":
                return ok("/Library/Developer/CommandLineTools") if xcode else fail("no developer tools")
            return ok(f"rustc 1.83.0\nhost: {host}\n")

        with mock.patch.object(checks, "run", side_effect=run), \
             mock.patch.object(checks, "probe_msvc", return_value=ToolResult("MSVC", msvc, version="17.12")), \
             mock.patch.object(checks, "which", side_effect=lambda name: (which or {}).get(name)):
            return checks.check_rust_linker(platform, "rustc")

    def test_msvc_toolchain_with_build_tools(self):
        linker = self.linker(WINDOWS, "x86_64-pc-windows-msvc", msvc=Status.OK)
        self.assertEqual((linker.status, linker.version), (Status.OK, "17.12"))

    def test_msvc_toolchain_without_build_tools(self):
        linker = self.linker(WINDOWS, "x86_64-pc-windows-msvc")
        self.assertEqual((linker.status, linker.hint), (Status.MISSING, "cpp"))
        self.assertIn("Build Tools", linker.detail)

    def test_gnu_toolchain_on_windows_uses_gcc(self):
        linker = self.linker(WINDOWS, "x86_64-pc-windows-gnu", which={"gcc": r"C:\msys64\ucrt64\bin\gcc.exe"})
        self.assertIs(linker.status, Status.OK)

    def test_linux_uses_cc(self):
        linker = self.linker(LINUX, "x86_64-unknown-linux-gnu", which={"cc": "/usr/bin/cc"})
        self.assertEqual((linker.status, linker.detail), (Status.OK, "cc (x86_64-unknown-linux-gnu)"))

    def test_linux_without_cc(self):
        linker = self.linker(LINUX, "x86_64-unknown-linux-gnu")
        self.assertEqual((linker.status, linker.hint), (Status.MISSING, "cpp"))

    def test_unknown_host(self):
        with mock.patch.object(checks, "run", return_value=fail()), mock.patch.object(checks, "which", return_value="/usr/bin/cc"):
            self.assertIn("unknown host", checks.check_rust_linker(LINUX, "rustc").detail)

    def test_macos_needs_command_line_tools(self):
        linker = self.linker(MACOS, "aarch64-apple-darwin", xcode=False)
        self.assertEqual((linker.status, linker.detail), (Status.MISSING, "Xcode Command Line Tools not installed"))
        self.assertIs(self.linker(MACOS, "aarch64-apple-darwin", which={"cc": "/usr/bin/cc"}).status, Status.OK)


class RustSmokeTest(unittest.TestCase):
    def test_offline_cargo_build_then_run(self):
        smoke_run = run_smoke("rust", [tool("cargo")], "hello from Rust")
        self.assertIs(smoke_run.result.status, Status.OK)
        build, binary = smoke_run.calls
        self.assertEqual(build.args, ["/usr/bin/cargo", "build", "--offline", "--quiet"])
        self.assertEqual(build.env, {"CARGO_TERM_COLOR": "never"})
        self.assertTrue(binary.args[0].endswith(str(Path("target", "debug", "hello" + (".exe" if os.name == "nt" else "")))))
        self.assertIn("[package]", smoke_run.written["Cargo.toml"])

    def test_skipped_without_cargo(self):
        self.assertIs(run_smoke("rust", [tool("cargo", status=Status.MISSING)]).result.status, Status.SKIPPED)


if __name__ == "__main__":
    unittest.main()
