"""Environment results and the check registry: status aggregation and running checks in parallel."""

import unittest
from unittest import mock

from devenv_check import checks, smoke
from devenv_check.checks import ENVIRONMENTS, EnvResult, Status, ToolResult
from tests.helpers import LINUX


class EnvStatusTest(unittest.TestCase):
    def test_aggregation(self):
        ok = ToolResult("a", Status.OK)
        warn = ToolResult("b", Status.WARN)
        optional_missing = ToolResult("c", Status.MISSING, required=False)
        required_missing = ToolResult("d", Status.MISSING)
        self.assertIs(EnvResult("x", "X", [ok]).status, Status.OK)
        self.assertIs(EnvResult("x", "X", [ok, warn]).status, Status.WARN)
        self.assertIs(EnvResult("x", "X", [ok, optional_missing]).status, Status.WARN)
        self.assertIs(EnvResult("x", "X", [ok, optional_missing, required_missing]).status, Status.MISSING)
        self.assertIs(EnvResult("x", "X", []).status, Status.OK)

    def test_skipped_rows_never_change_the_status(self):
        skipped = ToolResult("hello: Go", Status.SKIPPED, kind="hello")
        self.assertIs(EnvResult("go", "Go", [ToolResult("go", Status.OK), skipped]).status, Status.OK)

    def test_to_dict(self):
        data = EnvResult("go", "Go", [ToolResult("go", Status.WARN, version="1.21")]).to_dict()
        self.assertEqual((data["key"], data["title"], data["status"]), ("go", "Go", "warn"))
        self.assertEqual(data["tools"][0]["version"], "1.21")


class RegistryTest(unittest.TestCase):
    def test_every_environment_has_a_title_and_a_check(self):
        for key, (title, check) in ENVIRONMENTS.items():
            with self.subTest(key=key):
                self.assertTrue(title)
                self.assertTrue(callable(check))

    def test_every_smoke_test_belongs_to_an_environment(self):
        self.assertLessEqual(set(smoke.SMOKE_TESTS), set(ENVIRONMENTS))
        self.assertEqual(set(ENVIRONMENTS) - set(smoke.SMOKE_TESTS), {"vscode"})  # nothing to build for an editor


class RunChecksTest(unittest.TestCase):
    def fake_registry(self, **checks_by_key):
        return mock.patch.dict(ENVIRONMENTS, {key: (key.title(), check) for key, check in checks_by_key.items()}, clear=True)

    def test_runs_the_selected_checks_in_order(self):
        with self.fake_registry(a=lambda p: [ToolResult("a", Status.OK)], b=lambda p: [ToolResult("b", Status.WARN)],
                                c=lambda p: [ToolResult("c", Status.OK)]):
            results = checks.run_checks(LINUX, ["c", "a"])
        self.assertEqual([(env.key, env.title, env.tools[0].name) for env in results], [("c", "C", "c"), ("a", "A", "a")])

    def test_all_environments_by_default(self):
        with self.fake_registry(a=lambda p: [], b=lambda p: []):
            self.assertEqual([env.key for env in checks.run_checks(LINUX)], ["a", "b"])

    def test_a_crashing_check_is_reported_without_hiding_the_others(self):
        def boom(p):
            raise RuntimeError("boom")

        with self.fake_registry(bad=boom, good=lambda p: [ToolResult("good", Status.OK)]):
            bad, good = checks.run_checks(LINUX, ["bad", "good"])
        self.assertIs(bad.status, Status.MISSING)
        self.assertIn("internal error: RuntimeError('boom')", bad.tools[0].detail)
        self.assertIs(good.status, Status.OK)

    def test_checks_receive_the_platform(self):
        seen = []
        with self.fake_registry(a=lambda p: seen.append(p) or []):
            checks.run_checks(LINUX, ["a"])
        self.assertEqual(seen, [LINUX])

    def test_deep_appends_hello_world_results(self):
        hello = ToolResult("hello: A", Status.OK, kind="hello")
        with self.fake_registry(a=lambda p: [ToolResult("a", Status.OK)]), \
             mock.patch.object(smoke, "run_smoke", return_value=[hello]) as run_smoke:
            (shallow,) = checks.run_checks(LINUX, ["a"])
            (deep,) = checks.run_checks(LINUX, ["a"], deep=True)
        self.assertEqual([t.name for t in shallow.tools], ["a"])
        self.assertEqual([t.name for t in deep.tools], ["a", "hello: A"])
        self.assertEqual(run_smoke.call_args.args[:2], ("a", LINUX))


if __name__ == "__main__":
    unittest.main()
