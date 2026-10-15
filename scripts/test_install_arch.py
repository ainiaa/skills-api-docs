import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
INSTALLER = REPOSITORY / "install-arch.sh"
SKILL = REPOSITORY / "skills" / "project-docs-diagram"


class InstallArchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.environment = dict(os.environ, CODEX_HOME=str(self.root / "codex"))
        self.target = self.root / "codex" / "skills" / "project-docs-diagram"
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
        self.assertFalse((self.target.parent / "understand-arch").is_symlink())

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

    def test_migrates_relative_previous_name_and_preserves_unrelated_old_name(self):
        self.target.parent.mkdir(parents=True)
        previous = self.target.parent / "understand-arch"
        previous.symlink_to(os.path.relpath(REPOSITORY / "skills" / "understand-arch", previous.parent.resolve()))
        unrelated = self.root / "another skill"
        unrelated.mkdir()
        self.old_target.symlink_to(unrelated)

        self.assertEqual(self.run_installer().returncode, 0)
        self.assertFalse(previous.is_symlink())
        self.assertEqual(self.target.resolve(), SKILL)
        self.assertEqual(self.old_target.resolve(), unrelated.resolve())

        self.assertEqual(self.run_installer("--uninstall").returncode, 0)
        self.assertEqual(self.old_target.resolve(), unrelated.resolve())

    def test_uninstall_preserves_legacy_link_with_physical_parent_traversal(self):
        collection = self.root / "collection"
        source = collection / "skills/project-docs-diagram"
        source.mkdir(parents=True)
        shutil.copy(INSTALLER, collection / "install-arch.sh")
        self.target.parent.mkdir(parents=True)
        self.target.symlink_to(source)
        actual = self.root / "actual"
        (actual / "nested").mkdir(parents=True)
        foreign = actual / "collection/skills/understand-api-arch"
        foreign.mkdir(parents=True)
        redirect = self.root / "redirect"
        redirect.symlink_to(actual / "nested", target_is_directory=True)
        self.old_target.symlink_to(redirect / "../collection/skills/understand-api-arch")
        self.assertEqual(self.old_target.resolve(), foreign.resolve())
        result = subprocess.run(["bash", str(collection / "install-arch.sh"), "--uninstall"],
                                env=self.environment, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.target.is_symlink())
        self.assertTrue(self.old_target.is_symlink())

    def test_uninstall_removes_owned_link_after_skill_group_is_lost(self):
        collection = self.root / "collection"
        collection.mkdir()
        shutil.copy(INSTALLER, collection / "install-arch.sh")
        self.target.parent.mkdir(parents=True)
        self.target.symlink_to(collection / "skills/project-docs-diagram")
        result = subprocess.run(["bash", str(collection / "install-arch.sh"), "--uninstall"],
                                env=self.environment, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.target.is_symlink())

    def test_doctor_rejects_skill_directory_without_entry(self):
        collection = self.root / "collection"
        source = collection / "skills/project-docs-diagram"
        source.mkdir(parents=True)
        shutil.copy(INSTALLER, collection / "install-arch.sh")
        self.target.parent.mkdir(parents=True)
        self.target.symlink_to(source)
        result = subprocess.run(["bash", str(collection / "install-arch.sh"), "--doctor"],
                                env=self.environment, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0, result.stdout)


if __name__ == "__main__":
    unittest.main()
