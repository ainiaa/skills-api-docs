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
        self.claude_home = self.root / "claude home"
        self.target = self.codex_home / "skills" / "understand-docs"
        self.arch_target = self.codex_home / "skills" / "understand-arch"
        self.project_target = self.codex_home / "skills" / "understand-project"
        self.claude_docs_target = self.claude_home / "skills" / "understand-docs"
        self.claude_arch_target = self.claude_home / "skills" / "understand-arch"
        self.claude_project_target = self.claude_home / "skills" / "understand-project"
        self.old_target = self.codex_home / "skills" / "api-savior-docs"
        self.previous_target = self.codex_home / "skills" / "understand-api-docs"
        self.old_arch_target = self.codex_home / "skills" / "understand-api-arch"
        self.environment = dict(os.environ, CODEX_HOME=str(self.codex_home),
                                CLAUDE_HOME=str(self.claude_home), HOME=str(self.root),
                                UNDERSTAND_RENDERER_HOME=str(self.root / "renderers"))

    def run_installer(self, *arguments, isolated=True):
        options = ["--host", "codex", "--no-engines"] if isolated else []
        return subprocess.run(
            ["bash", str(INSTALLER), *arguments, *options],
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
        self.assertTrue(self.arch_target.is_symlink())
        self.assertEqual(self.arch_target.resolve(), REPOSITORY / "skills" / "understand-arch")
        self.assertTrue(self.project_target.is_symlink())
        self.assertEqual(self.project_target.resolve(), REPOSITORY / "skills" / "understand-project")
        self.assertTrue((self.project_target / "assets" / "project-overview.md").is_file())
        self.assertTrue((self.project_target / "assets" / "feature-description.md").is_file())
        self.assertTrue((self.project_target / "assets" / "developer-guide.md").is_file())
        self.assertTrue((self.project_target / "../../scripts/project_doc_context.py").resolve().is_file())
        self.assertTrue((self.project_target / "../../scripts/project_doc_impact.py").resolve().is_file())

        second = self.run_installer()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(self.target.resolve(), REPOSITORY)
        self.assertEqual(self.arch_target.resolve(), REPOSITORY / "skills" / "understand-arch")
        self.assertEqual(self.project_target.resolve(), REPOSITORY / "skills" / "understand-project")
        self.assertEqual(self.run_installer("--doctor").returncode, 0)

    def test_install_uses_home_when_codex_home_is_unset(self):
        del self.environment["CODEX_HOME"]
        expected = self.root / ".codex" / "skills" / "understand-docs"

        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(expected.is_symlink())
        self.assertEqual(expected.resolve(), REPOSITORY)
        arch_expected = self.root / ".codex" / "skills" / "understand-arch"
        self.assertTrue(arch_expected.is_symlink())
        self.assertEqual(arch_expected.resolve(), REPOSITORY / "skills" / "understand-arch")

    def test_install_preserves_existing_directory(self):
        self.target.mkdir(parents=True)
        sentinel = self.target / "sentinel.txt"
        sentinel.write_text("keep", encoding="utf-8")

        result = self.run_installer()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")
        self.assertFalse(self.target.is_symlink())
        self.assertFalse(self.arch_target.exists())

    def test_install_preserves_existing_arch_target_without_partial_install(self):
        self.arch_target.mkdir(parents=True)
        sentinel = self.arch_target / "sentinel.txt"
        sentinel.write_text("keep", encoding="utf-8")

        result = self.run_installer()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")
        self.assertFalse(self.target.exists())

    def test_install_preserves_existing_project_target_without_partial_install(self):
        self.project_target.mkdir(parents=True)
        sentinel = self.project_target / "sentinel.txt"
        sentinel.write_text("keep", encoding="utf-8")

        result = self.run_installer()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")
        self.assertFalse(self.target.exists())
        self.assertFalse(self.arch_target.exists())

    def test_install_completes_previous_api_only_installation(self):
        self.target.parent.mkdir(parents=True)
        self.target.symlink_to(REPOSITORY)

        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.target.resolve(), REPOSITORY)
        self.assertEqual(self.arch_target.resolve(), REPOSITORY / "skills" / "understand-arch")

    def test_install_completes_previous_arch_only_installation(self):
        self.arch_target.parent.mkdir(parents=True)
        self.arch_target.symlink_to(REPOSITORY / "skills" / "understand-arch")

        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.target.resolve(), REPOSITORY)
        self.assertEqual(self.arch_target.resolve(), REPOSITORY / "skills" / "understand-arch")

    def test_install_migrates_owned_old_names(self):
        self.old_target.parent.mkdir(parents=True)
        self.old_target.symlink_to(REPOSITORY)
        self.previous_target.symlink_to(REPOSITORY)
        self.old_arch_target.symlink_to(REPOSITORY / "skills" / "understand-api-arch")

        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.target.resolve(), REPOSITORY)
        self.assertEqual(self.arch_target.resolve(), REPOSITORY / "skills" / "understand-arch")
        self.assertFalse(self.old_target.is_symlink())
        self.assertFalse(self.previous_target.is_symlink())
        self.assertFalse(self.old_arch_target.is_symlink())

    def test_conflict_preserves_old_names_without_partial_migration(self):
        self.old_target.parent.mkdir(parents=True)
        self.old_target.symlink_to(REPOSITORY)
        self.previous_target.symlink_to(REPOSITORY)
        self.old_arch_target.symlink_to(REPOSITORY / "skills" / "understand-api-arch")
        self.arch_target.mkdir()

        self.assertNotEqual(self.run_installer().returncode, 0)
        self.assertTrue(self.old_target.is_symlink())
        self.assertTrue(self.previous_target.is_symlink())
        self.assertTrue(self.old_arch_target.is_symlink())
        self.assertFalse(self.target.exists())

    def test_install_preserves_unrelated_old_name(self):
        self.old_target.parent.mkdir(parents=True)
        other = self.root / "other skill"
        other.mkdir()
        self.old_target.symlink_to(other)

        self.assertEqual(self.run_installer().returncode, 0)
        self.assertEqual(self.old_target.resolve(), other.resolve())
        self.assertEqual(self.run_installer("--uninstall").returncode, 0)
        self.assertEqual(self.old_target.resolve(), other.resolve())

    def test_install_preserves_unrelated_symlink(self):
        self.target.parent.mkdir(parents=True)
        other = self.root / "other skill"
        other.mkdir()
        self.target.symlink_to(other)

        self.assertNotEqual(self.run_installer().returncode, 0)
        self.assertEqual(self.target.resolve(), other.resolve())
        self.assertNotEqual(self.run_installer("--uninstall").returncode, 0)
        self.assertEqual(self.target.resolve(), other.resolve())
        self.assertFalse(self.arch_target.exists())

    def test_uninstall_preserves_both_links_when_arch_target_is_unrelated(self):
        self.target.parent.mkdir(parents=True)
        self.target.symlink_to(REPOSITORY)
        other = self.root / "other skill"
        other.mkdir()
        self.arch_target.symlink_to(other)

        result = self.run_installer("--uninstall")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.target.resolve(), REPOSITORY)
        self.assertEqual(self.arch_target.resolve(), other.resolve())

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

    def test_doctor_requires_both_skills(self):
        self.assertEqual(self.run_installer().returncode, 0)
        self.arch_target.unlink()
        self.assertNotEqual(self.run_installer("--doctor").returncode, 0)

    def test_doctor_requires_project_skill(self):
        self.assertEqual(self.run_installer().returncode, 0)
        self.project_target.unlink()
        self.assertNotEqual(self.run_installer("--doctor").returncode, 0)

    def test_uninstall_removes_only_own_symlink(self):
        self.assertEqual(self.run_installer().returncode, 0)
        result = self.run_installer("--uninstall")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.target.exists())
        self.assertFalse(self.target.is_symlink())
        self.assertFalse(self.arch_target.exists())
        self.assertFalse(self.arch_target.is_symlink())
        self.assertFalse(self.project_target.exists())
        self.assertFalse(self.project_target.is_symlink())
        self.assertTrue((REPOSITORY / "SKILL.md").is_file())

    def test_uninstall_removes_owned_old_names(self):
        self.old_target.parent.mkdir(parents=True)
        self.old_target.symlink_to(REPOSITORY)
        self.previous_target.symlink_to(REPOSITORY)
        self.old_arch_target.symlink_to(REPOSITORY / "skills" / "understand-api-arch")

        self.assertEqual(self.run_installer("--uninstall").returncode, 0)
        self.assertFalse(self.old_target.is_symlink())
        self.assertFalse(self.previous_target.is_symlink())
        self.assertFalse(self.old_arch_target.is_symlink())

    def test_help_and_unknown_option(self):
        self.assertEqual(self.run_installer("--help").returncode, 0)
        self.assertNotEqual(self.run_installer("--unknown").returncode, 0)
        self.assertFalse(self.target.exists())

    def test_default_installs_both_hosts_with_existing_engines(self):
        fake_bin = self.root / "fake-bin"
        fake_bin.mkdir()
        for name in ("mmdc", "plantuml", "drawio", "archify"):
            binary = fake_bin / name
            binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            binary.chmod(0o755)
        self.environment["PATH"] = str(fake_bin) + os.pathsep + self.environment["PATH"]

        result = self.run_installer(isolated=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.claude_docs_target.resolve(), REPOSITORY)
        self.assertEqual(self.claude_arch_target.resolve(), REPOSITORY / "skills" / "understand-arch")
        self.assertEqual(self.claude_project_target.resolve(), REPOSITORY / "skills" / "understand-project")
        self.assertEqual(self.run_installer("--doctor", isolated=False).returncode, 0)

    def test_claude_only_and_no_engines(self):
        result = self.run_installer("--host", "claude", "--no-engines", isolated=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.target.exists())
        self.assertEqual(self.claude_docs_target.resolve(), REPOSITORY)
        self.assertEqual(self.claude_arch_target.resolve(), REPOSITORY / "skills" / "understand-arch")
        self.assertEqual(self.claude_project_target.resolve(), REPOSITORY / "skills" / "understand-project")
        self.assertEqual(self.run_installer("--doctor", "--host", "claude", "--no-engines",
                                            isolated=False).returncode, 0)
        self.assertEqual(self.run_installer("--uninstall", "--host", "claude",
                                            isolated=False).returncode, 0)
        self.assertFalse(self.claude_docs_target.exists())

    def test_claude_conflict_prevents_codex_partial_install(self):
        self.claude_arch_target.mkdir(parents=True)
        marker = self.claude_arch_target / "keep.txt"
        marker.write_text("keep", encoding="utf-8")

        result = self.run_installer("--no-engines", isolated=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.target.exists())
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_engine_selection_rejects_conflicting_options(self):
        result = self.run_installer("--engine", "mermaid", "--no-engines", isolated=False)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.target.exists())

    def test_no_engines_records_opt_out_for_future_skill_use(self):
        result = self.run_installer("--no-engines", isolated=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        marker = self.root / "renderers" / "no-auto-install"
        self.assertTrue(marker.is_file())
        denied = subprocess.run(["python3", str(REPOSITORY / "scripts/install_renderers.py"),
                                 "--auto", "--engine", "drawio"], env=self.environment,
                                capture_output=True, text=True)
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn("disabled", denied.stderr)

    def test_explicit_engine_install_clears_opt_out(self):
        self.assertEqual(self.run_installer("--no-engines", isolated=False).returncode, 0)
        fake_bin = self.root / "fake-bin"
        fake_bin.mkdir()
        binary = fake_bin / "mmdc"
        binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        binary.chmod(0o755)
        self.environment["PATH"] = str(fake_bin) + os.pathsep + self.environment["PATH"]

        result = self.run_installer("--engine", "mermaid", isolated=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / "renderers" / "no-auto-install").exists())

    def test_old_python_rejected_before_install(self):
        fake_python = self.root / "python-old"
        fake_python.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        fake_python.chmod(0o755)
        self.environment["UNDERSTAND_PYTHON"] = str(fake_python)

        result = self.run_installer("--no-engines", isolated=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("3.11", result.stderr)
        self.assertFalse(self.target.exists())


if __name__ == "__main__":
    unittest.main()
