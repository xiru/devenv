"""report: text and JSON rendering of the results."""

import ctypes
import json
import unittest
from unittest import mock

from devenv_check import install_hints, report
from devenv_check.checks import EnvResult, Status, ToolResult
from devenv_check.report import Style, hello_summary, make_style, render_json, render_text
from tests.helpers import LINUX, WINDOWS

PLAIN = Style(color=False, unicode=False)


def text(results, platform=LINUX, *, verbose=False, hints=True, style=PLAIN):
    return render_text(platform, results, style, verbose=verbose, hints=hints)


class StyleTest(unittest.TestCase):
    def test_plain_and_unicode_symbols(self):
        self.assertEqual((PLAIN.ok, PLAIN.missing, PLAIN.sep), ("+", "x", " | "))
        fancy = Style(color=False, unicode=True)
        self.assertEqual((fancy.ok, fancy.missing, fancy.sep), ("✔", "✘", " · "))

    def test_color_codes(self):
        color = Style(color=True, unicode=False)
        self.assertEqual(color.status("ok", Status.OK), "\033[32mok\033[0m")
        self.assertEqual(color.bold("b"), "\033[1mb\033[0m")
        self.assertEqual(color.dim("d"), "\033[2md\033[0m")
        self.assertEqual(PLAIN.status("ok", Status.MISSING), "ok")

    def make_style(self, *, no_color=False, tty=True, encoding="utf-8", environ=None):
        stream = mock.Mock(encoding=encoding)
        stream.isatty.return_value = tty
        with mock.patch.object(report.sys, "stdout", stream), mock.patch.dict("os.environ", environ or {}, clear=True), \
             mock.patch.object(report, "enable_windows_ansi", return_value=True):
            return make_style(no_color)

    def test_make_style(self):
        self.assertTrue(self.make_style().color)
        self.assertTrue(self.make_style().ok == "✔")
        self.assertFalse(self.make_style(no_color=True).color)
        self.assertFalse(self.make_style(tty=False).color)
        self.assertFalse(self.make_style(environ={"NO_COLOR": "1"}).color)
        self.assertEqual(self.make_style(encoding="cp1252").ok, "+")
        self.assertEqual(self.make_style(encoding=None).ok, "+")

    def test_enable_windows_ansi_is_a_no_op_elsewhere(self):
        with mock.patch.object(report.os, "name", "posix"):
            self.assertTrue(report.enable_windows_ansi())

    def enable_windows_ansi(self, kernel32):
        # ctypes is imported before os.name is faked: on Linux it would otherwise import Windows-only parts.
        windll = mock.Mock(kernel32=kernel32)
        with mock.patch.object(ctypes, "windll", windll, create=True), mock.patch.object(report.os, "name", "nt"):
            return report.enable_windows_ansi()

    def test_enable_windows_ansi_turns_on_vt_processing(self):
        kernel32 = mock.Mock()
        kernel32.GetConsoleMode.side_effect = lambda handle, mode: setattr(mode._obj, "value", 3) or 1
        kernel32.SetConsoleMode.return_value = 1
        self.assertTrue(self.enable_windows_ansi(kernel32))
        kernel32.GetStdHandle.assert_called_once_with(-11)
        self.assertEqual(kernel32.SetConsoleMode.call_args.args[1], 3 | 0x0004)

    def test_enable_windows_ansi_without_a_console(self):
        kernel32 = mock.Mock()
        kernel32.GetConsoleMode.return_value = 0  # output redirected to a file or pipe
        self.assertFalse(self.enable_windows_ansi(kernel32))
        kernel32.SetConsoleMode.assert_not_called()

    def test_enable_windows_ansi_failure(self):
        kernel32 = mock.Mock()
        kernel32.GetStdHandle.side_effect = OSError("no console")
        self.assertFalse(self.enable_windows_ansi(kernel32))


class ToolRowsTest(unittest.TestCase):
    def test_symbols(self):
        rows = text([EnvResult("x", "X", [
            ToolResult("fine", Status.OK, version="1.0"),
            ToolResult("old", Status.WARN, detail="older than recommended"),
            ToolResult("absent", Status.MISSING),
            ToolResult("nice to have", Status.MISSING, required=False),
            ToolResult("hello: X", Status.SKIPPED, kind="hello", detail="skipped: no x"),
        ])], hints=False).splitlines()
        row = {line.split()[1]: line for line in rows if line.startswith("    ") and not line.strip().startswith("--")}
        self.assertTrue(row["fine"].startswith("    + fine"))
        self.assertIn("1.0", row["fine"])
        self.assertTrue(row["old"].startswith("    ! old"))
        self.assertTrue(row["absent"].startswith("    x absent"))
        self.assertTrue(row["nice"].startswith("    - nice to have (optional)"))
        self.assertTrue(row["hello:"].startswith("    . hello: X"))  # hello rows never say "(optional)"

    def test_verbose_shows_paths_once(self):
        env = EnvResult("go", "Go", [ToolResult("go", Status.OK, path="/usr/bin/go"),
                                     ToolResult("gopath", Status.OK, path="/home/u/go/bin", detail="/home/u/go/bin")])
        self.assertNotIn("/usr/bin/go", text([env]))
        verbose = text([env], verbose=True)
        self.assertIn("/usr/bin/go", verbose)
        self.assertEqual(verbose.count("/home/u/go/bin"), 1)


class HelloWorldRenderingTest(unittest.TestCase):
    def env(self, *statuses):
        tools = [ToolResult("go", Status.OK, version="1.26.0")]
        tools += [ToolResult(f"hello: {i}", status, kind="hello", detail=f"d{i}", output="$ go build\nboom")
                  for i, status in enumerate(statuses)]
        return EnvResult("go", "Go", tools)

    def test_summary_counts(self):
        self.assertEqual(hello_summary(self.env(Status.OK, Status.MISSING, Status.SKIPPED)), (1, 1, 1))
        self.assertEqual(hello_summary(EnvResult("x", "X", [ToolResult("x", Status.OK)])), (0, 0, 0))

    def test_failed_test_shows_its_log_in_verbose_mode(self):
        output = text([self.env(Status.MISSING)], verbose=True)
        self.assertIn("Development environment check (deep: hello world build & run)", output)
        self.assertIn("hello world: 1 failed", output)
        self.assertIn("-- hello world: build & run --", output)
        self.assertIn("| boom", output)
        self.assertIn("Hello world: 0 of 1 environments built and ran every program.", output)
        self.assertIn("could not build/run it", output)
        self.assertNotIn("| boom", text([self.env(Status.MISSING)]))

    def test_header_labels(self):
        self.assertIn("hello world: 2/2 passed", text([self.env(Status.OK, Status.OK)]))
        self.assertIn("hello world: 1/2 passed, 1 skipped", text([self.env(Status.OK, Status.SKIPPED)]))
        self.assertIn("hello world: skipped", text([self.env(Status.SKIPPED)]))

    def test_without_hello_tests_there_is_no_deep_summary(self):
        output = text([EnvResult("go", "Go", [ToolResult("go", Status.OK)])])
        self.assertNotIn("deep", output)
        self.assertNotIn("Hello world:", output)


class SummaryAndFixesTest(unittest.TestCase):
    def results(self):
        return [
            EnvResult("go", "Go", [ToolResult("go", Status.OK)]),
            EnvResult("node", "Node", [ToolResult("node", Status.MISSING, hint="node"),
                                       ToolResult("npm", Status.MISSING, hint="node")]),
            EnvResult("bash", "Bash", [ToolResult("bash", Status.OK), ToolResult("shfmt", Status.WARN, required=False,
                                                                                 hint="shell_tools")]),
            EnvResult("vscode", "VS Code", [ToolResult("ext: Go", Status.MISSING, required=False,
                                                       fix=["code --install-extension golang.go", "# a comment"])]),
        ]

    def test_summary_line(self):
        self.assertIn("Summary: 1 of 4 environments ready, 2 partial, 1 missing.", text(self.results(), hints=False))

    def test_fix_section_groups_tools_by_hint(self):
        with mock.patch.object(report, "prerequisite_notes", return_value=["install curl first"]):
            output = text(self.results())
        self.assertIn("How to fix (Ubuntu, using apt):", output)
        self.assertIn("  ! install curl first", output)
        self.assertIn("    node, npm\n", output)
        self.assertIn("      " + report.hint_for("node", LINUX)[0], output)
        self.assertIn("      docs: " + install_hints.DOCS["node"], output)
        self.assertIn("shfmt (optional)", output)
        self.assertIn("ext: Go (optional)", output)
        self.assertIn("      code --install-extension golang.go", output)
        self.assertIn("Open a new terminal after installing", output)
        self.assertNotIn("\n  Go\n", output)  # nothing to fix there

    def test_prerequisite_notes_get_the_pending_hint_keys(self):
        with mock.patch.object(report, "prerequisite_notes", return_value=[]) as notes:
            text(self.results())
        self.assertEqual(notes.call_args.args, (LINUX, ["node", "shell_tools"]))

    def test_no_hints(self):
        self.assertNotIn("How to fix", text(self.results(), hints=False))

    def test_nothing_to_fix(self):
        self.assertNotIn("How to fix", text([EnvResult("go", "Go", [ToolResult("go", Status.OK)])]))

    def test_header_shows_platform_and_python(self):
        line = text([], WINDOWS).splitlines()[1]
        self.assertTrue(line.startswith("Windows 11 | amd64 | Python 3."))


class JsonTest(unittest.TestCase):
    def test_payload(self):
        results = [EnvResult("node", "Node", [ToolResult("node", Status.MISSING, hint="node"),
                                              ToolResult("hello: JavaScript", Status.SKIPPED, kind="hello")]),
                   EnvResult("go", "Go", [ToolResult("go", Status.OK)])]
        with mock.patch.object(report, "prerequisite_notes", return_value=["note"]) as notes:
            data = json.loads(render_json(LINUX, results))
        self.assertEqual(data["platform"]["family"], "debian")
        self.assertTrue(data["python"].startswith("3."))
        node, go = data["environments"]
        self.assertEqual(node["status"], "missing")
        self.assertEqual(node["hello_world"], {"passed": 0, "failed": 0, "skipped": 1})
        self.assertEqual(node["fix"], [{"hint": "node", "tools": ["node"], "commands": report.hint_for("node", LINUX),
                                        "docs": install_hints.DOCS["node"]}])
        self.assertNotIn("hello_world", go)
        self.assertEqual(go["fix"], [])
        self.assertEqual(data["notes"], ["note"])
        self.assertEqual(notes.call_args.args, (LINUX, ["node"]))


if __name__ == "__main__":
    unittest.main()
