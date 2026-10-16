#!/usr/bin/env python3
"""Install missing renderers or upgrade renderers to the collection's minimum CLI versions."""

import argparse
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from engine_paths import ENGINE_BINARIES, find_engine, prepare_runtime, renderer_home
from python_runtime import require_python


MERMAID_VERSION = "12.0.0"
PLANTUML_VERSION = "1.2026.8"
PLANTUML_SHA256 = "5e1ecfa8ecd32c90b03bbf3b1eb6f020943f98ab0fcf4032be31a0002ee2c462"
DRAWIO_VERSION = "32.4.1"
DRAWIO_DEB_SHA256 = "f4455b3bba3d3b539c3cd069218fc64f0462b1b01610fe8d11acc3ca8566f32b"
DRAWIO_DMG_SHA256 = "1e18db784d138cf0383ba66f662f5ace87e5b9415058075b50ce1b9560f68172"
ARCHIFY_VERSION = "3.1.0"
ARCHIFY_COMMIT = "1c2b42d660e4a7571813fb43839c79e3e9ca7720"
ARCHIFY_SHA256 = "ffedc53390c9da6e859f41e432c5d2d0615a23cf00a503181f07efbba88a7ce8"
NODE_VERSION = "22.13.1"
RENDERER_VERSIONS = {"mermaid": MERMAID_VERSION, "plantuml": PLANTUML_VERSION,
                     "drawio": DRAWIO_VERSION, "archify": ARCHIFY_VERSION}


class RendererInstaller:
    def __init__(self, home=None):
        self.home = Path(home) if home is not None else renderer_home()
        self.bin = self.home / "bin"
        self.updating = False

    @staticmethod
    def _run(command, env=None, timeout=None):
        try:
            result = subprocess.run(command, capture_output=True, text=True, env=env,
                                    check=False, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(f"{command[0]} timed out after {timeout}s") from error
        if result.returncode:
            detail = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(f"{' '.join(map(str, command))} failed: {detail}")
        return result.stdout.strip() or result.stderr.strip()

    @staticmethod
    def version(engine, executable):
        """Read native versions, without inferring a version from a directory name."""
        if engine == "archify":
            metadata = Path(executable).resolve().parent.parent / "package.json"
            try:
                package = json.loads(metadata.read_text(encoding="utf-8"))
                text = package["version"] if package["name"] == "archify" else ""
            except (OSError, ValueError, KeyError, TypeError) as error:
                raise RuntimeError(f"cannot determine archify version from {metadata}") from error
        else:
            command = [str(executable), "-version" if engine == "plantuml" else "--version"]
            try:
                result = subprocess.run(command, capture_output=True, text=True, timeout=20)
            except (OSError, subprocess.TimeoutExpired) as error:
                raise RuntimeError(f"{engine} version probe failed or timed out: {error}") from error
            text = result.stdout + "\n" + result.stderr
            # PlantUML still prints its version when Graphviz is missing; doctor checks dot separately.
            missing_dot = engine == "plantuml" and "Dot executable does not exist" in text
            if result.returncode and not missing_dot:
                raise RuntimeError(f"{engine} version probe failed (exit {result.returncode})")
            if engine == "plantuml":
                match = re.search(r"(?m)^PlantUML version\s+(\S+)", text)
            else:
                match = re.search(r"(?m)^\s*v?(\d+\.\d+\.\d+[^\s]*)\s*$", text)
            text = match[1] if match else ""
        if not isinstance(text, str) or not re.fullmatch(r"\d+\.\d+\.\d+(?:\+[\w.-]+)?", text):
            raise RuntimeError(f"unknown or prerelease {engine} version: {text!r}")
        return tuple(map(int, text.split("+", 1)[0].split(".")))

    def doctor(self, engine):
        prepare_runtime()
        executable = find_engine(engine)
        if not executable:
            raise RuntimeError(f"{engine} is not installed; run bash install.sh --engine {engine}")
        actual = self.version(engine, executable)
        minimum = tuple(map(int, RENDERER_VERSIONS[engine].split(".")))
        if actual < minimum:
            raise RuntimeError(f"{engine} version {'.'.join(map(str, actual))} is older than required {RENDERER_VERSIONS[engine]}")
        if engine in {"mermaid", "archify"}:
            node = shutil.which("node")
            if not node:
                raise RuntimeError("Node.js is missing")
            match = re.search(r"v?(\d+)\.(\d+)", self._run([node, "--version"], timeout=20))
            required = (22, 13) if engine == "mermaid" else (18, 0)
            if not match or tuple(map(int, match.groups())) < required:
                raise RuntimeError(f"Node.js {required[0]}.{required[1]}+ is required for {engine}")
        if engine == "plantuml":
            java = shutil.which("java")
            if not java:
                raise RuntimeError("Java 11+ is required for PlantUML")
            match = re.search(r'version\s+"?(\d+)(?:\.(\d+))?', self._run([java, "-version"], timeout=20))
            major = (int(match[2]) if match[1] == "1" and match[2] else int(match[1])) if match else 0
            if major < 11:
                raise RuntimeError("Java 11+ is required for PlantUML")
            dot = shutil.which(os.environ.get("GRAPHVIZ_DOT") or "dot")
            if not dot:
                raise RuntimeError("Graphviz dot is missing (check GRAPHVIZ_DOT or install graphviz)")
            self._run([dot, "-V"], timeout=20)
            self._run([executable, "-testdot"], timeout=20)
        elif engine == "archify":
            self._run([executable, "doctor"], timeout=30)
            visual = Path(executable).resolve().with_name("visual-check.mjs")
            code = (f"import {{findChrome}} from {json.dumps(visual.as_uri())};"
                    "const chrome=findChrome(); if(!chrome){console.error('Chrome/Chromium is missing');process.exit(1)};console.log(chrome)")
            self._run([node, "--input-type=module", "-e", code], timeout=20)
        elif engine == "mermaid":
            # A real temporary render also checks the browser selected by Puppeteer or a CLI wrapper.
            with tempfile.TemporaryDirectory(prefix="mermaid-doctor-") as temporary:
                source, target = Path(temporary) / "check.mmd", Path(temporary) / "check.svg"
                source.write_text("flowchart LR\n A --> B\n", encoding="utf-8")
                self._run([executable, "-i", str(source), "-o", str(target)], timeout=30)
                if not target.is_file() or "<svg" not in target.read_text(encoding="utf-8"):
                    raise RuntimeError("Mermaid browser check did not produce SVG")
        elif engine == "drawio" and platform.system() == "Linux" and not os.environ.get("DISPLAY"):
            if not shutil.which("xvfb-run"):
                raise RuntimeError("xvfb-run is required for headless draw.io")
        return f"{executable} (version {'.'.join(map(str, actual))}; required >= {RENDERER_VERSIONS[engine]}; dependencies OK)"

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
            if not self.updating or not self._owned_target(name, target):
                raise RuntimeError(f"refusing to replace existing renderer path: {target}")
            with tempfile.TemporaryDirectory(dir=self.bin) as temporary:
                staged = Path(temporary) / name
                staged.symlink_to(source)
                staged.replace(target)
        else:
            target.symlink_to(source)
        return target

    def _publish_wrapper(self, name, command):
        self.bin.mkdir(parents=True, exist_ok=True)
        target = self.bin / name
        content = "#!/bin/sh\nexec " + command + ' "$@"\n'
        if target.exists() or target.is_symlink():
            try:
                if target.is_file() and target.read_text(encoding="utf-8") == content:
                    return target
            except (OSError, UnicodeError):
                pass
            if not self.updating or not self._owned_target(name, target):
                raise RuntimeError(f"refusing to replace existing renderer path: {target}")
        with tempfile.TemporaryDirectory(dir=self.bin) as temporary:
            staged = Path(temporary) / name
            staged.write_text(content, encoding="utf-8")
            staged.chmod(0o755)
            staged.replace(target)
        return target

    def _owned_target(self, name, target):
        engine = next(engine for engine, binary in ENGINE_BINARIES.items() if binary == name)
        managed = (self.home / engine).resolve()
        if target.is_symlink():
            return target.resolve().is_relative_to(managed)
        try:
            lines = target.read_text(encoding="utf-8").splitlines()
            if len(lines) != 2 or lines[0] != "#!/bin/sh":
                return False
            words = shlex.split(lines[1])
        except (OSError, UnicodeError, ValueError):
            return False
        if len(words) < 3 or words[0] != "exec" or words[-1] != "$@":
            return False
        if name == "plantuml":
            return (len(words) == 5 and words[2] == "-jar" and Path(words[3]).name == "plantuml.jar"
                    and Path(words[3]).resolve().is_relative_to(managed))
        if name == "drawio":
            command = words[1:-1]
            if len(command) == 3 and Path(command[0]).name == "xvfb-run" and command[1] == "-a":
                command = command[2:]
            known = {Path("/usr/bin/drawio"), Path("/Applications/draw.io.app/Contents/MacOS/draw.io"),
                     Path.home() / "Applications/draw.io.app/Contents/MacOS/draw.io"}
            return len(command) == 1 and (Path(command[0]) in known or Path(command[0]).resolve().is_relative_to(managed))
        return False

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

    def _ensure_graphviz(self):
        configured = os.environ.get("GRAPHVIZ_DOT")
        dot = shutil.which(configured or "dot")
        if not dot and configured:
            raise RuntimeError(f"configured GRAPHVIZ_DOT is unavailable: {configured}")
        if not dot:
            if platform.system() == "Darwin":
                brew = shutil.which("brew")
                if not brew:
                    raise RuntimeError("Graphviz dot is missing and Homebrew is unavailable")
                self._run([brew, "install", "graphviz"])
            elif platform.system() == "Linux":
                self._apt_install("graphviz")
            dot = shutil.which("dot")
        if not dot:
            raise RuntimeError("Graphviz dot is required for PlantUML; automatic setup failed")
        self._run([dot, "-V"], timeout=20)
        return Path(dot)

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
        self._ensure_graphviz()
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
        managed = self.home / "drawio" / DRAWIO_VERSION / "draw.io.app"
        apps = (managed,) if self.updating else (Path("/Applications/draw.io.app"),
                                                Path.home() / "Applications/draw.io.app", managed)
        for app in apps:
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
            if self.updating or not executable.is_file():
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
            self.home.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=self.home) as temporary:
                temporary = Path(temporary)
                archive = temporary / "archify.zip"
                self._download(f"https://github.com/tt-a1i/archify/releases/download/v{ARCHIFY_VERSION}/archify.zip", archive)
                if self._digest(archive) != ARCHIFY_SHA256:
                    raise RuntimeError("Archify archive checksum does not match the pinned release")
                staged = temporary / "unpacked"
                with zipfile.ZipFile(archive) as package:
                    package.extractall(staged)
                entry = staged / "archify/bin/archify.mjs"
                if not entry.is_file():
                    raise RuntimeError("Archify release archive is missing its CLI")
                entry.chmod(entry.stat().st_mode | 0o111)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(staged), str(destination))
        self._ensure_chrome()
        return self._publish_link("archify", cli)

    def ensure(self, engine, update=False):
        if engine not in ENGINE_BINARIES:
            raise ValueError(f"unknown renderer: {engine}")
        self.updating = update
        configured = os.environ.get(f"{engine.upper()}_OFFICIAL_CLI")
        target = self.bin / ENGINE_BINARIES[engine]
        if update and (target.exists() or target.is_symlink()) and not self._owned_target(ENGINE_BINARIES[engine], target):
            raise RuntimeError(f"refusing to replace existing renderer path: {target}")
        existing = find_engine(engine)
        if update and configured and not existing:
            raise RuntimeError(f"configured {engine} CLI is unavailable: {configured}")
        if existing and (not update or configured or
                         self.version(engine, existing) >= tuple(map(int, RENDERER_VERSIONS[engine].split(".")))):
            if engine == "archify":
                self._ensure_chrome()
            elif engine == "plantuml":
                self._ensure_graphviz()
            return str(existing)
        installed = getattr(self, f"_install_{engine}")()
        return str(installed)


def main(argv=None):
    require_python()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", action="append", choices=tuple(ENGINE_BINARIES))
    parser.add_argument("--doctor", action="store_true", help="check selected versions and runtime dependencies without installing")
    parser.add_argument("--auto", action="store_true", help="respect an explicit --no-engines preference")
    parser.add_argument("--update", action="store_true", help="upgrade to minimum versions without downgrading; retain explicit CLI overrides")
    args = parser.parse_args(argv)
    if args.update and (args.doctor or args.auto):
        parser.error("--update cannot be combined with --doctor or --auto")
    selected = list(dict.fromkeys(args.engine or ENGINE_BINARIES))
    installer = RendererInstaller()
    marker = installer.home / "no-auto-install"
    if args.auto and marker.is_file():
        print("Renderer auto installation is disabled by --no-engines", file=sys.stderr)
        return 1
    status = 0
    for engine in selected:
        try:
            path = installer.doctor(engine) if args.doctor else installer.ensure(engine, update=args.update)
            if not path:
                raise RuntimeError(f"{engine} is not installed; run bash install.sh --engine {engine}")
            retained = args.update and os.environ.get(f"{engine.upper()}_OFFICIAL_CLI")
            print(f"{engine}: {'retained explicit CLI override ' if retained else ''}{path}")
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            print(f"Renderer setup failed: {error}", file=sys.stderr)
            if not args.doctor:
                return 1
            status = 1
    if not args.doctor and not args.auto:
        marker.unlink(missing_ok=True)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
