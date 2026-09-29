import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engine_paths import find_engine
from install_renderers import RendererInstaller
from python_runtime import require_python


class PythonRuntimeTests(unittest.TestCase):
    def test_rejects_python_before_311(self):
        with self.assertRaisesRegex(RuntimeError, "3.11"):
            require_python((3, 10, 14))

    def test_accepts_python_311(self):
        require_python((3, 11, 0))


class EnginePathTests(unittest.TestCase):
    def test_managed_engine_is_found_without_path_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            executable = home / "bin" / "drawio"
            executable.parent.mkdir()
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            executable.chmod(0o755)
            with patch.dict(os.environ, UNDERSTAND_RENDERER_HOME=str(home)):
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


if __name__ == "__main__":
    unittest.main()
