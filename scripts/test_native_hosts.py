"""Opt-in acceptance tests against real host loaders; never install host software."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
NAMES = {"project-docs", "project-docs-api", "project-docs-diagram", "project-docs-overview"}


class NativeHostTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="project docs native ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.work = self.root / "workspace"
        self.work.mkdir()
        # Only pass runtime essentials, so real host configuration cannot leak in.
        self.environment = {
            "PATH": os.environ["PATH"], "HOME": str(self.root),
            "TMPDIR": str(self.root), "LANG": "en_US.UTF-8",
            "XDG_CONFIG_HOME": str(self.root / ".config"),
            "XDG_CACHE_HOME": str(self.root / "cache"),
            "XDG_DATA_HOME": str(self.root / "data"),
            "XDG_STATE_HOME": str(self.root / "state"),
            "UNDERSTAND_RENDERER_HOME": str(self.root / "renderers"),
        }

    def run_command(self, *command, success=True):
        result = subprocess.run(command, cwd=self.work, env=self.environment,
                                capture_output=True, text=True, timeout=90)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def install(self, host, action):
        self.run_command("bash", str(REPOSITORY / "install.sh"), "--host", host,
                         "--no-engines", action)

    def assert_body(self, name, content):
        source = (REPOSITORY / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
        self.assertEqual(content.strip(), source.split("---", 2)[2].strip())

    @unittest.skipUnless(os.environ.get("ZCODE_NATIVE_CLI"), "set ZCODE_NATIVE_CLI to zcode.cjs")
    def test_zcode_native_discovery_load_and_uninstall(self):
        cli = str(Path(os.environ["ZCODE_NATIVE_CLI"]).resolve())

        def catalog():
            result = json.loads(self.run_command("node", cli, "skills", "list", "--json").stdout)
            self.assertEqual(result["diagnostics"], [])
            return {skill["name"]: skill for skill in result["skills"] if skill["name"] in NAMES}

        self.assertEqual(catalog(), {})
        self.install("zcode", "--install")
        skills = catalog()
        self.assertEqual(set(skills), NAMES)
        for name, entry in skills.items():
            self.assertEqual(entry["source"], "zcode")
            self.assertEqual(entry["scope"], "user")
            expected = self.root / ".zcode" / "skills" / name / "SKILL.md"
            self.assertEqual(Path(entry["path"]).resolve(), expected.resolve())
            result = json.loads(self.run_command("node", cli, "skills", "inspect", name, "--json").stdout)
            self.assertFalse(result["skill"]["truncated"])
            self.assert_body(name, result["skill"]["content"])
        self.install("zcode", "--doctor")
        self.install("zcode", "--uninstall")
        self.assertEqual(catalog(), {})
        for name in NAMES:
            result = self.run_command("node", cli, "skills", "inspect", name, "--json", success=False)
            self.assertIn("Skill not found", result.stderr)

    @unittest.skipUnless(os.environ.get("DSH_NATIVE_MODULES"), "set DSH_NATIVE_MODULES to official node_modules")
    def test_dsh_native_discovery_load_and_uninstall(self):
        modules = str(Path(os.environ["DSH_NATIVE_MODULES"]).resolve())
        for override in (None, "~/custom dsh"):
            with self.subTest(DSH_HOME=override):
                if override is not None:
                    self.environment["DSH_HOME"] = override

                def catalog():
                    result = json.loads(self.run_command(
                        "node", str(Path(__file__).with_name("fixtures") / "dsh_native_skills.mjs"), modules
                    ).stdout)
                    self.assertTrue(result["complete"], result)
                    return result

                before = catalog()
                self.assertEqual(before["skills"], [])
                self.assertTrue(all(skill is None for skill in before["loaded"]))
                self.install("dsh", "--install")
                result = catalog()
                self.assertEqual({skill["name"] for skill in result["skills"]}, NAMES)
                self.assertEqual({skill["name"] for skill in result["loaded"]}, NAMES)
                for skill in result["loaded"]:
                    self.assertEqual(skill["source"], "user-dsh")
                    self.assertEqual(skill["provider"], "filesystem")
                    self.assertEqual(Path(skill["path"]).resolve(),
                                     REPOSITORY / "skills" / skill["name"] / "SKILL.md")
                    self.assert_body(skill["name"], skill["content"])
                self.install("dsh", "--doctor")
                self.install("dsh", "--uninstall")
                after = catalog()
                self.assertEqual(after["skills"], [])
                self.assertTrue(all(skill is None for skill in after["loaded"]))

    @unittest.skipUnless(os.environ.get("OPENCODE_NATIVE_CLI"), "set OPENCODE_NATIVE_CLI to opencode")
    def test_opencode_native_discovery_load_and_uninstall(self):
        cli = str(Path(os.environ["OPENCODE_NATIVE_CLI"]).absolute())
        self.environment.update(OPENCODE_DISABLE_DEFAULT_PLUGINS="true", OPENCODE_DISABLE_MODELS_FETCH="true")
        for config_home in (self.root / ".config", self.root / "custom config"):
            with self.subTest(XDG_CONFIG_HOME=config_home):
                if config_home == self.root / ".config":
                    self.environment.pop("XDG_CONFIG_HOME", None)
                else:
                    self.environment["XDG_CONFIG_HOME"] = str(config_home)

                def catalog():
                    result = json.loads(self.run_command(cli, "debug", "skill").stdout)
                    return {skill["name"]: skill for skill in result if skill["name"] in NAMES}

                self.assertEqual(catalog(), {})
                self.install("opencode", "--install")
                skills = catalog()
                self.assertEqual(set(skills), NAMES)
                for name, skill in skills.items():
                    expected = config_home / "opencode" / "skills" / name / "SKILL.md"
                    self.assertEqual(Path(skill["location"]).absolute(), expected.absolute())
                    self.assert_body(name, skill["content"])
                self.install("opencode", "--doctor")
                self.install("opencode", "--uninstall")
                self.assertEqual(catalog(), {})


if __name__ == "__main__":
    unittest.main()
