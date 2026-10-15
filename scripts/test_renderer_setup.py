import os
import io
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engine_paths import find_engine
from install_renderers import DRAWIO_DEB_SHA256, DRAWIO_VERSION, MERMAID_VERSION, PLANTUML_VERSION, RendererInstaller, main
from python_runtime import require_python


class PythonRuntimeTests(unittest.TestCase):
    def test_rejects_python_before_311(self):
        with self.assertRaisesRegex(RuntimeError, "3.11"):
            require_python((3, 10, 14))

    def test_accepts_python_311(self):
        require_python((3, 11, 0))


class EnginePathTests(unittest.TestCase):
    def test_environment_cli_precedes_managed_engine(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            managed = home / "bin" / "mmdc"
            managed.parent.mkdir()
            managed.write_text("#!/bin/sh\n", encoding="utf-8")
            managed.chmod(0o755)
            override = home / "mmdc-ci"
            override.write_text("#!/bin/sh\n", encoding="utf-8")
            override.chmod(0o755)
            with patch.dict(os.environ, UNDERSTAND_RENDERER_HOME=str(home),
                            MERMAID_OFFICIAL_CLI=str(override)):
                self.assertEqual(find_engine("mermaid"), str(override))

    def test_managed_engine_precedes_system_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            executable = home / "bin" / "drawio"
            executable.parent.mkdir()
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            executable.chmod(0o755)
            with patch.dict(os.environ, UNDERSTAND_RENDERER_HOME=str(home), DRAWIO_OFFICIAL_CLI=""):
                with patch("engine_paths.shutil.which", return_value="/usr/bin/drawio"):
                    self.assertEqual(find_engine("drawio"), str(executable))

    def test_managed_engine_is_found_without_path_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            executable = home / "bin" / "drawio"
            executable.parent.mkdir()
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            executable.chmod(0o755)
            with patch.dict(os.environ, UNDERSTAND_RENDERER_HOME=str(home), DRAWIO_OFFICIAL_CLI=""):
                with patch("engine_paths.shutil.which", return_value=None):
                    self.assertEqual(find_engine("drawio"), str(executable))

    def test_explicit_engine_path_takes_priority(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "mmdc"
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            executable.chmod(0o755)
            self.assertEqual(find_engine("mermaid", executable), str(executable))


class RendererInstallerTests(unittest.TestCase):
    def setUp(self):
        overrides = patch.dict(os.environ, {f"{engine}_OFFICIAL_CLI": ""
                                           for engine in ("MERMAID", "PLANTUML", "DRAWIO", "ARCHIFY")})
        overrides.start()
        self.addCleanup(overrides.stop)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)

    def test_reuses_existing_engine_without_install(self):
        installer = RendererInstaller(self.home)
        with patch("install_renderers.find_engine", return_value="/existing/mmdc"):
            with patch.object(installer, "_install_mermaid") as install:
                self.assertEqual(installer.ensure("mermaid"), "/existing/mmdc")
        install.assert_not_called()

    def test_missing_selected_engine_only_installs_that_engine(self):
        installer = RendererInstaller(self.home)
        managed = self.home / "bin" / "plantuml"
        with patch("install_renderers.find_engine", return_value=None):
            with patch.object(installer, "_install_plantuml", return_value=managed) as plantuml:
                with patch.object(installer, "_install_mermaid") as mermaid:
                    self.assertEqual(installer.ensure("plantuml"), str(managed))
        plantuml.assert_called_once_with()
        mermaid.assert_not_called()

    def test_failed_install_does_not_claim_engine_available(self):
        installer = RendererInstaller(self.home)
        with patch("install_renderers.find_engine", return_value=None):
            with patch.object(installer, "_install_archify", side_effect=RuntimeError("download failed")):
                with self.assertRaisesRegex(RuntimeError, "download failed"):
                    installer.ensure("archify")

    def test_missing_managed_executable_does_not_create_broken_link(self):
        installer = RendererInstaller(self.home)
        with self.assertRaisesRegex(RuntimeError, "missing executable"):
            installer._publish_link("mmdc", self.home / "missing/mmdc")
        self.assertFalse((self.home / "bin/mmdc").is_symlink())

    def test_existing_archify_also_checks_export_browser(self):
        installer = RendererInstaller(self.home)
        with patch("install_renderers.find_engine", return_value="/existing/archify"):
            with patch.object(installer, "_ensure_chrome") as chrome:
                self.assertEqual(installer.ensure("archify"), "/existing/archify")
        chrome.assert_called_once_with()

    def test_old_java_is_not_reused_for_plantuml(self):
        installer = RendererInstaller(self.home)
        with patch("install_renderers.shutil.which", side_effect=lambda name, **_kwargs:
                   "/usr/bin/java" if name == "java" else None):
            with patch.object(installer, "_run", return_value='openjdk version "1.8.0_392"'):
                with patch("install_renderers.platform.system", return_value="Unsupported"):
                    with self.assertRaisesRegex(RuntimeError, "Java 11"):
                        installer._ensure_java()

    def test_linux_arm_drawio_fails_before_downloading_amd64_package(self):
        installer = RendererInstaller(self.home)
        with patch("install_renderers.platform.system", return_value="Linux"):
            with patch("install_renderers.platform.machine", return_value="aarch64"):
                with patch.object(installer, "_download") as download:
                    with self.assertRaisesRegex(RuntimeError, "x86-64"):
                        installer._install_drawio()
        download.assert_not_called()

    def test_linux_drawio_prepares_headless_display(self):
        installer = RendererInstaller(self.home)
        with patch("install_renderers.platform.system", return_value="Linux"):
            with patch("install_renderers.platform.machine", return_value="x86_64"):
                with patch("install_renderers.Path.is_file", lambda path: str(path) == "/usr/bin/drawio"):
                    with patch("install_renderers.shutil.which", return_value="/usr/bin/xvfb-run"):
                        with patch.object(installer, "_publish_wrapper", return_value=self.home / "bin/drawio") as wrapper:
                            installer._install_drawio()
        self.assertIn("xvfb-run", wrapper.call_args.args[1])

    def test_macos_drawio_rejects_bad_dmg_before_mounting(self):
        installer = RendererInstaller(self.home)
        def write_bad_archive(_url, destination):
            destination.write_bytes(b"wrong package")
        with patch("install_renderers.platform.system", return_value="Darwin"):
            with patch.object(installer, "_find_drawio_app", return_value=None):
                with patch.object(installer, "_download", side_effect=write_bad_archive):
                    with patch.object(installer, "_run") as run:
                        with self.assertRaisesRegex(RuntimeError, "checksum"):
                            installer._install_drawio()
        run.assert_not_called()

    def executable(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\nexit 0\n")
        path.chmod(0o755)
        return path

    def test_update_flag_preserves_explicit_external_cli(self):
        external = self.executable(self.home / "external-mmdc")
        result = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("install_renderers.py")), "--update", "--engine", "mermaid"],
            env=dict(os.environ, MERMAID_OFFICIAL_CLI=str(external), UNDERSTAND_RENDERER_HOME=str(self.home)),
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("retained", result.stdout)
        self.assertFalse((self.home / "bin").exists())

    def test_update_switches_managed_link_only_after_new_version_is_available(self):
        installer = RendererInstaller(self.home)
        old = self.executable(self.home / "mermaid" / "old" / "node_modules/.bin/mmdc")
        desired = self.executable(self.home / "mermaid" / MERMAID_VERSION / "node_modules/.bin/mmdc")
        active = installer._publish_link("mmdc", old)
        with patch("install_renderers.find_engine", return_value=str(active)):
            with patch.object(installer, "_ensure_node", return_value=Path("/runtime/node")):
                with patch("install_renderers.shutil.which", return_value="/runtime/npm"):
                    self.assertEqual(installer.ensure("mermaid", update=True), str(active))
        self.assertEqual(active.resolve(), desired.resolve())
        self.assertTrue(old.is_file())

    def test_failed_update_keeps_active_managed_version(self):
        installer = RendererInstaller(self.home)
        old = self.executable(self.home / "mermaid" / "old" / "node_modules/.bin/mmdc")
        active = installer._publish_link("mmdc", old)
        with patch("install_renderers.find_engine", return_value=str(active)):
            with patch.object(installer, "_ensure_node", return_value=Path("/runtime/node")):
                with patch("install_renderers.shutil.which", return_value="/runtime/npm"):
                    with patch.object(installer, "_run", side_effect=RuntimeError("download failed")):
                        with self.assertRaisesRegex(RuntimeError, "download failed"):
                            installer.ensure("mermaid", update=True)
        self.assertEqual(active.resolve(), old.resolve())

    def test_update_replaces_generated_plantuml_wrapper_and_is_idempotent(self):
        installer = RendererInstaller(self.home)
        old_jar = self.home / "plantuml" / "old" / "plantuml.jar"
        old_jar.parent.mkdir(parents=True)
        old_jar.write_bytes(b"old")
        active = installer._publish_wrapper("plantuml", f"/runtime/java -jar {shlex.quote(str(old_jar))}")
        desired = self.home / "plantuml" / PLANTUML_VERSION / "plantuml.jar"
        desired.parent.mkdir()
        desired.write_bytes(b"new")
        with patch("install_renderers.find_engine", return_value=str(active)):
            with patch.object(installer, "_ensure_java", return_value=Path("/runtime/java")):
                installer.ensure("plantuml", update=True)
                installer.ensure("plantuml", update=True)
        self.assertIn(str(desired), active.read_text())
        self.assertEqual(old_jar.read_bytes(), b"old")

    def test_update_refuses_to_replace_custom_managed_directory_entry(self):
        installer = RendererInstaller(self.home)
        active = self.executable(self.home / "bin" / "plantuml")
        original = active.read_text()
        desired = self.home / "plantuml" / PLANTUML_VERSION / "plantuml.jar"
        desired.parent.mkdir(parents=True)
        desired.write_bytes(b"new")
        with patch("install_renderers.find_engine", return_value=str(active)):
            with patch.object(installer, "_ensure_java", return_value=Path("/runtime/java")):
                with self.assertRaisesRegex(RuntimeError, "refusing to replace"):
                    installer.ensure("plantuml", update=True)
        self.assertEqual(active.read_text(), original)

    def test_custom_entry_stops_update_before_installing_packages(self):
        installer = RendererInstaller(self.home)
        active = self.executable(self.home / "bin" / "drawio")
        with patch.object(installer, "_install_drawio", return_value=active) as install:
            with self.assertRaisesRegex(RuntimeError, "refusing to replace"):
                installer.ensure("drawio", update=True)
        install.assert_not_called()

    def test_update_refuses_to_replace_link_to_unmanaged_binary(self):
        installer = RendererInstaller(self.home)
        external = self.executable(self.home / "external" / "mmdc")
        active = installer._publish_link("mmdc", external)
        self.executable(self.home / "mermaid" / MERMAID_VERSION / "node_modules/.bin/mmdc")
        with patch("install_renderers.find_engine", return_value=str(active)):
            with patch.object(installer, "_ensure_node", return_value=Path("/runtime/node")):
                with patch("install_renderers.shutil.which", return_value="/runtime/npm"):
                    with self.assertRaisesRegex(RuntimeError, "refusing to replace"):
                        installer.ensure("mermaid", update=True)
        self.assertEqual(active.resolve(), external.resolve())

    def test_update_refuses_custom_binary_without_decoding_it_as_a_wrapper(self):
        installer = RendererInstaller(self.home)
        active = self.executable(self.home / "bin" / "plantuml")
        active.write_bytes(b"\xffcustom binary")
        desired = self.home / "plantuml" / PLANTUML_VERSION / "plantuml.jar"
        desired.parent.mkdir(parents=True)
        desired.write_bytes(b"new")
        with patch("install_renderers.find_engine", return_value=str(active)):
            with patch.object(installer, "_ensure_java", return_value=Path("/runtime/java")):
                with self.assertRaisesRegex(RuntimeError, "refusing to replace"):
                    installer.ensure("plantuml", update=True)
        self.assertEqual(active.read_bytes(), b"\xffcustom binary")

    def test_macos_update_selects_managed_drawio_instead_of_system_app(self):
        installer = RendererInstaller(self.home)
        installer.updating = True
        with patch("install_renderers.Path.is_file", return_value=True):
            self.assertEqual(installer._find_drawio_app(), self.home / "drawio" / DRAWIO_VERSION / "draw.io.app")

    def test_linux_update_installs_pinned_package_even_when_drawio_exists(self):
        installer = RendererInstaller(self.home)
        installer.updating = True
        with patch("install_renderers.platform.system", return_value="Linux"), \
             patch("install_renderers.platform.machine", return_value="x86_64"), \
             patch("install_renderers.Path.is_file", return_value=True), \
             patch("install_renderers.shutil.which", return_value="/usr/bin/xvfb-run"), \
             patch.object(installer, "_download") as download, \
             patch.object(installer, "_digest", return_value=DRAWIO_DEB_SHA256), \
             patch.object(installer, "_apt_install") as install, \
             patch.object(installer, "_publish_wrapper", return_value=self.home / "bin/drawio"):
            installer._install_drawio()
        download.assert_called_once()
        self.assertIn(DRAWIO_VERSION, download.call_args.args[0])
        self.assertTrue(install.call_args.args[0].endswith("drawio.deb"))

    def test_doctor_reports_all_missing_engines_and_available_engines(self):
        output, errors = io.StringIO(), io.StringIO()
        def find(engine):
            return "/existing/plantuml" if engine == "plantuml" else None
        with patch("install_renderers.find_engine", side_effect=find), \
             patch.object(RendererInstaller, "ensure") as install, \
             patch("sys.stdout", output), patch("sys.stderr", errors):
            self.assertEqual(main(["--doctor"]), 1)
        self.assertIn("plantuml: /existing/plantuml", output.getvalue())
        for engine in ("mermaid", "drawio", "archify"):
            self.assertIn(engine + " is not installed", errors.getvalue())
        install.assert_not_called()


if __name__ == "__main__":
    unittest.main()
