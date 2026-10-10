"""C / C++: compilers (gcc, clang, MSVC), cmake, make / ninja and the C / C++ hello worlds."""

import json
import os
import unittest
from pathlib import Path
from unittest import mock

from devenv_check import checks, smoke
from devenv_check.checks import Status, ToolResult
from tests.helpers import LINUX, MACOS, WINDOWS, TempDirMixin, fail, fake_system, ok, platform_for, run_smoke, tool

EXE = ".exe" if os.name == "nt" else ""
VS_INSTANCE = {"installationVersion": "17.12.35527.113", "installationPath": r"C:\BuildTools",
               "displayName": "Visual Studio Build Tools 2022"}


class CheckCppTest(unittest.TestCase):
    def check(self, outputs, platform=LINUX, msvc=Status.MISSING):
        def probe_msvc():  # a fresh result per call: first_available renames what it returns
            return ToolResult("MSVC", msvc, path=r"C:\BuildTools")

        with fake_system(outputs), mock.patch.object(checks, "probe_msvc", side_effect=probe_msvc):
            return {t.name: t for t in checks.check_cpp(platform)}

    def test_linux_gcc_and_make(self):
        tools = self.check({"gcc": "gcc (Ubuntu 13.3.0-6ubuntu2) 13.3.0", "g++": "g++ 13.3.0", "cmake": "cmake version 3.28.3",
                            "make": "GNU Make 4.3"})
        self.assertEqual((tools["C compiler"].provider, tools["C++ compiler"].provider), ("gcc", "g++"))
        self.assertEqual(tools["make / ninja"].provider, "make")
        self.assertEqual(tools["cmake"].version, "3.28.3")

    def test_clang_and_ninja_as_fallbacks(self):
        tools = self.check({"clang": "clang version 18.1.3", "clang++": "clang version 18.1.3", "ninja": "1.11.1"})
        self.assertEqual((tools["C compiler"].provider, tools["make / ninja"].provider), ("clang", "ninja"))

    def test_nothing_installed(self):
        tools = self.check({})
        self.assertEqual(tools["C compiler"].detail, "no gcc, clang or MSVC found")
        self.assertFalse(tools["cmake"].required or tools["make / ninja"].required)

    def test_macos_prefers_clang(self):
        tools = self.check({"xcode-select": "/Library/Developer/CommandLineTools", "gcc": "Apple clang version 16.0.0",
                            "clang": "Apple clang version 16.0.0", "clang++": "Apple clang version 16.0.0"}, MACOS)
        self.assertEqual(tools["C compiler"].provider, "clang")

    def test_macos_without_command_line_tools_runs_no_compiler(self):
        with fake_system({"xcode-select": fail("no developer tools"), "gcc": "would open a dialog"}) as calls:
            tools = {t.name: t for t in checks.check_cpp(MACOS)}
        self.assertEqual(tools["C compiler"].detail, "Xcode Command Line Tools not installed")
        self.assertFalse(any(call[0].endswith("gcc") for call in calls))

    def test_windows_prefers_msvc_and_accepts_mingw_make(self):
        tools = self.check({"gcc": "gcc 14.2.0", "mingw32-make": "GNU Make 4.4.1"}, WINDOWS, msvc=Status.OK)
        self.assertEqual((tools["C compiler"].provider, tools["C++ compiler"].provider), ("MSVC", "MSVC"))
        self.assertEqual(tools["make / ninja"].provider, "mingw32-make")

    def test_windows_cl_on_path(self):
        tools = self.check({"cl": fail("Microsoft (R) C/C++ Optimizing Compiler Version 19.44.35211 for x64")}, WINDOWS)
        self.assertEqual((tools["C compiler"].provider, tools["C compiler"].version), ("cl", "19.44.35211"))


class ProbeMsvcTest(TempDirMixin, unittest.TestCase):
    def probe(self, result=None, vswhere=True):
        if vswhere:
            installer = self.tmp / "Microsoft Visual Studio" / "Installer"
            installer.mkdir(parents=True, exist_ok=True)
            (installer / "vswhere.exe").touch()
        with mock.patch.dict(os.environ, {"ProgramFiles(x86)": str(self.tmp)}),              mock.patch.object(checks, "run", return_value=result) as run:
            return checks.probe_msvc(), run

    def test_build_tools_with_the_cpp_workload(self):
        msvc, run = self.probe(ok(json.dumps([VS_INSTANCE])))
        self.assertEqual((msvc.status, msvc.version, msvc.path), (Status.OK, "17.12.35527.113", r"C:\BuildTools"))
        self.assertIn("Developer PowerShell", msvc.detail)
        self.assertIn("Microsoft.VisualStudio.Component.VC.Tools.x86.x64", run.call_args.args[0])

    def test_without_vswhere(self):
        msvc, run = self.probe(vswhere=False)
        self.assertIs(msvc.status, Status.MISSING)
        run.assert_not_called()

    def test_no_instance_or_bad_output(self):
        for result in (ok("[]"), ok("not json"), ok(""), fail("boom")):
            with self.subTest(result=result):
                self.assertIs(self.probe(result)[0].status, Status.MISSING)


class CompileStepTest(TempDirMixin, unittest.TestCase):
    def test_gcc_and_clang(self):
        step = smoke._compile_step(LINUX, tool("C compiler", "/usr/bin/clang", provider="clang"), "hello.c", self.tmp)
        self.assertEqual(step, ["/usr/bin/clang", "hello.c", "-o", f"hello{EXE}"])

    def test_cl_on_path(self):
        step = smoke._compile_step(WINDOWS, tool("C compiler", r"C:\VS\cl.exe", provider="cl"), "hello.c", self.tmp)
        self.assertEqual(step, [r"C:\VS\cl.exe", "/nologo", "/EHsc", "hello.c", "/Fe:hello.exe"])

    def test_msvc_goes_through_vcvars(self):
        compiler = tool("C compiler", r"C:\VS\BuildTools", provider="MSVC")
        step = smoke._compile_step(WINDOWS, compiler, "hello.cpp", self.tmp)
        script = Path(step[-1]).read_bytes()
        self.assertEqual(step[1:3], ["/d", "/c"])
        self.assertIn(b"vcvars64.bat", script)
        self.assertIn(b"cl /nologo /EHsc hello.cpp /Fe:hello.exe\r\n", script)  # batch files need CRLF

    def test_msvc_on_arm64(self):
        compiler = tool("C compiler", r"C:\VS\BuildTools", provider="MSVC")
        step = smoke._compile_step(platform_for("windows", arch="arm64"), compiler, "hello.c", self.tmp)
        self.assertIn(b"vcvarsarm64.bat", Path(step[-1]).read_bytes())


class CppSmokeTest(unittest.TestCase):
    def output(self, args):
        return "hello from C++" if Path(args[0]).parent.name == "hello_cpp" or "hello.cpp" in args else "hello from C"

    def test_c_and_cpp(self):
        smoke_run = run_smoke("cpp", [tool("C compiler", "/usr/bin/gcc", provider="gcc"),
                                      tool("C++ compiler", "/usr/bin/g++", provider="g++")], self.output)
        c, cpp = smoke_run.results
        self.assertEqual((c.status, cpp.status), (Status.OK, Status.OK))
        self.assertEqual((c.detail, cpp.detail), ("compiled with gcc", "compiled with g++"))
        self.assertEqual(smoke_run.commands[0], ["/usr/bin/gcc", "hello.c", "-o", f"hello{EXE}"])
        self.assertTrue(smoke_run.commands[1][0].endswith(str(Path("hello_c", f"hello{EXE}"))))
        self.assertEqual(smoke_run.written["hello.cpp"], smoke.CPP_SOURCE)

    def test_missing_compilers_are_skipped(self):
        c, cpp = run_smoke("cpp", [tool("C compiler", status=Status.MISSING)]).results
        self.assertEqual((c.status, cpp.status), (Status.SKIPPED, Status.SKIPPED))
        self.assertEqual(cpp.detail, "skipped: no c++ compiler")


if __name__ == "__main__":
    unittest.main()
