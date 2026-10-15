import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]


class UpdateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="project docs update ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.remote = self.root / "remote.git"
        self.seed = self.root / "seed"
        self.checkout = self.root / "checkout"
        self.git(self.root, "init", "--bare", "--initial-branch=main", str(self.remote))
        self.git(self.root, "clone", str(self.remote), str(self.seed))
        self.git(self.seed, "config", "user.name", "Jeff.Liu")
        self.git(self.seed, "config", "user.email", "tests@example.invalid")
        shutil.copy(REPOSITORY / "install.sh", self.seed)
        shutil.copy(REPOSITORY / ".gitignore", self.seed)
        shutil.copytree(REPOSITORY / "skills", self.seed / "skills")
        scripts = self.seed / "scripts"
        scripts.mkdir()
        for name in ("update_project_docs.py", "python_runtime.py"):
            source = REPOSITORY / "scripts" / name
            if source.exists():
                shutil.copy(source, scripts / name)
        for name in ("generate_api_docs.py", "generate_architecture.py", "validate_project_doc.py",
                     "project_doc_context.py", "project_doc_impact.py"):
            (scripts / name).write_text("")
        (scripts / "install_renderers.py").write_text(
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "with Path(os.environ['UPDATE_TEST_LOG']).open('a') as log:\n"
            "    log.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "sys.exit(int(os.environ.get('UPDATE_TEST_FAIL', '0')))\n"
        )
        (self.seed / "VERSION").write_text("0.5.0\n")
        self.git(self.seed, "add", ".")
        self.git(self.seed, "add", "-f", ".gitignore")
        self.git(self.seed, "commit", "-m", "Initial test collection")
        self.git(self.seed, "push", "origin", "main")
        self.git(self.root, "clone", str(self.remote), str(self.checkout))
        self.environment = dict(os.environ, CODEX_HOME=str(self.root / "codex"),
                                CLAUDE_HOME=str(self.root / "claude"),
                                UNDERSTAND_PYTHON=sys.executable,
                                UNDERSTAND_RENDERER_HOME=str(self.root / "renderers"),
                                UPDATE_TEST_LOG=str(self.root / "engine-calls.jsonl"))

    @staticmethod
    def git(directory, *arguments):
        return subprocess.run(["git", "-C", str(directory), *arguments], check=True,
                              capture_output=True, text=True).stdout.strip()

    def advance_remote(self):
        (self.seed / "VERSION").write_text("0.5.1\n")
        self.git(self.seed, "add", "VERSION")
        self.git(self.seed, "commit", "-m", "Updated collection")
        self.git(self.seed, "push", "origin", "main")

    def run_update(self, *arguments):
        return subprocess.run(["bash", str(self.checkout / "install.sh"), "--update",
                               "--host", "codex", *arguments], env=self.environment,
                              capture_output=True, text=True)

    def assert_no_dependency_changes(self):
        self.assertFalse((self.root / "engine-calls.jsonl").exists())
        self.assertFalse((self.root / "codex" / "skills").exists())

    def test_updates_tracked_branch_and_reinstalls_all_child_skills(self):
        self.advance_remote()
        result = self.run_update("--no-engines")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.checkout / "VERSION").read_text(), "0.5.1\n")
        for name in ("project-docs", "project-docs-api", "project-docs-diagram", "project-docs-overview"):
            self.assertEqual((self.root / "codex" / "skills" / name).resolve(), self.checkout / "skills" / name)
        self.assertFalse((self.root / "claude" / "skills").exists())
        self.assertFalse((self.root / "renderers" / "no-auto-install").exists())
        self.assertEqual(self.run_update("--no-engines").returncode, 0)

    def test_update_passes_selected_dependency_to_new_installer(self):
        self.advance_remote()
        result = self.run_update("--engine", "mermaid")
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [json.loads(line) for line in (self.root / "engine-calls.jsonl").read_text().splitlines()]
        self.assertEqual(len(calls), 1)
        self.assertIn("--update", calls[0])
        self.assertEqual(calls[0][calls[0].index("--engine") + 1], "mermaid")

    def test_tracked_local_changes_stop_before_pull_or_dependency_changes(self):
        self.advance_remote()
        (self.checkout / "VERSION").write_text("my local version\n")
        result = self.run_update("--engine", "mermaid")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("local changes", result.stderr)
        self.assertEqual((self.checkout / "VERSION").read_text(), "my local version\n")
        self.assert_no_dependency_changes()

    def test_untracked_files_also_stop_update(self):
        self.advance_remote()
        (self.checkout / "local-notes.md").write_text("keep")
        result = self.run_update()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("local changes", result.stderr)
        self.assertEqual((self.checkout / "local-notes.md").read_text(), "keep")
        self.assertEqual((self.checkout / "VERSION").read_text(), "0.5.0\n")
        self.assert_no_dependency_changes()

    def test_diverged_history_preserves_local_commit(self):
        self.advance_remote()
        self.git(self.checkout, "config", "user.name", "Jeff.Liu")
        self.git(self.checkout, "config", "user.email", "tests@example.invalid")
        (self.checkout / "VERSION").write_text("local committed version\n")
        self.git(self.checkout, "commit", "-am", "Local commit")
        before = self.git(self.checkout, "rev-parse", "HEAD")
        result = self.run_update()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.git(self.checkout, "rev-parse", "HEAD"), before)
        self.assertEqual((self.checkout / "VERSION").read_text(), "local committed version\n")
        self.assert_no_dependency_changes()

    def test_detached_head_and_missing_upstream_stop_update(self):
        self.git(self.checkout, "checkout", "--detach")
        self.assertNotEqual(self.run_update().returncode, 0)
        self.assert_no_dependency_changes()
        self.git(self.checkout, "checkout", "-b", "local-only")
        self.assertNotEqual(self.run_update().returncode, 0)
        self.assert_no_dependency_changes()

    def test_dependency_failure_reports_nonzero_after_successful_checkout_update(self):
        self.advance_remote()
        self.environment["UPDATE_TEST_FAIL"] = "1"
        result = self.run_update("--engine", "mermaid")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.checkout / "VERSION").read_text(), "0.5.1\n")
        self.assertIn("dependency", result.stderr.lower())
        self.assertFalse((self.root / "codex" / "skills").exists())

    def test_dependency_only_update_does_not_change_checkout(self):
        self.advance_remote()
        (self.checkout / "local-notes.md").write_text("keep")
        result = subprocess.run(["bash", str(self.checkout / "install.sh"), "--update-deps",
                                 "--host", "codex", "--engine", "mermaid"],
                                env=self.environment, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.checkout / "VERSION").read_text(), "0.5.0\n")
        self.assertEqual((self.checkout / "local-notes.md").read_text(), "keep")

    def test_rejects_conflicting_actions_before_updating(self):
        self.advance_remote()
        result = self.run_update("--doctor")
        self.assertEqual(result.returncode, 2)
        self.assertEqual((self.checkout / "VERSION").read_text(), "0.5.0\n")
        self.assert_no_dependency_changes()

    def test_copied_skill_does_not_update_its_enclosing_business_repository(self):
        nested = self.checkout / "copied-skill"
        shutil.copytree(self.seed, nested, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        result = subprocess.run(["bash", str(nested / "install.sh"), "--update", "--host", "codex"],
                                env=self.environment, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("own Git checkout", result.stderr)
        self.assert_no_dependency_changes()


if __name__ == "__main__":
    unittest.main()
