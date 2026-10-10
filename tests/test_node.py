"""JavaScript / TypeScript: node, npm, npx and the JavaScript / TypeScript hello worlds.

TypeScript itself is never checked: projects install it locally (npm install --save-dev typescript).
"""

import unittest

from devenv_check import checks, install_hints
from devenv_check.checks import Status
from tests.helpers import FAMILIES, LINUX, fake_system, platform_for, run_smoke, tool


class CheckNodeTest(unittest.TestCase):
    def test_node_npm_npx(self):
        with fake_system({"node": "v24.4.0", "npm": "11.4.2", "npx": "11.4.2"}):
            node, npm, npx = checks.check_node(LINUX)
        self.assertEqual([(t.name, t.status, t.version) for t in (node, npm, npx)],
                         [("node", Status.OK, "24.4.0"), ("npm", Status.OK, "11.4.2"), ("npx", Status.OK, "11.4.2")])

    def test_old_node_warns(self):
        with fake_system({"node": "v20.11.0", "npm": "10.2.4", "npx": "10.2.4"}):
            node, _, _ = checks.check_node(LINUX)
        self.assertIs(node.status, Status.WARN)

    def test_typescript_is_not_checked(self):
        with fake_system({"node": "v24.4.0", "npm": "11.4.2", "npx": "11.4.2", "tsc": "Version 5.7.2"}) as calls:
            tools = checks.check_node(LINUX)
        self.assertFalse(any("tsc" in t.name or "TypeScript" in t.name for t in tools))
        self.assertFalse(any(call[0].endswith("tsc") for call in calls))


class NodeSmokeTest(unittest.TestCase):
    def output(self, args):
        return "hello from TypeScript" if args[-1] == "hello.ts" else "hello from JavaScript"

    def smoke(self, version):
        return run_smoke("node", [tool("node", version=version)], self.output)

    def test_javascript(self):
        smoke_run = self.smoke("24.4.0")
        self.assertEqual(smoke_run.commands[0], ["/usr/bin/node", "hello.js"])
        self.assertIs(smoke_run.results[0].status, Status.OK)

    def test_typescript_with_built_in_type_stripping(self):
        for version in ("24.4.0", "23.6.0", "22.18.0"):
            with self.subTest(version=version):
                smoke_run = self.smoke(version)
                self.assertIs(smoke_run.results[1].status, Status.OK)
                self.assertEqual(smoke_run.commands[-1], ["/usr/bin/node", "hello.ts"])

    def test_typescript_with_the_experimental_flag(self):
        for version in ("22.6.0", "22.17.1", "23.5.0"):
            with self.subTest(version=version):
                smoke_run = self.smoke(version)
                self.assertEqual(smoke_run.commands[-1], ["/usr/bin/node", "--experimental-strip-types", "hello.ts"])

    def test_old_node_skips_typescript(self):
        smoke_run = self.smoke("20.11.0")
        self.assertIs(smoke_run.results[1].status, Status.SKIPPED)
        self.assertIn("local TypeScript", smoke_run.results[1].detail)
        self.assertEqual(len(smoke_run.commands), 1)  # never looks for a global tsc

    def test_skipped_without_node(self):
        smoke_run = run_smoke("node", [tool("node", status=Status.MISSING)])
        self.assertEqual([r.status for r in smoke_run.results], [Status.SKIPPED, Status.SKIPPED])


class NodeHintsTest(unittest.TestCase):
    def test_never_installs_typescript_globally(self):
        for family in FAMILIES:
            hint = " ".join(install_hints.hint_for("node", platform_for(family)))
            with self.subTest(family=family):
                self.assertTrue(hint)
                self.assertNotIn("typescript", hint.lower())
        self.assertNotIn("typescript", install_hints.DOCS)


if __name__ == "__main__":
    unittest.main()
