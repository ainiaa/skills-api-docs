import os
import json
import sys
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
INSTALLER = REPOSITORY / "install.sh"
API_SKILL = REPOSITORY / "skills" / "project-docs-api"


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="api docs install ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.codex_home = self.root / "codex home"
        self.claude_home = self.root / "claude home"
        self.suite_target = self.codex_home / "skills" / "project-docs"
        self.claude_suite_target = self.claude_home / "skills" / "project-docs"
        self.target = self.codex_home / "skills" / "project-docs-api"
        self.arch_target = self.codex_home / "skills" / "project-docs-diagram"
        self.project_target = self.codex_home / "skills" / "project-docs-overview"
        self.claude_docs_target = self.claude_home / "skills" / "project-docs-api"
        self.claude_arch_target = self.claude_home / "skills" / "project-docs-diagram"
        self.claude_project_target = self.claude_home / "skills" / "project-docs-overview"
        self.old_target = self.codex_home / "skills" / "api-savior-docs"
        self.previous_target = self.codex_home / "skills" / "understand-api-docs"
        self.old_arch_target = self.codex_home / "skills" / "understand-api-arch"
        self.environment = dict(os.environ, CODEX_HOME=str(self.codex_home),
                                CLAUDE_HOME=str(self.claude_home), HOME=str(self.root),
                                UNDERSTAND_RENDERER_HOME=str(self.root / "renderers"))
        for variable in ("DSH_HOME", "PI_CODING_AGENT_DIR", "XDG_CONFIG_HOME", "GEMINI_CLI_HOME", "GROK_HOME"):
            self.environment.pop(variable, None)

    def host_directories(self):
        return {
            "codex": self.codex_home / "skills",
            "claude": self.claude_home / "skills",
            "zcode": self.root / ".zcode" / "skills",
            "dsh": self.root / ".dsh" / "skills",
            "gemini": self.root / ".gemini" / "skills",
            "grok": self.root / ".grok" / "skills",
            "pi": self.root / ".pi" / "agent" / "skills",
            "opencode": self.root / ".config" / "opencode" / "skills",
        }

    def linked_collection(self, relative=False):
        collection = self.root / "collection"
        collection.mkdir()
        shutil.copy(INSTALLER, collection / "install.sh")
        shutil.copy(REPOSITORY / "VERSION", collection / "VERSION")
        shutil.copytree(REPOSITORY / "skills", collection / "skills")
        for directory in self.host_directories().values():
            directory.mkdir(parents=True)
            for source in (collection / "skills").iterdir():
                target = os.path.relpath(source, directory) if relative else source
                (directory / source.name).symlink_to(target)
        return collection

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
        self.assertEqual(self.suite_target.resolve(), REPOSITORY / "skills" / "project-docs")
        self.assertTrue(self.target.is_symlink())
        self.assertEqual(self.target.resolve(), API_SKILL)
        self.assertTrue(self.arch_target.is_symlink())
        self.assertEqual(self.arch_target.resolve(), REPOSITORY / "skills" / "project-docs-diagram")
        self.assertTrue(self.project_target.is_symlink())
        self.assertEqual(self.project_target.resolve(), REPOSITORY / "skills" / "project-docs-overview")
        self.assertTrue((self.project_target / "assets" / "project-overview.md").is_file())
        self.assertTrue((self.project_target / "assets" / "feature-description.md").is_file())
        self.assertTrue((self.project_target / "assets" / "developer-guide.md").is_file())
        self.assertTrue((self.project_target / "assets" / "architecture-overview.md").is_file())
        self.assertTrue((self.project_target / "../../scripts/project_doc_context.py").resolve().is_file())
        self.assertTrue((self.project_target / "../../scripts/project_doc_impact.py").resolve().is_file())

        second = self.run_installer()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(self.target.resolve(), API_SKILL)
        self.assertEqual(self.arch_target.resolve(), REPOSITORY / "skills" / "project-docs-diagram")
        self.assertEqual(self.project_target.resolve(), REPOSITORY / "skills" / "project-docs-overview")
        self.assertEqual(self.run_installer("--doctor").returncode, 0)

    def test_install_uses_home_when_codex_home_is_unset(self):
        del self.environment["CODEX_HOME"]
        expected = self.root / ".codex" / "skills" / "project-docs-api"

        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(expected.is_symlink())
        self.assertEqual(expected.resolve(), API_SKILL)
        arch_expected = self.root / ".codex" / "skills" / "project-docs-diagram"
        self.assertTrue(arch_expected.is_symlink())
        self.assertEqual(arch_expected.resolve(), REPOSITORY / "skills" / "project-docs-diagram")

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
        self.target.symlink_to(API_SKILL)

        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.target.resolve(), API_SKILL)
        self.assertEqual(self.arch_target.resolve(), REPOSITORY / "skills" / "project-docs-diagram")

    def test_install_completes_previous_arch_only_installation(self):
        self.arch_target.parent.mkdir(parents=True)
        self.arch_target.symlink_to(REPOSITORY / "skills" / "project-docs-diagram")

        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.target.resolve(), API_SKILL)
        self.assertEqual(self.arch_target.resolve(), REPOSITORY / "skills" / "project-docs-diagram")

    def test_install_migrates_owned_old_names(self):
        self.old_target.parent.mkdir(parents=True)
        self.old_target.symlink_to(REPOSITORY)
        self.previous_target.symlink_to(REPOSITORY)
        self.old_arch_target.symlink_to(REPOSITORY / "skills" / "understand-api-arch")

        result = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.target.resolve(), API_SKILL)
        self.assertEqual(self.arch_target.resolve(), REPOSITORY / "skills" / "project-docs-diagram")
        self.assertFalse(self.old_target.is_symlink())
        self.assertFalse(self.previous_target.is_symlink())
        self.assertFalse(self.old_arch_target.is_symlink())

    def legacy_links(self, skills_dir):
        return {
            skills_dir / "understand-docs": REPOSITORY,
            skills_dir / "understand-arch": REPOSITORY / "skills" / "understand-arch",
            skills_dir / "understand-project": REPOSITORY / "skills" / "understand-project",
            skills_dir / "api-savior-docs": REPOSITORY,
            skills_dir / "understand-api-docs": REPOSITORY,
            skills_dir / "understand-api-arch": REPOSITORY / "skills" / "understand-api-arch",
        }

    def test_migrates_all_legacy_names_for_both_hosts(self):
        legacy = {}
        for home in (self.codex_home, self.claude_home):
            skills_dir = home / "skills"
            skills_dir.mkdir(parents=True)
            for target, source in self.legacy_links(skills_dir).items():
                target.symlink_to(os.path.relpath(source, skills_dir.resolve()))
                legacy[target] = source

        result = self.run_installer("--no-engines", isolated=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        for target in legacy:
            self.assertFalse(target.is_symlink(), target)
        for home in (self.codex_home, self.claude_home):
            for name in ("project-docs", "project-docs-api", "project-docs-diagram", "project-docs-overview"):
                installed = home / "skills" / name
                self.assertEqual(installed.resolve(), REPOSITORY / "skills" / name)
                self.assertIn(f"name: {name}\n", (installed / "SKILL.md").read_text())
        self.assertEqual(self.run_installer("--doctor", "--no-engines", isolated=False).returncode, 0)
        self.assertEqual(self.run_installer("--no-engines", isolated=False).returncode, 0)

    def test_suite_conflict_preserves_legacy_links_on_both_hosts(self):
        for home in (self.codex_home, self.claude_home):
            skills_dir = home / "skills"
            skills_dir.mkdir(parents=True)
            (skills_dir / "understand-docs").symlink_to(REPOSITORY)
        self.claude_suite_target.mkdir()
        marker = self.claude_suite_target / "keep.txt"
        marker.write_text("keep")

        result = self.run_installer("--no-engines", isolated=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(marker.read_text(), "keep")
        self.assertFalse(self.suite_target.exists())
        for home in (self.codex_home, self.claude_home):
            self.assertTrue((home / "skills" / "understand-docs").is_symlink())
            self.assertFalse((home / "skills" / "project-docs-api").exists())

    def test_migration_preserves_unrelated_legacy_directory_and_broken_link(self):
        skills_dir = self.codex_home / "skills"
        unrelated = skills_dir / "understand-project"
        unrelated.mkdir(parents=True)
        marker = unrelated / "keep.txt"
        marker.write_text("keep")
        broken = skills_dir / "understand-arch"
        destination = self.root / "missing unrelated skill"
        broken.symlink_to(destination)

        self.assertEqual(self.run_installer().returncode, 0)
        self.assertEqual(self.run_installer("--uninstall").returncode, 0)
        self.assertEqual(marker.read_text(), "keep")
        self.assertTrue(broken.is_symlink())
        self.assertEqual(broken.readlink(), destination)

    def test_doctor_reports_remaining_owned_legacy_name(self):
        self.assertEqual(self.run_installer().returncode, 0)
        legacy = self.codex_home / "skills" / "understand-arch"
        legacy.symlink_to(REPOSITORY / "skills" / "understand-arch")
        self.assertNotEqual(self.run_installer("--doctor").returncode, 0)
        self.assertEqual(self.run_installer("--uninstall").returncode, 0)
        self.assertFalse(legacy.is_symlink())

    def test_doctor_requires_suite_entry(self):
        self.assertEqual(self.run_installer().returncode, 0)
        self.suite_target.unlink()
        self.assertNotEqual(self.run_installer("--doctor").returncode, 0)

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
        self.target.symlink_to(API_SKILL)
        other = self.root / "other skill"
        other.mkdir()
        self.arch_target.symlink_to(other)

        result = self.run_installer("--uninstall")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.target.resolve(), API_SKILL)
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
        self.assertFalse(self.suite_target.is_symlink())
        self.assertFalse(self.target.exists())
        self.assertFalse(self.target.is_symlink())
        self.assertFalse(self.arch_target.exists())
        self.assertFalse(self.arch_target.is_symlink())
        self.assertFalse(self.project_target.exists())
        self.assertFalse(self.project_target.is_symlink())
        self.assertTrue((API_SKILL / "SKILL.md").is_file())

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
        versions = {"mmdc": "12.0.0", "plantuml": "PlantUML version 1.2026.8", "drawio": "32.4.1",
                    "archify": "", "dot": "dot - graphviz version 14.0.0", "java": 'openjdk version "21.0.10"'}
        for name, version in versions.items():
            binary = fake_bin / name
            binary.write_text(f"#!{sys.executable}\nimport sys\nfrom pathlib import Path\n"
                              f"print({version!r})\n"
                              "if '-o' in sys.argv: Path(sys.argv[sys.argv.index('-o')+1]).write_text('<svg/>')\n")
            binary.chmod(0o755)
        (self.root / "package.json").write_text(json.dumps({"name": "archify", "version": "3.1.0"}))
        (fake_bin / "visual-check.mjs").write_text("export function findChrome(){return '/fake/chrome'}")
        for engine, binary in (("MERMAID", "mmdc"), ("PLANTUML", "plantuml"), ("DRAWIO", "drawio"), ("ARCHIFY", "archify")):
            self.environment[f"{engine}_OFFICIAL_CLI"] = str(fake_bin / binary)
        self.environment["GRAPHVIZ_DOT"] = str(fake_bin / "dot")
        self.environment["PATH"] = str(fake_bin) + os.pathsep + self.environment["PATH"]

        result = self.run_installer(isolated=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.claude_suite_target.resolve(), REPOSITORY / "skills" / "project-docs")
        self.assertEqual(self.claude_docs_target.resolve(), API_SKILL)
        self.assertEqual(self.claude_arch_target.resolve(), REPOSITORY / "skills" / "project-docs-diagram")
        self.assertEqual(self.claude_project_target.resolve(), REPOSITORY / "skills" / "project-docs-overview")
        self.assertEqual(self.run_installer("--doctor", isolated=False).returncode, 0)

    def test_claude_only_and_no_engines(self):
        result = self.run_installer("--host", "claude", "--no-engines", isolated=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.target.exists())
        self.assertEqual(self.claude_suite_target.resolve(), REPOSITORY / "skills" / "project-docs")
        self.assertEqual(self.claude_docs_target.resolve(), API_SKILL)
        self.assertEqual(self.claude_arch_target.resolve(), REPOSITORY / "skills" / "project-docs-diagram")
        self.assertEqual(self.claude_project_target.resolve(), REPOSITORY / "skills" / "project-docs-overview")
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

    def test_new_hosts_install_update_doctor_and_uninstall_in_isolation(self):
        names = ("project-docs", "project-docs-api", "project-docs-diagram", "project-docs-overview")
        for host, directory in self.host_directories().items():
            if host in ("codex", "claude"):
                continue
            with self.subTest(host=host):
                options = ("--host", host, "--no-engines")
                self.assertNotEqual(self.run_installer("--doctor", *options, isolated=False).returncode, 0)
                for action in ("--install", "--install", "--update-deps", "--doctor"):
                    result = self.run_installer(action, *options, isolated=False)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    for name in names:
                        installed = directory / name
                        self.assertTrue(installed.is_symlink(), installed)
                        self.assertEqual(installed.resolve(), REPOSITORY / "skills" / name)
                        self.assertIn(f"name: {name}\n", (installed / "SKILL.md").read_text())
                    self.assertTrue((directory / "project-docs" / "../../scripts/update_project_docs.py").resolve().is_file())
                for other, other_directory in self.host_directories().items():
                    if other != host:
                        self.assertFalse((other_directory / "project-docs").is_symlink(), other)
                result = self.run_installer("--uninstall", *options, isolated=False)
                self.assertEqual(result.returncode, 0, result.stderr)
                for name in names:
                    self.assertFalse((directory / name).is_symlink())
                self.assertNotEqual(self.run_installer("--doctor", *options, isolated=False).returncode, 0)

    def test_all_hosts_migrate_legacy_links_and_share_one_collection(self):
        legacy = []
        for directory in self.host_directories().values():
            directory.mkdir(parents=True)
            for target, source in self.legacy_links(directory).items():
                target.symlink_to(os.path.relpath(source, directory.resolve()))
                self.assertEqual(target.resolve(), source)
                legacy.append(target)
        for action in ("--install", "--update-deps", "--doctor"):
            result = self.run_installer(action, "--host", "all", "--no-engines", isolated=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            for directory in self.host_directories().values():
                for name in ("project-docs", "project-docs-api", "project-docs-diagram", "project-docs-overview"):
                    self.assertEqual((directory / name).resolve(), REPOSITORY / "skills" / name)
            self.assertFalse(any(target.is_symlink() for target in legacy))
        result = self.run_installer("--uninstall", "--host", "all", isolated=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        for directory in self.host_directories().values():
            self.assertEqual(list(directory.iterdir()), [])

    def test_new_host_conflicts_block_all_actions_before_any_link_changes(self):
        self.suite_target.parent.mkdir(parents=True)
        self.suite_target.symlink_to(REPOSITORY / "skills" / "project-docs")
        for host, directory in self.host_directories().items():
            if host in ("codex", "claude"):
                continue
            directory.mkdir(parents=True)
            target = directory / "project-docs-overview"
            for kind in ("directory", "file", "broken-link"):
                with self.subTest(host=host, kind=kind):
                    if kind == "directory":
                        target.mkdir()
                    elif kind == "file":
                        target.write_text("keep")
                    else:
                        target.symlink_to(self.root / "missing-unrelated-skill")
                    try:
                        for action in ("--install", "--update", "--update-deps", "--uninstall"):
                            result = self.run_installer(action, "--host", "all", "--no-engines", isolated=False)
                            self.assertNotEqual(result.returncode, 0, result.stdout)
                            self.assertIn("refusing to replace unrelated path", result.stderr)
                            self.assertTrue(self.suite_target.is_symlink())
                            self.assertFalse(self.target.is_symlink())
                            self.assertFalse((directory / "project-docs").is_symlink())
                        if kind == "file":
                            self.assertEqual(target.read_text(), "keep")
                        elif kind == "broken-link":
                            self.assertEqual(target.readlink(), self.root / "missing-unrelated-skill")
                    finally:
                        if kind == "directory":
                            target.rmdir()
                        else:
                            target.unlink()

    def test_native_dsh_and_pi_home_overrides(self):
        for host, variable in (("dsh", "DSH_HOME"), ("pi", "PI_CODING_AGENT_DIR")):
            with self.subTest(host=host):
                home = self.root / (host + " custom home")
                self.environment[variable] = str(home)
                options = ("--host", host, "--no-engines")
                self.assertEqual(self.run_installer(*options, isolated=False).returncode, 0)
                self.assertEqual((home / "skills" / "project-docs").resolve(), REPOSITORY / "skills" / "project-docs")
                self.assertFalse((self.host_directories()[host] / "project-docs").is_symlink())
                self.assertEqual(self.run_installer("--doctor", *options, isolated=False).returncode, 0)
                self.assertEqual(self.run_installer("--uninstall", *options, isolated=False).returncode, 0)
                self.assertFalse((home / "skills" / "project-docs").is_symlink())

    def test_opencode_respects_xdg_config_home_for_every_local_action(self):
        config = self.root / "custom config home"
        self.environment["XDG_CONFIG_HOME"] = str(config)
        options = ("--host", "opencode", "--no-engines")
        installed = config / "opencode" / "skills" / "project-docs"
        for action in ("--install", "--update-deps", "--doctor"):
            result = self.run_installer(action, *options, isolated=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(installed.resolve(), REPOSITORY / "skills" / "project-docs")
            self.assertFalse(self.host_directories()["opencode"].exists())
        self.assertEqual(self.run_installer("--uninstall", *options, isolated=False).returncode, 0)
        self.assertFalse(installed.is_symlink())

    def test_pi_home_override_expands_tilde_as_native_pi_does(self):
        self.environment["PI_CODING_AGENT_DIR"] = "~/custom pi home"
        options = ("--host", "pi", "--no-engines")
        installed = self.root / "custom pi home" / "skills" / "project-docs"
        for action in ("--install", "--update-deps", "--doctor"):
            result = self.run_installer(action, *options, isolated=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(installed.resolve(), REPOSITORY / "skills" / "project-docs")
            self.assertFalse((self.root / "~").exists())
        self.assertEqual(self.run_installer("--uninstall", *options, isolated=False).returncode, 0)
        self.assertFalse(installed.is_symlink())

    def test_default_and_both_do_not_install_new_hosts(self):
        for options in ((), ("--host", "both")):
            result = self.run_installer(*options, "--no-engines", isolated=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            for host, directory in self.host_directories().items():
                self.assertEqual((directory / "project-docs").is_symlink(), host in ("codex", "claude"), host)

    def test_invalid_host_stops_without_installing_any_skills(self):
        for host in ("unknown", "", "gemini,pi", "ALL"):
            result = self.run_installer("--host", host, "--no-engines", isolated=False)
            self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(self.run_installer("--host", isolated=False).returncode, 2)
        for directory in self.host_directories().values():
            self.assertFalse(directory.exists())

    def test_invalid_skill_root_or_ancestor_blocks_all_hosts_before_mutation(self):
        for host, directory in self.host_directories().items():
            if host in ("codex", "claude"):
                continue
            relative = directory.relative_to(self.root)
            for kind in ("root-file", "root-link", "parent-file", "parent-link"):
                with self.subTest(host=host, kind=kind):
                    home = self.root / (host + "-" + kind)
                    skills_dir = home / relative
                    conflict = skills_dir.parent if kind.startswith("parent") else skills_dir
                    conflict.parent.mkdir(parents=True)
                    if kind.endswith("file"):
                        conflict.write_text("keep")
                    else:
                        conflict.symlink_to(home / "missing-directory")
                    environment = dict(self.environment, HOME=str(home),
                                       CODEX_HOME=str(home / "codex"), CLAUDE_HOME=str(home / "claude"),
                                       UNDERSTAND_RENDERER_HOME=str(home / "renderers"))
                    for action in ("--install", "--update", "--update-deps", "--uninstall"):
                        result = subprocess.run(["bash", str(INSTALLER), action, "--host", "all", "--no-engines"],
                                                env=environment, capture_output=True, text=True)
                        self.assertNotEqual(result.returncode, 0, result.stdout)
                        self.assertIn("not a usable skill directory", result.stderr)
                        self.assertFalse((home / "codex" / "skills").exists())
                        self.assertFalse((home / "renderers").exists())
                    if kind.endswith("file"):
                        self.assertEqual(conflict.read_text(), "keep")
                    else:
                        self.assertEqual(conflict.readlink(), home / "missing-directory")

    def test_existing_skill_root_symlink_to_directory_is_supported(self):
        directory = self.host_directories()["gemini"]
        shared = self.root / "shared skills"
        shared.mkdir()
        directory.parent.mkdir(parents=True)
        directory.symlink_to(shared, target_is_directory=True)
        options = ("--host", "gemini", "--no-engines")
        for action in ("--install", "--doctor", "--uninstall"):
            result = self.run_installer(action, *options, isolated=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            if action != "--uninstall":
                self.assertEqual((shared / "project-docs").resolve(), REPOSITORY / "skills" / "project-docs")
        self.assertEqual(directory.readlink(), shared)
        self.assertEqual(list(shared.iterdir()), [])

    def test_gemini_and_grok_native_home_overrides_apply_to_all_local_actions(self):
        for host, variable, suffix in (("gemini", "GEMINI_CLI_HOME", ".gemini/skills"),
                                       ("grok", "GROK_HOME", "skills")):
            with self.subTest(host=host):
                home = self.root / (host + " custom home")
                self.environment[variable] = str(home)
                options = ("--host", host, "--no-engines")
                for action in ("--install", "--update-deps", "--doctor"):
                    result = self.run_installer(action, *options, isolated=False)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual((home / suffix / "project-docs").resolve(), REPOSITORY / "skills" / "project-docs")
                    self.assertFalse(self.host_directories()[host].exists())
                self.assertEqual(self.run_installer("--uninstall", *options, isolated=False).returncode, 0)
                self.assertFalse((home / suffix / "project-docs").is_symlink())

    def test_dsh_home_uses_native_tilde_expansion_and_blank_fallback(self):
        for value, directory in (("~/custom dsh home", self.root / "custom dsh home"),
                                 ("~\\custom dsh home", self.root / "custom dsh home"),
                                 ("~", self.root), (" \t ", self.root / ".dsh")):
            with self.subTest(value=value):
                self.environment["DSH_HOME"] = value
                options = ("--host", "dsh", "--no-engines")
                try:
                    for action in ("--install", "--update-deps", "--doctor"):
                        result = self.run_installer(action, *options, isolated=False)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual((directory / "skills" / "project-docs").resolve(), REPOSITORY / "skills" / "project-docs")
                finally:
                    self.run_installer("--uninstall", *options, isolated=False)

    def test_relative_xdg_config_home_is_ignored_as_required_by_xdg(self):
        self.environment["XDG_CONFIG_HOME"] = "relative config"
        options = ("--host", "opencode", "--no-engines")
        for action in ("--install", "--update-deps", "--doctor"):
            result = self.run_installer(action, *options, isolated=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((self.host_directories()["opencode"] / "project-docs").resolve(), REPOSITORY / "skills" / "project-docs")
            self.assertFalse((self.root / "relative config").exists())
        self.assertEqual(self.run_installer("--uninstall", *options, isolated=False).returncode, 0)

    def test_doctor_rejects_missing_skill_entries_and_version_file(self):
        collection = self.linked_collection()
        for fault in ("missing-skill", "empty-skill", "missing-version", "empty-version"):
            with self.subTest(fault=fault):
                file = collection / ("VERSION" if fault.endswith("version") else "skills/project-docs-api/SKILL.md")
                original = file.read_bytes()
                if fault.startswith("empty"):
                    file.write_text("")
                else:
                    file.unlink()
                try:
                    result = subprocess.run(["bash", str(collection / "install.sh"), "--doctor", "--host", "all", "--no-engines"],
                                            env=self.environment, capture_output=True, text=True)
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    self.assertIn("VERSION" if fault.endswith("version") else "SKILL.md", result.stderr)
                finally:
                    file.write_bytes(original)

    def test_doctor_reports_skill_problems_even_when_renderer_check_fails(self):
        fake_python = self.root / "failing renderer probe"
        fake_python.write_text("#!/bin/sh\necho 'renderer probe failed' >&2\nexit 9\n")
        fake_python.chmod(0o755)
        self.environment["UNDERSTAND_PYTHON"] = str(fake_python)
        result = self.run_installer("--doctor", "--host", "all", "--engine", "mermaid", isolated=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("renderer probe failed", result.stderr)
        for directory in self.host_directories().values():
            self.assertIn(str(directory / "project-docs"), result.stderr)
        self.assertFalse((self.root / "renderers").exists())

    def check_uninstall_with_missing_sources(self, relative=False, entire_group=False):
        collection = self.linked_collection(relative=relative)
        shutil.rmtree(collection / "skills" if entire_group else collection / "skills/project-docs-api")
        result = subprocess.run(["bash", str(collection / "install.sh"), "--uninstall", "--host", "all"],
                                env=self.environment, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        for directory in self.host_directories().values():
            self.assertEqual(list(directory.iterdir()), [])

    def test_uninstall_removes_owned_broken_absolute_links(self):
        self.check_uninstall_with_missing_sources()

    def test_uninstall_removes_owned_broken_relative_links(self):
        self.check_uninstall_with_missing_sources(relative=True)

    def test_uninstall_removes_owned_links_when_entire_skill_group_is_missing(self):
        self.check_uninstall_with_missing_sources(entire_group=True)

    def test_uninstall_removes_owned_relative_links_when_entire_skill_group_is_missing(self):
        self.check_uninstall_with_missing_sources(relative=True, entire_group=True)

    def test_symlink_with_parent_traversal_is_not_mistaken_for_owned_source(self):
        collection = self.linked_collection()
        actual = self.root / "actual"
        (actual / "nested").mkdir(parents=True)
        foreign = actual / "collection/skills/project-docs"
        foreign.mkdir(parents=True)
        (foreign / "SKILL.md").write_text("keep")
        redirect = self.root / "redirect"
        redirect.symlink_to(actual / "nested", target_is_directory=True)
        self.suite_target.unlink()
        self.suite_target.symlink_to(redirect / "../collection/skills/project-docs")
        self.assertEqual(self.suite_target.resolve(), foreign.resolve())
        for action in ("--doctor", "--uninstall"):
            with self.subTest(action=action):
                result = subprocess.run(["bash", str(collection / "install.sh"), action, "--host", "codex", "--no-engines"],
                                        env=self.environment, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertTrue(self.suite_target.is_symlink())
                self.assertEqual((foreign / "SKILL.md").read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
