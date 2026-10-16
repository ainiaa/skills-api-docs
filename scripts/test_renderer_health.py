import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import install_renderers as setup


class RendererHealthTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="renderer health ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.installer = setup.RendererInstaller(self.root / "managed")
        environment = patch.dict(os.environ, {
            "GRAPHVIZ_DOT": "", "ARCHIFY_CHROME": "",
            **{f"{engine}_OFFICIAL_CLI": "" for engine in ("MERMAID", "PLANTUML", "DRAWIO", "ARCHIFY")},
        })
        environment.start()
        self.addCleanup(environment.stop)

    def cli(self, output, status=0):
        path = self.root / "test cli"
        path.write_text(f"#!{sys.executable}\nprint({output!r})\nraise SystemExit({status})\n")
        path.chmod(0o755)
        return path

    def test_pins_match_current_stable_releases_and_official_digests(self):
        self.assertEqual(setup.DRAWIO_VERSION, "32.4.1")
        self.assertEqual(setup.DRAWIO_DEB_SHA256, "f4455b3bba3d3b539c3cd069218fc64f0462b1b01610fe8d11acc3ca8566f32b")
        self.assertEqual(setup.DRAWIO_DMG_SHA256, "1e18db784d138cf0383ba66f662f5ace87e5b9415058075b50ce1b9560f68172")
        self.assertEqual(setup.ARCHIFY_VERSION, "3.1.0")
        self.assertEqual(setup.ARCHIFY_COMMIT, "1c2b42d660e4a7571813fb43839c79e3e9ca7720")

    def test_native_cli_versions_are_parsed_without_picking_up_runtime_versions(self):
        for engine, output, expected in (
            ("mermaid", "12.0.0", (12, 0, 0)),
            ("drawio", "32.4.1", (32, 4, 1)),
            ("plantuml", 'Java version 21.0.10\nPlantUML version 1.2026.8 / abc', (1, 2026, 8)),
        ):
            with self.subTest(engine=engine):
                self.assertEqual(self.installer.version(engine, self.cli(output)), expected)

    def test_unknown_failed_and_prerelease_versions_are_not_guessed(self):
        for output, status in (("unknown", 0), ("32.4.1", 7), ("32.4.1-beta.1", 0)):
            with self.subTest(output=output, status=status):
                with self.assertRaisesRegex(RuntimeError, "version|prerelease"):
                    self.installer.version("drawio", self.cli(output, status))

    def test_version_probe_has_a_timeout(self):
        with patch("install_renderers.subprocess.run", side_effect=subprocess.TimeoutExpired("drawio", 20)):
            with self.assertRaisesRegex(RuntimeError, "timed out|timeout"):
                self.installer.version("drawio", Path("/drawio"))

    def test_archify_version_comes_from_real_package_metadata_through_symlink(self):
        package = self.root / "archify"
        (package / "bin").mkdir(parents=True)
        (package / "package.json").write_text(json.dumps({"name": "archify", "version": "3.1.0"}))
        cli = package / "bin/archify.mjs"
        cli.write_text("#!/usr/bin/env node\n")
        entry = self.root / "archify-link"
        entry.symlink_to(cli)
        self.assertEqual(self.installer.version("archify", entry), (3, 1, 0))

    def test_update_preserves_equal_and_newer_effective_versions(self):
        for engine, versions in (
            ("drawio", ((32, 4, 1), (33, 0, 0))),
            ("archify", ((3, 1, 0), (4, 0, 0))),
            ("mermaid", ((12, 0, 0), (13, 0, 0))),
            ("plantuml", ((1, 2026, 8), (1, 2027, 1))),
        ):
            for version in versions:
                with self.subTest(engine=engine, version=version), \
                     patch("install_renderers.find_engine", return_value="/existing/cli"), \
                     patch.object(self.installer, "version", return_value=version), \
                     patch.object(self.installer, "_ensure_graphviz"), \
                     patch.object(self.installer, "_ensure_chrome"), \
                     patch.object(self.installer, f"_install_{engine}") as install:
                    self.assertEqual(self.installer.ensure(engine, update=True), "/existing/cli")
                    install.assert_not_called()

    def test_unknown_existing_version_stops_update_before_installing(self):
        with patch("install_renderers.find_engine", return_value="/existing/cli"), \
             patch.object(self.installer, "version", side_effect=RuntimeError("unknown version")), \
             patch.object(self.installer, "_install_drawio") as install:
            with self.assertRaisesRegex(RuntimeError, "unknown version"):
                self.installer.ensure("drawio", update=True)
        install.assert_not_called()

    def test_update_never_shadows_a_newer_path_cli(self):
        current = self.cli("33.0.0")
        with patch("install_renderers.find_engine", return_value=str(current)), \
             patch.object(self.installer, "_install_drawio", return_value=Path("/older/drawio")) as install:
            self.assertEqual(self.installer.ensure("drawio", update=True), str(current))
        install.assert_not_called()

    def test_doctor_does_not_accept_an_executable_with_no_version_output(self):
        current = self.cli("")
        with patch("install_renderers.find_engine", return_value=str(current)), \
             patch("sys.stdout", io.StringIO()), patch("sys.stderr", io.StringIO()):
            self.assertEqual(setup.main(["--doctor", "--engine", "drawio"]), 1)

    def test_archify_archive_checksum_failure_does_not_publish_a_cli(self):
        with patch.object(self.installer, "_ensure_node"), \
             patch.object(self.installer, "_download", side_effect=lambda url, destination: destination.write_bytes(b"bad")), \
             patch.object(self.installer, "_ensure_chrome"):
            with self.assertRaisesRegex(RuntimeError, "checksum"):
                self.installer._install_archify()
        self.assertFalse((self.installer.home / "bin/archify").exists())

    def test_verified_archify_release_archive_publishes_executable(self):
        def download(url, destination):
            self.assertIn("v3.1.0/archify.zip", url)
            with zipfile.ZipFile(destination, "w") as archive:
                archive.writestr("archify/bin/archify.mjs", "#!/usr/bin/env node\n")
        with patch.object(self.installer, "_ensure_node"), \
             patch.object(self.installer, "_download", side_effect=download), \
             patch.object(self.installer, "_digest", return_value=setup.ARCHIFY_SHA256), \
             patch.object(self.installer, "_ensure_chrome"):
            path = self.installer._install_archify()
        self.assertTrue(path.is_symlink())
        self.assertTrue(os.access(path, os.X_OK))

    def test_older_renderer_is_upgraded_to_the_pin(self):
        with patch("install_renderers.find_engine", return_value="/existing/drawio"), \
             patch.object(self.installer, "version", return_value=(29, 3, 6)), \
             patch.object(self.installer, "_install_drawio", return_value=Path("/managed/drawio")) as install:
            self.assertEqual(self.installer.ensure("drawio", update=True), "/managed/drawio")
        install.assert_called_once()

    def test_existing_plantuml_repairs_graphviz_without_reinstalling_plantuml(self):
        with patch("install_renderers.find_engine", return_value="/existing/plantuml"), \
             patch.object(self.installer, "_ensure_graphviz") as graphviz, \
             patch.object(self.installer, "_install_plantuml") as install:
            self.assertEqual(self.installer.ensure("plantuml"), "/existing/plantuml")
        graphviz.assert_called_once()
        install.assert_not_called()

    def test_graphviz_missing_on_macos_is_installed_with_brew(self):
        def which(name, **kwargs):
            if name == "brew":
                return "/brew"
            return "/dot" if name == "dot" and run.called else None
        with patch("install_renderers.platform.system", return_value="Darwin"), \
             patch("install_renderers.shutil.which", side_effect=which), \
             patch.object(self.installer, "_run", return_value="dot - graphviz version 14.0.0") as run:
            self.assertEqual(self.installer._ensure_graphviz(), Path("/dot"))
        self.assertIn((["/brew", "install", "graphviz"],), [call.args for call in run.call_args_list])

    def test_graphviz_missing_on_linux_uses_existing_apt_helper(self):
        with patch("install_renderers.platform.system", return_value="Linux"), \
             patch("install_renderers.shutil.which", side_effect=lambda name, **kwargs: "/dot" if apt.called and name == "dot" else None), \
             patch.object(self.installer, "_apt_install") as apt, \
             patch.object(self.installer, "_run", return_value="dot - graphviz version 14.0.0"):
            self.assertEqual(self.installer._ensure_graphviz(), Path("/dot"))
        apt.assert_called_once_with("graphviz")

    def test_bad_graphviz_override_is_reported_without_installing_another_copy(self):
        with patch.dict(os.environ, GRAPHVIZ_DOT="/absent/dot"), \
             patch("install_renderers.shutil.which", return_value=None), \
             patch.object(self.installer, "_apt_install") as apt:
            with self.assertRaisesRegex(RuntimeError, "GRAPHVIZ_DOT"):
                self.installer._ensure_graphviz()
        apt.assert_not_called()

    def test_doctor_rejects_old_version_without_installing(self):
        with patch("install_renderers.find_engine", return_value="/existing/drawio"), \
             patch.object(self.installer, "version", return_value=(29, 3, 6)), \
             patch.object(self.installer, "ensure") as install:
            with self.assertRaisesRegex(RuntimeError, "29.3.6.*32.4.1|32.4.1.*29.3.6"):
                self.installer.doctor("drawio")
        install.assert_not_called()

    def test_doctor_reports_missing_graphviz_with_installed_plantuml(self):
        with patch("install_renderers.find_engine", return_value="/existing/plantuml"), \
             patch.object(self.installer, "version", return_value=(1, 2026, 8)), \
             patch("install_renderers.shutil.which", side_effect=lambda name, **kwargs: "/java" if name == "java" else None), \
             patch.object(self.installer, "_run", return_value='openjdk version "21.0.10"'), \
             patch.object(self.installer, "_ensure_graphviz") as install:
            with self.assertRaisesRegex(RuntimeError, "Graphviz|dot"):
                self.installer.doctor("plantuml")
        install.assert_not_called()

    def test_doctor_checks_node_minimum_and_missing_runtime(self):
        for engine, version, required in (("mermaid", "v22.12.0", "22.13"), ("archify", "v17.9.0", "18.0")):
            for node in (None, "/node"):
                with self.subTest(engine=engine, node=node), \
                     patch("install_renderers.find_engine", return_value="/cli"), \
                     patch.object(self.installer, "version", return_value=(99, 0, 0)), \
                     patch("install_renderers.shutil.which", return_value=node), \
                     patch.object(self.installer, "_run", return_value=version):
                    with self.assertRaisesRegex(RuntimeError, "Node.js"):
                        self.installer.doctor(engine)

    def test_doctor_rejects_java8_before_graphviz_probe(self):
        with patch("install_renderers.find_engine", return_value="/plantuml"), \
             patch.object(self.installer, "version", return_value=(1, 2026, 8)), \
             patch("install_renderers.shutil.which", return_value="/java"), \
             patch.object(self.installer, "_run", return_value='java version "1.8.0_442"') as run:
            with self.assertRaisesRegex(RuntimeError, "Java 11"):
                self.installer.doctor("plantuml")
        self.assertEqual(run.call_count, 1)

    def test_mermaid_doctor_requires_browser_to_produce_svg(self):
        for produces_svg in (False, True):
            def run(command, **kwargs):
                if "--version" in command:
                    return "v22.13.0"
                if produces_svg:
                    Path(command[command.index("-o") + 1]).write_text("<svg/>")
                return ""
            with self.subTest(produces_svg=produces_svg), \
                 patch("install_renderers.find_engine", return_value="/mmdc"), \
                 patch.object(self.installer, "version", return_value=(12, 0, 0)), \
                 patch("install_renderers.shutil.which", return_value="/node"), \
                 patch.object(self.installer, "_run", side_effect=run):
                if produces_svg:
                    self.assertIn("dependencies OK", self.installer.doctor("mermaid"))
                else:
                    with self.assertRaisesRegex(RuntimeError, "SVG"):
                        self.installer.doctor("mermaid")

    def test_archify_doctor_reports_unusable_browser(self):
        with patch("install_renderers.find_engine", return_value="/archify/bin/archify.mjs"), \
             patch.object(self.installer, "version", return_value=(3, 1, 0)), \
             patch("install_renderers.shutil.which", return_value="/node"), \
             patch.object(self.installer, "_run", side_effect=["v22.13.0", "OK", RuntimeError("Chrome/Chromium is missing")]):
            with self.assertRaisesRegex(RuntimeError, "Chrome"):
                self.installer.doctor("archify")

    def test_doctor_main_accumulates_failures_and_still_reports_other_engines(self):
        def doctor(engine):
            if engine == "plantuml":
                raise RuntimeError("Graphviz dot is missing")
            return f"/existing/{engine} (version 99.0.0)"
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(setup.RendererInstaller, "doctor", side_effect=doctor), \
             patch.object(setup.RendererInstaller, "ensure") as install, \
             patch("sys.stdout", output), patch("sys.stderr", errors):
            self.assertEqual(setup.main(["--doctor"]), 1)
        for engine in ("mermaid", "drawio", "archify"):
            self.assertIn(f"{engine}: /existing/{engine}", output.getvalue())
        self.assertIn("Graphviz dot is missing", errors.getvalue())
        install.assert_not_called()


if __name__ == "__main__":
    unittest.main()
