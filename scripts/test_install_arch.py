import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
INSTALLER = REPOSITORY / "install-arch.sh"
SKILL = REPOSITORY / "skills" / "understand-arch"


class InstallArchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.environment = dict(os.environ, CODEX_HOME=str(self.root / "codex"))
        self.target = self.root / "codex" / "skills" / "understand-arch"
        self.old_target = self.root / "codex" / "skills" / "understand-api-arch"

    def run_installer(self, *args):
        return subprocess.run(["bash", str(INSTALLER), *args], env=self.environment, text=True, capture_output=True)

    def test_install_doctor_and_uninstall(self):
        self.assertEqual(self.run_installer().returncode, 0)
        self.assertEqual(self.target.resolve(), SKILL)
        self.assertEqual(self.run_installer().returncode, 0)
        self.assertEqual(self.run_installer("--doctor").returncode, 0)
        self.assertEqual(self.run_installer("--uninstall").returncode, 0)
        self.assertFalse(self.target.is_symlink())

    def test_preserves_unrelated_target(self):
        self.target.parent.mkdir(parents=True)
        self.target.mkdir()
        self.assertNotEqual(self.run_installer().returncode, 0)
        self.assertTrue(self.target.is_dir())

    def test_install_migrates_owned_old_name(self):
        self.old_target.parent.mkdir(parents=True)
        self.old_target.symlink_to(REPOSITORY / "skills" / "understand-api-arch")

        self.assertEqual(self.run_installer().returncode, 0)
        self.assertEqual(self.target.resolve(), SKILL)
        self.assertFalse(self.old_target.is_symlink())


if __name__ == "__main__":
    unittest.main()
