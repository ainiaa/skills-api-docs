import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
INSTALLER = REPOSITORY / "install.sh"


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="api docs install ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.codex_home = self.root / "codex home"
        self.target = self.codex_home / "skills" / "api-savior-docs"
        self.environment = dict(os.environ, CODEX_HOME=str(self.codex_home), HOME=str(self.root))

    def run_installer(self, *arguments):
        return subprocess.run(
            ["bash", str(INSTALLER), *arguments],
            cwd=self.root,
            env=self.environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_install_is_idempotent_and_doctor_accepts_link(self):
        first = self.run_installer()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertTrue(self.target.is_symlink())
        self.assertEqual(self.target.resolve(), REPOSITORY)

        second = self.run_installer()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(self.target.resolve(), REPOSITORY)
        self.assertEqual(self.run_installer("--doctor").returncode, 0)

    def test_install_uses_home_when_codex_home_is_unset(self):
        del self.environment["CODEX_HOME"]
        expected = self.root / ".codex" / "skills" / "api-savior-docs"

        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(expected.is_symlink())
        self.assertEqual(expected.resolve(), REPOSITORY)

    def test_install_preserves_existing_directory(self):
        self.target.mkdir(parents=True)
        sentinel = self.target / "sentinel.txt"
        sentinel.write_text("keep", encoding="utf-8")

        result = self.run_installer()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")
        self.assertFalse(self.target.is_symlink())

    def test_install_preserves_unrelated_symlink(self):
        self.target.parent.mkdir(parents=True)
        other = self.root / "other skill"
        other.mkdir()
        self.target.symlink_to(other)

        self.assertNotEqual(self.run_installer().returncode, 0)
        self.assertEqual(self.target.resolve(), other.resolve())
        self.assertNotEqual(self.run_installer("--uninstall").returncode, 0)
        self.assertEqual(self.target.resolve(), other.resolve())

    def test_install_preserves_broken_symlink(self):
        self.target.parent.mkdir(parents=True)
        missing = self.root / "missing skill"
        self.target.symlink_to(missing)

        self.assertNotEqual(self.run_installer().returncode, 0)
        self.assertTrue(self.target.is_symlink())
        self.assertEqual(self.target.readlink(), missing)

    def test_doctor_reports_version(self):
        self.run_installer()
        result = self.run_installer("--doctor")
        self.assertEqual(result.returncode, 0, result.stderr)
        version = (REPOSITORY / "VERSION").read_text(encoding="utf-8").strip()
        self.assertIn(version, result.stdout)

    def test_doctor_and_uninstall_report_missing_installation(self):
        self.assertNotEqual(self.run_installer("--doctor").returncode, 0)
        self.assertEqual(self.run_installer("--uninstall").returncode, 0)

    def test_uninstall_removes_only_own_symlink(self):
        self.assertEqual(self.run_installer().returncode, 0)
        result = self.run_installer("--uninstall")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.target.exists())
        self.assertFalse(self.target.is_symlink())
        self.assertTrue((REPOSITORY / "SKILL.md").is_file())

    def test_help_and_unknown_option(self):
        self.assertEqual(self.run_installer("--help").returncode, 0)
        self.assertNotEqual(self.run_installer("--unknown").returncode, 0)
        self.assertFalse(self.target.exists())


if __name__ == "__main__":
    unittest.main()
