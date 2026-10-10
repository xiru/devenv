import tempfile
import unittest
from pathlib import Path
from unittest import mock

from devenv_check import smoke
from devenv_check.checks import EnvResult, Status, ToolResult
from devenv_check.platform_info import PlatformInfo
from devenv_check.report import Style, hello_summary, render_text
from devenv_check.runner import CommandResult

LINUX = PlatformInfo("linux", "debian", "Ubuntu", "amd64")
WINDOWS = PlatformInfo("windows", "windows", "Windows 11", "amd64")


def ok(stdout=""):
    return CommandResult(True, stdout, "", 0)


class BuildAndRunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_success_requires_expected_output(self):
        with mock.patch.object(smoke, "run", side_effect=[ok(), ok("hello from Go")]):
            result = smoke.build_and_run("hello: Go", [(["go", "build"], 1), (["./hello"], 1)], "hello from Go", self.work)
        self.assertIs(result.status, Status.OK)
        self.assertEqual(result.kind, "hello")

    def test_build_failure_reports_error_line(self):
        failure = CommandResult(False, "", "hello.c:1: warning: x\nhello.c:2: error: expected ';'", 1)
        with mock.patch.object(smoke, "run", return_value=failure):
            result = smoke.build_and_run("hello: C", [(["gcc"], 1), (["./hello"], 1)], "hello from C", self.work)
        self.assertIs(result.status, Status.MISSING)
        self.assertIn("build failed", result.detail)
        self.assertIn("error: expected", result.detail)

    def test_unexpected_output(self):
        with mock.patch.object(smoke, "run", return_value=ok("bonjour")):
            result = smoke.build_and_run("hello: JS", [(["node"], 1)], "hello from JavaScript", self.work)
        self.assertIs(result.status, Status.MISSING)
        self.assertIn("unexpected output", result.detail)


class SmokeSelectionTest(unittest.TestCase):
    def test_missing_toolchain_is_skipped(self):
        tools = [ToolResult("go", Status.MISSING)]
        (result,) = smoke.run_smoke("go", LINUX, tools)
        self.assertIs(result.status, Status.SKIPPED)

    def test_old_node_without_tsc_cannot_run_typescript(self):
        tools = [ToolResult("node", Status.WARN, version="20.11.0", path="/usr/bin/node"),
                 ToolResult("tsc (TypeScript)", Status.MISSING, required=False)]
        with mock.patch.object(smoke, "run", return_value=ok("hello from JavaScript")):
            results = smoke.run_smoke("node", LINUX, tools)
        ts = results[1]
        self.assertIs(ts.status, Status.MISSING)
        self.assertEqual(ts.hint, "typescript")

    def test_msvc_build_goes_through_vcvars(self):
        compiler = ToolResult("C compiler", Status.OK, path=r"C:\VS\BuildTools", provider="MSVC")
        with tempfile.TemporaryDirectory() as tmp:
            step = smoke._compile_step(WINDOWS, compiler, "hello.c", Path(tmp))
            script = Path(step[-1]).read_text()
        self.assertIn("vcvars64.bat", script)
        self.assertIn("cl /nologo", script)

    def test_remote_kube_context_only_dry_runs(self):
        tools = [ToolResult("kubectl", Status.OK, path="/usr/bin/kubectl"),
                 ToolResult("kube context", Status.OK, detail="prod-eu-1", required=False)]
        calls = []

        def fake_run(args, timeout=30, **kwargs):
            calls.append(args)
            return ok(f"pod/{args[args.index('run') + 1]}")

        with mock.patch.object(smoke, "run", side_effect=fake_run):
            (result,) = smoke.run_smoke("kubernetes", LINUX, tools)
        self.assertIs(result.status, Status.OK)
        self.assertTrue(all("--dry-run=server" in call for call in calls))

    def test_local_kube_context_detection(self):
        for context in ("docker-desktop", "kind-dev", "minikube", "k3d-test"):
            self.assertTrue(smoke.LOCAL_KUBE_CONTEXT.match(context), context)
        self.assertFalse(smoke.LOCAL_KUBE_CONTEXT.match("arn:aws:eks:us-east-1:1:cluster/prod"))


class ReportTest(unittest.TestCase):
    def test_hello_rows_and_summary(self):
        env = EnvResult("go", "Go", [
            ToolResult("go", Status.OK, version="1.26.0"),
            ToolResult("hello: Go", Status.MISSING, detail="build failed: boom", kind="hello", output="$ go build\nboom"),
        ])
        self.assertEqual(hello_summary(env), (0, 1, 0))
        self.assertIs(env.status, Status.MISSING)
        text = render_text(LINUX, [env], Style(color=False, unicode=False), verbose=True, hints=True)
        self.assertIn("hello world: 1 failed", text)
        self.assertIn("| boom", text)
        self.assertIn("Hello world: 0 of 1", text)

    def test_skipped_tests_do_not_change_status(self):
        env = EnvResult("go", "Go", [ToolResult("go", Status.OK), ToolResult("hello: Go", Status.SKIPPED, kind="hello")])
        self.assertIs(env.status, Status.OK)


if __name__ == "__main__":
    unittest.main()
