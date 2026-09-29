#!/usr/bin/env python3
"""Install only missing official renderer CLIs into a user-owned directory."""

import argparse
import hashlib
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from engine_paths import ENGINE_BINARIES, find_engine, prepare_runtime, renderer_home
from python_runtime import require_python


MERMAID_VERSION = "12.0.0"
PLANTUML_VERSION = "1.2026.8"
PLANTUML_SHA256 = "5e1ecfa8ecd32c90b03bbf3b1eb6f020943f98ab0fcf4032be31a0002ee2c462"
DRAWIO_VERSION = "29.3.6"
DRAWIO_DEB_SHA256 = "ff13b6604806faa3f1cfe169ef940a1358914c83905edf2cda9afb939a0fb3f4"
DRAWIO_DMG_SHA256 = "38b4653d312bbb0f038c84bed8c74bb989697f1bc24d57d182ed1e463e17bdde"
ARCHIFY_VERSION = "2.16.0"
ARCHIFY_COMMIT = "c826e6c3a7abad19c0f3cd1ca57207d54b1ad8de"
NODE_VERSION = "22.13.1"


class RendererInstaller:
    def __init__(self, home=None):
        self.home = Path(home) if home is not None else renderer_home()
        self.bin = self.home / "bin"

    @staticmethod
    def _run(command, env=None):
        result = subprocess.run(command, capture_output=True, text=True, env=env, check=False)
        if result.returncode:
            detail = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(f"{' '.join(map(str, command))} failed: {detail}")
        return result.stdout.strip() or result.stderr.strip()

    @staticmethod
    def _download(url, destination):
        with urllib.request.urlopen(url, timeout=60) as response, destination.open("wb") as output:
            shutil.copyfileobj(response, output)

    @staticmethod
    def _digest(path):
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _publish_link(self, name, source):
        if not source.is_file() or not os.access(source, os.X_OK):
            raise RuntimeError(f"missing executable for {name}: {source}")
        self.bin.mkdir(parents=True, exist_ok=True)
        target = self.bin / name
        if target.is_symlink() and target.resolve() == source.resolve():
            return target
        if target.exists() or target.is_symlink():
            raise RuntimeError(f"refusing to replace existing renderer path: {target}")
        target.symlink_to(source)
        return target

    def _publish_wrapper(self, name, command):
        self.bin.mkdir(parents=True, exist_ok=True)
        target = self.bin / name
        if target.exists() or target.is_symlink():
            raise RuntimeError(f"refusing to replace existing renderer path: {target}")
        target.write_text("#!/bin/sh\nexec " + command + ' "$@"\n', encoding="utf-8")
        target.chmod(0o755)
        return target

    def _ensure_node(self, minimum=(22, 13)):
        prepare_runtime()
        existing = shutil.which("node")
        if existing:
            match = re.search(r"v?(\d+)\.(\d+)", self._run([existing, "--version"]))
            if match and (int(match[1]), int(match[2])) >= minimum:
                return Path(existing)
        destination = self.home / "runtime" / f"node-v{NODE_VERSION}"
        binary = destination / "bin" / "node"
        if binary.is_file():
            return binary
        system = {"Darwin": "darwin", "Linux": "linux"}.get(platform.system())
        machine = {"x86_64": "x64", "amd64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(platform.machine().lower())
        if not system or not machine:
            raise RuntimeError("automatic Node.js installation supports macOS/Linux x64 and arm64")
        archive_name = f"node-v{NODE_VERSION}-{system}-{machine}.tar.xz"
        base_url = f"https://nodejs.org/dist/v{NODE_VERSION}/"
        self.home.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.home) as temporary:
            temporary = Path(temporary)
            manifest = temporary / "SHASUMS256.txt"
            archive = temporary / archive_name
            self._download(base_url + "SHASUMS256.txt", manifest)
            self._download(base_url + archive_name, archive)
            expected = next((line.split()[0] for line in manifest.read_text(encoding="utf-8").splitlines()
                             if line.split()[-1] == archive_name), None)
            if not expected or self._digest(archive) != expected:
                raise RuntimeError("Node.js archive checksum does not match the official release manifest")
            staged = temporary / "node"
            staged.mkdir()
            self._run(["tar", "-xJf", str(archive), "-C", str(staged), "--strip-components=1"])
            if not (staged / "bin" / "node").is_file():
                raise RuntimeError("Node.js archive is missing bin/node")
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists():
                shutil.move(str(staged), str(destination))
        return binary

    def _ensure_java(self):
        existing = shutil.which("java")
        if existing:
            version = re.search(r'version\s+"?(\d+)(?:\.(\d+))?', self._run([existing, "-version"]))
            if version:
                major = int(version[2]) if version[1] == "1" and version[2] else int(version[1])
                if major >= 11:
                    return Path(existing)
        system = platform.system()
        if system == "Darwin":
            brew = shutil.which("brew")
            if not brew:
                raise RuntimeError("Java is missing and Homebrew is unavailable")
            self._run([brew, "install", "openjdk@21"])
            return Path(self._run([brew, "--prefix", "openjdk@21"])) / "bin" / "java"
        if system == "Linux":
            self._apt_install("openjdk-21-jre-headless")
            java = shutil.which("java")
            if java:
                return Path(java)
        raise RuntimeError("Java 11+ is required for PlantUML; automatic setup failed")

    def _apt_install(self, package):
        apt = shutil.which("apt-get")
        if not apt:
            raise RuntimeError("automatic Linux package installation requires apt-get")
        prefix = [] if os.geteuid() == 0 else [shutil.which("sudo") or "sudo"]
        self._run([*prefix, apt, "update"])
        self._run([*prefix, apt, "install", "-y", package])

    def _ensure_chrome(self):
        for name in ("google-chrome", "chromium", "chromium-browser"):
            if shutil.which(name):
                return
        if platform.system() == "Darwin":
            for app in (Path("/Applications/Google Chrome.app"),
                        Path.home() / "Applications/Google Chrome.app"):
                if app.exists():
                    return
            brew = shutil.which("brew")
            if not brew:
                raise RuntimeError("Chrome/Chromium is missing and Homebrew is unavailable")
            self._run([brew, "install", "--cask", "google-chrome"])
        elif platform.system() == "Linux":
            self._apt_install("chromium")
        else:
            raise RuntimeError("automatic Chrome/Chromium installation supports macOS and apt-based Linux")

    def _install_mermaid(self):
        node = self._ensure_node()
        npm = shutil.which("npm", path=str(node.parent) + os.pathsep + os.environ.get("PATH", ""))
        if not npm:
            raise RuntimeError("Node.js installation did not provide npm")
        destination = self.home / "mermaid" / MERMAID_VERSION
        if not destination.is_dir():
            self.home.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=self.home) as temporary:
                staged = Path(temporary) / "mermaid"
                environment = dict(os.environ, PATH=str(node.parent) + os.pathsep + os.environ.get("PATH", ""))
                self._run([npm, "install", "--prefix", str(staged),
                           f"@mermaid-js/mermaid-cli@{MERMAID_VERSION}", "--no-audit", "--no-fund"], environment)
                if not (staged / "node_modules/.bin/mmdc").exists():
                    raise RuntimeError("Mermaid CLI installation did not produce mmdc")
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(staged), str(destination))
        return self._publish_link("mmdc", destination / "node_modules/.bin/mmdc")

    def _install_plantuml(self):
        java = self._ensure_java()
        destination = self.home / "plantuml" / PLANTUML_VERSION
        jar = destination / "plantuml.jar"
        if not jar.is_file():
            self.home.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=self.home) as temporary:
                downloaded = Path(temporary) / "plantuml.jar"
                self._download(f"https://github.com/plantuml/plantuml/releases/download/v{PLANTUML_VERSION}/plantuml-{PLANTUML_VERSION}.jar", downloaded)
                if self._digest(downloaded) != PLANTUML_SHA256:
                    raise RuntimeError("PlantUML JAR checksum does not match the pinned release")
                destination.mkdir(parents=True, exist_ok=True)
                shutil.move(str(downloaded), str(jar))
        return self._publish_wrapper("plantuml", f"{shlex.quote(str(java))} -jar {shlex.quote(str(jar))}")

    def _find_drawio_app(self):
        for app in (Path("/Applications/draw.io.app"),
                    Path.home() / "Applications/draw.io.app",
                    self.home / "drawio" / DRAWIO_VERSION / "draw.io.app"):
            if (app / "Contents/MacOS/draw.io").is_file():
                return app
        return None

    def _install_drawio(self):
        system = platform.system()
        if system == "Darwin":
            app = self._find_drawio_app()
            if app is None:
                self.home.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(dir=self.home) as temporary:
                    temporary = Path(temporary)
                    package = temporary / "drawio.dmg"
                    mount = temporary / "mount"
                    staged = temporary / "draw.io.app"
                    self._download(
                        f"https://github.com/jgraph/drawio-desktop/releases/download/v{DRAWIO_VERSION}/draw.io-universal-{DRAWIO_VERSION}.dmg",
                        package,
                    )
                    if self._digest(package) != DRAWIO_DMG_SHA256:
                        raise RuntimeError("draw.io DMG checksum does not match the pinned release")
                    mount.mkdir()
                    self._run(["hdiutil", "attach", "-nobrowse", "-readonly", "-mountpoint", str(mount), str(package)])
                    try:
                        source = mount / "draw.io.app"
                        if not (source / "Contents/MacOS/draw.io").is_file():
                            raise RuntimeError("draw.io DMG is missing draw.io.app")
                        shutil.copytree(source, staged, symlinks=True)
                    finally:
                        self._run(["hdiutil", "detach", str(mount)])
                    destination = self.home / "drawio" / DRAWIO_VERSION / "draw.io.app"
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    if not destination.exists():
                        shutil.move(str(staged), str(destination))
                app = self._find_drawio_app()
            if app is None:
                raise RuntimeError("draw.io Desktop installation did not provide its CLI")
            executable = app / "Contents/MacOS/draw.io"
        elif system == "Linux":
            if platform.machine().lower() not in {"x86_64", "amd64"}:
                raise RuntimeError("automatic draw.io Desktop installation on Linux requires x86-64")
            executable = Path("/usr/bin/drawio")
            if not executable.is_file():
                self.home.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(dir=self.home) as temporary:
                    package = Path(temporary) / "drawio.deb"
                    self._download(f"https://github.com/jgraph/drawio-desktop/releases/download/v{DRAWIO_VERSION}/drawio-amd64-{DRAWIO_VERSION}.deb", package)
                    if self._digest(package) != DRAWIO_DEB_SHA256:
                        raise RuntimeError("draw.io package checksum does not match the pinned release")
                    self._apt_install(str(package))
            if not executable.is_file():
                raise RuntimeError("draw.io Desktop installation did not provide /usr/bin/drawio")
            xvfb = shutil.which("xvfb-run")
            if not xvfb:
                self._apt_install("xvfb")
                xvfb = shutil.which("xvfb-run")
            if not xvfb:
                raise RuntimeError("headless draw.io export requires xvfb-run")
        else:
            raise RuntimeError("automatic draw.io installation supports macOS and apt-based Linux")
        command = f"{shlex.quote(xvfb)} -a {shlex.quote(str(executable))}" if system == "Linux" else shlex.quote(str(executable))
        return self._publish_wrapper("drawio", command)

    def _install_archify(self):
        self._ensure_node(minimum=(18, 0))
        destination = self.home / "archify" / ARCHIFY_VERSION
        cli = destination / "archify" / "bin" / "archify.mjs"
        if not cli.is_file():
            git = shutil.which("git")
            if not git:
                raise RuntimeError("Git is required for the pinned Archify installation")
            self.home.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=self.home) as temporary:
                staged = Path(temporary) / "archify"
                self._run([git, "clone", "--quiet", "--depth", "1", "--branch",
                           f"v{ARCHIFY_VERSION}", "https://github.com/tt-a1i/archify.git", str(staged)])
                commit = self._run([git, "-C", str(staged), "rev-parse", "HEAD"])
                if commit != ARCHIFY_COMMIT or not (staged / "archify/bin/archify.mjs").is_file():
                    raise RuntimeError("Archify checkout does not match the pinned official commit")
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(staged), str(destination))
        self._ensure_chrome()
        return self._publish_link("archify", cli)

    def ensure(self, engine):
        if engine not in ENGINE_BINARIES:
            raise ValueError(f"unknown renderer: {engine}")
        existing = find_engine(engine)
        if existing:
            if engine == "archify":
                self._ensure_chrome()
            return str(existing)
        installed = getattr(self, f"_install_{engine}")()
        return str(installed)


def main(argv=None):
    require_python()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", action="append", choices=tuple(ENGINE_BINARIES))
    parser.add_argument("--doctor", action="store_true", help="check selected renderer commands without installing")
    parser.add_argument("--auto", action="store_true", help="respect an explicit --no-engines preference")
    args = parser.parse_args(argv)
    selected = list(dict.fromkeys(args.engine or ENGINE_BINARIES))
    installer = RendererInstaller()
    marker = installer.home / "no-auto-install"
    if args.auto and marker.is_file():
        print("Renderer auto installation is disabled by --no-engines", file=sys.stderr)
        return 1
    try:
        for engine in selected:
            path = find_engine(engine) if args.doctor else installer.ensure(engine)
            if not path:
                raise RuntimeError(f"{engine} is not installed; run bash install.sh --engine {engine}")
            print(f"{engine}: {path}")
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Renderer setup failed: {error}", file=sys.stderr)
        return 1
    if not args.doctor and not args.auto:
        marker.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
