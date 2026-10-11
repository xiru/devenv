"""install_hints: per-platform install commands, their lookup order and the prerequisite notes.

Language-specific hint content is tested next to each language; this file covers the tables as a whole.
"""

import unittest
from unittest import mock

from devenv_check import install_hints
from devenv_check.install_hints import hint_for, manager_label, prerequisite_notes
from devenv_check.platform_info import PlatformInfo
from tests.helpers import FAMILIES, LINUX, MACOS, WINDOWS, WSL, platform_for


def installed(*names):
    """Patch install_hints.which so only `names` are on PATH."""
    return mock.patch.object(install_hints, "which", side_effect=lambda n: f"/bin/{n}" if n in names else None)


class CoverageTest(unittest.TestCase):
    def test_every_key_has_a_hint_on_every_family(self):
        for family in FAMILIES:
            for key in install_hints.DOCS:
                with self.subTest(family=family, key=key):
                    self.assertTrue(hint_for(key, platform_for(family)))

    def test_every_key_has_a_hint_under_wsl(self):
        for key in install_hints.DOCS:
            with self.subTest(key=key):
                self.assertTrue(hint_for(key, WSL))

    def test_every_hint_used_by_a_table_has_docs(self):
        for family, table in install_hints.HINTS.items():
            for key in table:
                with self.subTest(family=family, key=key):
                    self.assertIn(key, install_hints.DOCS)

    def test_unknown_key(self):
        self.assertEqual(hint_for("cobol", LINUX), [])


class LookupOrderTest(unittest.TestCase):
    def test_wsl_then_distro_family_then_generic_linux(self):
        self.assertTrue(any("WSL integration" in line for line in hint_for("docker_daemon", WSL)))
        self.assertTrue(any("apt" in line for line in hint_for("cpp", WSL)))
        self.assertTrue(any("get-helm-3" in line or "snap" in line for line in hint_for("helm", WSL)))
        self.assertFalse(any("WSL" in line for line in hint_for("docker_daemon", LINUX)))

    def test_generic_linux_fills_gaps_of_a_family(self):
        gaps = [key for key in install_hints.HINTS["linux"] if key not in install_hints.HINTS["suse"]]
        self.assertTrue(gaps)
        for key in gaps:
            with self.subTest(key=key):
                expected = [line.replace("{arch}", "amd64") for line in install_hints.HINTS["linux"][key]]
                self.assertEqual(hint_for(key, platform_for("suse")), expected)

    def test_generic_linux_is_never_used_for_macos_or_windows(self):
        for platform in (MACOS, WINDOWS):
            for key, lines in install_hints.HINTS["linux"].items():
                if key not in install_hints.HINTS[platform.family]:
                    with self.subTest(family=platform.family, key=key):
                        self.assertEqual(hint_for(key, platform), [])

    def test_arch_placeholder_is_filled(self):
        lines = hint_for("kubectl", platform_for("linux", arch="arm64"))
        self.assertTrue(any("linux/arm64/kubectl" in line for line in lines))
        self.assertFalse(any("{arch}" in line for family in FAMILIES for line in hint_for("kubectl", platform_for(family))))


class ScoopOrChocoTest(unittest.TestCase):
    """Gradle and Kotlin are not in winget: the command follows whichever of Scoop / Chocolatey exists."""

    def hints_with(self, *names, key="gradle"):
        with installed(*names):
            return hint_for(key, WINDOWS), prerequisite_notes(WINDOWS, ["gradle", "kotlin", "go", "gradle"])

    def test_scoop_installed(self):
        lines, notes = self.hints_with("winget", "scoop", "choco")
        self.assertEqual(lines[0], "scoop install gradle")
        self.assertEqual(notes, [])

    def test_only_choco_installed(self):
        lines, notes = self.hints_with("winget", "choco", key="kotlin")
        self.assertEqual(lines[0], "choco install kotlinc -y   (from an elevated terminal)")
        self.assertEqual(lines[1:], install_hints.HINTS["windows"]["kotlin"][1:])  # other lines are kept
        self.assertEqual(notes, [])

    def test_neither_installed_bootstraps_scoop_once(self):
        lines, notes = self.hints_with("winget")
        self.assertEqual(lines[0], "scoop install gradle")
        (note,) = notes
        self.assertIn("gradle, kotlin need one", note)
        self.assertIn("get.scoop.sh", note)

    def test_no_note_when_nothing_needs_it(self):
        with installed("winget"):
            self.assertEqual(prerequisite_notes(WINDOWS, ["go", "node"]), [])

    def test_lines_without_the_choice_are_untouched(self):
        with installed("winget", "choco"):
            self.assertEqual(hint_for("go", WINDOWS), install_hints.HINTS["windows"]["go"])

    def test_other_platforms_untouched(self):
        self.assertFalse(install_hints.needs_scoop_or_choco("gradle", MACOS))
        self.assertTrue(install_hints.needs_scoop_or_choco("gradle", WINDOWS))

    def test_scoop_is_preferred(self):
        with installed("scoop", "choco"):
            self.assertEqual(install_hints.windows_extra_manager(), "scoop")
        with installed():
            self.assertIsNone(install_hints.windows_extra_manager())


class PrerequisiteNotesTest(unittest.TestCase):
    def test_windows_without_winget(self):
        with installed("scoop"):
            (note,) = prerequisite_notes(WINDOWS)
        self.assertIn("App Installer", note)

    def test_macos_without_homebrew(self):
        with installed():
            (note,) = prerequisite_notes(MACOS)
        self.assertIn("Homebrew/install", note)
        with installed("brew"):
            self.assertEqual(prerequisite_notes(MACOS), [])

    def test_linux_without_curl(self):
        with installed():
            (debian,) = prerequisite_notes(LINUX)
            (fedora,) = prerequisite_notes(platform_for("fedora"))
        self.assertIn("sudo apt install -y curl", debian)
        self.assertIn("install curl first", fedora)
        with installed("curl"):
            self.assertEqual(prerequisite_notes(LINUX), [])

    def test_wsl_explains_that_windows_tools_do_not_count(self):
        with installed("curl"):
            (note,) = prerequisite_notes(WSL)
        self.assertIn("Running inside WSL", note)


class ManagerLabelTest(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(manager_label(WINDOWS), "winget")
        self.assertEqual(manager_label(MACOS), "Homebrew")
        self.assertEqual(manager_label(LINUX), "apt")
        self.assertEqual(manager_label(WSL), "apt inside WSL")
        self.assertEqual(manager_label(platform_for("linux")), "generic installers")
        self.assertEqual(manager_label(PlatformInfo("freebsd", "freebsd", "FreeBSD", "amd64")), "freebsd")


if __name__ == "__main__":
    unittest.main()
